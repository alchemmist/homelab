"""Read-only reconciliation of verified historical candidates and live inventory.

Ancestry/time overlap is a planning hint, never a substitute for full canonical
or sample-subset verification. Does not publish, delete, or certify integrity.
"""
import argparse
import json
import re
from pathlib import Path


def resolution(meta):
    return meta.get('thanos', {}).get('downsample', {}).get('resolution', 0)


def classify(candidate, current):
    meta = candidate['meta']
    labels = meta.get('thanos', {}).get('labels', {})
    ancestors = set(meta.get('compaction', {}).get('sources', []))
    exact = []
    covering = []
    related = []
    for row in current:
        other = row['meta']
        if labels != other.get('thanos', {}).get('labels', {}):
            continue
        roots = set(other.get('compaction', {}).get('sources', []))
        shared = ancestors & roots
        if shared:
            related.append({'block': other['ulid'], 'resolution': resolution(other), 'sharedAncestors': len(shared)})
        if resolution(other) != 0:
            continue
        if ancestors and roots == ancestors and (meta['minTime'], meta['maxTime']) == (other['minTime'], other['maxTime']) and meta['stats']['numSamples'] == other['stats']['numSamples']:
            exact.append(other['ulid'])
        if other['minTime'] <= meta['minTime'] and other['maxTime'] >= meta['maxTime']:
            covering.append(other['ulid'])
    if len(exact) > 1:
        raise ValueError('Ambiguous live ancestry; publication refused')
    category = 'exact-ancestry-replacement-needs-current-canonical-check' if exact else (
        'contained-range-needs-full-sample-subset-proof' if covering else 'no-active-raw-counterpart-needs-retention-and-coverage-review')
    return {'candidate': meta['ulid'], 'samples': meta['stats']['numSamples'], 'category': category,
            'exactAncestryMatches': exact, 'coveringRawBlocks': covering, 'relatedRepresentations': related,
            'publicationApproved': False, 'sampleCoverageVerified': False}


def reconcile(candidates, current):
    if not candidates or not current:
        raise ValueError('Both verified candidate and live inventory are required')
    return {'productionModified': False, 'publicationApproved': False, 'allCurrentHistoryVerified': False,
            'candidateSamples': sum(item['meta']['stats']['numSamples'] for item in candidates),
            'currentBlockCount': len(current), 'candidates': [classify(item, current) for item in candidates]}


def reconcile_preserved_tail(capture, replica, current):
    """Bind a verified archive replica to immutable captured identities, not samples.

    Out-of-order companion blocks are independent sources, never assumed to be
    duplicates of larger blocks with the same time bounds and external labels.
    """
    blocks = capture.get('blocks', [])
    if not blocks or capture.get('captured') is not True or capture.get('originalFilesUnchanged') is not True or replica.get('verified') is not True:
        raise ValueError('Verified immutable capture and replica required')
    if not re.fullmatch(r'[0-9a-f]{64}', str(capture.get('archiveSHA256', ''))) or not isinstance(capture.get('archiveBytes'), int) or capture['archiveBytes'] <= 0:
        raise ValueError('Complete archive digest and size required')
    if capture.get('archiveSHA256') != replica.get('archiveSHA256') or capture.get('archiveBytes') != replica.get('archiveBytes'):
        raise ValueError('Replica is not bound to captured originals')
    if len({block['ulid'] for block in blocks}) != len(blocks) or sum(block['stats']['numSamples'] for block in blocks) != replica.get('samples') or len(blocks) != replica.get('blockCount'):
        raise ValueError('Replica scope count differs')
    raw = [row['meta'] for row in current if resolution(row['meta']) == 0]
    if len({meta['ulid'] for meta in raw}) != len(raw):
        raise ValueError('Ambiguous current raw block identity')
    report = []
    for block in blocks:
        exact = next((meta for meta in raw if meta['ulid'] == block['ulid']), None)
        if exact is not None:
            if any(exact.get(key) != block.get(key) for key in ['minTime', 'maxTime', 'stats', 'compaction']) or exact.get('thanos', {}).get('labels', {}) != block['externalLabels']:
                raise ValueError('Captured original semantic identity changed')
        roots = set(block['compaction']['sources'])
        possible = [meta['ulid'] for meta in raw if meta['ulid'] != block['ulid'] and
                    meta.get('thanos', {}).get('labels', {}) == block['externalLabels'] and
                    meta['minTime'] <= block['minTime'] and meta['maxTime'] >= block['maxTime'] and
                    roots <= set(meta['compaction']['sources'])]
        report.append({'originalBlock': block['ulid'], 'samples': block['stats']['numSamples'],
                       'unchangedLiveSemanticIdentity': exact is not None,
                       'outOfOrderCompanion': 'from-out-of-order' in block['compaction'].get('hints', []),
                       'possibleCompactedCounterpartsRequiringFullSubsetProof': possible,
                       'fullCanonicalVerified': False, 'otlpRoundtripVerified': False,
                       'publicationApproved': False})
    captured = {block['ulid'] for block in blocks}
    return {'productionModified': False, 'allCurrentHistoryVerified': False,
            'publicationApproved': False, 'archiveReplicaVerified': True,
            'archiveSHA256': capture['archiveSHA256'], 'samples': replica['samples'],
            'currentBlockCount': len(current), 'capturedSources': report,
            'otherCurrentRawBlocksNotCertifiedByThisAudit': [meta['ulid'] for meta in raw if meta['ulid'] not in captured]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['candidates', 'current', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    report = reconcile(json.loads(args.candidates.read_text()), json.loads(args.current.read_text()))
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
