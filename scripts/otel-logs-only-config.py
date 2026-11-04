#!/usr/bin/env python3
"""Merge log-only Collector changes; refuse any shared component mutation.
Reads YAML files, emits YAML (config may contain credentials: keep output private).
Never changes metric/trace pipelines, existing exporters, TLS, storage or receivers.
"""
import argparse
import copy
import pathlib
import yaml


def merge(live, desired):
    result = copy.deepcopy(live)
    target = desired['service']['pipelines']['logs']
    other = [v for k, v in live['service']['pipelines'].items() if k != 'logs']
    for section in ('receivers', 'processors', 'exporters'):
        shared = {name for pipeline in other for name in pipeline.get(section, [])}
        for name in target[section]:
            candidate = desired[section][name]
            if section == 'receivers':
                # Keep cursor paths, ingestion bounds and live host adaptations.
                if name not in live[section]:
                    raise ValueError('Missing live receiver: ' + name)
                continue
            if name in shared:
                if candidate != live[section][name]:
                    raise ValueError('Shared component differs: ' + name)
                continue
            if section == 'exporters' and name in live[section]:
                # Existing live endpoint/TLS is authoritative; enable backpressure only.
                candidate = copy.deepcopy(live[section][name])
                candidate.setdefault('sending_queue', {})['block_on_overflow'] = True
            result.setdefault(section, {})[name] = copy.deepcopy(candidate)
    result['service']['pipelines']['logs'] = copy.deepcopy(target)
    for name, pipeline in live['service']['pipelines'].items():
        if name != 'logs':
            assert result['service']['pipelines'][name] == pipeline
            for section in ('receivers', 'processors', 'exporters'):
                for component in pipeline.get(section, []):
                    assert result[section][component] == live[section][component]
    assert result.get('extensions') == live.get('extensions')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('live'); p.add_argument('desired'); p.add_argument('output')
    args = p.parse_args()
    result = merge(yaml.safe_load(pathlib.Path(args.live).read_text()),
                   yaml.safe_load(pathlib.Path(args.desired).read_text()))
    pathlib.Path(args.output).write_text(yaml.safe_dump(result, sort_keys=False))
    pathlib.Path(args.output).chmod(0o600)
