import json
import sys


MEMORY_FACTORS = (
    ('Ti', 1024 ** 4),
    ('Gi', 1024 ** 3),
    ('Mi', 1024 ** 2),
    ('Ki', 1024),
    ('T', 1000 ** 4),
    ('G', 1000 ** 3),
    ('M', 1000 ** 2),
    ('K', 1000),
    ('k', 1000),
)


def memory_bytes(value):
    text = str(value).strip()
    for suffix, factor in MEMORY_FACTORS:
        if text.endswith(suffix):
            return int(float(text[:-len(suffix)]) * factor)
    return int(float(text))


def problems(document, pods=None):
    if not document:
        return ['Prometheus is not installed']
    items = document.get('items') if isinstance(document, dict) and 'items' in document else [document]
    if not items:
        return ['Prometheus is not installed']
    spec = items[0].get('spec') or {}
    found = []
    if spec.get('scrapeInterval') != '5s':
        found.append('Prometheus scrapeInterval is not 5s')
    limit = (spec.get('resources') or {}).get('limits', {}).get('memory', '0')
    if memory_bytes(limit) < memory_bytes('8Gi'):
        found.append('Prometheus memory limit is below 8Gi')
    if pods is not None:
        running = [p for p in pods.get('items', []) if p.get('status', {}).get('phase') == 'Running']
        if not running:
            found.append('No running Prometheus Pod to verify effective memory')
        for pod in running:
            containers = [c for c in pod.get('spec', {}).get('containers', []) if c['name'] == 'prometheus']
            statuses = [c for c in pod.get('status', {}).get('containerStatuses', []) if c['name'] == 'prometheus']
            if len(containers) != 1 or len(statuses) != 1:
                found.append('Prometheus Pod container/status is missing or ambiguous')
                continue
            if not statuses[0].get('ready'):
                found.append('Prometheus container is not Ready')
            for label, resources in [('Pod spec', containers[0].get('resources', {})),
                                     ('runtime status', statuses[0].get('resources', {}))]:
                if memory_bytes(resources.get('limits', {}).get('memory', '0')) < memory_bytes('8Gi'):
                    found.append('Effective Prometheus ' + label + ' memory limit is below 8Gi')
    return found


def main():
    document = json.load(sys.stdin)
    found = (problems(document['prometheus'], document['pods'])
             if 'prometheus' in document and 'pods' in document else problems(document))
    if found:
        print('; '.join(found), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
