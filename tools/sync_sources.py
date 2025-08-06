"""
Scan every Markdown file under docs/, find links marked `.source-link`,
and make sure a local archive exists in docs/sources/.
"""
import pathlib, re, subprocess, sys, slug, fetch, argparse

DOCS  = pathlib.Path("docs")
OUT   = DOCS / "sources"
LINK  = re.compile(r'\[.*?\]\((https?://[^\s\)]+)\)\{[^}]*?\.source-link[^}]*?}')

def main(force: bool):
    urls = set()
    for md in DOCS.rglob("*.md"):
        for m in LINK.finditer(md.read_text()):
            urls.add(m.group(1))

    for url in sorted(urls):
        fetch.archive(url, OUT, force)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if local copy exists")
    args = ap.parse_args()
    main(args.force)

