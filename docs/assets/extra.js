/* assets/extra.js
 *
 * Shows #source-pane only when we actually have a source to display.
 * Opens source externally when there's not enough space for the iframe.
 * Makes source pane state stateful via URL hash.
 * Preloads and caches all source pages for instant loading.
 */

/* ---------- cache system -------------------------------------------- */

class SourceCache {
  constructor() {
    this.cache = new Map();
    this.sourceRegistry = new Map(); // Maps original URLs to local paths
    this.preloadComplete = false;
    this.cacheTimeout = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
  }

  get(url) {
    const cached = this.cache.get(url);
    if (cached) {
      // Check if cache entry has expired
      if (Date.now() - cached.timestamp > this.cacheTimeout) {
        console.log(`⏰ Cache expired for: ${url}`);
        this.cache.delete(url);
        return null;
      }
      
      // Move to end (LRU) and update access time
      this.cache.delete(url);
      cached.lastAccessed = Date.now();
      this.cache.set(url, cached);
      return cached.content;
    }
    return null;
  }

  set(url, content) {
    const now = Date.now();
    this.cache.set(url, {
      content: content,
      timestamp: now,
      lastAccessed: now
    });
  }

  has(url) {
    const cached = this.cache.get(url);
    if (cached) {
      // Check if expired
      if (Date.now() - cached.timestamp > this.cacheTimeout) {
        this.cache.delete(url);
        return false;
      }
      return true;
    }
    return false;
  }

  getLocalPath(originalUrl) {
    return this.sourceRegistry.get(originalUrl);
  }

  registerSource(originalUrl, localPath) {
    this.sourceRegistry.set(originalUrl, localPath);
  }

  isAvailableLocally(originalUrl) {
    return this.sourceRegistry.has(originalUrl);
  }

  clear() {
    this.cache.clear();
    this.sourceRegistry.clear();
  }

  size() {
    return this.cache.size;
  }

  setCacheTimeout(hours) {
    this.cacheTimeout = hours * 60 * 60 * 1000;
    console.log(`🕐 Cache timeout set to ${hours} hours`);
  }

  cleanExpired() {
    const now = Date.now();
    let cleaned = 0;
    for (const [url, cached] of this.cache.entries()) {
      if (now - cached.timestamp > this.cacheTimeout) {
        this.cache.delete(url);
        cleaned++;
      }
    }
    if (cleaned > 0) {
      console.log(`🧹 Cleaned ${cleaned} expired cache entries`);
    }
    return cleaned;
  }

  getCacheStats() {
    const now = Date.now();
    const stats = {
      total: this.cache.size,
      fresh: 0,
      stale: 0,
      avgAge: 0
    };
    
    let totalAge = 0;
    for (const cached of this.cache.values()) {
      const age = now - cached.timestamp;
      totalAge += age;
      if (age > this.cacheTimeout) {
        stats.stale++;
      } else {
        stats.fresh++;
      }
    }
    
    stats.avgAge = stats.total > 0 ? Math.round(totalAge / stats.total / 1000 / 60) : 0; // minutes
    return stats;
  }
}

const sourceCache = new SourceCache();
let currentSourceUrl = null; // Track current source for header buttons

/* ---------- helpers -------------------------------------------------- */

async function sha1hex(str) {
  const buf = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function slug(url) {
  const u    = new URL(url);
  const host = u.host.toLowerCase().replace(/\W+/g, '-').replace(/^-+|-+$/g, '');
  const path = (u.pathname.replace(/^\/|\/$/g, '').toLowerCase().replace(/\W+/g, '-').slice(0, 60)) || 'root';
  const hash = (await sha1hex(url)).slice(0, 10);
  return `${host}__${path}__${hash}.html`;
}

function hasSpaceForSourcePane() {
  // Check if screen is wide enough for main content (600px) + source pane (400px) + gap
  return window.innerWidth >= 1024; // 64rem ≈ 1024px
}

function getSourceUrlFromHash() {
  // Extract source URL from hash like #source=https://example.com
  const hash = window.location.hash;
  const match = hash.match(/[#&]source=([^&]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function setSourceUrlInHash(url) {
  // Update URL hash with source parameter
  const currentHash = window.location.hash;
  const newHash = currentHash.includes('source=') 
    ? currentHash.replace(/([#&])source=[^&]*/, `$1source=${encodeURIComponent(url)}`)
    : (currentHash ? `${currentHash}&source=${encodeURIComponent(url)}` : `#source=${encodeURIComponent(url)}`);
  
  history.pushState(null, '', newHash);
}

function removeSourceFromHash() {
  // Remove source parameter from hash
  const currentHash = window.location.hash;
  const newHash = currentHash
    .replace(/[#&]source=[^&]*/, '')
    .replace(/^&/, '#')
    .replace(/&$/, '');
  
  if (newHash !== currentHash) {
    history.pushState(null, '', newHash || '#');
  }
}

async function discoverAndPreloadSources() {
  console.log('🔍 Discovering available source pages...');
  
  // Find all source-link elements on the page
  const sourceLinks = document.querySelectorAll('a.source-link');
  const discoveryPromises = [];

  for (const link of sourceLinks) {
    const originalUrl = link.href;
    const localPath = `/sources/${await slug(originalUrl)}`;
    
    // Check if local version exists (do this once during preload)
    discoveryPromises.push(
      fetch(localPath, { method: 'HEAD' })
        .then(response => {
          if (response.ok) {
            sourceCache.registerSource(originalUrl, localPath);
            console.log(`📍 Registered: ${originalUrl} -> ${localPath}`);
          }
        })
        .catch(() => {
          // Local version doesn't exist, that's fine
        })
    );
  }

  await Promise.all(discoveryPromises);
  console.log(`✅ Discovery complete. Found ${sourceCache.sourceRegistry.size} local sources.`);
}

async function preloadSource(url) {
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    
    const content = await response.text();
    sourceCache.set(url, content);
    return content;
  } catch (error) {
    console.warn(`Failed to preload source: ${url}`, error);
    return null;
  }
}

async function preloadAllSources() {
  if (sourceCache.preloadComplete) return;
  
  await discoverAndPreloadSources();
  
  // Preload a few of the most recently discovered sources
  const localSources = Array.from(sourceCache.sourceRegistry.values()).slice(0, 10); // Limit to first 10
  
  if (localSources.length > 0) {
    console.log(`📦 Preloading ${localSources.length} source pages...`);
    const preloadPromises = localSources.map(async (localPath) => {
      if (!sourceCache.has(localPath)) {
        await preloadSource(localPath);
      }
    });
    
    await Promise.all(preloadPromises);
    console.log(`🚀 Preloaded ${sourceCache.size()} source pages`);
  }
  
  sourceCache.preloadComplete = true;
}

function createDataUrl(htmlContent) {
  // Create a data URL for the HTML content
  const blob = new Blob([htmlContent], { type: 'text/html' });
  return URL.createObjectURL(blob);
}

async function updateSourceControls() {
  const originalBtn = document.querySelector('.source-control-original');
  const archiveBtn = document.querySelector('.source-control-archive');
  
  if (!currentSourceUrl || !originalBtn || !archiveBtn) return;
  
  // Update original button
  originalBtn.href = currentSourceUrl;
  
  // Check if archive is available (including checking if it exists)
  let localPath = null;
  if (sourceCache.isAvailableLocally(currentSourceUrl)) {
    localPath = sourceCache.getLocalPath(currentSourceUrl);
  } else {
    // Try to find the archive if not in registry yet
    const expectedLocalPath = `/sources/${await slug(currentSourceUrl)}`;
    try {
      const response = await fetch(expectedLocalPath, { method: 'HEAD' });
      if (response.ok) {
        localPath = expectedLocalPath;
        sourceCache.registerSource(currentSourceUrl, expectedLocalPath);
      }
    } catch {
      // No archive available
    }
  }
  
  // Update archive button
  if (localPath) {
    archiveBtn.href = localPath;
    archiveBtn.style.display = 'inline-flex';
  } else {
    archiveBtn.style.display = 'none';
  }
}

async function showSourcePane(sourceUrl) {
  const pane = document.getElementById('wiki-source-pane');
  const frame = document.getElementById('source-frame');
  
  if (!hasSpaceForSourcePane()) {
    window.open(sourceUrl, '_blank');
    return;
  }

  // Update current source URL for header controls
  currentSourceUrl = sourceUrl;

  // Show pane first for immediate feedback
  if (pane) pane.style.display = 'block';

  // Update header controls (async to check for archives)
  updateSourceControls().catch(console.error);

  // Always prefer archived version if available, never load original in iframe
  let target = sourceUrl;
  if (sourceCache.isAvailableLocally(sourceUrl)) {
    target = sourceCache.getLocalPath(sourceUrl);
  } else {
    // If no local archive exists, try to generate the expected path and check if it exists
    const expectedLocalPath = `/sources/${await slug(sourceUrl)}`;
    try {
      const response = await fetch(expectedLocalPath, { method: 'HEAD' });
      if (response.ok) {
        target = expectedLocalPath;
        sourceCache.registerSource(sourceUrl, expectedLocalPath);
      }
    } catch {
      // No local archive available - show message instead of loading original
      if (frame) {
        const noArchiveHtml = `
          <html>
            <head>
              <meta charset="utf-8">
              <style>
                body { 
                  font-family: system-ui, sans-serif; 
                  padding: 2rem; 
                  text-align: center; 
                  color: #666; 
                  background: #fafafa;
                }
                .message { 
                  max-width: 30rem; 
                  margin: 0 auto; 
                  line-height: 1.6;
                }
                .url { 
                  word-break: break-all; 
                  background: #f0f0f0; 
                  padding: 0.5rem; 
                  border-radius: 0.25rem; 
                  margin: 1rem 0;
                  font-family: monospace;
                  font-size: 0.9rem;
                }
                a { color: #007acc; text-decoration: none; }
                a:hover { text-decoration: underline; }
              </style>
            </head>
            <body>
              <div class="message">
                <h3>📄 No Archive Available</h3>
                <p>This source hasn't been archived yet. The original URL cannot be loaded in a frame due to security restrictions.</p>
                <div class="url">${sourceUrl}</div>
                <p>Use the "original" button above to open it in a new tab.</p>
              </div>
            </body>
          </html>
        `;
        const dataUrl = createDataUrl(noArchiveHtml);
        frame.src = dataUrl;
      }
      setSourceUrlInHash(sourceUrl);
      return;
    }
  }

  // Load archived content
  if (sourceCache.has(target)) {
    const cachedContent = sourceCache.get(target);
    const dataUrl = createDataUrl(cachedContent);
    if (frame) frame.src = dataUrl;
    console.log(`⚡ Instant load from cache: ${target}`);
  } else {
    // Load and cache the archived content
    console.log(`📥 Loading and caching: ${target}`);
    const content = await preloadSource(target);
    if (content && frame) {
      const dataUrl = createDataUrl(content);
      frame.src = dataUrl;
    } else if (frame) {
      // Show error message if archive fails to load
      const errorHtml = `
        <html>
          <head>
            <meta charset="utf-8">
            <style>
              body { 
                font-family: system-ui, sans-serif; 
                padding: 2rem; 
                text-align: center; 
                color: #666; 
                background: #fafafa;
              }
            </style>
          </head>
          <body>
            <h3>❌ Archive Load Error</h3>
            <p>Failed to load the archived content.</p>
            <p>Use the "original" button to open in a new tab.</p>
          </body>
        </html>
      `;
      const dataUrl = createDataUrl(errorHtml);
      frame.src = dataUrl;
    }
  }
  
  // Update URL
  setSourceUrlInHash(sourceUrl);
}

function hideSourcePane() {
  const pane = document.getElementById('wiki-source-pane');
  if (pane) {
    pane.style.display = 'none';
    currentSourceUrl = null;
  }
  removeSourceFromHash();
}

function createSourcePaneHeader() {
  const header = document.createElement('div');
  header.className = 'source-pane-header';
  
  // Left side - links
  const links = document.createElement('div');
  links.className = 'source-pane-links';
  
  // Archive button  
  const archiveBtn = document.createElement('a');
  archiveBtn.className = 'source-control-btn source-control-archive';
  archiveBtn.target = '_blank';
  archiveBtn.innerHTML = '<span class="icon">↗</span>Open this archive copy';
 
  // Original button
  const originalBtn = document.createElement('a');
  originalBtn.className = 'source-control-btn source-control-original';
  originalBtn.target = '_blank';
  originalBtn.innerHTML = '<span class="icon">↗</span>View original';
  
  links.appendChild(archiveBtn);
  links.appendChild(originalBtn);
  
  // Right side - close button only
  const controls = document.createElement('div');
  controls.className = 'source-pane-controls';
  
  // Close button
  const closeBtn = document.createElement('button');
  closeBtn.className = 'close-btn';
  closeBtn.innerHTML = '×';
  closeBtn.addEventListener('click', hideSourcePane);
  
  controls.appendChild(closeBtn);
  
  header.appendChild(links);
  header.appendChild(controls);
  
  return header;
}

/* ---------- main ----------------------------------------------------- */

document.addEventListener('DOMContentLoaded', async () => {

  const pane  = document.getElementById('wiki-source-pane');   // wrapper <aside>
  const frame = document.getElementById('source-frame');  // iframe inside it
  if (pane) pane.style.display = 'none';                  // start hidden

  // Add header with controls to source pane
  if (pane && !pane.querySelector('.source-pane-header')) {
    const header = createSourcePaneHeader();
    pane.insertBefore(header, frame);
  }

  // Preload sources in the background
  setTimeout(() => {
    preloadAllSources().catch(console.error);
  }, 1000); // Wait 1 second after page load

  // Check URL hash on page load
  const initialSourceUrl = getSourceUrlFromHash();
  if (initialSourceUrl && hasSpaceForSourcePane()) {
    showSourcePane(initialSourceUrl);
  }

  document.body.addEventListener('click', async ev => {
    const link = ev.target.closest('a.source-link');
    if (!link) return;

    ev.preventDefault();
    await showSourcePane(link.href);
  });

  /* Handle window resize - hide source pane if not enough space */
  window.addEventListener('resize', () => {
    if (pane && !hasSpaceForSourcePane()) {
      hideSourcePane();
    }
  });

  /* Handle browser back/forward buttons */
  window.addEventListener('popstate', () => {
    const sourceUrl = getSourceUrlFromHash();
    if (sourceUrl && hasSpaceForSourcePane()) {
      showSourcePane(sourceUrl);
    } else {
      hideSourcePane();
    }
  });

  // Periodic cache cleanup every hour
  setInterval(() => {
    sourceCache.cleanExpired();
  }, 60 * 60 * 1000); // 1 hour

  // Add cache management to window for debugging
  if (typeof window !== 'undefined') {
    window.sourceCache = sourceCache;
    window.clearSourceCache = () => {
      sourceCache.clear();
      console.log('🗑️ Source cache cleared');
    };
    window.preloadAllSources = preloadAllSources;
    window.setCacheTimeout = (hours) => sourceCache.setCacheTimeout(hours);
    window.getCacheStats = () => {
      const stats = sourceCache.getCacheStats();
      console.log('📊 Cache Stats:', stats);
      return stats;
    };
    window.cleanExpiredCache = () => sourceCache.cleanExpired();
  }

});