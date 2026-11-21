"""Credential-free GitHub REST reader for one public repo; MCP SDK from Canvas image."""
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("monori-github-read")
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args): return None


def read(path: str):
    req = Request("https://api.github.com/repos/alchemmist/monori/" + path,
                  headers={"User-Agent":"socrat-monori-review","Accept":"application/vnd.github+json"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=12) as r:
        b = r.read(2_000_001)
        if len(b)>2_000_000: raise ValueError("Response too large; not complete")
        return json.loads(b), 'rel="next"' in r.headers.get("Link","")


def positive(n: object) -> int:
    if type(n) is not int or not 1<=n<=1_000_000_000: raise ValueError("Positive ID/page required")
    return n


@mcp.tool()
def issue(number:int)->dict:
    """Read a Monori issue, returning a bounded excerpt."""
    x,_=read(f"issues/{positive(number)}");
    body=x.get("body") or ""
    return {"number": x["number"],"title": x["title"],"state": x["state"],"comments": x["comments"],"body": body[:3500],"truncated": len(body)>3500}


@mcp.tool()
def pr(number:int, section:str="summary", page:int=1)->dict:
    """Read a Monori PR: summary, files, reviews, comments, checks or statuses. Pages of five. Not a readiness verdict."""
    n=positive(number);
    pg=positive(page);
    base=f"pulls/{n}";
    x,_=read(base);
    sha=x["head"]["sha"]
    if section=="summary":return {"number": n,"title": x["title"],"state": x["state"],"draft": x["draft"],"merged": x["merged"],"head": sha,"base": x["base"]["ref"]}
    paths={"files":base+"/files","reviews":base+"/reviews","comments":base+"/comments","checks":f"commits/{sha}/check-runs","statuses":f"commits/{sha}/statuses"}
    if section not in paths:raise ValueError("Unknown read section")
    data,more=read(paths[section]+f"?per_page=5&page={pg}");
    rows=[]
    for item in data["check_runs"] if section=="checks" else data:
        fields=("id","filename","path","status","state","conclusion","name","context","commit_id","line","in_reply_to_id","additions","deletions")
        row={k:item[k] for k in fields if k in item};
        row["author"]=(item.get("user") or {}).get("login");
        text=(item.get("patch") if section=="files" else item.get("body")) or "";
        row.update(excerpt=text[:800],truncated=len(text)>800);
        rows.append(row)
    return {"head": sha,"page": pg,"more": more,"items": rows}

if __name__=="__main__":mcp.run()
