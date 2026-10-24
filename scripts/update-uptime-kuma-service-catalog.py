#!/usr/bin/env python3
import sqlite3

DB = '/srv/uptime-kuma/kuma.db'
STATUS_SLUG = 'socrat'
SERVICES = {
    'Socrat core': [
        ('Grafana', 'http://kube-prometheus-stack-grafana.cattle-monitoring-system.svc.cluster.local/api/health'),
        ('Prometheus', 'http://kube-prometheus-stack-prometheus.cattle-monitoring-system.svc.cluster.local:9090/-/ready'),
        ('Alertmanager', 'http://kube-prometheus-stack-alertmanager.cattle-monitoring-system.svc.cluster.local:9093/-/ready'),
        ('Grafana MCP', 'http://monitoring-grafana-mcp-health.cattle-monitoring-system.svc.cluster.local:8080/healthz'),
    ],
    'Socrat apps': [
        ('LiteLLM', 'https://llm.alchemmist.xyz/'),
        ('Open WebUI', 'https://chat.alchemmist.xyz/'),
    ],
}

con = sqlite3.connect(DB)
cur = con.cursor()
status_page_id = cur.execute('select id from status_page where slug=?', (STATUS_SLUG,)).fetchone()[0]
for group_name, monitors in SERVICES.items():
    group_id = cur.execute('select id from `group` where name=? and status_page_id=?', (group_name, status_page_id)).fetchone()[0]
    for index, (name, url) in enumerate(monitors, 1):
        row = cur.execute('select id from monitor where name=?', (name,)).fetchone()
        if row:
            monitor_id = row[0]
            cur.execute('update monitor set active=1,url=?,type="http",method="GET",accepted_statuscodes_json=? where id=?', (url, '["200"]', monitor_id))
        else:
            cur.execute('''insert into monitor(name,active,user_id,interval,retry_interval,maxretries,url,type,weight,maxredirects,accepted_statuscodes_json,method,timeout)
                values(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (name,1,1,60,30,2,url,'http',100+index,5,'["200"]','GET',30))
            monitor_id = cur.lastrowid
        cur.execute('delete from monitor_group where monitor_id=?', (monitor_id,))
        cur.execute('insert into monitor_group(monitor_id,group_id,weight,send_url) values(?,?,?,0)', (monitor_id,group_id,index+20))
con.commit()
print('updated catalog:', ', '.join(name for values in SERVICES.values() for name, _ in values))
con.close()
