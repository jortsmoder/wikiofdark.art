# tools/slug.py
import hashlib, sys, urllib.parse, pathlib, re

def slug(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host   = re.sub(r'\W+', '-', parsed.netloc.lower()).strip('-')
    path   = re.sub(r'\W+', '-', parsed.path.strip('/').lower())[:60]
    h      = hashlib.sha1(url.encode()).hexdigest()[:10]
    return f"{host}__{path or 'root'}__{h}.html"

if __name__ == "__main__":
    print(slug(sys.argv[1]))

