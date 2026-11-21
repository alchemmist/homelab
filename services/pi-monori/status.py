"""Read-only operator status on the SSH node (stdlib only, no leaked candidate code)."""
import json,pathlib,sqlite3
p=pathlib.Path(__file__).resolve().parent/"campaign.sqlite";d=sqlite3.connect("file:"+str(p)+"?mode=ro",uri=True)
print(json.dumps({"counts":dict(d.execute("select state,count(*) from tasks group by state")),"published":list(d.execute("select pr,id,state from tasks where pr is not null order by pr desc limit 12")),"recent":list(d.execute("select datetime(t,'unixepoch'),state,id from audit order by rowid desc limit 6"))},ensure_ascii=False))
