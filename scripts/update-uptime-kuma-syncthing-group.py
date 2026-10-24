#!/usr/bin/env python3
import datetime
import json
import shutil
import sqlite3

DB = '/srv/uptime-kuma/kuma.db'
STATUS_SLUG = 'socrat'
USER_ID = 1
SYNC_MONITORS = [
    ('Syncthing sync-0', 'http://10.250.0.1:18444/healthz'),
]

con = sqlite3.connect(DB)
cur = con.cursor()
status_page_id = cur.execute('select id from status_page where slug=?', (STATUS_SLUG,)).fetchone()[0]
apps_group_id = cur.execute(
    'select id from `group` where name=? and status_page_id=?',
    ('Socrat apps', status_page_id),
).fetchone()[0]

backup = DB + '.before-syncthing-apps-' + datetime.datetime.now().strftime('%Y%m%d%H%M%S')
shutil.copy2(DB, backup)

syncthing_group = cur.execute(
    'select id from `group` where name=? and status_page_id=?',
    ('Syncthing', status_page_id),
).fetchone()
if syncthing_group:
    cur.execute('delete from monitor_group where group_id=?', (syncthing_group[0],))
    cur.execute('delete from `group` where id=?', (syncthing_group[0],))

accepted = json.dumps(['200'])
desired_names = {name for name, _url in SYNC_MONITORS}
for stale_id, stale_name in cur.execute("select id, name from monitor where name like 'Syncthing sync-%'").fetchall():
    if stale_name not in desired_names:
        cur.execute('delete from monitor_group where monitor_id=?', (stale_id,))
        cur.execute('delete from heartbeat where monitor_id=?', (stale_id,))
        cur.execute('delete from monitor where id=?', (stale_id,))

for idx, (name, url) in enumerate(SYNC_MONITORS, 1):
    row = cur.execute('select id from monitor where name=?', (name,)).fetchone()
    vals = dict(name=name, active=1, user_id=USER_ID, interval=60, retry_interval=30,
                maxretries=2, url=url, type='http', hostname=None, port=None,
                maxredirects=10, accepted_statuscodes_json=accepted, method='GET',
                upside_down=0, ignore_tls=0, expiry_notification=1,
                description='Private node-local Syncthing health check', timeout=30,
                resend_interval=0, weight=300 + idx)
    if row:
        mid = row[0]
        cur.execute('''update monitor set active=:active,user_id=:user_id,interval=:interval,retry_interval=:retry_interval,
            maxretries=:maxretries,url=:url,type=:type,hostname=:hostname,port=:port,maxredirects=:maxredirects,
            accepted_statuscodes_json=:accepted_statuscodes_json,method=:method,upside_down=:upside_down,ignore_tls=:ignore_tls,
            expiry_notification=:expiry_notification,description=:description,timeout=:timeout,resend_interval=:resend_interval,weight=:weight
            where id=:id''', {**vals, 'id': mid})
    else:
        cur.execute('''insert into monitor(name,active,user_id,interval,retry_interval,maxretries,url,type,hostname,port,
            maxredirects,accepted_statuscodes_json,method,upside_down,ignore_tls,expiry_notification,description,timeout,resend_interval,weight)
            values(:name,:active,:user_id,:interval,:retry_interval,:maxretries,:url,:type,:hostname,:port,
            :maxredirects,:accepted_statuscodes_json,:method,:upside_down,:ignore_tls,:expiry_notification,:description,:timeout,:resend_interval,:weight)''', vals)
        mid = cur.lastrowid
    cur.execute('delete from monitor_group where monitor_id=?', (mid,))
    cur.execute('insert into monitor_group(monitor_id, group_id, weight, send_url) values(?,?,?,1)', (mid, apps_group_id, idx + 20))

con.commit()
print('Syncthing monitor moved to Socrat apps; backup:', backup)
for row in cur.execute('''select g.name, m.name, m.url from monitor_group mg join `group` g on g.id=mg.group_id join monitor m on m.id=mg.monitor_id where g.status_page_id=? and m.name like 'Syncthing%' order by g.name, m.name''', (status_page_id,)):
    print(row)
con.close()
