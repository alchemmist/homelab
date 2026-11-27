"""Model-only metric projection; immutable collection/artifact data is untouched."""
from core import digest, SECRET_KEY

METRIC_SOURCES = frozenset(('prometheus_metrics', 'loki_error_frequency',
                            'host_log_error_frequency', 'loki_rule_metric'))


def project_metric_series(data, limit):
    """Bound high-cardinality summaries with explicit, deterministic omissions.

    This is NOT metric aggregation or relevance ranking. Never truncate artifact
    indexes, candidate identities, query paths/parameters or stored evidence.
    Only bundled analysis contexts can use this escape hatch. Legacy evidence
    without immutable-artifact references keeps its existing fail-closed path.
    """
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError('Invalid model metric series projection limit')
    evidence = data.get('evidence', {})
    context = evidence.get('artifact_context')
    if not isinstance(context, dict) or not context.get('index'):
        return data
    queries = []
    changed = False
    for query in evidence.get('queries', []):
        result = query.get('result', {})
        rows = result.get('series') if isinstance(result, dict) else None
        if (not isinstance(result, dict) or query.get('source') not in METRIC_SOURCES or
            result.get('format') != 'observed_metric_summary_v1' or
            not isinstance(rows, list) or len(rows) <= limit):
            queries.append(query)
            continue
        changed = True
        projected = {
            **result,
            'series': rows[:limit],
            'model_series_projection': {
                'format': 'explicit_metric_series_prefix_v1',
                'original_series_count': len(rows),
                'selected_series_count': limit,
                'omitted_series_count': len(rows) - limit,
                'original_series_sha256': digest(rows),
                'selection': 'Collected order prefix, not relevance ranking or an aggregate.',
                'limitation': ('Only selected series were supplied to the model. Omitted series were not reviewed. '
                               'The complete collected summary remains in the durable job snapshot. Consult '
                               'immutable evidence for upstream JSON and its original collection limits.'),
            },
        }
        queries.append({**query, 'result': projected})
    if not changed:
        return data
    return {**data, 'evidence': {**evidence, 'queries': queries}}


def compact_metric_table(result, dictionary=False):
    """Lossless second-stage compaction of already aggregated metric samples.

    Factor repeated label keys/values and shared first/last timestamps, rather
    than discard series. Unknown structures are never silently normalized.
    """
    if not isinstance(result, dict) or result.get('format') != 'observed_metric_summary_v1':
        return result
    rows = result.get('series')
    allowed = {'labels', 'sample_count', 'finite_count', 'first', 'last',
               'minimum', 'maximum', 'nonzero_samples'}
    if not isinstance(rows, list) or len(rows) < 4:
        return result
    if any(not isinstance(r, dict) or 'labels' not in r or set(r) - allowed or
           not isinstance(r['labels'], dict) or
           any(SECRET_KEY.search(k) for k in r['labels']) or
           any(not isinstance(v, str) for v in r['labels'].values()) for r in rows):
        return result
    fields = set(rows[0])
    if any(set(r) != fields for r in rows):
        return result
    for r in rows:
        for k in ('first', 'last'):
            p = r.get(k)
            if p is not None and (not isinstance(p, dict) or set(p) != {'time', 'value'}):
                return result
    common = {k: v for k, v in rows[0]['labels'].items()
              if all(r['labels'].get(k) == v for r in rows)}
    label_columns = sorted(set().union(*(set(r['labels']) for r in rows)) - set(common))
    columns = ['labels'] + [k for k in ('sample_count', 'finite_count', 'first', 'last',
                                      'minimum', 'maximum', 'nonzero_samples') if k in fields]
    times = {}
    for k in ('first', 'last'):
        if all(r.get(k) is not None for r in rows):
            t = rows[0][k]['time']
            if all(r[k]['time'] == t for r in rows):
                times[k] = t
    # Deduplicate values shared by subsets of rows as well as all-row labels.
    # Only use dictionary coding when smaller; indices never rank relevance.
    import json
    raw_labels = [[r['labels'].get(k) for k in label_columns] for r in rows]
    label_values = list(dict.fromkeys(v for values in raw_labels for v in values if v is not None))
    positions = {v:i for i,v in enumerate(label_values)}
    coded = [[positions[v] if v is not None else None for v in values] for values in raw_labels]
    use_dictionary = dictionary and len(json.dumps([label_values,coded],separators=(',',':'))) < len(json.dumps(raw_labels,separators=(',',':'))) * .9
    table = []
    for index, r in enumerate(rows):
        values = [coded[index] if use_dictionary else raw_labels[index]]
        for k in columns[1:]:
            values.append(r[k]['value'] if k in times else r[k])
        table.append(values)
    return {**result, 'format': 'observed_metric_table_v1', 'series': table,
            'common_labels': common, 'label_columns': label_columns, 'columns': columns,
            'shared_times': times, **({'label_values': label_values} if use_dictionary else {}), 'compaction': {
                'format': 'lossless_metric_table_v1', 'source_summary_sha256': digest(rows),
                'input_series_count': len(rows), 'output_series_count': len(table),
                'omitted_series_count': 0,
                'limitation': 'All collected summary rows retained, not all upstream data. Original collection limits still apply. No matching series or zero values do not establish health.'}}


def compact_analysis_context(data, dictionary=False):
    """Named pre-analysis stage; originals and artifact allowlists stay intact."""
    evidence = data.get('evidence', {})
    queries = []
    for q in evidence.get('queries', []):
        if isinstance(q, dict) and q.get('source') in METRIC_SOURCES:
            result = compact_metric_table(q.get('result'), dictionary)
            queries.append({**q, 'result': result} if result is not q.get('result') else q)
        else:
            queries.append(q)
    return {**data, 'evidence': {**evidence, 'queries': queries}}
