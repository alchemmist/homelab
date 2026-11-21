"""Bounded authorized Actions log read. Never forward credential across redirect or return full logs."""
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request,build_opener

def extract(n,head,api,no_redirect,check):
 files=api(f"pulls/{n}/files?per_page=20");check(len(files)==1 and files[0]["status"]=="added");dest=files[0]["filename"];check(re.fullmatch(r"(ci/tests|server/tests/unit)/test_[\w]+\.py",dest));runs=api("commits/"+head+"/check-runs?per_page=100");out=[];summaries=[]
 for r in runs["check_runs"]:
  if r.get("conclusion")!="failure":continue
  m=re.fullmatch(r"https://github.com/alchemmist/monori/actions/runs/\d+/job/(\d+)",r.get("details_url") or "");
  if not m:continue
  job=api("actions/jobs/"+m[1]);check(job["head_sha"]==head);op=build_opener(no_redirect());req=Request("https://api.github.com/repos/alchemmist/monori/actions/jobs/"+m[1]+"/logs",headers={"Authorization":"Bearer "+Path("/credential/token").read_text().strip(),"User-Agent":"mutation-pr-lifecycle"});
  try:resp=op.open(req,timeout=10)
  except HTTPError as e:
   if e.code not in (301,302,303,307,308):continue
   loc=e.headers.get("Location","");u=urlparse(loc);check(u.scheme=="https" and not u.username and not u.password and u.port in (None,443) and (u.hostname or "").endswith((".blob.core.windows.net",".actions.githubusercontent.com")));resp=op.open(Request(loc),timeout=10)
  with resp:lines=resp.read(4*1024*1024).decode("utf8","replace").splitlines()
  for line in lines:
   line=re.sub(r"^\S+Z\s+|\x1b\[[0-9;]*m","",line);line=re.sub(r"https?://\S+","[link]",line)
   if re.search(r"token|password|secret|authorization|gh[pousr]_|github_pat_|bearer|cookie|@",line,re.I):continue
   if re.search(r"failed|error|\b[A-Z]{1,5}\d{3}\b",line,re.I):
    if dest in line and len(out)<10:out.append(r["name"]+": "+line[:220]);
    elif len(summaries)<6:summaries.append(r["name"]+": "+line[:180])
 return {"owned":out,"other":summaries}
