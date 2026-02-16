"""
Download script for Haskell GHC 9.10.2-rc1 documentation.

Downloads the HTML source of every page from four documentation sources:
1. GHC User's Guide (Sphinx-generated docs)
2. GHC Libraries index + all library module pages (Haddock-generated)
3. GHC Compiler library documentation (Haddock-generated)
4. Haddock tool documentation (ReadTheDocs/Sphinx)

Each source is saved into its own subfolder under the output directory,
preserving the relative path structure so cross-links still work locally.

Uses bounded crawling: only follows links that share the same URL prefix
as the documentation root, preventing the crawler from wandering off-site.

Usage:
    python download_haskell_docs.py

Requirements:
    pip install requests beautifulsoup4

Note:
    Adds a short delay between requests to be polite to the servers.
    Total download time depends on library count (~30-60 min for everything).
"""

import os
import re
import sys
import time
from collections import deque
from typing import Optional
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# =============================================================================
# Configuration
# =============================================================================

OUTPUT_DIR: str = "Haskell_GHC_Documentation"
DELAY: float = 0.3  # seconds between requests (be polite to servers)

HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Documentation roots (the crawler stays within each prefix)
USERS_GUIDE_START: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/users_guide/intro.html"
)
USERS_GUIDE_PREFIX: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/users_guide/"
)

LIBRARIES_INDEX: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/libraries/index.html"
)
LIBRARIES_PREFIX: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/libraries/"
)

GHC_LIB_INDEX: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/libraries/"
    "ghc-9.10.1.20250417-963f/index.html"
)
GHC_LIB_PREFIX: str = (
    "https://downloads.haskell.org/ghc/9.10.2-rc1/docs/libraries/"
    "ghc-9.10.1.20250417-963f/"
)

HADDOCK_START: str = "https://haskell-haddock.readthedocs.io/latest/"
HADDOCK_PREFIX: str = "https://haskell-haddock.readthedocs.io/latest/"


# =============================================================================
# Helpers
# =============================================================================


def ensure_dir(path: str) -> None:
    """Creates directory (and parents) if it doesn't exist."""
    if not os.path.exists(path):
        os.makedirs(path)


def sanitize_path(raw: str) -> str:
    """
    Replaces characters illegal in Windows file paths.

    Args:
        raw: raw path string from URL

    Returns:
        Sanitized path safe for Windows and Linux filesystems.
    """
    # Replace characters invalid on Windows
    return re.sub(r'[*?"<>|]', "_", raw)


def url_to_filepath(url: str, prefix: str, subfolder: str) -> str:
    """
    Converts a URL into a local file path under OUTPUT_DIR/subfolder,
    preserving the relative path structure after stripping the prefix.

    Args:
        url: full URL of the page
        prefix: the documentation root URL to strip
        subfolder: local subfolder name under OUTPUT_DIR

    Returns:
        Absolute file path where the HTML should be saved.

    Examples:
        >>> url_to_filepath(
        ...     "https://example.com/docs/foo/bar.html",
        ...     "https://example.com/docs/",
        ...     "my_docs"
        ... )
        'Haskell_GHC_Documentation/my_docs/foo/bar.html'
    """
    # Strip fragment
    url, _ = urldefrag(url)

    # Get relative part after prefix
    if url.startswith(prefix):
        relative = url[len(prefix):]
    else:
        # Fallback: use the URL path
        parsed = urlparse(url)
        relative = parsed.path.lstrip("/")

    # If relative is empty or ends with /, treat as index.html
    if not relative or relative.endswith("/"):
        relative += "index.html"

    relative = sanitize_path(relative)

    # After sanitizing, check if path became effectively empty or invalid (just dots/underscores)
    # This handles edge cases like URLs ending in "..." or other special paths
    if not relative or relative.strip("._") == "":
        relative = "index.html"

    return os.path.join(OUTPUT_DIR, subfolder, relative)


def extract_text(html: str) -> str:
    """
    Extracts readable text content from raw HTML.

    Strips navigation, scripts, styles, and boilerplate. Returns clean
    text with reasonable whitespace.

    Args:
        html: raw HTML source

    Returns:
        Plain text content of the page.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that aren't content
    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # Try to find the main content area (Sphinx and Haddock use different structures)
    content = (
        soup.find("div", {"role": "main"})
        or soup.find("div", {"id": "content"})
        or soup.find("div", {"id": "description"})
        or soup.find("div", {"class": "document"})
        or soup.find("body")
        or soup
    )

    text = content.get_text(separator="\n")

    # Collapse runs of blank lines into at most two
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_page(url: str) -> Optional[str]:
    """
    Fetches a URL and returns the raw HTML text.

    Args:
        url: URL to fetch

    Returns:
        HTML source as string, or None on failure.
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"  [ERROR] Could not fetch {url}: {e}")
        return None


def extract_links(html: str, base_url: str, prefix: str) -> list[str]:
    """
    Parses HTML and extracts all <a href> links that fall within the prefix.

    Only returns links to HTML pages (ignores anchors-only, images, archives,
    external links, etc.).

    Args:
        html: raw HTML source
        base_url: the URL this HTML was fetched from (for resolving relative links)
        prefix: only links starting with this prefix are returned

    Returns:
        Deduplicated list of absolute URLs within the documentation boundary.
    """
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []

    for a_tag in soup.find_all("a", href=True):
        href: str = a_tag["href"]

        # Skip fragment-only links, javascript, mailto
        if href.startswith(("#", "javascript:", "mailto:")):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Strip fragment
        absolute, _ = urldefrag(absolute)

        # Only keep links within our documentation prefix
        if not absolute.startswith(prefix):
            continue

        # Skip non-HTML resources (tarballs, source archives, etc.)
        parsed = urlparse(absolute)
        path_lower = parsed.path.lower()
        skip_extensions = (
            ".tar.gz", ".tar.bz2", ".tar.xz", ".zip",
            ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
            ".pdf", ".ps", ".dvi",
            ".hs", ".lhs", ".cabal",
            ".css", ".js",
        )
        if any(path_lower.endswith(ext) for ext in skip_extensions):
            continue

        links.append(absolute)

    return links


def crawl_and_save(
    start_urls: list[str],
    prefix: str,
    subfolder: str,
    description: str,
) -> int:
    """
    BFS-crawls documentation starting from seed URLs, saving every page.

    Stays within the given URL prefix boundary. Saves raw HTML source
    preserving relative directory structure.

    Args:
        start_urls: seed URLs to begin crawling from
        prefix: URL prefix boundary (only links within this are followed)
        subfolder: local directory name under OUTPUT_DIR
        description: human-readable name for progress messages

    Returns:
        Total number of pages successfully saved.
    """
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"  Prefix: {prefix}")
    print(f"{'=' * 60}")

    visited: set[str] = set()
    queue: deque[str] = deque()
    saved_count: int = 0

    # Seed the queue
    for url in start_urls:
        clean_url, _ = urldefrag(url)
        if clean_url not in visited:
            queue.append(clean_url)
            visited.add(clean_url)

    while queue:
        url = queue.popleft()
        filepath = url_to_filepath(url, prefix, subfolder)

        # Check if file already exists (resume from power outage, etc.)
        if os.path.exists(filepath):
            print(f"  [{saved_count + 1}] Using cached: {url}")
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()
        else:
            print(f"  [{saved_count + 1}] Fetching: {url}")
            html = fetch_page(url)
            if html is None:
                continue

            # Save the raw HTML
            ensure_dir(os.path.dirname(filepath))
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html)

            # Rate limiting (only when actually fetching from network)
            time.sleep(DELAY)

        # Generate .txt version with extracted text content
        txt_path = re.sub(r"\.html?$", ".txt", filepath, flags=re.IGNORECASE)
        if txt_path == filepath:
            txt_path = filepath + ".txt"
        if not os.path.exists(txt_path):
            text = extract_text(html)
            if text:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"Source: {url}\n\n{text}")

        saved_count += 1

        # Extract and enqueue new links (works with cached or fresh HTML)
        new_links = extract_links(html, url, prefix)
        for link in new_links:
            if link not in visited:
                visited.add(link)
                queue.append(link)

    print(f"  => Saved {saved_count} pages for {description}")
    return saved_count


# =============================================================================
# Source-specific crawlers
# =============================================================================


def download_users_guide() -> int:
    """
    Downloads every page of the GHC User's Guide.

    The User's Guide is Sphinx-generated HTML. We start from the intro page
    and crawl all links within the users_guide/ prefix.

    Returns:
        Number of pages saved.
    """
    return crawl_and_save(
        start_urls=[USERS_GUIDE_START],
        prefix=USERS_GUIDE_PREFIX,
        subfolder="Users_Guide",
        description="GHC User's Guide",
    )


def download_libraries_docs() -> int:
    """
    Downloads the libraries index and every library's Haddock pages.

    Starts from the libraries index.html which lists all bundled libraries.
    Crawls into each library's Haddock documentation to get every module page.

    Note:
        This is the largest section — hundreds of libraries with thousands
        of module pages. This will take a while.

    Returns:
        Number of pages saved.
    """
    return crawl_and_save(
        start_urls=[LIBRARIES_INDEX],
        prefix=LIBRARIES_PREFIX,
        subfolder="Libraries",
        description="GHC Libraries Documentation (all libraries)",
    )


def download_ghc_compiler_docs() -> int:
    """
    Downloads the GHC compiler library documentation.

    This is the Haddock documentation for the GHC library itself
    (ghc-9.10.1.20250417-963f), including all internal compiler modules.

    Returns:
        Number of pages saved.
    """
    return crawl_and_save(
        start_urls=[GHC_LIB_INDEX],
        prefix=GHC_LIB_PREFIX,
        subfolder="GHC_Compiler_Lib",
        description="GHC Compiler Library Documentation",
    )


def download_haddock_docs() -> int:
    """
    Downloads every page of the Haddock tool documentation.

    Haddock docs are hosted on ReadTheDocs (Sphinx-generated).
    Crawls from the root and follows all internal links.

    Returns:
        Number of pages saved.
    """
    return crawl_and_save(
        start_urls=[HADDOCK_START],
        prefix=HADDOCK_PREFIX,
        subfolder="Haddock",
        description="Haddock Documentation (ReadTheDocs)",
    )


# =============================================================================
# Main
# =============================================================================


def main() -> None:
    """
    Entry point. Downloads all four documentation sources sequentially.

    Creates the output directory structure and runs each crawler,
    printing a final summary of total pages saved.

    Command-line flags:
        --force-extract: Convert all HTML to .txt without checking if .txt
                        already exists (faster for retroactive conversion).
    """
    # Parse command-line arguments
    force_extract: bool = "--force-extract" in sys.argv

    # pylint: disable=C0303

    if "--help" in sys.argv or "-h" in sys.argv:
        print("""
Usage: python download_haskell_docs.py [OPTIONS]

Options:
  --force-extract   Convert all HTML files to .txt without checking if .txt
                    already exists. Useful for faster retroactive conversion
                    of large cached HTML file sets. (default: False)
  -h, --help        Show this help message and exit
""")
        return
    
    # pylint: disable=C0303
    
    ensure_dir(OUTPUT_DIR)

    print("=" * 60)
    print("  Haskell GHC 9.10.2-rc1 Documentation Downloader")
    print("=" * 60)
    print(f"Output directory: {os.path.abspath(OUTPUT_DIR)}")
    print(f"Request delay:    {DELAY}s between requests")
    if force_extract:
        print("Mode:             Force extract (skip .txt existence checks)")
    print()

    total: int = 0
    start_time: float = time.time()

    # 1. GHC User's Guide
    total += download_users_guide()

    # 2. All libraries documentation (this is the big one)
    total += download_libraries_docs()

    # 3. GHC compiler library specifically
    total += download_ghc_compiler_docs()

    # 4. Haddock documentation
    total += download_haddock_docs()

    # Convert any HTML files from previous runs that don't have .txt yet
    convert_existing_html(force=force_extract)

    elapsed: float = time.time() - start_time
    minutes: int = int(elapsed // 60)
    seconds: int = int(elapsed % 60)

    print()
    print("=" * 60)
    print(f"  COMPLETE — {total} pages saved in {minutes}m {seconds}s")
    print(f"  Output: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 60)


def convert_existing_html(force: bool = False) -> None:
    """
    Walks the output directory and generates .txt files for HTML files.

    Args:
        force: If True, overwrites existing .txt files. If False, skips
               HTML files that already have a .txt version.

    This handles HTML files from previous runs that were saved before
    the text extraction feature was added. Use force=True to convert all
    HTML files without checking if .txt already exists (faster).
    """
    converted: int = 0
    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for name in files:
            if not name.lower().endswith((".html", ".htm")):
                continue
            html_path = os.path.join(root, name)
            txt_path = re.sub(r"\.html?$", ".txt", html_path, flags=re.IGNORECASE)

            # pylint: disable=C0303

            # Skip if .txt already exists (unless force=True)
            if not force and os.path.exists(txt_path):
                continue

            # pylint: disable=C0303

            try:
                with open(html_path, "r", encoding="utf-8") as f:
                    html = f.read()
                text = extract_text(html)
                if text:
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    converted += 1
            except (OSError, UnicodeError) as e:
                # Only catch file I/O / encoding-related errors here; let other
                # unexpected exceptions propagate so they aren't silently swallowed.
                print(f"  [WARN] Could not convert {html_path}: {e}")
    if converted:
        print(f"  => Converted {converted} existing HTML files to .txt")


if __name__ == "__main__":
    main()
