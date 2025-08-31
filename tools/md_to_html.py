#!/usr/bin/env python3
"""
md_to_html.py

Convert a Markdown file (.md) to an HTML file (.html) wrapped in a specific
template including base target, styles, archive header, and title.

Usage:
  python wiki/tools/md_to_html.py INPUT.md [-o OUTPUT.html]
      [--title TITLE] [--archived YYYY-MM] [--source SOURCE]
      [--no-extract-title] [--base-target _blank]

Defaults:
  - title: first H1 in the markdown (or filename stem if none)
  - archived: current UTC year-month (YYYY-MM)
  - source: ""
  - base-target: _blank

Requires the 'Markdown' package:
  pip install markdown
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html as _html
import sys
from pathlib import Path
from textwrap import indent as _indent

try:
    import markdown as _md
except Exception as exc:  # pragma: no cover
    print(
        "Error: Python package 'markdown' is required. Install with: pip install markdown",
        file=sys.stderr,
    )
    raise


CSS_BLOCK = (
    """
    body{font-family:system-ui,sans-serif;max-width:50rem;margin:2rem auto;line-height:1.6;padding:1rem}
    img,iframe{max-width:100%}
    .post-content{background:#f9f9f9;padding:1rem;border-radius:5px;margin:1rem 0}
    .archive-header{background:#f0f8ff;border:1px solid #e0e0e0;border-radius:5px;padding:0.75rem;margin-bottom:1rem;font-size:0.9rem}
    .archive-info{margin-bottom:0.5rem;color:#666}
    .archive-source{color:#666}
    .archive-header a{color:#007acc;text-decoration:none}
    .archive-header a:hover{text-decoration:underline}
    @media (prefers-color-scheme: dark) {
        .archive-header{background:#1a1a2e;border-color:#333;color:#e0e0e0}
        .archive-info, .archive-source{color:#ccc}
        .archive-header a{color:#66b3ff}
    }
    """
    .strip()
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def extract_title(markdown_text: str) -> tuple[str | None, str]:
    """Return (title, remaining_markdown).

    Finds the first ATX-style H1 (lines starting with '# ') and removes that
    line from the markdown body. If none found, returns (None, original).
    """
    lines = markdown_text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            remaining = lines[:idx] + lines[idx + 1 :]
            # Drop one following blank line if present
            if idx < len(remaining) and remaining[idx : idx + 1] == [""]:
                remaining = remaining[:idx] + remaining[idx + 1 :]
            return title, "\n".join(remaining)
    return None, markdown_text


def render_markdown_to_html(markdown_text: str) -> str:
    # Keep extensions minimal to avoid extra dependencies
    return _md.markdown(markdown_text, extensions=["extra", "sane_lists", "smarty"])


def build_html_document(*, title: str, archived: str, source: str, base_target: str, body_html: str) -> str:
    safe_title = _html.escape(title)
    safe_archived = _html.escape(archived)
    safe_source = _html.escape(source)

    # Indent rendered HTML for readability inside the container
    indented_body = _indent(body_html.strip(), " " * 8)

    return (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "    <meta charset=\"utf-8\">\n"
        f"    <base target=\"{_html.escape(base_target)}\">\n"
        "    <style>\n"
        + _indent(CSS_BLOCK, " " * 8)
        + "\n    </style>\n"
        "</head>\n"
        "<body>\n\n"
        "<div class=\"archive-header\">\n"
        "    <div class=\"archive-info\">\n"
        f"        <strong>📄 Archived:</strong> {safe_archived}\n"
        "    </div>\n"
        "    <div class=\"archive-source\">\n"
        f"        <strong>🔗 Source:</strong> {safe_source}\n"
        "    </div>\n"
        "</div>\n\n"
        f"<h1>{safe_title}</h1>\n\n"
        "<div class='post-content'>\n\n"
        "    <div class=\"md\">\n\n"
        f"{indented_body}\n\n"
        "    </div>\n"
        "</div>\n\n"
        "</body>\n"
        "</html>\n"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert Markdown to templated HTML")
    parser.add_argument("input", type=Path, help="Input .md file path or '-' for stdin")
    parser.add_argument("-o", "--output", type=Path, help="Output .html file path")
    parser.add_argument("--title", type=str, default=None, help="Title for <h1> (defaults to first H1 or filename)")
    parser.add_argument(
        "--archived",
        type=str,
        default=_dt.datetime.utcnow().strftime("%Y-%m"),
        help="Archive period like YYYY-MM (default: current UTC year-month)",
    )
    parser.add_argument("--source", type=str, default="", help="Source label (e.g., 'ChatGPT o3')")
    parser.add_argument("--base-target", type=str, default="_blank", help="Value for <base target>")
    parser.add_argument(
        "--no-extract-title",
        action="store_true",
        help="Do not detect/remove first H1 from markdown when inferring title",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv or sys.argv[1:])

    if str(ns.input) == "-":
        md_text = sys.stdin.read()
        input_stem = "stdin"
    else:
        md_path = ns.input
        if not md_path.exists():
            print(f"Error: input file not found: {md_path}", file=sys.stderr)
            return 2
        md_text = _read_text(md_path)
        input_stem = md_path.stem

    title: str | None = ns.title
    body_md = md_text
    if title is None and not ns.no_extract_title:
        found_title, body_md = extract_title(md_text)
        title = found_title
    if title is None:
        title = input_stem

    body_html = render_markdown_to_html(body_md)
    html_doc = build_html_document(
        title=title,
        archived=ns.archived,
        source=ns.source,
        base_target=ns.base_target,
        body_html=body_html,
    )

    if ns.output:
        out_path = ns.output
    else:
        if str(ns.input) == "-":
            out_path = Path(f"{input_stem}.html")
        else:
            out_path = md_path.with_suffix(".html")  # type: ignore[name-defined]

    _write_text(out_path, html_doc)
    print(str(out_path))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


