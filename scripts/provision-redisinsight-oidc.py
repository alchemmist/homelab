#!/usr/bin/env python3
"""Redis Insight OIDC registration; same guarded protocol as pgAdmin."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("oidc", Path(__file__).with_name("provision-pgadmin-oidc.py"))
oidc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oidc)
oidc.HOST = "redis.socrat.alchemmist.xyz"
oidc.CLIENT = "socrat-redisinsight"
oidc.APP.update(name="Redis Insight", slug="redisinsight", meta_launch_url="https://" + oidc.HOST + "/",
                meta_description="Owner-only shared Redis browser.")
oidc.PROVIDER.update(name="homelab-redisinsight", client_id=oidc.CLIENT,
                     redirect_uris=[{"matching_mode":"strict","url":"https://" + oidc.HOST + "/oauth2/callback"}])
READERS = 'redisinsight-readers'
ATTRS = {'homelab_public_web_role': READERS}


def reader_group(api):
    group = oidc.iam.one(api, 'core/groups/', 'name', READERS)
    if group:
        oidc.check(group['attributes'] == ATTRS and group['is_superuser'] is False
                   and all(group[k] == [] for k in ('parents', 'children', 'roles')),
                   'Unexpected privileged or foreign readers group')
    return group


def extra_bindings(api, app):
    group = reader_group(api)
    bindings = api.rows('policies/bindings/?target=' + str(app['pk']))
    return {READERS: group['pk']} if group and any(b.get('group') == group['pk'] for b in bindings) else {}


if __name__ == '__main__':
    oidc.main(namespace='redis', extra_bindings=extra_bindings)
