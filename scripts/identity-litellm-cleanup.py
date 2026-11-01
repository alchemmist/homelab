"""Internal smoke helper. Caller supplies the just-created fixture's exact UUID."""
import json
import os
import subprocess
import uuid

assert target.startswith('authentik:')
uuid.UUID(target.split(':', 1)[1])
os.environ['K3S_CONFIG_FILE'] = '/dev/null'
code = '''import asyncio
from prisma import Prisma
async def main():
 db=Prisma();await db.connect()
 try:
  await db.execute_raw('DELETE FROM "LiteLLM_VerificationToken" WHERE user_id=$1', target)
  await db.execute_raw('DELETE FROM "LiteLLM_UserTable" WHERE user_id=$1', target)
 finally:await db.disconnect()
asyncio.run(main())
'''
code = 'target=' + repr(target) + '\n' + code
result = subprocess.run(['kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml', '-n', 'llm',
                         'exec', '-i', 'deployment/litellm', '--', 'python', '-'],
                        input=code.encode(), capture_output=True)
if result.returncode:
    raise RuntimeError('Fixture database cleanup failed; details suppressed')
print('Temporary LiteLLM identity, session keys and admission binding removed')
