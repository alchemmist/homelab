#!/usr/bin/env python3
"""Guarded NetBird control-plane check, plan, and apply.

Does not sync Argo CD, edit the Traefik chart, deploy routing peers, or grant
overlay access. Repo inputs are blocked until separate reviews are true.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('netbird_pilot', ROOT / 'scripts/netbird-pilot.py')
nb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nb)
CONFIRM = 'apply-netbird-control-plane'
FORBIDDEN_KINDS = {'Secret', 'Application', 'DaemonSet', 'ClusterRole', 'ClusterRoleBinding', 'IngressRoute'}


def load_json(path):
    return json.loads(Path(path).read_text())


def assert_candidates(candidates):
    """Repo candidate marks are not approval. verified must stay false."""
    nb.require(candidates['management_fqdn']['value'] == 'netbird.socrat.alchemmist.xyz', 'approved FQDN missing')
    nb.require(candidates['management_fqdn']['approved'] is True, 'FQDN approval missing')
    nb.require(candidates['management_fqdn']['dns_tls_verified'] is False, 'DNS/TLS was not verified')
    nb.require(candidates['authentik_oidc']['approved'] is True and candidates['authentik_oidc']['configured'] is False,
               'Authentik approval must stay distinct from a configured connector')
    nb.require(candidates['authentik_oidc']['groups_claim_verified'] is False,
               'Authentik groups claim was marked verified')
    nb.require(candidates['ingress_class']['value'] == 'traefik' and candidates['ingress_class']['verified'] is False,
               'ingress class candidate was marked verified')
    nb.require(candidates['storage_class']['value'] == 'local-path' and candidates['storage_class']['verified'] is False,
               'storage class candidate was marked verified')
    nb.require(candidates['resources']['private_grafana']['deployable'] is False, 'Grafana must not be deployable')
    nb.require(candidates['resources']['socrat_2_openssh']['deployable'] is False, 'socrat-2 SSH must not be deployable')
    nb.require(candidates['pilot_users'] == ['owner', 'tim'], 'pilot users must stay owner and tim')
    routers = candidates['routers']
    nb.require(routers['required'] == 2, 'two routing peers remain required')
    nb.require(routers['placement_resolved'] is False, 'router placement is unresolved')
    nb.require(routers['mode'] == 'existing-node', 'router mode must stay the existing-node candidate')
    nb.require(routers['existing_node_router_mode_reviewed'] is False,
               'existing-node router review was marked done without evidence')
    nb.require(routers['new_machines_approved'] is False, 'new machines were not approved')


def scope_matches_chart(chart, delta):
    watched = list(chart['watchNamespaces'])
    crd = chart['kubernetesCRD']['namespaces']
    return {'watch_namespaces': watched,
            'netbird_edge_watched': 'netbird-edge' in watched,
            'netbird_pilot_watched': 'netbird-pilot' in watched,
            'crd_namespaces': list(crd),
            'crd_label': chart['kubernetesCRD']['labelSelector'],
            'delta_applied': False,
            'would_add': delta['add_watch_namespace'],
            'argo_automated_self_heal': delta['argo_automated_self_heal']}


def report(inputs, candidates, audit, chart, delta):
    assert_candidates(candidates)
    scope = scope_matches_chart(chart, delta)
    apply_blockers = []
    try:
        nb.validate_control_plane(inputs)
    except ValueError as exc:
        apply_blockers.append(str(exc))
    if audit['kubectl_api_read'] is not True:
        apply_blockers.append('kubectl API was not read: ' + audit['kubectl_blocker'])
    if audit['udp_3478_listening'] is not True:
        apply_blockers.append(
            'UDP 3478 is not listening. v0.82.0 advertises stun:<fqdn>:3478 to clients; '
            'the NodePort is only the in-cluster target and is not that advertisement')
    if audit['traefik_watches_netbird_edge'] is not True or scope['netbird_edge_watched'] is not True:
        apply_blockers.append(
            'Traefik ingress watch does not include netbird-edge, so the rendered Ingress is inert')
    if audit['traefik_watches_netbird_pilot'] is True or scope['netbird_pilot_watched'] is True:
        apply_blockers.append('Traefik must not watch netbird-pilot; that Role can read the runtime secret')
    if audit['traefik_allow_cross_namespace'] is not False or audit['traefik_allow_external_name'] is not False:
        apply_blockers.append('Traefik cross-namespace or ExternalName bypass is enabled')
    if delta['applied'] is not False or delta['verified'] is not False:
        apply_blockers.append('Traefik scope delta must stay unapplied and unverified in git')
    network_blockers = [
        candidates['resources']['private_grafana']['reason'],
        candidates['resources']['socrat_2_openssh']['reason'],
        'Existing-node router placement is unresolved. This control plane does not generate host routers.',
        'Authentik OIDC is approved and not configured. localAuthDisabled cannot be true on first boot.',
        'Authentik groups claim is not verified.',
        'v0.82.0 simplified config cannot disable the Default allow-all policy. Delete it before any enrollment.',
        'Owner signup password is not reachable on the public forwarder. /api/setup stays denied except loopback.',
    ]
    return {'apply_allowed': not apply_blockers,
            'network_grant_allowed': False,
            'approved_fqdn': candidates['management_fqdn']['value'],
            'pilot_users': candidates['pilot_users'],
            'management_ha': False,
            'apply_blockers': apply_blockers,
            'network_blockers': network_blockers,
            'scope': scope}


def assert_safe_manifests(docs):
    namespaces = set()
    runtime_refs = []
    for doc in docs:
        nb.require(doc.get('kind') not in FORBIDDEN_KINDS, 'forbidden manifest kind')
        name = doc['metadata']['name']
        namespace = doc['metadata'].get('namespace')
        if doc['kind'] == 'Namespace':
            namespaces.add(name)
        else:
            nb.require(namespace in {nb.NS, nb.EDGE}, 'unexpected namespace')
        blob = json.dumps(doc)
        for banned in ['hostNetwork', 'NB_SETUP_PAT', 'client_secret', 'BEGIN ', 'wg-socrat', 'syncPolicy']:
            nb.require(banned not in blob, 'unsafe manifest field')
        if 'netbird-runtime' in blob:
            runtime_refs.append(namespace)
    nb.require(namespaces == {nb.NS, nb.EDGE}, 'control plane namespaces mismatch')
    nb.require(runtime_refs == [nb.NS], 'runtime secret reference must stay in netbird-pilot')


def plan_document(manifest):
    return {'manifest': manifest.name,
            'argo_sync': False,
            'routers': False,
            'network_grant': False,
            'secrets_in_manifest': False,
            'management_ha': False,
            'stun_advertised_port': nb.STUN_PORT,
            'stun_node_port_is_not_the_advertised_port': True,
            'apply_requires': ['--context', '--confirm-apply ' + CONFIRM],
            'kubectl': ['kubectl', '--context', '<explicit>', 'apply', '--server-side',
                        '--field-manager', 'netbird-control-plane', '-f', manifest.name]}


def apply_argv(manifest, context):
    nb.require(nb.text(context) and context not in {'', 'current', 'default'}, 'explicit kubectl context required')
    nb.require(manifest.is_file(), 'rendered manifest required')
    nb.require(not manifest.resolve().is_relative_to(ROOT), 'manifest must stay outside the worktree')
    docs = list(yaml.safe_load_all(manifest.read_text()))
    assert_safe_manifests(docs)
    return ['kubectl', '--context', context, 'apply', '--server-side',
            '--field-manager', 'netbird-control-plane', '-f', str(manifest)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['check', 'plan', 'apply', 'scope'])
    p.add_argument('--inputs', type=Path, default=ROOT / 'deploy/netbird/pilot.inputs.json')
    p.add_argument('--candidates', type=Path, default=ROOT / 'deploy/netbird/candidates.json')
    p.add_argument('--audit', type=Path, default=ROOT / 'deploy/netbird/runtime-audit.json')
    p.add_argument('--out', type=Path)
    p.add_argument('--context')
    p.add_argument('--confirm-apply', default='')
    p.add_argument('--print-only', action='store_true')
    a = p.parse_args()
    candidates = load_json(a.candidates)
    audit = load_json(a.audit)
    chart = yaml.safe_load((ROOT / 'charts/traefik-edge/values.yaml').read_text())
    delta = load_json(ROOT / 'deploy/netbird/traefik-scope-delta.json')
    if a.command == 'scope':
        print(json.dumps(scope_matches_chart(chart, delta), indent=2))
        print('Chart was not modified')
        return
    inputs = load_json(a.inputs)
    status = report(inputs, candidates, audit, chart, delta)
    if a.command == 'check':
        print(json.dumps(status, indent=2))
        if not status['apply_allowed']:
            raise ValueError('control plane apply is blocked')
        return
    nb.require(status['apply_allowed'], 'control plane apply is blocked')
    nb.require(a.out is not None, '--out required')
    nb.require(not a.out.resolve().is_relative_to(ROOT), '--out must be outside the Git worktree')
    nb.render_control_plane(inputs, a.out)
    manifest = a.out / 'management.yaml'
    nb.dump(a.out / 'plan.json', plan_document(manifest))
    if a.command == 'plan':
        print('Plan written; kubectl was not run and Argo was not synced')
        return
    nb.require(a.confirm_apply == CONFIRM, 'apply confirmation phrase mismatch')
    argv = apply_argv(manifest, a.context)
    if a.print_only:
        print(json.dumps({'argv': argv, 'executed': False}))
        return
    subprocess.run(argv, check=True)
    print('Control plane apply finished; no router and no Argo sync')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print('BLOCKED: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__), file=sys.stderr)
        sys.exit(2)
