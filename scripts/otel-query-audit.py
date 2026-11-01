import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re

import yaml


SELECTOR = re.compile(r'(?<![A-Za-z0-9_])(le|quantile)\s*(=~|!~|!=|=)\s*("(?:\\.|[^"\\])*")')


def otlp_number(value):
    number = float(value)
    if math.isnan(number):
        raise ValueError('NaN is not a valid numeric dimension')
    if math.isinf(number):
        return '+Inf' if number > 0 else '-Inf'
    text = format(Decimal(repr(number)), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def compatible_numeric_regex(value):
    match = re.fullmatch(r'([+-]?[0-9]+)\(\\\.0\)\?', value)
    if match is None:
        return False
    number = float(match[1])
    if not math.isfinite(number) or abs(number) >= 1e6:
        return False
    canonical = otlp_number(match[1])
    try:
        return bool(re.fullmatch(value, canonical) and re.fullmatch(value, canonical + '.0'))
    except re.error:
        return False


def audit_expression(expression):
    findings = []
    selectors = dynamic = 0
    for match in SELECTOR.finditer(expression):
        selectors += 1
        label, operator, quoted = match.groups()
        try:
            value = json.loads(quoted)
        except ValueError:
            findings.append({'label': label, 'kind': 'quoted-selector-needs-review'})
            continue
        if '$' in value:
            dynamic += 1
            continue
        if operator in ('=~', '!~'):
            if value not in ('.*', '.+') and not compatible_numeric_regex(value):
                findings.append({'label': label, 'kind': 'numeric-dimension-regex-needs-review',
                                 'valueSHA256': hashlib.sha256(value.encode()).hexdigest()})
            continue
        try:
            canonical = otlp_number(value)
        except ValueError:
            continue
        if canonical != value:
            findings.append({'label': label, 'kind': 'numeric-literal-needs-review',
                             'operator': operator, 'legacyValue': value, 'otlpCandidate': canonical})
    return {'selectorCount': selectors, 'dynamicSelectorCount': dynamic, 'findings': findings}


def expressions(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('expr', 'query', 'definition') and isinstance(item, str):
                yield path + (str(key),), item
            elif isinstance(item, str) and key.endswith('.json'):
                try:
                    embedded = json.loads(item)
                except ValueError:
                    continue
                yield from expressions(embedded, path + (str(key),))
            else:
                yield from expressions(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from expressions(item, path + (str(index),))


def audit_files(paths):
    records = []
    expression_count = selector_count = dynamic_count = 0
    for path in paths:
        with path.open() as stream:
            documents = [json.load(stream)] if path.suffix == '.json' else list(yaml.safe_load_all(stream))
        for index, document in enumerate(documents):
            for location, expression in expressions(document, ('documents', str(index))):
                expression_count += 1
                result = audit_expression(expression)
                selector_count += result['selectorCount']
                dynamic_count += result['dynamicSelectorCount']
                if result['findings']:
                    records.append({'source': str(path), 'expressionPath': '.'.join(location),
                                    'expressionSHA256': hashlib.sha256(expression.encode()).hexdigest(),
                                    'findings': result['findings']})
    return {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
            'productionModified': False, 'scope': 'supplied repository/rendered configuration only; not live Grafana database',
            'sourceFileCount': len(paths), 'expressionCount': expression_count,
            'numericDimensionSelectorCount': selector_count, 'dynamicSelectorCount': dynamic_count,
            'reviewRequiredCount': len(records), 'reviews': records, 'queriesAutomaticallyRewritten': False,
            'liveQueryRegressionVerified': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_files(args.paths)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({key: result[key] for key in ['sourceFileCount', 'expressionCount', 'numericDimensionSelectorCount', 'reviewRequiredCount']}, indent=2))


if __name__ == '__main__':
    main()
