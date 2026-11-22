#!/usr/bin/python
"""Read a unit property or test active units without loading or changing services."""

from ansible.module_utils.basic import AnsibleModule


def main() -> None:
    """Preserve systemctl's distinction between missing, inactive and bus errors."""
    module = AnsibleModule(
        argument_spec={
            "units": {"type": "list", "elements": "str", "required": True},
            "property": {"type": "str", "choices": ["ActiveState", "LoadState", "DropInPaths", "ExecStart"]},
        },
        supports_check_mode=True,
    )
    units = module.params["units"]
    prop = module.params["property"]
    if not units or any(not unit or unit.startswith("-") for unit in units):
        module.fail_json(msg="Unit names are required, not systemctl options")
    if prop and len(units) != 1:
        module.fail_json(msg="Read a property from exactly one unit")
    if module.check_mode:
        # Match command without creates/removes: a caller can explicitly use check_mode: false.
        module.exit_json(skipped=True, changed=False, rc=0, stdout="", stderr="")
    query = ["show", "--property", prop, "--value"] if prop else ["is-active"]
    rc, out, err = module.run_command(["systemctl", *query, "--", *units])
    result = {"changed": False, "rc": rc, "stdout": out.rstrip("\r\n"), "stderr": err.rstrip("\r\n")}
    if rc:
        module.fail_json(msg="Systemd unit probe failed", **result)
    module.exit_json(**result)


if __name__ == "__main__":
    main()
