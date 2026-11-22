#!/usr/bin/env python3
"""Reviewed Authentik-shell helper. Import then run(action, nonce).

Never invoked by chart/bootstrap. Plan is read-only; apply/rollback require an
operator-reviewed fresh backup and parent approval OUTSIDE this helper. Atomic
transaction journal lives in a private local file on the Authentik container;
contains metadata only, no cookie/client/encryption secrets. Do not auto-retry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Protocol, TypedDict
from urllib.parse import urlsplit

NAME = "spi-rustfs-browser-private"
HOST = "https://rustfs.socrat.alchemmist.xyz/"
OUTPOST = "8d374315-42b7-4122-8277-05d58bcaad57"
FLOWS = {
    "authentication_flow_id": "9047ea57-13ff-48a8-ae6c-2a62d05bf6b3",
    "authorization_flow_id": "5990fa74-d8bc-41b5-935a-b2dcbde4d2b9",
    "invalidation_flow_id": "d48cb1ca-bb68-462b-83ed-6976b231b53c",
}
GROUPS = ("homelab-owner", "homelab-platform-operator")


class MappingQuery(Protocol):
    """A Django values-list query result capable of iteration."""

    def values_list(self, *args: object, **kwargs: object) -> Iterable[int]:
        """Return the selected primary keys as a flat iterable."""
        ...


class HandleProvider(Protocol):
    """Handle of an ORM-related manager with a values-list query."""

    def values_list(self, *args: object, **kwargs: object) -> Iterable[int]:
        """Return the selected primary keys as a flat iterable."""
        ...


class OutpostLike(Protocol):
    """Outpost instance exposing its provider relations."""

    providers: HandleProvider


class OutpostManager(Protocol):
    """ORM manager exposing provider-filtered outpost queries."""

    def filter(self, **kwargs: object) -> MappingQuery:
        """Return the outposts matching the given filters."""
        ...


class OutpostModel(Protocol):
    """Outpost ORM model class with a query manager."""

    objects: OutpostManager


class BindingQuery(Protocol):
    """Ordered policy-binding queryset exposing column selection."""

    def order_by(self, *args: object) -> BindingQuery:
        """Return an ordered copy of the query."""
        ...

    def values(self, *args: object) -> Iterable[object]:
        """Return the selected columns of the query as an iterable."""
        ...


class BindingManager(Protocol):
    """ORM manager exposing target-filtered policy-binding queries."""

    def filter(self, **kwargs: object) -> BindingQuery:
        """Return the bindings matching the given filters."""
        ...


class BindingModel(Protocol):
    """PolicyBinding ORM model class with a query manager."""

    objects: BindingManager


class ProviderLike(Protocol):
    """Proxy/OAuth2 provider instance fields the contract check reads."""

    pk: object
    property_mappings: HandleProvider
    redirect_uris: object
    certificate_id: object
    client_id: object
    client_secret: str
    signing_key_id: object
    encryption_key_id: object


class AppLike(Protocol):
    """Application instance fields the contract check reads."""

    pk: object
    slug: object
    policy_engine_mode: object


class StateModels(TypedDict):
    """ORM model classes the captured-state reader queries."""

    bindings: BindingModel
    outpost: OutpostModel


class StateContext(TypedDict):
    """Values the captured-state reader captures alongside its arguments."""

    settings: dict[str, object]
    native_guard: str
    outpost: OutpostLike
    models: StateModels


def captured_state(
    provider: ProviderLike, app: AppLike, context: StateContext
) -> dict[str, object]:
    """Capture the mutable deployment contract: settings, bindings, mappings."""
    settings = context["settings"]
    native_guard = context["native_guard"]
    outpost = context["outpost"]
    models = context["models"]
    actual: dict[str, object] = {key: str(getattr(provider, key)) for key in settings}
    actual["property_mappings"] = sorted(
        str(x) for x in provider.property_mappings.values_list("pk", flat=True)
    )
    actual["redirect_uris"] = provider.redirect_uris
    actual["certificate_id"] = str(provider.certificate_id)
    actual["client_id"] = provider.client_id
    actual["client_secret_sha256"] = hashlib.sha256(provider.client_secret.encode()).hexdigest()
    actual["signing_key_id"] = str(provider.signing_key_id)
    actual["encryption_key_id"] = str(provider.encryption_key_id)
    bindings = list(
        models["bindings"]
        .objects.filter(target=app.pk)
        .order_by("order")
        .values(
            "pk",
            "group_id",
            "user_id",
            "policy_id",
            "order",
            "enabled",
            "negate",
            "failure_result",
        )
    )
    return {
        "provider": provider.pk,
        "settings": actual,
        "app": str(app.pk),
        "slug": app.slug,
        "mode": app.policy_engine_mode,
        "bindings": bindings,
        "native_guard": native_guard,
        "outpost_providers": sorted(outpost.providers.values_list("pk", flat=True)),
        "provider_outposts": sorted(
            str(x)
            for x in models["outpost"]
            .objects.filter(providers=provider)
            .values_list("pk", flat=True)
        ),
    }


class DriftOutpost(Protocol):
    """Outpost identity fields pinned by the drift check."""

    managed: object
    type: object


class DriftHuman(Protocol):
    """Human operator identity fields pinned by the drift check."""

    username: object
    uuid: object


def require_outpost_shape(outpost: DriftOutpost) -> None:
    """Fail unless the embedded proxy outpost keeps its managed identity."""
    if outpost.managed != "goauthentik.io/outposts/embedded" or outpost.type != "proxy":
        raise ValueError("outpost identity drift")


def require_human_shape(human: DriftHuman) -> None:
    """Fail unless the pinned human operator identity is unchanged."""
    if human.username != "alchemmist" or str(human.uuid) != "9e33877a-3eaa-4541-98eb-8cdc10088ef6":
        raise ValueError("human identity drift")


def require_unique_origin(hosts: Iterable[str]) -> None:
    """Fail if any existing provider already answers on the canonical origin."""
    if any(authority(url) == authority(HOST) for url in hosts):
        raise ValueError("canonical-host provider already exists")


def require_fresh_journal(journal: Path) -> None:
    """Fail if a rerun journal exists; interrupted applies are resolved manually."""
    if journal.exists():
        raise ValueError("journal already exists; no retry")


def require_valid_action(action: str, nonce: str | None) -> None:
    """Fail unless an explicit supported action carries a 128-bit hex nonce."""
    if action not in ("plan", "apply", "rollback") or not re.fullmatch("[a-f0-9]{32}", nonce or ""):
        raise ValueError("explicit action and random 128-bit operator nonce required")


def ensure_journal_dir(root: Path, action: str) -> None:
    """Prepare the private journal directory for mutating actions."""
    if action == "plan":
        return
    if root.exists():
        st = root.lstat()
        if root.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError("unsafe journal directory")
    else:
        root.mkdir(mode=0o700)


def require_safe_journal(journal: Path) -> None:
    """Fail unless the journal file is an operator-owned private regular file."""
    st = journal.lstat()
    if journal.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError("unsafe journal")


def expected_native_bindings() -> list[dict[str, object]]:
    """Return the pinned group-only authorization binding set."""
    return [
        {
            "group__name": name,
            "user_id": None,
            "policy_id": None,
            "order": order,
            "enabled": True,
            "negate": False,
            "failure_result": False,
        }
        for order, name in enumerate(GROUPS)
    ]


def require_default_flows() -> None:
    """Fail unless each pinned flow keeps its default slug and primary key."""
    from authentik.flows.models import Flow

    for field, pk in FLOWS.items():
        Flow.objects.get(
            pk=pk,
            slug={
                "authentication_flow_id": "default-authentication-flow",
                "authorization_flow_id": "default-provider-authorization-implicit-consent",
                "invalidation_flow_id": "default-provider-invalidation-flow",
            }[field],
        )


def authority(url: str) -> tuple[str, int]:
    """Execute authority."""
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("invalid provider origin")
    return (
        parsed.hostname.lower().rstrip("."),
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


def digest(value: object) -> str:
    """Execute digest."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def run(action: str = "plan", nonce: str | None = None) -> None:
    """Execute run."""
    from authentik.core.models import Application, Group, User
    from authentik.outposts.models import Outpost
    from authentik.policies.models import PolicyBinding
    from authentik.providers.oauth2.models import OAuth2Provider, ScopeMapping
    from authentik.providers.proxy.models import ProxyProvider
    from django.db import transaction

    require_valid_action(action, nonce)
    root = Path(f"/tmp/rustfs-private-migration-{nonce}")
    journal = root / "metadata.json"
    ensure_journal_dir(root, action)
    with transaction.atomic():
        outpost = Outpost.objects.select_for_update().get(pk=OUTPOST)
        require_outpost_shape(outpost)
        human = User.objects.get(pk=5)
        require_human_shape(human)
        native = OAuth2Provider.objects.get(pk=12, name="spi-rustfs-native")
        app_native = Application.objects.get(
            pk="3d0da327-3083-4906-b0d4-b5328795b2a0", provider=native
        )
        scope = ScopeMapping.objects.get(name="spi-rustfs-policy")
        # Snapshot only; never write native identity, memberships or admin scope.
        native_bindings = list(
            PolicyBinding.objects.filter(target=app_native.pk)
            .order_by("order")
            .values(
                "group__name",
                "user_id",
                "policy_id",
                "order",
                "enabled",
                "negate",
                "failure_result",
            )
        )
        expected_bindings = expected_native_bindings()
        if app_native.policy_engine_mode != "any" or native_bindings != expected_bindings:
            raise ValueError("native authorization drift")
        native_guard = digest(
            {
                "native": native.pk,
                "app": str(app_native.pk),
                "bindings": native_bindings,
                "expression": scope.expression,
            }
        )
        groups = [Group.objects.get(name=name) for name in GROUPS]
        require_default_flows()
        original = sorted(outpost.providers.values_list("pk", flat=True))
        settings: dict[str, object] = dict(
            name=NAME,
            mode="forward_single",
            external_host=HOST,
            internal_host="",
            cookie_domain="rustfs.socrat.alchemmist.xyz",
            skip_path_regex="",
            intercept_header_auth=False,
            basic_auth_enabled=False,
            **FLOWS,
        )

        def state(provider: ProviderLike, app: AppLike) -> dict[str, object]:
            return captured_state(
                provider,
                app,
                {
                    "settings": settings,
                    "native_guard": native_guard,
                    "outpost": outpost,
                    "models": {"bindings": PolicyBinding, "outpost": Outpost},
                },
            )

        if action == "rollback":
            require_safe_journal(journal)
            saved = json.loads(journal.read_text())
            provider = ProxyProvider.objects.select_for_update().get(
                pk=saved["created"]["provider"], name=NAME
            )
            app = Application.objects.select_for_update().get(
                pk=saved["created"]["app"], slug=NAME, provider=provider
            )
            if digest(state(provider, app)) != saved["created_hash"]:
                raise ValueError("rollback CAS drift; do not delete")
            if provider.backchannel_application.exists():
                raise ValueError("unexpected provider consumers")
            outpost.providers.remove(provider)
            if (
                sorted(outpost.providers.values_list("pk", flat=True))
                != saved["original_outpost_providers"]
            ):
                raise ValueError("outpost restore mismatch")
            PolicyBinding.objects.filter(target=app.pk).delete()
            app.delete()
            provider.delete()
            print("Rolled back dedicated objects only; native identity unchanged.")
            return
        # Refuse adoption, even if an existing name happens to match settings.
        if (
            ProxyProvider.objects.filter(name=NAME).exists()
            or Application.objects.filter(slug=NAME).exists()
        ):
            raise ValueError("name already exists; no adoption/overwrite")
        require_unique_origin(ProxyProvider.objects.values_list("external_host", flat=True))
        if action == "plan":
            print(
                json.dumps(
                    {
                        "provider": settings,
                        "application": NAME,
                        "groups": GROUPS,
                        "original_outpost_providers": original,
                        "native_guard": native_guard,
                    },
                    sort_keys=True,
                )
            )
            return
        require_fresh_journal(journal)
        provider = ProxyProvider.objects.create(**settings)
        # Exact installed ProxyProviderSerializer.create behavior (2026.8.6).
        provider.set_oauth_defaults()
        provider.save()
        app = Application.objects.create(
            name="RustFS private browser",
            slug=NAME,
            provider=provider,
            policy_engine_mode="any",
            meta_launch_url=HOST,
        )
        for order, group in enumerate(groups):
            PolicyBinding.objects.create(
                target_id=app.pk,
                group=group,
                order=order,
                enabled=True,
                negate=False,
                failure_result=False,
            )
        outpost.providers.add(provider)
        created = state(provider, app)
        payload = {
            "nonce": nonce,
            "original_outpost_providers": original,
            "created": created,
            "created_hash": digest(created),
        }
        fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(payload, output, default=str)
            output.flush()
            os.fsync(output.fileno())
        # Journal written before transaction commit; commit failure => STOP/manual
        # read-only reconciliation, never blindly rerun or delete journal.
        print(
            json.dumps(
                {
                    "provider_id": provider.pk,
                    "application_id": str(app.pk),
                    "nonce": nonce,
                    "created_hash": payload["created_hash"],
                }
            )
        )
