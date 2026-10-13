#!/usr/bin/env python3
import json
import sqlite3

DB = '/srv/uptime-kuma/kuma.db'
STATUS_SLUG = 'socrat'
USER_ID = 1
GROUP_NAME = 'Syncthing'
SYNC_MONITORS = [
    # Uptime Kuma runs on socrat-2; check node-local Syncthing GUIs over the
    # Socrat WireGuard mesh instead of via public Traefik ingress. Otherwise a
    # 401 from Traefik/basic-auth can look healthy even when the target
    # Syncthing pod on that node is crash-looping.
    ('Syncthing sync-0', 'http://10.250.0.1:8384/'),
    ('Syncthing sync-1', 'http://10.250.0.3:8384/'),
    ('Syncthing sync-2', 'http://10.250.0.2:8384/'),
]

con = sqlite3.connect(DB)
cur = con.cursor()

status_page_id = cur.execute('select id from status_page where slug=?', (STATUS_SLUG,)).fetchone()[0]

# Keep ordering: core=1, apps=2, Syncthing=3, VPN=4, GitHub=5
for name, weight in [('Socrat core', 1), ('Socrat apps', 2), ('VPN and edge', 4), ('GitHub Pages projects', 5)]:
    cur.execute('update `group` set weight=? where name=? and status_page_id=?', (weight, name, status_page_id))

row = cur.execute('select id from `group` where name=? and status_page_id=?', (GROUP_NAME, status_page_id)).fetchone()
if row:
    group_id = row[0]
    cur.execute('update `group` set public=1, active=1, weight=3 where id=?', (group_id,))
else:
    cur.execute('insert into `group`(name, public, active, weight, status_page_id) values(?,?,?,?,?)', (GROUP_NAME, 1, 1, 3, status_page_id))
    group_id = cur.lastrowid

# Remove old single Syncthing UI monitor from Socrat apps/status page grouping.
old = cur.execute('select id from monitor where name=?', ('Syncthing UI',)).fetchone()
if old:
    old_id = old[0]
    cur.execute('delete from monitor_group where monitor_id=?', (old_id,))
    cur.execute('update monitor set active=0 where id=?', (old_id,))

accepted = json.dumps(['200-499'])
for idx, (name, url) in enumerate(SYNC_MONITORS, 1):
    row = cur.execute('select id from monitor where name=?', (name,)).fetchone()
    vals = dict(
        name=name,
        active=1,
        user_id=USER_ID,
        interval=60,
        retry_interval=30,
        maxretries=2,
        url=url,
        type='http',
        hostname=None,
        port=None,
        maxredirects=10,
        accepted_statuscodes_json=accepted,
        method='GET',
        upside_down=0,
        ignore_tls=0,
        expiry_notification=1,
        description=f'{name} direct node-local Syncthing GUI check',
        timeout=15,
        resend_interval=0,
        weight=300 + idx,
    )
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

    # Ensure monitor belongs only to Syncthing group on the public page.
    cur.execute('delete from monitor_group where monitor_id=?', (mid,))
    cur.execute('insert into monitor_group(monitor_id, group_id, weight, send_url) values(?,?,?,0)', (mid, group_id, idx))

con.commit()

print('Syncthing group id:', group_id)
for row in cur.execute('''select g.weight, g.name, mg.weight, m.name, m.url, m.accepted_statuscodes_json
                          from monitor_group mg
                          join `group` g on g.id=mg.group_id
                          join monitor m on m.id=mg.monitor_id
                          where g.status_page_id=?
                          order by g.weight, mg.weight''', (status_page_id,)):
    print(row)
con.close()
