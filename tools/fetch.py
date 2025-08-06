"""
Usage:
    python tools/fetch.py <url> <out_dir> [--force]
"""

import requests, sys, pathlib, slug, argparse, re, html, datetime
from readability import Document
from bs4 import BeautifulSoup
from urllib.parse import urlparse

def reader_mode(html_content: str) -> str:
    doc = Document(html_content)
    body = BeautifulSoup(doc.summary(), "html.parser")
    return f"<h1>{doc.short_title()}</h1>\n{body}"

def is_reddit_url(url: str) -> bool:
    """Check if URL is a Reddit link"""
    parsed = urlparse(url)
    return 'reddit.com' in parsed.netloc

def clean_reddit_html(html_content):
    """Clean up Reddit's HTML content"""
    if not html_content:
        return ""
    
    # Decode HTML entities
    cleaned = html.unescape(html_content)
    
    # Parse and clean up the HTML
    soup = BeautifulSoup(cleaned, 'html.parser')
    
    # Remove Reddit-specific formatting comments
    for comment in soup.find_all(string=lambda text: isinstance(text, str) and 
                                 ('SC_OFF' in text or 'SC_ON' in text)):
        comment.extract()
    
    return str(soup)

def archive_reddit(url: str) -> str:
    """Archive Reddit post with comments using JSON API"""
    try:
        # Convert to JSON API endpoint
        json_url = url.rstrip('/') + '.json'
        headers = {"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"}
        
        response = requests.get(json_url, timeout=30, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Extract post data
        post = data[0]['data']['children'][0]['data']
        comments = data[1]['data']['children'] if len(data) > 1 else []
        
        # Build HTML
        html_content = f"<h1>{post['title']}</h1>\n"
        html_content += f"<p><strong>r/{post['subreddit']}</strong> • by u/{post['author']} • {post['score']} points</p>\n"
        
        if post.get('selftext_html'):
            html_content += f"<div class='post-content'>{clean_reddit_html(post['selftext_html'])}</div>\n"
        
        html_content += "<hr>\n<h2>Comments</h2>\n"
        html_content += format_comments(comments)
        
        return html_content
        
    except Exception as e:
        print(f"⚠ Reddit JSON failed ({e}), trying HTML fallback...")
        # Fallback: get HTML and try to preserve more content
        response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"})
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try to get comments section too
        comments_section = soup.find('div', class_=re.compile('comments|commentarea'))
        main_content = reader_mode(response.text)
        
        if comments_section:
            main_content += "<hr>\n<h2>Comments</h2>\n" + str(comments_section)
        
        return main_content

def format_comments(comments, depth=0):
    """Format Reddit comments recursively with proper HTML"""
    html_content = ""
    
    for comment in comments:
        if comment['kind'] != 't1':  # Skip non-comments
            continue
            
        data = comment['data']
        if data.get('body') in ['[deleted]', '[removed]', None]:
            continue
            
        # Style based on depth
        margin_left = depth * 20
        border_color = '#ddd' if depth == 0 else '#eee'
        
        html_content += f'''
        <div style="margin-left: {margin_left}px; border-left: 3px solid {border_color}; padding: 10px; margin: 10px 0; background: #fafafa;">
            <div style="font-size: 0.9em; color: #666; margin-bottom: 5px;">
                <strong>u/{data.get("author", "[deleted]")}</strong> • {data.get("score", 0)} points
            </div>
            <div>
                {clean_reddit_html(data.get("body_html", ""))}
            </div>
        '''
        
        # Handle replies recursively
        if data.get('replies') and isinstance(data['replies'], dict):
            html_content += format_comments(data['replies']['data']['children'], depth + 1)
            
        html_content += '</div>\n'
    
    return html_content

def generate_archive_header(url: str, archive_date: datetime.datetime) -> str:
    """Generate archive header with date and metadata"""
    formatted_date = archive_date.strftime('%Y-%m-%d %H:%M:%S UTC')
    iso_date = archive_date.isoformat() + 'Z'
    
    return f'''<div class="archive-header">
        <div class="archive-info">
            <strong>📄 Archived:</strong> {formatted_date}
        </div>
        <div class="archive-source">
            <strong>🔗 Source:</strong> <a href="{url}">{url}</a>
        </div>
    </div>
    <script>
        // Archive metadata for cache management
        window.archiveData = {{
            url: {repr(url)},
            archivedAt: "{iso_date}",
            timestamp: {int(archive_date.timestamp() * 1000)}
        }};
    </script>
    <hr>'''

def archive(url: str, out_dir: pathlib.Path, force: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / slug.slug(url)
    if fname.exists() and not force:
        print(f"✓ cached: {url}")
        return

    print(f"↓ fetching: {url}")
    
    try:
        archive_date = datetime.datetime.now(datetime.timezone.utc)
        
        if is_reddit_url(url):
            content = archive_reddit(url)
        else:
            html_response = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"
            }).text
            content = reader_mode(html_response)
        
        # Enhanced styling with archive header
        archive_style = """
        <style>
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
        </style>
        """
        
        fname.write_text(
            "<meta charset='utf-8'>\n" +
            "<base target='_blank'>\n" +
            archive_style + "\n" +
            generate_archive_header(url, archive_date) + "\n" +
            content,
            encoding="utf-8"
        )
        print(f"✓ saved   : {fname.relative_to(out_dir.parent)}")
        
    except Exception as e:
        print(f"✗ failed  : {url} - {e}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out_dir")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    archive(args.url, pathlib.Path(args.out_dir), args.force)