#!/usr/bin/env python3
"""Read-only operational summary; never prints credentials or candidate source."""
import subprocess

CODE = '''
import sqlite3,json
c=sqlite3.connect('file:/state/queue.sqlite?mode=ro',uri=True)
for row in c.execute('SELECT id,lane,state,pr,result,review FROM runs ORDER BY created DESC LIMIT 12'):
    work=json.loads(row[4] or '{}');review=json.loads(row[5] or '{}')
    print(json.dumps({'id':row[0],'lane':row[1],'state':row[2],'pr':row[3],
      'agent_status':work.get('agent_status'),'baseline':work.get('baseline'),'checks':work.get('checks'),
      'error':work.get('error') or review.get('error'),'review':review.get('review')},ensure_ascii=False))
'''
subprocess.run(['kubectl', '-n', 'swe-mini', 'get', 'deployment,pods,jobs,pvc'], check=True)
subprocess.run(['kubectl', '-n', 'swe-mini', 'exec', 'deployment/swe-mini-controller', '--', 'python', '-c', CODE], check=True)
