"""Analyze actual consecutive native capacity samples, never infer retention acceptance."""
import argparse
import json
from pathlib import Path

COUNTERS = {'loki': 'loki_distributor_bytes_received_total', 'tempo': 'tempo_distributor_bytes_received_total'}


def summarize(observations):
    if not observations:
        raise ValueError('No measured capacity observations')
    window = []
    resets = []
    previous = None
    for observation in observations:
        timestamp = observation['observedAtUnix']
        if previous is not None and timestamp <= previous['observedAtUnix']:
            raise ValueError('Capacity timestamps must strictly increase')
        if observation.get('errors'):
            window = []
            resets.append({'atUnix': timestamp, 'reason': 'failed-observation'})
            previous = observation
            continue
        reason = None
        if window:
            old = window[-1]
            if observation['configurationSHA256'] != old['configurationSHA256']:
                reason = 'configuration-changed'
            elif timestamp - old['observedAtUnix'] > 900:
                reason = 'observation-gap'
            else:
                for backend, counter in COUNTERS.items():
                    current = observation['nativeCounters'][backend]
                    prior = old['nativeCounters'][backend]
                    if current.get('process_start_time_seconds') != prior.get('process_start_time_seconds') or current[counter] < prior[counter]:
                        reason = 'backend-counter-reset'
        if reason:
            window = []
            resets.append({'atUnix': timestamp, 'reason': reason})
        window.append(observation)
        previous = observation
    if not window:
        return {'success': False, 'fullRetentionCapacityAcceptance': False, 'resets': resets, 'consecutiveMeasuredSeconds': 0}
    elapsed = window[-1]['observedAtUnix'] - window[0]['observedAtUnix']
    trends = {}
    for backend, counter in COUNTERS.items():
        rates = []
        for old, new in zip(window, window[1:]):
            duration = new['observedAtUnix'] - old['observedAtUnix']
            # Near-simultaneous manual samples are retained but cannot establish rate peaks.
            if duration >= 60:
                rates.append((new['nativeCounters'][backend][counter] - old['nativeCounters'][backend][counter]) / duration)
        trends[backend] = {'measuredIngressBytes': window[-1]['nativeCounters'][backend][counter] - window[0]['nativeCounters'][backend][counter],
                           'meanIngressBytesPerSecond': (window[-1]['nativeCounters'][backend][counter] - window[0]['nativeCounters'][backend][counter]) / elapsed if elapsed else None,
                           'peakObservedIntervalBytesPerSecond': max(rates) if rates else None,
                           'peakIntervalIsNotPeakHourOrRetentionProjection': True,
                           'latestAllocatedBytes': window[-1]['storage'][backend]['allocatedBytes']}
    return {'success': True, 'totalObservations': len(observations), 'consecutiveObservations': len(window),
            'consecutiveMeasuredSeconds': elapsed, 'configurationSHA256': window[-1]['configurationSHA256'],
            'resets': resets, 'nativeSignalTrends': trends, 'latestFilesystem': window[-1]['filesystem'],
            'fullRetentionCapacityAcceptance': False, 'fullMetricsHistoryIncluded': False,
            'minimum24hMeasurementReached': elapsed >= 86400,
            'assumptionsOfCompressionPeakCompactionReplicationStillRequired': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize([json.loads(line) for line in args.input.read_text().splitlines() if line.strip()])
    with args.output.open('x') as target:
        target.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
