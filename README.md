# Wiki of Dark Arts

This is the git repo for [https://wikiofdark.art/](https://wikiofdark.art/).

Make changes to docs/index.md for updates to the wiki.

If adding sources, add them as such:
```
non-archival link

[text here](https://example.com/)

archival link

[text here](https://example.com/){.source-link}

```

if archiving new links, you can pull them using 
```
python3 ./tools/sync_sources.py
```
