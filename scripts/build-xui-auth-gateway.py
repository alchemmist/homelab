#!/usr/bin/env python3
"""Regenerate only the public, reviewed x-ui gateway manifest; no deployment."""
import os
from pathlib import Path
import json,yaml
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
image=json.load(open('deploy/authentik/quiet-mono/static-image.json'))['image']
icon=Path('deploy/xui-auth-gateway/xui-icon.png').read_bytes()
icon_name=__import__('hashlib').sha256(icon).hexdigest()[:12]+'.png'
config='''worker_processes 1;
pid /tmp/nginx.pid;
error_log /dev/stderr crit;
events { worker_connections 256; }
http {
 access_log off;
 server_tokens off;
 client_body_temp_path /tmp/client_temp;
 proxy_temp_path /tmp/proxy_temp;
 fastcgi_temp_path /tmp/fastcgi_temp;
 uwsgi_temp_path /tmp/uwsgi_temp;
 scgi_temp_path /tmp/scgi_temp;
 map $http_upgrade $connection_upgrade { default upgrade; '' close; }
 # Only canonical Bearer API calls may avoid interactive authentication.
 map "$uri|$http_authorization" $machine_api {
  default 0;
  ~^/[^/]+/panel/api/[^|]*\\|Bearer\\ [A-Za-z0-9._~+/-]+=*$ 1;
 }
 upstream panel { server 10.250.0.2:18082; }
 resolver 10.43.0.10 valid=30s ipv6=off;
 resolver_timeout 5s;
 server {
  listen 8080;
  server_name vpn.alchemmist.xyz;
  set $authentik_backend http://authentik-server.identity.svc.cluster.local:80;
  client_max_body_size 32m;
  proxy_http_version 1.1;
  proxy_set_header Host vpn.alchemmist.xyz;
  proxy_set_header X-Forwarded-Host vpn.alchemmist.xyz;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection $connection_upgrade;
  proxy_read_timeout 3600s;
  proxy_buffering off;
  proxy_cookie_flags ~ secure;
  location = /-/xui-brand/__ICON__ {
   alias /etc/nginx/xui-icon.png;
   default_type image/png;
   add_header Cache-Control "public, max-age=31536000, immutable";
   add_header X-Content-Type-Options nosniff always;
   limit_except GET HEAD { deny all; }
  }
  location = /healthz { return 200 "ok\\n"; }
  location = /__ak_auth {
   internal;
   proxy_pass $authentik_backend/outpost.goauthentik.io/auth/nginx;
   proxy_set_header Host vpn.alchemmist.xyz;
   proxy_set_header X-Forwarded-Host vpn.alchemmist.xyz;
   proxy_set_header X-Forwarded-Proto https;
   proxy_pass_request_body off;
   proxy_set_header Content-Length "";
   proxy_set_header X-Original-URL https://vpn.alchemmist.xyz$request_uri;
  }
  location /outpost.goauthentik.io/ { proxy_pass $authentik_backend$request_uri; }
  location @auth_login {
   add_header Set-Cookie $auth_cookie always;
   return 302 https://vpn.alchemmist.xyz/outpost.goauthentik.io/start?rd=https://vpn.alchemmist.xyz$request_uri;
  }
  location @machine {
   # Invalid Bearer must NEVER fall back to a valid native browser cookie.
   proxy_set_header Host vpn.alchemmist.xyz;
   proxy_set_header X-Forwarded-Host vpn.alchemmist.xyz;
   proxy_set_header X-Forwarded-Proto https;
   proxy_set_header Cookie "";
   proxy_pass http://panel;
  }
  location / {
   error_page 418 = @machine;
   if ($machine_api) { return 418; }
   auth_request /__ak_auth;
   auth_request_set $auth_cookie $upstream_http_set_cookie;
   add_header Set-Cookie $auth_cookie always;
   error_page 401 = @auth_login;
   proxy_pass http://panel;
  }
 }
}
'''
config=config.replace('__ICON__',icon_name)
Path('deploy/xui-auth-gateway/nginx.conf').write_text(config)
labels={'app.kubernetes.io/name':'xui-auth-gateway'};meta={'name':'xui-auth-gateway','namespace':'traefik-edge'}
resources=[{'apiVersion':'v1','kind':'ConfigMap','metadata':meta,'data':{'nginx.conf':config},'binaryData':{'xui-icon.png':__import__('base64').b64encode(icon).decode()}},
{'apiVersion':'apps/v1','kind':'Deployment','metadata':meta,'spec':{'replicas':1,'selector':{'matchLabels':labels},'template':{'metadata':{'labels':labels,'annotations':{'checksum/config':__import__('hashlib').sha256(config.encode()).hexdigest()}},'spec':{'automountServiceAccountToken':False,'nodeSelector':{'kubernetes.io/hostname':'socrat-2'},'securityContext':{'runAsNonRoot':True,'runAsUser':101,'runAsGroup':101,'fsGroup':101,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'gateway','image':image,'args':['nginx','-g','daemon off;'],'securityContext':{'readOnlyRootFilesystem':True,'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}},'ports':[{'containerPort':8080,'name':'http'}],'resources':{'requests':{'cpu':'10m','memory':'16Mi'},'limits':{'cpu':'200m','memory':'64Mi'}},'readinessProbe':{'httpGet':{'path':'/healthz','port':'http'}},'livenessProbe':{'httpGet':{'path':'/healthz','port':'http'}},'volumeMounts':[{'name':'config','mountPath':'/etc/nginx/nginx.conf','subPath':'nginx.conf','readOnly':True},{'name':'config','mountPath':'/etc/nginx/xui-icon.png','subPath':'xui-icon.png','readOnly':True},{'name':'tmp','mountPath':'/tmp'}]}],'volumes':[{'name':'config','configMap':{'name':'xui-auth-gateway'}},{'name':'tmp','emptyDir':{'sizeLimit':'32Mi'}}]}}}},
{'apiVersion':'v1','kind':'Service','metadata':meta,'spec':{'selector':labels,'ports':[{'name':'http','port':80,'targetPort':'http'}]}}]
Path('deploy/xui-auth-gateway/resources.yaml').write_text('---\n'.join(yaml.safe_dump(x,sort_keys=False) for x in resources))
