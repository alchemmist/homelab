#!/usr/bin/env python3
"""Fresh, secret-free, network-denied validation of the OpenHands demo snapshot.

Operator-only; never run candidate code on the operator laptop. Original tests are
from Git, not the agent workspace. Creates only uniquely named temporary resources
in identity and cleans up those exact resources. No PVC/production writes.
"""
import hashlib
import json
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/openhands/agent-canvas:1.41.0@sha256:dcae97b63c9845fd1d4313857af6b10fb5888324a154238c4795ef86233d227c'


def kubectl(*args, data=None):
    return subprocess.check_output(['kubectl', *args], input=data)


def selector_matches(selector, labels):
    if any(labels.get(k) != v for k,v in selector.get('matchLabels',{}).items()):
        return False
    for rule in selector.get('matchExpressions',[]):
        key,op=rule['key'],rule['operator']
        values=rule.get('values',[])
        if op=='In': matches=key in labels and labels[key] in values
        elif op=='NotIn': matches=key not in labels or labels[key] not in values
        elif op=='Exists': matches=key in labels
        elif op=='DoesNotExist': matches=key not in labels
        else: raise ValueError('Unknown label selector operator')
        if not matches:return False
    return True


def resources(name, candidate, original):
    labels = {'app':name,'homelab-app':'openhands-demo-validation'}
    cm = {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':name,'namespace':'identity','labels':labels},'data':{'intervals.py':candidate,'test_intervals.py':original}}
    np = {'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name,'namespace':'identity'},'spec':{'podSelector':{'matchLabels':{'app':name}},'policyTypes':['Ingress','Egress'],'ingress':[],'egress':[]}}
    pod = {'restartPolicy':'Never','automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':'socrat-5'},
           'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
           'volumes':[{'name':'snapshot','configMap':{'name':name}}],
           'containers':[{'name':'validate','image':IMAGE,'imagePullPolicy':'IfNotPresent','command':['python','-B','-m','unittest','-v','test_intervals.py'],'workingDir':'/snapshot',
                          'env':[{'name':'PYTHONDONTWRITEBYTECODE','value':'1'}],
                          'volumeMounts':[{'name':'snapshot','mountPath':'/snapshot','readOnly':True}],
                          'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
                          'resources':{'requests':{'cpu':'25m','memory':'32Mi'},'limits':{'cpu':'200m','memory':'128Mi'}}}]}
    job = {'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name,'namespace':'identity','labels':labels},'spec':{'activeDeadlineSeconds':45,'backoffLimit':0,'ttlSecondsAfterFinished':300,'template':{'metadata':{'labels':labels},'spec':pod}}}
    return cm, np, job


def main():
    base = '/home/openhands/workspace/the-loop-demo/'
    candidate = kubectl('-n','openhands','exec','openhands-0','--','cat',base+'intervals.py').decode()
    original = (ROOT/'services/openhands/the-loop-demo/test_intervals.py.fixture').read_text()
    live_tests = kubectl('-n','openhands','exec','openhands-0','--','cat',base+'test_intervals.py').decode()
    if live_tests != original: raise SystemExit('STOP: agent modified acceptance tests')
    name = 'openhands-demo-validation-'+secrets.token_hex(4)
    cm, np, job = resources(name, candidate, original)
    # NetworkPolicies are additive: an overlapping allow policy defeats deny-all.
    policies=json.loads(kubectl('-n','identity','get','networkpolicy','-o','json'))
    labels=job['spec']['template']['metadata']['labels']
    if any(selector_matches(p['spec']['podSelector'],labels) for p in policies['items']):
        raise SystemExit('STOP: overlapping NetworkPolicy; isolation not established')
    created = []
    try:
        for kind,obj in [('configmap',cm),('networkpolicy',np),('job',job)]:
            kubectl('create','-f','-',data=json.dumps(obj).encode())
            created.append(kind)
        wait = subprocess.run(['kubectl','-n','identity','wait','--for=condition=complete','job/'+name,'--timeout=65s'],capture_output=True)
        logs = kubectl('-n','identity','logs','job/'+name).decode()
        print(logs)
        status = json.loads(kubectl('-n','identity','get','job',name,'-o','json'))['status']
        ok = wait.returncode == 0 and status.get('succeeded') == 1
        report = {'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),'tests_sha256':hashlib.sha256(original.encode()).hexdigest(),
                  'tests_unchanged':True,'fresh_job':name,'independent_success':ok,'credentials':False,'network':'deny-all','readonly_snapshot':True}
        print(json.dumps(report))
        if not ok:raise SystemExit('Independent validation failed')
    finally:
        # Do not remove the isolation policy while any candidate process can run.
        # On deletion failure, retain the policy/snapshot and fail visibly.
        for kind in reversed(created):
            subprocess.run(['kubectl','-n','identity','delete',kind,name,'--cascade=foreground','--wait=true','--timeout=35s','--ignore-not-found'],stdout=subprocess.DEVNULL,check=True)


if __name__ == '__main__': main()
