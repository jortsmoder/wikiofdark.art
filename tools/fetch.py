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
    short_title = doc.short_title() or ""
    title_html = f"<h1>{html.escape(short_title)}</h1>\n" if short_title else ""

    soup = BeautifulSoup(html_content, "html.parser")

    def pick_largest(elements):
        largest = None
        max_len = 0
        for el in elements:
            text_len = len(el.get_text(separator=" ", strip=True))
            if text_len > max_len:
                largest = el
                max_len = text_len
        return largest

    candidate = None

    # Prefer <main>
    mains = soup.find_all("main")
    if mains:
        candidate = pick_largest(mains)

    # Then [role="main"]
    if not candidate:
        role_mains = soup.select('[role="main"]')
        if role_mains:
            candidate = pick_largest(role_mains)

    # Then <article> (prefer itemprop="articleBody" if present)
    if not candidate:
        articles = soup.find_all("article")
        if articles:
            bodies = []
            for art in articles:
                bodies.extend(art.select('[itemprop="articleBody"]'))
            candidate = pick_largest(bodies) or pick_largest(articles)

    if candidate:
        # Remove non-content elements inside the candidate
        for tag in candidate.find_all(["script", "style", "noscript", "svg", "canvas", "form"]):
            tag.decompose()
        for tag in candidate.find_all(["header", "footer", "nav", "aside"]):
            tag.decompose()

        # Normalize lazy-loaded images
        for img in candidate.find_all("img"):
            src = img.get("src")
            if not src or src.startswith("data:"):
                for attr in ["data-src", "data-original", "data-lazy-src"]:
                    val = img.get(attr)
                    if val:
                        img["src"] = val
                        break
            if not img.get("srcset") and img.get("data-srcset"):
                img["srcset"] = img.get("data-srcset")

        return title_html + str(candidate)

    # Fallback to Readability result
    body = BeautifulSoup(doc.summary(), "html.parser")
    return title_html + str(body)

def is_twitter_url(url: str) -> bool:
    """Check if URL is a Twitter/X link"""
    parsed = urlparse(url)
    return parsed.netloc in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com', 'mobile.twitter.com')

def clean_twitter_url(url: str) -> str:
    """Strip tracking query params from Twitter/X URLs"""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def archive_twitter(url: str) -> str:
    """Archive Twitter/X post using fxtwitter API proxy"""
    try:
        parsed = urlparse(url)
        # Convert x.com/user/status/123 -> api.fxtwitter.com/user/status/123
        api_url = f"https://api.fxtwitter.com{parsed.path}"
        headers = {"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"}

        response = requests.get(api_url, timeout=30, headers=headers)
        response.raise_for_status()
        data = response.json()

        tweet = data.get('tweet', {})
        author = tweet.get('author', {})
        text = tweet.get('text', '')
        author_name = author.get('name', '')
        screen_name = author.get('screen_name', '')
        likes = tweet.get('likes', 0)
        retweets = tweet.get('retweets', 0)
        replies = tweet.get('replies', 0)
        views = tweet.get('views', 0)
        created_at = tweet.get('created_at', '')

        # Build clean HTML
        html_content = f'<h1>{html.escape(author_name)} (@{html.escape(screen_name)})</h1>\n'
        html_content += f'<p class="tweet-meta">{html.escape(created_at)}</p>\n'

        # Tweet text - preserve newlines
        escaped_text = html.escape(text).replace('\n', '<br>\n')
        html_content += f'<div class="tweet-text">{escaped_text}</div>\n'

        # Media (photos and videos)
        media = tweet.get('media', {})
        all_media = media.get('all', [])
        for item in all_media:
            if item.get('type') == 'photo':
                img_url = item.get('url', '')
                html_content += f'<div class="tweet-media"><img src="{html.escape(img_url)}" alt="Tweet image"></div>\n'
            elif item.get('type') == 'video' or item.get('type') == 'gif':
                thumb = item.get('thumbnail_url', '')
                html_content += f'<div class="tweet-media"><img src="{html.escape(thumb)}" alt="Tweet video thumbnail"><p><em>(Video - see original tweet)</em></p></div>\n'

        # Engagement stats
        html_content += f'<div class="tweet-stats">'
        html_content += f'{replies:,} replies &bull; {retweets:,} reposts &bull; {likes:,} likes'
        if views:
            html_content += f' &bull; {views:,} views'
        html_content += '</div>\n'

        # Quote tweet if present
        quote = tweet.get('quote')
        if quote:
            q_author = quote.get('author', {})
            q_text = html.escape(quote.get('text', '')).replace('\n', '<br>\n')
            html_content += f'<blockquote class="quote-tweet">'
            html_content += f'<strong>{html.escape(q_author.get("name", ""))} (@{html.escape(q_author.get("screen_name", ""))})</strong><br>'
            html_content += f'{q_text}</blockquote>\n'

        return html_content

    except Exception as e:
        print(f"⚠ Twitter API proxy failed ({e}), returning minimal content...")
        return f"<h1>Tweet</h1><p>Failed to fetch tweet content: {html.escape(str(e))}</p><p><a href='{html.escape(url)}'>View original tweet</a></p>"

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

def is_reddit_search_tool(url: str) -> bool:
    """Check if URL is from the Reddit search tool (ihsoyct.github.io)"""
    parsed = urlparse(url)
    return 'ihsoyct.github.io' in parsed.netloc

def archive_reddit_search_tool(url: str) -> str:
    """Archive Reddit search tool results as minimal Markdown"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract search parameters for simple title
        parsed_url = urlparse(url)
        params = dict(param.split('=') for param in parsed_url.query.split('&') if '=' in param)
        
        # Simple title
        if params.get('author'):
            title = f"Comments by u/{params['author']}"
        elif params.get('subreddit'):
            title = f"r/{params['subreddit']} comments"
        else:
            title = "Reddit Comments"
        
        if params.get('body'):
            title += f" containing '{params['body']}'"
        
        # Start with minimal content
        md_content = f"# {title}\n\n"
        
        # Find the submission div and all posts within it
        submission_div = soup.find('div', id='submission')
        if not submission_div:
            md_content += "No submissions found.\n"
            return md_content
            
        posts = submission_div.find_all('div', class_='post')
        
        if not posts:
            md_content += "No posts found.\n"
            return md_content
        
        for post in posts:
            # Extract comment path and create Reddit URL
            title_elem = post.find('p', class_='comment_title')
            if title_elem:
                comment_path = title_elem.get_text().strip()
                reddit_url = f"https://reddit.com{comment_path}"
                md_content += f"**{comment_path}**\n"
                md_content += f"{reddit_url}\n\n"
            
            # Extract user and score info (simplified)
            user_elem = post.find('p', class_='comment_user')
            if user_elem:
                user_text = user_elem.get_text().strip()
                # Extract just username and score
                import re
                score_match = re.search(r'Score: (\d+)', user_text)
                user_match = re.search(r'(u/\w+)', user_text)
                date_match = re.search(r'at (.+)$', user_text)
                
                if user_match and score_match:
                    user_info = f"{user_match.group(1)} • {score_match.group(1)} points"
                    if date_match:
                        user_info += f" • {date_match.group(1)}"
                    md_content += f"{user_info}\n\n"
            
            # Extract actual comment content
            # Find all p tags that are not comment_title, comment_user, and not empty
            content_paragraphs = []
            
            # Get all p elements in the post
            all_p_tags = post.find_all('p')
            
            for p in all_p_tags:
                # Skip the title and user info paragraphs
                if p.get('class') and ('comment_title' in p.get('class') or 'comment_user' in p.get('class')):
                    continue
                
                # Get the text content
                text = p.get_text().strip()
                
                # Only add non-empty paragraphs
                if text:
                    content_paragraphs.append(text)
            
            # Add the comment content
            if content_paragraphs:
                for para in content_paragraphs:
                    md_content += f"{para}\n\n"
            
            md_content += "---\n\n"
        
        return md_content
        
    except Exception as e:
        print(f"⚠ Reddit search tool archiving failed ({e})")
        # Fallback to regular reader mode
        response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"})
        return reader_mode(response.text)

def generate_markdown_archive_header(url: str, archive_date: datetime.datetime) -> str:
    """Generate minimal archive header in Markdown format"""
    formatted_date = archive_date.strftime('%Y-%m-%d %H:%M UTC')
    return f"*Archived {formatted_date} from {url}*\n\n"

def is_arctic_shift_api(url: str) -> bool:
    """Check if URL is from the Arctic Shift API"""
    parsed = urlparse(url)
    return 'arctic-shift.photon-reddit.com' in parsed.netloc and '/api/' in parsed.path

def archive_arctic_shift_api(url: str) -> str:
    """Archive Arctic Shift API results as HTML"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"}
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        comments = data.get('data', [])
        
        if not comments:
            return "<h1>Reddit Comments</h1><p>No comments found.</p>"
        
        # Extract search info from URL for title
        parsed_url = urlparse(url)
        query_params = {}
        if parsed_url.query:
            for param in parsed_url.query.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    query_params[key] = value
        
        # Build title
        title_parts = []
        if query_params.get('author'):
            title_parts.append(f"u/{query_params['author']}")
        if query_params.get('subreddit'):
            title_parts.append(f"r/{query_params['subreddit']}")
        if query_params.get('body'):
            title_parts.append(f"containing '{query_params['body']}'")
        
        title = "Comments by " + " • ".join(title_parts) if title_parts else "Reddit Comments"
        
        html_content = f"<h1>{html.escape(title)}</h1>\n\n"
        
        for comment in comments:
            # Extract comment info
            permalink = comment.get('permalink', '')
            reddit_url = f"https://reddit.com{permalink}"
            author = comment.get('author', 'unknown')
            score = comment.get('score', 0)
            subreddit = comment.get('subreddit', '')
            body = comment.get('body', '')
            
            # Convert timestamp to readable date
            created_utc = comment.get('created_utc')
            date_str = ''
            if created_utc:
                import datetime
                date_obj = datetime.datetime.fromtimestamp(created_utc, tz=datetime.timezone.utc)
                date_str = date_obj.strftime('%Y-%m-%d %H:%M UTC')
            
            # Format the comment as HTML
            html_content += '<div class="comment">\n'
            html_content += f'  <div class="comment-header">\n'
            html_content += f'    <strong><a href="{reddit_url}" target="_blank">{html.escape(permalink)}</a></strong>\n'
            html_content += f'  </div>\n'
            
            # User info line
            user_info = f"u/{author} • {score} points"
            if date_str:
                user_info += f" • {date_str}"
            if subreddit:
                user_info += f" • r/{subreddit}"
            html_content += f'  <div class="comment-meta">{html.escape(user_info)}</div>\n'
            
            # Comment body (handle newlines properly)
            if body:
                # Replace \n with actual newlines and clean up
                clean_body = body.replace('\\n', '\n').strip()
                # Convert newlines to HTML line breaks and escape HTML
                clean_body_html = html.escape(clean_body).replace('\n', '<br>\n')
                html_content += f'  <div class="comment-body">{clean_body_html}</div>\n'
            
            html_content += '</div>\n<hr>\n\n'
        
        return html_content
        
    except Exception as e:
        print(f"⚠ Arctic Shift API archiving failed ({e})")
        return f"<h1>Error</h1><p>Failed to archive API response: {html.escape(str(e))}</p>"

def convert_ihsoyct_to_api_url(url: str) -> str:
    """Convert ihsoyct.github.io URL to Arctic Shift API URL"""
    try:
        parsed = urlparse(url)
        
        # Extract query parameters
        params = {}
        if parsed.query:
            for param in parsed.query.split('&'):
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key] = value
        
        # Build API URL
        api_base = "https://arctic-shift.photon-reddit.com/api"
        
        # Determine endpoint based on mode
        mode = params.get('mode', 'comments')
        if mode == 'submissions':
            endpoint = f"{api_base}/submissions/search"
        else:
            endpoint = f"{api_base}/comments/search"
        
        # Build query string for API
        api_params = []
        for key, value in params.items():
            if key in ['author', 'subreddit', 'body', 'title', 'selftext', 'limit', 'sort', 'after', 'before']:
                api_params.append(f"{key}={value}")
        
        api_url = f"{endpoint}?{'&'.join(api_params)}"
        return api_url
        
    except Exception as e:
        print(f"⚠ Failed to convert URL: {e}")
        return url

def archive(url: str, out_dir: pathlib.Path, force: bool):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Clean Twitter URLs before slugging so filenames match the JS slug
    if is_twitter_url(url):
        url = clean_twitter_url(url)

    fname = out_dir / slug.slug(url)

    # Check if this is a Reddit search tool and convert to API URL
    original_url = url
    if is_reddit_search_tool(url):
        print("🔄 Converting to Arctic Shift API URL...")
        url = convert_ihsoyct_to_api_url(url)
        print(f"   API URL: {url}")
    
    # Check for API URL and change extension to .html
    is_api_url = is_arctic_shift_api(url)
    if is_api_url or is_reddit_search_tool(original_url):
        fname = fname.with_suffix('.html')
    
    if fname.exists() and not force:
        print(f"✓ cached: {original_url}")
        return

    print(f"↓ fetching: {original_url}")
    
    try:
        archive_date = datetime.datetime.now(datetime.timezone.utc)
        
        if is_twitter_url(original_url):
            content = archive_twitter(original_url)
            archive_style = """
        <style>
            body{font-family:system-ui,sans-serif;max-width:50rem;margin:2rem auto;line-height:1.6;padding:1rem}
            img,iframe{max-width:100%}
            .archive-header{background:#f0f8ff;border:1px solid #e0e0e0;border-radius:5px;padding:0.75rem;margin-bottom:1rem;font-size:0.9rem}
            .archive-info{margin-bottom:0.5rem;color:#666}
            .archive-source{color:#666}
            .archive-header a{color:#007acc;text-decoration:none}
            .archive-header a:hover{text-decoration:underline}
            .tweet-text{font-size:1.15rem;line-height:1.7;margin:1rem 0;white-space:pre-wrap}
            .tweet-meta{color:#666;font-size:0.9em}
            .tweet-media{margin:1rem 0}
            .tweet-media img{border-radius:12px;max-width:100%;display:block}
            .tweet-stats{color:#666;font-size:0.9em;margin-top:1rem;padding-top:0.75rem;border-top:1px solid #e5e7eb}
            .quote-tweet{border:1px solid #e5e7eb;border-radius:12px;padding:1rem;margin:1rem 0}
            @media (prefers-color-scheme: dark) {
                body{background:#0b0f14;color:#e6e6e6}
                .archive-header{background:#1a1a2e;border-color:#333;color:#e0e0e0}
                .archive-info, .archive-source{color:#ccc}
                .archive-header a{color:#66b3ff}
                .tweet-meta, .tweet-stats{color:#aaa}
                .tweet-stats{border-top-color:#333}
                .quote-tweet{border-color:#333}
            }
        </style>
        """
            final_content = (
                "<meta charset='utf-8'>\n" +
                "<base target='_blank'>\n" +
                archive_style + "\n" +
                generate_archive_header(original_url, archive_date) + "\n" +
                content
            )
        elif is_arctic_shift_api(url):
            content = archive_arctic_shift_api(url)
            # Enhanced styling with archive header for HTML
            archive_style = """
        <style>
            body{font-family:system-ui,sans-serif;max-width:50rem;margin:2rem auto;line-height:1.6;padding:1rem}
            img,iframe{max-width:100%}
            .archive-header{background:#f0f8ff;border:1px solid #e0e0e0;border-radius:5px;padding:0.75rem;margin-bottom:1rem;font-size:0.9rem}
            .archive-info{margin-bottom:0.5rem;color:#666}
            .archive-source{color:#666}
            .archive-header a{color:#007acc;text-decoration:none}
            .archive-header a:hover{text-decoration:underline}
            .comment{background:#f9f9f9;border:1px solid #e0e0e0;border-radius:5px;padding:1rem;margin:1rem 0}
            .comment-header{font-weight:bold;margin-bottom:0.5rem}
            .comment-header a{color:#007acc;text-decoration:none}
            .comment-header a:hover{text-decoration:underline}
            .comment-meta{color:#666;font-size:0.9em;margin-bottom:0.75rem}
            .comment-body{white-space:pre-wrap;line-height:1.5}
            hr{border:none;border-top:1px solid #ddd;margin:1.5rem 0}
            @media (prefers-color-scheme: dark) {
                body{background:#1a1a1a;color:#e0e0e0}
                .archive-header{background:#1a1a2e;border-color:#333;color:#e0e0e0}
                .archive-info, .archive-source{color:#ccc}
                .archive-header a{color:#66b3ff}
                .comment{background:#2a2a2a;border-color:#444;color:#e0e0e0}
                .comment-header a{color:#66b3ff}
                .comment-meta{color:#aaa}
                hr{border-top-color:#444}
            }
        </style>
        """
            final_content = (
                "<meta charset='utf-8'>\n" +
                "<base target='_blank'>\n" +
                archive_style + "\n" +
                generate_archive_header(original_url, archive_date) + "\n" +
                content
            )
        elif is_reddit_url(url):
            content = archive_reddit(url)
            # Enhanced styling with archive header for HTML
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
            final_content = (
                "<meta charset='utf-8'>\n" +
                "<base target='_blank'>\n" +
                archive_style + "\n" +
                generate_archive_header(url, archive_date) + "\n" +
                content
            )
        else:
            html_response = requests.get(url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (ArchiveBot/1.0)"
            }).text
            content = reader_mode(html_response)
            # Enhanced styling with archive header for HTML
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
            final_content = (
                "<meta charset='utf-8'>\n" +
                "<base target='_blank'>\n" +
                archive_style + "\n" +
                generate_archive_header(url, archive_date) + "\n" +
                content
            )
        
        fname.write_text(final_content, encoding="utf-8")
        print(f"✓ saved   : {fname.relative_to(out_dir.parent)}")
        
    except Exception as e:
        print(f"✗ failed  : {original_url} - {e}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out_dir")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    archive(args.url, pathlib.Path(args.out_dir), args.force)