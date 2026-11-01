"""Offline publication ledger, NOT a publisher or an integrity verifier.

Consumes bounded metadata snapshots and existing canonical receipts. Never reads
TSDB chunks, contacts production, moves blocks, or approves a serving change.
Ancestry and time overlap are hints; only explicit full-content receipts establish
replacement/containment. Snapshot freshness is an execution-time gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import time

EVIDENCE = Path(__file__).resolve().parents[1] / 'deploy/monitoring/migration-evidence'
ID = re.compile(r'[0-9A-HJKMNP-TV-Z]{26}')
SHA = re.compile(r'[0-9a-f]{64}')
REPAIR = '01M66BZJJH7AX3HTZFRZD02SXP'
SNAPSHOT = '01M61CDMNWPCZ4GZWFB5FHS67S'


def checked_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid block identity')
    return value


def make_plan(sources, stages, live, subsets, now, observed_at):
    if not sources or observed_at > now + 30 or now - observed_at > 900:
        raise ValueError('Nonempty source scope and fresh metadata required')
    originals = [checked_id(row['originalBlock']) for row in sources]
    if len(set(originals)) != len(originals):
        raise ValueError('Duplicate source identity')
    for rows in [stages, live]:
        ids = [checked_id(row['meta']['ulid']) for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError('Ambiguous block identity across observations')
    live_ids = {row['meta']['ulid'] for row in live}
    source_by_id = {row['originalBlock']: row for row in sources}
    rows = []
    for source in sources:
        original = source['originalBlock']
        digest = source.get('canonicalSHA256')
        if digest is not None and not SHA.fullmatch(digest):
            raise ValueError('Malformed canonical digest')
        candidates = [row for row in stages if digest and row.get('canonicalSHA256') == digest
                      and row['meta']['stats']['numSamples'] == source['samples']]
        if len(candidates) > 1:
            raise ValueError('Ambiguous full-content candidate')
        candidate = candidates[0] if candidates else None
        row = dict(source, candidateBlock=candidate['meta']['ulid'] if candidate else None,
                   originalPresentInSnapshot=original in live_ids,
                   publicationApproved=False, blockers=[])
        covered = None
        for proof in subsets:
            target = source_by_id.get(proof.get('target'))
            if (proof.get('source') == source.get('containedCandidate') and target
                    and all(proof.get(key) is True for key in [
                        'fullSourceSubsetVerified', 'ordinaryLabelsTimestampsFloatBitsAndMultiplicityVerified'])
                    and proof.get('sourceSamplesVerified') == source['samples']
                    and proof.get('targetCanonicalSHA256') == target.get('canonicalSHA256')):
                covered = proof['target']
        if covered:
            row.update(action='do-not-publish-contained-copy', coveredByOriginal=covered)
        elif not candidate:
            row.update(action='await-full-roundtrip-and-native-stage')
            row['blockers'].append('No uniquely content-bound completed native candidate')
        else:
            meta = candidate['meta']
            result = candidate.get('result.json', {})
            durable = candidate.get('durability.json', {})
            if (result.get('verified') is not True or result.get('block') != meta['ulid']
                    or result.get('archiveSHA256Verified') is not True
                    or result.get('nativeIndexIssueVerificationPassed') is not True
                    or durable.get('block') != meta['ulid']
                    or durable.get('sameFilesystemRenameVerified') is not True):
                row['blockers'].append('Missing or misbound native/durability receipt')
            if source.get('fullOriginalCanonicalVerified') is not True:
                row['blockers'].append('Full original canonical comparison not established')
            if (meta.get('thanos', {}).get('downsample', {}).get('resolution', 0) != 0
                    or meta.get('thanos', {}).get('labels', {}) != source['externalLabels']
                    or (meta['minTime'], meta['maxTime']) != (source['minTime'], source['maxTime'])):
                row['blockers'].append('Native candidate range/resolution/external labels differ')
            row['potentialLiveOverlap'] = [item['meta']['ulid'] for item in live
                if not item.get('deletionMarked', False)
                and item['meta'].get('thanos', {}).get('downsample', {}).get('resolution', 0) == 0
                and item['meta'].get('thanos', {}).get('labels', {}) == source['externalLabels']
                and item['meta']['minTime'] < source['maxTime']
                and source['minTime'] < item['meta']['maxTime']]
            row.update(action='replace-exact-original-after-serving-barrier' if original in live_ids
                       else 'reconcile-missing-original-before-publication')
            if original not in live_ids:
                row['blockers'].append('Original absent: rule out compaction/retention/subset coverage')
            else:
                active = next(item['meta'] for item in live if item['meta']['ulid'] == original)
                if (active['stats']['numSamples'] != source['samples']
                        or (active['minTime'], active['maxTime']) != (source['minTime'], source['maxTime'])
                        or active.get('thanos', {}).get('labels', {}) != source['externalLabels']):
                    row['blockers'].append('Original live semantic metadata changed; refresh canonical proof')
            if meta['ulid'] in live_ids:
                row['blockers'].append('Candidate already in live bucket: reconcile serving identity')
            # Time overlap does NOT prove duplication. In particular, OOO sources
            # are independent multiplicity and must not be dropped or auto-retired.
            row['blockers'].append('Fresh serving inventory, content identity and fenced handoff still required')
        rows.append(row)
    return {'schemaVersion': 1, 'generatedAtUnix': now, 'metadataObservedAtUnix': observed_at,
            'productionModified': False, 'productionPublicationApproved': False,
            'allCurrentHistoryVerified': False, 'sourceRows': rows,
            'summedSamplesIntentionallyOmitted': 'Contained backups and OOO multiplicity are not additive scope proofs',
            'requiredExecutionGates': [
                'All nine tail sources complete exact roundtrip/native/durable staging',
                'Refresh inventory including post-capture legacy-boundary blocks and deletion marks',
                'Explicit native exceptions: downsampled aggregates and unsupported histograms',
                'Bind candidate and original immutable file inventories before any move',
                'Freeze competing bucket writers/compactors with preimages and restore procedure',
                'Withdraw historical serving endpoints and drain in-flight queries before bucket mutation',
                'Retire originals outside every served bucket before exposing replacements; never co-serve',
                'Reconcile Store discovery, caches and downsample selection, not only filesystem names',
                'Queries with dedup=false and max_source_resolution=0; verify labels/bits/multiplicity',
                'Rehearse reverse serving barrier with retained original inventories',
                'Disk/memory reserve >=20%; no retention reduction, deletion or extra sample loss'],
            'finalAcceptanceDeferred': ['Application SDK/cross-app gaps', 'Production-owner rollback proof',
                                        'Sustained capacity and genuine configuration-bound 72h window']}


def build(snapshots, tail_scope, evidence=EVIDENCE, now=None):
    bindings = []
    def read(path):
        body = path.read_bytes()
        bindings.append({'name': path.name, 'sha256': hashlib.sha256(body).hexdigest()})
        return json.loads(body)
    docs = [read(Path(path)) for path in snapshots]
    scope = read(Path(tail_scope))
    classification = read(evidence / 'history-classification-20261028.json')
    comparisons = read(evidence / 'history-original-comparison-complete-20261101.json')
    if comparisons.get('success') is not True:
        raise ValueError('Successful original comparison receipts required')
    stages = [dict(row) for doc in docs for row in doc['staged']]
    live = [row for doc in docs for row in doc['live']]
    canonical = {row['block']: row['canonicalSHA256'] for row in
                 read(evidence / 'history-staged-revalidation-20261101.json')['blocks']}
    final = read(evidence / 'history-backup-final-block-20261031.json')
    canonical[final['restoredBlock']] = final['canonicalSHA256']
    current = next(doc['currentNativeFinalization'] for doc in docs if 'currentNativeFinalization' in doc)
    if not all(current.get(key) is True for key in ['success', 'actualNativeThanosQueryVerified', 'durableStagingVerified']):
        raise ValueError('Current block finalization receipt incomplete')
    canonical[current['restoredBlock']] = current['canonicalSHA256']
    completed = {}
    for doc in docs:
        for row in doc.get('queue', {}).get('canonical-progress.json', {}).get('blocks', []):
            completed[row['originalBlock']] = row
            canonical[row['restoredBlock']] = row['canonicalSHA256']
    for row in stages:
        row['canonicalSHA256'] = canonical.get(row['meta']['ulid'])
    preservation = read(evidence / 'history-tail-preservation-20261101.json')
    tail_audit = read(evidence / 'history-tail-live-reconciliation-20261101.json')
    if (preservation.get('verified') is not True
            or len(scope['blocks']) != preservation['blockCount']
            or sum(row['stats']['numSamples'] for row in scope['blocks']) != preservation['samples']
            or {row['ulid'] for row in scope['blocks']} != {row['originalBlock'] for row in tail_audit['capturedSources']}):
        raise ValueError('Frozen tail scope differs from preserved archive')
    for doc in docs:
        progress = doc.get('queue', {}).get('canonical-progress.json', {})
        if progress.get('blocks') and progress.get('sourceArchiveSHA256') != preservation['archiveSHA256']:
            raise ValueError('Completed tail receipts bind a different archive')
    sources = []
    subset_doc = read(evidence / 'history-complete-subset-20261031.json')
    if subset_doc.get('success') is not True:
        raise ValueError('Successful containment receipt required')
    subsets = subset_doc['subsets']
    stage_by_digest = {row.get('canonicalSHA256'): row for row in stages if row.get('canonicalSHA256')}
    raw_by_id = {row['ulid']: row for row in classification['rawBlocks']}
    for original, proof in comparisons['blocks'].items():
        if proof.get('fullOriginalToRestoredCanonicalEqualityVerified') is not True:
            raise ValueError('Original full-content proof missing')
        meta = raw_by_id[original]
        stage = stage_by_digest.get(proof['canonicalSHA256'])
        sources.append({'originalBlock': original, 'samples': proof['samples'],
                        'canonicalSHA256': proof['canonicalSHA256'], 'fullOriginalCanonicalVerified': True,
                        'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
                        'externalLabels': stage['meta']['thanos']['labels'] if stage else {},
                        'containedCandidate': stage['meta']['ulid'] if stage else None})
    stage = stage_by_digest[current['canonicalSHA256']]
    meta = stage['meta']
    sources.append({'originalBlock': REPAIR, 'samples': current['samples'],
                    'canonicalSHA256': current['canonicalSHA256'], 'fullOriginalCanonicalVerified': True,
                    'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
                    'externalLabels': meta['thanos']['labels'], 'approvedPriorRepairLossSamples': 120})
    meta = raw_by_id[SNAPSHOT]
    snapshot_stage = next(row for row in stages if row['meta']['ulid'] == '01M61PJFZ9Q86GRQ70N0M81NH3')
    sources.append({'originalBlock': SNAPSHOT, 'samples': meta['inventory']['samplesInChunks'],
                    'canonicalSHA256': snapshot_stage['canonicalSHA256'],
                    'fullOriginalCanonicalVerified': False, 'containedCandidate': snapshot_stage['meta']['ulid'],
                    'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
                    'externalLabels': snapshot_stage['meta']['thanos']['labels']})
    for block in scope['blocks']:
        receipt = completed.get(block['ulid'])
        if receipt and (receipt.get('samples') != block['stats']['numSamples']
                        or receipt.get('actualNativeThanosQueryVerified') is not True
                        or receipt.get('durableStagingVerified') is not True):
            raise ValueError('Incomplete or mismatched completed tail receipt')
        sources.append({'originalBlock': block['ulid'], 'samples': block['stats']['numSamples'],
                        'canonicalSHA256': receipt['canonicalSHA256'] if receipt else None,
                        'fullOriginalCanonicalVerified': receipt is not None,
                        'minTime': block['minTime'], 'maxTime': block['maxTime'],
                        'externalLabels': block['externalLabels'],
                        'outOfOrderCompanion': 'from-out-of-order' in block['compaction'].get('hints', [])})
    report = make_plan(sources, stages, live, subsets, time.time() if now is None else now,
                       min(doc['observedAtUnix'] for doc in docs))
    report['inputBindings'] = bindings
    report['nativePreservationExceptions'] = [row for row in classification['nativePreservation']
                                               if row['resolution'] != 0]
    report['scopeWarning'] = 'Frozen backup + repaired block + nine-tail scope only; later live blocks are not certified'
    planned = {row['originalBlock'] for row in sources}
    report['otherLiveBlocksNotCertified'] = [row['meta']['ulid'] for row in live
                                            if row['meta']['ulid'] not in planned]
    boundary = scope['conservativeMetricsCutoverUpperBoundMilliseconds']
    report['frozenLegacyBoundaryUpperBoundMilliseconds'] = boundary
    report['otherLiveBlockClassification'] = []
    for row in live:
        meta = row['meta']
        if meta['ulid'] in planned:
            continue
        resolution = meta.get('thanos', {}).get('downsample', {}).get('resolution', 0)
        category = ('retain-native-downsampled-aggregate' if resolution else
                    'after-frozen-boundary-preserve-native-not-certified' if meta['minTime'] >= boundary else
                    'unreconciled-legacy-intersection-blocks-publication')
        report['otherLiveBlockClassification'].append({
            'block': meta['ulid'], 'category': category, 'resolution': resolution,
            'minTime': meta['minTime'], 'maxTime': meta['maxTime'],
            'outOfOrderCompanion': 'from-out-of-order' in meta.get('compaction', {}).get('hints', []),
            'deletionMarked': row.get('deletionMarked', False), 'deleteOrRetireApproved': False})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', action='append', required=True, type=Path)
    parser.add_argument('--tail-scope', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = build(args.snapshot, args.tail_scope)
    with open(args.output, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    main()
