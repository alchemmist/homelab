"""Keep Explore deep links usable with Grafana's anonymous dashboard access.

Anonymous Viewer can view the home dashboard but cannot open Explore. Without
forceLogin Grafana redirects there and drops the incident query/time. Use the
native login/return flow; do not widen anonymous or user permissions.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ORIGIN = "grafana.socrat.alchemmist.xyz"


def require_explore_login(url: str) -> str:
    """Pivot Explore links onto the reviewed login/return flow, else pass through."""
    parts = urlsplit(url)
    if (parts.scheme, parts.netloc, parts.path) != ("https", ORIGIN, "/explore"):
        return url
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "forceLogin"
    ]
    # Last is intentional: Grafana removes this parameter from the return URL.
    pairs.append(("forceLogin", "true"))
    return urlunsplit(parts._replace(query=urlencode(pairs)))


def repair_markdown_links(body: str) -> str:
    """Rewrite rendered Markdown Explore links; never touch checksummed JSON."""
    # Only rendered Markdown links; never rewrite checksummed artifact JSON.
    return re.sub(
        r"\]\((https://grafana\.socrat\.alchemmist\.xyz/explore\?[^\s)]+)\)",
        lambda match: "](" + require_explore_login(str(match.group(1))) + ")",
        body,
    )
