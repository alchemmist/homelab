"""Run inside the pinned proxy image, on the disposable private network only."""
import asyncio
import os
from urllib.parse import urlencode

from litellm.proxy.proxy_server import ProxyConfig
from redis.exceptions import AuthenticationError, ConnectionError


async def test(mode):
    host = 'wrong-name' if mode == 'wrong-name' else 'redis-common'
    ca = '/probe/other.crt' if mode == 'wrong-ca' else '/probe/ca.crt'
    password = 'incorrect' if mode == 'bad-auth' else 'fixture'
    query = urlencode(dict(ssl_ca_certs=ca, ssl_check_hostname='true', ssl_cert_reqs='required'))
    os.environ['TEST_REDIS_URL'] = f'rediss://litellm:{password}@{host}:6379/0?{query}'
    cache = ProxyConfig()._init_coordination_redis({'general_settings': {
        'coordination_redis': {'url': 'os.environ/TEST_REDIS_URL'}}})
    client = cache.init_async_client()
    try:
        await client.ping()
    except AuthenticationError:
        if mode != 'bad-auth':
            raise
    except ConnectionError as exc:
        if mode not in ('wrong-name', 'wrong-ca') or 'CERTIFICATE_VERIFY_FAILED' not in str(exc):
            raise
    else:
        assert mode in ('first', 'second'), f'{mode} unexpectedly connected'
        assert await client.incr('probe:shared') == (1 if mode == 'first' else 2)
    finally:
        await client.aclose()
    print('PASS', mode)


async def main():
    for mode in os.environ["MODES"].split(","):
        await test(mode)


asyncio.run(main())
