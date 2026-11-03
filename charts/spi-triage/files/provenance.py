"""Read-only, allowlisted workload metadata. Never export pod specs or env values."""
import json
import re
import ssl
import time
import urllib.request
import urllib.error
from pathlib import Path
from core import Failure
SAFE=re.compile(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z')
ROOT=Path('/var/run/secrets/kubernetes.io/serviceaccount')

class DeploymentCollector:
    def __init__(self,http=None,github=None,reader=None):self.http=http;self.github=github;self.reader=reader
    def get(self,path):
        if self.reader:return self.reader(path)
        if not (ROOT/'token').exists():raise Failure('KUBERNETES_READ_IDENTITY_MISSING')
        from integrations import NoRedirect, REQUEST_DEADLINE
        remaining=getattr(REQUEST_DEADLINE,'at',time.monotonic()+12)-time.monotonic()
        if remaining<1:raise Failure('REQUEST_BUDGET_EXCEEDED')
        opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(ROOT/'ca.crt'))),NoRedirect())
        request=urllib.request.Request('https://kubernetes.default.svc'+path,headers={'Authorization':'Bearer '+(ROOT/'token').read_text().strip()})
        try:
            with opener.open(request,timeout=min(12,remaining))as response:
                raw=response.read(2000001)
                if len(raw)>2000000:raise Failure('KUBERNETES_RESPONSE_TOO_LARGE')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:raise Failure('KUBERNETES_HTTP_'+str(exc.code))from None
        except (OSError,ValueError):raise Failure('KUBERNETES_READ_FAILED')from None
    def collect(self,event):
        labels=event.get('labels',{});namespace=labels.get('namespace')or labels.get('k8s_namespace_name');pod=labels.get('pod')or labels.get('k8s_pod_name')
        job=labels.get('job_name');unit=labels.get('name')or labels.get('systemd_unit')
        result={'artifacts':[],'missing':[]}
        if unit or not namespace:
            result['missing'].append({'source':'deployed_source','reason':'HOST_INSTALLED_VERSION_NOT_EXPOSED' if unit else 'WORKLOAD_NAMESPACE_UNKNOWN'});return result
        if not SAFE.fullmatch(namespace)or len(namespace)>63 or any(not SAFE.fullmatch(x)for x in (pod,job)if x):
            result['missing'].append({'source':'deployed_source','reason':'INVALID_WORKLOAD_SCOPE'});return result
        try:
            root='/api/v1/namespaces/'+namespace
            if job:
                from urllib.parse import quote
                data=self.get(root+'/pods?limit=6&labelSelector='+quote('job-name='+job,safe=''));pods=data.get('items',[])[:5]
                if len(data.get('items',[]))>5 or data.get('metadata',{}).get('continue'):result['missing'].append({'source':'deployed_source','reason':'POD_SAMPLE_TRUNCATED_AT_FIVE'})
            elif pod:pods=[self.get(root+'/pods/'+pod)]
            else:
                result['missing'].append({'source':'deployed_source','reason':'AFFECTED_POD_UNKNOWN_EXPORTER_NOT_ASSUMED'});return result
            records=[]
            for raw in pods:
                record=self.project(raw);owners=raw.get('metadata',{}).get('ownerReferences',[])[:1];chain=[]
                for _ in range(3):
                    if not owners:break
                    owner=owners[0];kind=owner.get('kind');name=owner.get('name','')
                    resources={'ReplicaSet':('apps/v1','replicasets'),'Deployment':('apps/v1','deployments'),'StatefulSet':('apps/v1','statefulsets'),'DaemonSet':('apps/v1','daemonsets'),'Job':('batch/v1','jobs'),'CronJob':('batch/v1','cronjobs')}
                    if kind not in resources or not SAFE.fullmatch(name):break
                    group,resource=resources[kind];obj=self.get('/apis/'+group+'/namespaces/'+namespace+'/'+resource+'/'+name)
                    chain.append(self.project(obj));owners=obj.get('metadata',{}).get('ownerReferences',[])[:1]
                record['owner_chain']=chain;records.append(record)
            result['artifacts'].append({'id':'deployment','name':'deployed-workload.json','media_type':'application/json','content':{'collected_at':int(time.time()),'namespace':namespace,'workloads':records,
                'limitations':['Observed now, not a historical snapshot. A pod may have changed since the incident.','Image IDs establish running image digest. Tags and revision labels alone do not verify source commit.']},'source':{'kind':'Kubernetes read-only API','namespace':namespace,'pod':pod,'job_name':job}})
            for record in records:
                for container in record.get('containers',[]):
                    proof=self.image_source(container)
                    if proof:result['artifacts'].append(proof)
            if not records:result['missing'].append({'source':'deployed_source','reason':'NO_CURRENT_PODS_FOR_INCIDENT'})
            result['missing'].append({'source':'deployed_source','reason':'SOURCE_UNVERIFIED_UNLESS_OCI_PROOF_PRESENT'})
        except Failure as exc:result['missing'].append({'source':'deployed_source','reason':exc.code})
        return result
    @staticmethod
    def project(obj):
        meta=obj.get('metadata',{});status=obj.get('status',{});spec=obj.get('spec',{});template=spec.get('template',{})
        containers=spec.get('containers',template.get('spec',{}).get('containers',[]))
        statuses={x.get('name'):x for x in status.get('containerStatuses',[])}
        labels={k:v for k,v in meta.get('labels',{}).items()if k in ('app','app.kubernetes.io/name','app.kubernetes.io/version','pod-template-hash','controller-revision-hash','org.opencontainers.image.revision')}
        return {'kind':obj.get('kind'),'name':meta.get('name'),'uid':meta.get('uid'),'created_at':meta.get('creationTimestamp'),'labels':labels,'phase':status.get('phase'),
            'deployment_revision':meta.get('annotations',{}).get('deployment.kubernetes.io/revision'),
            'containers':[{'name':c.get('name'),'image':c.get('image'),'imageID':statuses.get(c.get('name'),{}).get('imageID'),'restartCount':statuses.get(c.get('name'),{}).get('restartCount'),
              'state':{k:{x:v for x,v in details.items()if x in ('reason','exitCode','startedAt','finishedAt','signal')}for k,details in statuses.get(c.get('name'),{}).get('state',{}).items()if isinstance(details,dict)}}for c in containers[:10]]}
    def image_source(self,container):
        if not self.http:return None
        image=container.get('image','');identity=container.get('imageID')or''
        match=re.fullmatch(r'harbor\.socrat\.alchemmist\.xyz/(homelab/[A-Za-z0-9_.-]+)(?::[^/@]+)?(?:@sha256:[0-9a-f]{64})?',image)
        digest=re.search(r'sha256:[0-9a-f]{64}',identity)
        if not match or not digest:return None
        repository=match[1];base='https://harbor.socrat.alchemmist.xyz';source={'imageID':identity,'repository':repository}
        try:
            # Anonymous pull token only: never fetch Kubernetes imagePullSecrets.
            from urllib.parse import urlencode
            grant=self.http.request('GET',base+'/service/token?'+urlencode({'service':'harbor-registry','scope':'repository:'+repository+':pull'}),timeout=10,limit=20000)
            token=grant.get('token')or grant.get('access_token');headers={'Authorization':'Bearer '+token}if token else {}
            headers['Accept']='application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.index.v1+json'
            manifest=self.http.request('GET',base+'/v2/'+repository+'/manifests/'+digest[0],headers,timeout=10,limit=100000)
            if 'manifests'in manifest:
                chosen=next((x['digest']for x in manifest['manifests']if x.get('platform',{}).get('os')=='linux'and x.get('platform',{}).get('architecture')=='amd64'),None)
                if not chosen or not re.fullmatch(r'sha256:[a-f0-9]{64}',chosen):raise Failure('OCI_PLATFORM_UNKNOWN')
                manifest=self.http.request('GET',base+'/v2/'+repository+'/manifests/'+chosen,headers,timeout=10,limit=100000)
            config=manifest.get('config',{}).get('digest','')
            if not re.fullmatch(r'sha256:[a-f0-9]{64}',config):raise Failure('OCI_CONFIG_MISSING')
            raw=self.http.request('GET',base+'/v2/'+repository+'/blobs/'+config,headers,timeout=10,limit=200000)
            import hashlib
            # Registry JSON reserialization is not byte-identical: record registry claim, not cryptographic binary/source equivalence.
            labels=raw.get('config',{}).get('Labels')or{};revision=labels.get('org.opencontainers.image.revision','');url=labels.get('org.opencontainers.image.source','')
            proof={'imageID':identity,'config_digest':config,'oci_revision':revision if re.fullmatch(r'[a-f0-9]{40}',revision)else None,
                'source_repository':url if re.fullmatch(r'https://github.com/alchemmist/[A-Za-z0-9_.-]+',url)else None,
                'association':'OCI metadata from digest-addressed deployed image','source_equivalence_proven':False,
                'limitation':'OCI labels attest a build claim, not reproducible-build proof. Source commit is unknown if labels are absent.'}
            return {'id':'oci-'+repository.split('/')[-1],'name':'image-source-'+repository.split('/')[-1]+'.json','content':proof,'source':source}
        except Failure as exc:return {'id':'oci-gap','name':'image-source-gap.json','content':{'reason':exc.code,'limitation':'Source could not be established; do not substitute main.'},'source':source}
