"""Render bounded, deterministic Loki retention; no cluster operations.

Service keys are exact service_name values, not arbitrary LogQL selectors.
Long error retention requires a reviewed measured capacity approval in the policy.
"""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'deploy/monitoring/otel/retention-policy.json'
COPIES = [ROOT / p for p in ('deploy/monitoring/otel/loki.yaml', 'charts/otel-backends/files/loki.yaml')]
LEVELS = {'trace', 'debug', 'info', 'warn', 'error', 'fatal', 'unknown'}


def rules(policy):
    if policy.get('schemaVersion') != 1:
        raise ValueError('Unsupported policy schema')
    fallback = policy['fallbackHours']
    def hours(value, level):
        if type(value) is not int or not 24 <= value <= 8760:
            raise ValueError('Retention must be integer hours between 24h and 365d')
        if value > 720:
            approval = policy.get('capacityApproval') or {}
            if level not in ('error', 'fatal') or not all(approval.get(k) for k in (
                    'measuredAt', 'evidence', 'budgetBytes', 'projectedBytes', 'approvedBy')):
                raise ValueError('Only error/fatal may exceed 30d, with measured capacity approval')
            if (type(approval['budgetBytes']) is not int or type(approval['projectedBytes']) is not int
                    or not 0 < approval['projectedBytes'] <= approval['budgetBytes']):
                raise ValueError('Projected disk must fit approved positive budget')
        return value
    hours(fallback, 'unknown')
    if set(policy['severityHours']) != LEVELS:
        raise ValueError('All seven normalized severity policies are required')
    result = []
    for level, value in sorted(policy['severityHours'].items()):
        result.append((10, '{severity=' + json.dumps(level) + '}', hours(value, level)))
    for service, overrides in sorted(policy.get('services', {}).items()):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,199}', service):
            raise ValueError('Unsafe or empty service name')
        if not overrides or not set(overrides) <= LEVELS:
            raise ValueError('Service overrides must map normalized severity to hours')
        for level, value in sorted(overrides.items()):
            selector = '{service_name=' + json.dumps(service) + ',severity=' + json.dumps(level) + '}'
            result.append((100, selector, hours(value, level)))
    return fallback, result


def render(text, policy):
    fallback, streams = rules(policy)
    block = '  retention_period: ' + str(fallback) + 'h\n  retention_stream:\n'
    for priority, selector, period in streams:
        block += f"    - selector: '{selector}'\n      priority: {priority}\n      period: {period}h\n"
    # Replace only the limits retention stanza, preserving all unrelated Loki settings.
    text, count = re.subn(r'  retention_period:.*?\n(?=  allow_structured_metadata:)', block, text, flags=re.S)
    if count != 1:
        raise ValueError('Expected one bounded limits retention stanza')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--policy', type=Path, default=POLICY)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text())
    rendered = render(COPIES[0].read_text(), policy)
    for path in COPIES:
        if args.check:
            if path.read_text() != rendered:
                raise SystemExit(f'Retention/config drift: {path.relative_to(ROOT)}')
        else:
            path.write_text(rendered)


if __name__ == '__main__':
    main()
