"""Tests for the router API endpoints."""

import copy
import html
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "ansible/roles/home_ingress_ha/files/router_api.py"
)
SPEC = importlib.util.spec_from_file_location("home_ingress_router_api", MODULE_PATH)
ROUTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTER)


def _mapping(value: object) -> dict[str, object]:
    """Narrow decoded router responses to a mapping-shaped view."""
    assert isinstance(value, dict)
    return value


def forward(address, local_port, external_port, protocol, comment) -> dict[str, str]:
    return dict(
        zip(
            ROUTER.FIELDS,
            [
                address,
                str(local_port),
                protocol,
                "0.0.0.0",
                str(external_port),
                "Wan2",
                "Enabled",
                comment,
            ],
            strict=True,
        )
    )


def existing_forwards() -> list[dict[str, str]]:
    return [
        forward("192.168.0.23", 80, 80, "TCP", "socrat-http"),
        forward("192.168.0.23", 443, 443, "TCP", "socrat-https"),
        forward("192.168.0.23", 22000, 1145, "TCP", "UPNP_device"),
        forward("192.168.0.23", 22000, 1145, "UDP", "UPNP_device"),
        forward("192.168.0.23", 51830, 51830, "UDP", "wg-socrat-0"),
        forward("192.168.0.24", 51830, 51831, "UDP", "wg-socrat-1"),
        forward("192.168.0.23", 22, 2222, "TCP", "ssh-socrat-0"),
        forward("192.168.0.24", 2222, 2223, "TCP", "ssh-socrat-1"),
        forward("192.168.0.23", 2224, 2224, "TCP", "ssh-socrat-2"),
    ]


class SimulatedRouter(ROUTER.Router):
    """Router stub with canned rows and injectable add-port failures."""

    def __init__(self, rows=None, fail_add_port=None) -> None:
        self.rows = copy.deepcopy(existing_forwards() if rows is None else rows)
        self.mutations: list[dict[str, str]] = []
        self.fail_add_port = fail_add_port
        self.failed = False

    def request(self, path, data=None) -> str:
        """Send a fixture request to the router API."""
        if data is None:
            if path != "/portfw.htm":
                raise AssertionError(path)
            rows = []
            for index, row in enumerate(self.rows, 1):
                cells = "".join(
                    '<td><font size="2">' + html.escape(row[field]) + "</td>"
                    for field in ROUTER.FIELDS
                )
                rows.append(
                    "<tr>" + cells + f'<td><input name="select{index}" value="ON"></td></tr>'
                )
            return "<table>" + "".join(rows) + "</table>"
        if path != "/boafrm/formPortFw":
            raise AssertionError(path)
        self.mutations.append(copy.deepcopy(data))
        if "deleteSelPortFw" in data:
            selectors = [key for key in data if key.startswith("select")]
            if len(selectors) != 1:
                raise AssertionError("Deletion must target exactly one row")
            self.rows.pop(int(selectors[0][6:]) - 1)
        elif data.get("addPortFwFlag") == "1":
            if (
                data["externalFromPort"] == self.fail_add_port
                and data["ip"] == "192.168.0.250"
                and not self.failed
            ):
                self.failed = True
                raise OSError("Simulated target add failure")
            if data["WAN2"] != "ON" or data["protocol"] != "1":
                raise AssertionError("Unexpected interface or protocol")
            if (
                data["fromPort"] != data["toPort"]
                or data["externalFromPort"] != data["externalToPort"]
            ):
                raise AssertionError("Port range unexpectedly changed")
            self.rows.append(
                forward(
                    data["ip"],
                    data["fromPort"],
                    data["externalFromPort"],
                    "TCP",
                    data["comment"],
                )
            )
        else:
            raise AssertionError("Unexpected mutation")
        return "<html>Applied</html>"


class RouterApiTests(unittest.TestCase):
    """Exercise the router API against the simulated router."""

    def run_main(self, router, *arguments) -> dict[str, object]:
        """Run the CLI and return parsed JSON output."""
        output = io.StringIO()
        with (
            patch.object(ROUTER, "Router", return_value=router),
            patch.object(ROUTER.sys, "argv", ["router_api.py", *arguments]),
            patch.object(ROUTER.sys, "stdin", io.StringIO("{}")),
            patch.object(ROUTER.time, "sleep"),
            redirect_stdout(output),
        ):
            ROUTER.main()
        return _mapping(json.loads(output.getvalue()))

    def apply(self, router) -> dict[str, object]:
        """Run the apply flow for the router."""
        return self.run_main(
            router,
            "--apply",
            "--expected-old",
            "192.168.0.23",
            "--destination",
            "192.168.0.250",
        )

    def test_only_web_forwards_move_and_seven_unrelated_forwards_survive(self) -> None:
        """Only web forwards move and seven unrelated forwards survive."""
        router = SimulatedRouter()
        original = copy.deepcopy(router.rows)
        result = self.apply(router)
        expected = [
            dict(row, ip="192.168.0.250") if row["external_port"] in ("80", "443") else row
            for row in original
        ]
        assert result["changed"]
        assert ROUTER.canonical(router.rows) == ROUTER.canonical(expected)
        expected_row_count = 9
        expected_mutation_count = 4
        assert len(router.rows) == expected_row_count
        assert len(router.mutations) == expected_mutation_count
        assert all("deleteAllPortFw" not in request for request in router.mutations)

    def test_second_add_failure_restores_both_original_web_forwards(self) -> None:
        """Second add failure restores both original web forwards."""
        router = SimulatedRouter(fail_add_port="443")
        original = copy.deepcopy(router.rows)
        with self.assertRaisesRegex(OSError, "Simulated target add failure"):
            self.apply(router)
        assert ROUTER.canonical(router.rows) == ROUTER.canonical(original)
        assert router.failed

    def test_concurrent_unrelated_insert_with_shifted_selectors_refuses_mutation(
        self,
    ) -> None:
        """Concurrent unrelated insert with shifted selectors refuses mutation."""
        router = SimulatedRouter()
        expected = router.forwards()
        router.rows.insert(0, forward("192.168.0.50", 9000, 9000, "TCP", "unrelated"))
        current = copy.deepcopy(router.rows)
        with (
            patch.object(ROUTER.time, "sleep"),
            self.assertRaisesRegex(RuntimeError, "expected state"),
        ):
            router.replace(expected, expected[0], dict(expected[0], ip="192.168.0.250"))
        assert router.mutations == []
        assert router.rows == current

    def test_reordered_unchanged_table_uses_fresh_selector_instead_of_stale_index(
        self,
    ) -> None:
        """Reordered unchanged table uses fresh selector instead of stale index."""
        router = SimulatedRouter()
        expected = router.forwards()
        router.rows.reverse()
        expected_row_count = len(router.forwards())
        router.replace(expected, expected[0], dict(expected[0], ip="192.168.0.250"))
        assert "select9" in router.mutations[0]
        assert "select1" not in router.mutations[0]
        changed = [row for row in router.rows if row["ip"] == "192.168.0.250"]
        assert [row["external_port"] for row in changed] == ["80"]
        assert len(router.rows) == expected_row_count

    def test_unexpected_https_target_refuses_entire_operation_before_http_change(
        self,
    ) -> None:
        """Unexpected https target refuses entire operation before http change."""
        router = SimulatedRouter()
        router.rows[1]["ip"] = "192.168.0.99"
        with self.assertRaisesRegex(RuntimeError, "expected old state: 443"):
            self.apply(router)
        assert router.mutations == []

    def test_already_targeted_router_rejects_stale_expected_old_without_mutation(
        self,
    ) -> None:
        """Already targeted router rejects stale expected old without mutation."""
        router = SimulatedRouter()
        for row in router.rows[:2]:
            row["ip"] = "192.168.0.250"
        with self.assertRaisesRegex(RuntimeError, "expected old state: 80"):
            self.apply(router)
        assert router.mutations == []

    def test_read_only_default_never_mutates_router(self) -> None:
        """Read only default never mutates router."""
        router = SimulatedRouter()
        result = self.run_main(router)
        assert ROUTER.canonical(result["forwards"]) == ROUTER.canonical(existing_forwards())
        assert router.mutations == []

    def test_lost_delete_response_restores_original_after_readback(self) -> None:
        """Lost delete response restores original after readback."""
        router = SimulatedRouter()
        request = router.request
        lost = False

        def lose_delete_response(path, data=None):
            nonlocal lost
            response = request(path, data)
            if data and "deleteSelPortFw" in data and not lost:
                lost = True
                raise OSError("Delete response lost after apply")
            return response

        with patch.object(router, "request", side_effect=lose_delete_response):
            with self.assertRaisesRegex(OSError, "Delete response lost after apply"):
                self.apply(router)
        assert ROUTER.canonical(router.rows) == ROUTER.canonical(existing_forwards())
        expected_mutation_count = 2
        assert len(router.mutations) == expected_mutation_count
        assert router.mutations[1]["ip"] == "192.168.0.23"

    def test_lost_add_response_is_verified_without_duplicate_add(self) -> None:
        """Lost add response is verified without duplicate add."""
        router = SimulatedRouter()
        request = router.request
        lost = False

        def lose_add_response(path, data=None):
            nonlocal lost
            response = request(path, data)
            if data and data.get("addPortFwFlag") == "1" and not lost:
                lost = True
                raise OSError("Add response lost after apply")
            return response

        with patch.object(router, "request", side_effect=lose_add_response):
            result = self.apply(router)
        assert result["changed"]
        expected_row_count = 9
        expected_mutation_count = 4
        assert len(router.mutations) == expected_mutation_count
        assert len(router.rows) == expected_row_count
        moved = [row for row in router.rows if row["ip"] == "192.168.0.250"]
        assert sorted(row["external_port"] for row in moved) == ["443", "80"]

    def test_lost_delete_response_with_unexpected_state_does_not_blindly_restore(
        self,
    ) -> None:
        """Lost delete response with unexpected state does not blindly restore."""
        router = SimulatedRouter()
        request = router.request

        def concurrent_change_after_delete(path, data=None):
            response = request(path, data)
            if data and "deleteSelPortFw" in data:
                router.rows.append(forward("192.168.0.50", 9000, 9000, "TCP", "concurrent"))
                raise OSError("Delete response lost with concurrent change")
            return response

        with patch.object(router, "request", side_effect=concurrent_change_after_delete):
            with self.assertRaisesRegex(OSError, "Delete response lost with concurrent change"):
                self.apply(router)
        assert len(router.mutations) == 1
        assert any(row["comment"] == "concurrent" for row in router.rows)
        assert not any(row["external_port"] == "80" for row in router.rows)

    def test_malformed_forward_table_is_rejected(self) -> None:
        """Malformed forward table is rejected."""
        with self.assertRaisesRegex(ValueError, "Unexpected router forwarding table format"):
            ROUTER.parse_forwards('<tr><td>192.168.0.23</td><td><input name="select1"></td></tr>')
        with self.assertRaisesRegex(ValueError, "Missing router forwarding table"):
            ROUTER.parse_forwards("<html>Login required</html>")


if __name__ == "__main__":
    unittest.main()
