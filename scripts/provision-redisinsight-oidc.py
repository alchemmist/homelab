#!/usr/bin/env python3
"""Owner-only Redis Insight OIDC registration; same guarded protocol as pgAdmin."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('oidc', Path(__file__).with_name('provision-pgadmin-oidc.py'))
oidc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oidc)
oidc.HOST = 'redis.socrat.alchemmist.xyz'
oidc.CLIENT = 'socrat-redisinsight'
oidc.APP.update(name='Redis Insight', slug='redisinsight', meta_launch_url='https://' + oidc.HOST + '/',
                meta_description='Owner-only shared Redis browser.')
oidc.PROVIDER.update(name='homelab-redisinsight', client_id=oidc.CLIENT,
                     redirect_uris=[{'matching_mode':'strict','url':'https://' + oidc.HOST + '/oauth2/callback'}])
if __name__ == '__main__':
    oidc.main(namespace='redis')
