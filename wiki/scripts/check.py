import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.ids = set()
        self.robots = ""
        self.editor_path = None
        self.editor_hidden = False
        self.editor_dialog = False
        self.textarea = False
        self.redirect = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") == "wiki-editor":
            self.editor_path = attrs.get("data-path")
            self.editor_hidden = "hidden" in attrs
        if tag == "dialog" and attrs.get("id") == "wiki-editor-dialog":
            self.editor_dialog = True
        if tag == "textarea":
            self.textarea = True
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "meta" and attrs.get("name") == "robots":
            self.robots = attrs.get("content", "")
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            match = re.fullmatch(r"0;\s*url=(.+)", attrs.get("content", ""))
            self.redirect = match.group(1) if match else "invalid"
        for name in ("href", "src"):
            if attrs.get(name):
                self.links.append(attrs[name])


root = Path(sys.argv[1]).resolve()
pages = {p: Page(p.read_text()) for p in root.rglob("*.html")}
errors = []
for path, page in pages.items():
    if not {"noindex", "nofollow"}.issubset(set(page.robots.replace(" ", "").split(","))):
        errors.append(f"Missing robots policy: {path.relative_to(root)}")
    if page.redirect:
        destination = urlsplit(page.redirect)
        if destination.scheme != "https" or destination.netloc != "wiki.alchemmist.xyz" or page.editor_path:
            errors.append(f"Invalid alias redirect: {path.relative_to(root)}")
        page.links.append(page.redirect)
    elif path.name != "404.html":
        if not page.editor_path or not page.editor_hidden or page.editor_dialog or page.textarea:
            errors.append(f"Missing protected editor mapping: {path.relative_to(root)}")
        elif not (root.parent / "content" / page.editor_path).is_file():
            errors.append(f"Editor source does not exist: {page.editor_path}")
    page_url = "/" + path.relative_to(root).as_posix().removesuffix("index.html")
    for link in page.links:
        url = urlsplit(urljoin(page_url, link))
        if url.scheme or url.netloc:
            if url.netloc != "wiki.alchemmist.xyz":
                continue
        target = (root / unquote(url.path).lstrip("/")).resolve()
        if not target.is_relative_to(root):
            errors.append(f"Link escapes publication: {link}")
            continue
        if target.is_dir():
            target /= "index.html"
        if not target.exists():
            errors.append(f"Broken link in {path.relative_to(root)}: {link}")
        elif url.fragment and target in pages:
            visited = set()
            while target in pages and pages[target].redirect and target not in visited:
                visited.add(target)
                target = (root / unquote(urlsplit(pages[target].redirect).path).lstrip('/')).resolve()
                if target.is_dir():
                    target /= 'index.html'
            if target not in pages or unquote(url.fragment) not in pages[target].ids:
                errors.append(f"Missing anchor in {path.relative_to(root)}: {link}")
for forbidden in ("sitemap.xml", "index.xml", "docs", "ansible", "go.mod", "hugo.toml"):
    if (root / forbidden).exists():
        errors.append(f"Unexpected published file: {forbidden}")
index = json.loads((root / "search-index.json").read_text())
if not index or not re.search(r"[А-Яа-я]", json.dumps(index, ensure_ascii=False)):
    errors.append("Search index missing Russian content")
if not (root / "404.html").exists():
    errors.append("Missing custom 404")
version = json.loads((root / "version.json").read_text())
if not re.fullmatch(r"local|[0-9a-f]{40}", version.get("source_sha", "")):
    errors.append("Invalid build metadata")
if errors:
    raise SystemExit("\n".join(errors))
print(f"Checked {len(pages)} HTML pages, internal links, Russian search, robots and publication boundaries")
