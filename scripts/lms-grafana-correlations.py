"""Run on socrat-0: add a Loki trace-ID link without exposing/rewriting mTLS keys.

Updates only the existing datasource provisioning document in its Secret.
No Secret data is printed, written to disk, or sent back to the operator.
The equivalent rule is maintained in otel-production-grafana.py for rebuilds.
"""
import base64
import json
import subprocess

NAMESPACE = 'cattle-monitoring-system'
SECRET = 'otel-grafana-datasources'
FIELD = {'name': 'TraceID', 'matcherRegex': 'trace_id=([0-9a-f]{32})',
         'datasourceUid': 'tempo', 'url': '$${__value.raw}'}


def configure(document):
    loki = next(source for source in document['datasources'] if source['uid']=='loki')
    data = loki.setdefault('jsonData', {})
    fields = [field for field in data.get('derivedFields', []) if field.get('name')!='TraceID']
    data['derivedFields'] = fields + [FIELD]
    return document


def run():
    result = subprocess.run(['kubectl','-n',NAMESPACE,'get','secret',SECRET,'-o','json'],
                            text=True, capture_output=True, check=True)
    secret = json.loads(result.stdout)
    content = json.loads(base64.b64decode(secret['data']['otel-datasources.yaml']))
    encoded = base64.b64encode(json.dumps(configure(content)).encode()).decode()
    patch = json.dumps({'data': {'otel-datasources.yaml': encoded}})
    result = subprocess.run(['kubectl','-n',NAMESPACE,'patch','secret',SECRET,'--type=merge','--patch-file=/dev/stdin'],
                            input=patch, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Datasource update failed; sensitive response suppressed')
    print(json.dumps({'lokiToTempoDerivedFieldConfigured': True, 'secretValuesLogged': False,
                      'otherDatasourceAndTlsConfigurationPreserved': True}))


if __name__ == '__main__':
    run()
