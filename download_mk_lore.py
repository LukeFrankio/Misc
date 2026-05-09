from __future__ import annotations

import os
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup


# Configuration
OUTPUT_DIR = "Michael_Kirkbride_Writings"
REQUEST_TIMEOUT_SECONDS = 20.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def href_string(value: Any) -> str | None:
    """Normalizes a BeautifulSoup href attribute into a string."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first_value = value[0]
        if isinstance(first_value, str):
            return first_value
    return None


def clean_filename(title: str) -> str:
    """Removes invalid characters from filenames."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "", title)
    return cleaned.strip()[:100]


def save_text(title: str, content: str, subfolder: str = "") -> None:
    """Saves content to a text file."""
    folder = os.path.join(OUTPUT_DIR, subfolder)
    os.makedirs(folder, exist_ok=True)

    filename = f"{clean_filename(title)}.txt"
    filepath = os.path.join(folder, filename)

    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(content)
    print(f"[SAVED] {filename}")


def get_soup(
    url: str,
    session: requests.Session | None = None,
) -> BeautifulSoup | None:
    """Fetches a URL and returns a BeautifulSoup object."""
    active_session = session or requests.Session()
    try:
        response = active_session.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")
    except requests.RequestException as error:
        print(f"[ERROR] Could not fetch {url}: {error}")
        return None
    finally:
        if session is None:
            active_session.close()


# ==========================================
# SCRAPER 1: UESP Wiki (The Major Texts)
# ==========================================

def scrape_uesp_texts(session: requests.Session | None = None) -> None:
    print("\n--- Starting UESP Wiki Scraper ---")
    base_url = "https://en.uesp.net"
    list_url = "https://en.uesp.net/wiki/General:Michael_Kirkbride%27s_Texts"

    soup = get_soup(list_url, session=session)
    if soup is None:
        return

    content_div: Any = soup.find("div", {"id": "mw-content-text"})
    if content_div is None:
        print("[ERROR] Could not locate the UESP content block.")
        return

    links_to_scrape: list[tuple[str, str]] = []
    for ul in content_div.find_all("ul"):
        for li in ul.find_all("li"):
            a_tag: Any = li.find("a", href=True)
            if a_tag is None:
                continue

            href = href_string(a_tag.get("href"))
            if href and ("/wiki/General:" in href or "/wiki/Lore:" in href):
                full_link = base_url + href
                title = a_tag.get_text()
                links_to_scrape.append((title, full_link))

    print(f"Found {len(links_to_scrape)} texts to download...")

    for title, link in links_to_scrape:
        if "Michael Kirkbride" in title:
            continue

        print(f"Fetching: {title}...")
        text_soup = get_soup(link, session=session)
        if text_soup is None:
            time.sleep(0.5)
            continue

        article_body: Any = text_soup.find("div", {"class": "mw-parser-output"})
        if article_body is not None:
            for remove_tag in article_body.find_all(
                ["div", "table"],
                {"class": ["toc", "navbox", "infobox"]},
            ):
                remove_tag.decompose()
            for edit_section in article_body.find_all("span", {"class": "mw-editsection"}):
                edit_section.decompose()

            text_content = f"Source: {link}\n\n" + article_body.get_text(separator="\n\n")
            save_text(title, text_content, subfolder="UESP_Texts")

        time.sleep(0.5)


# ==========================================
# SCRAPER 2: The Imperial Library (The Forum Posts)
# ==========================================

def scrape_imperial_library_posts(session: requests.Session | None = None) -> None:
    print("\n--- Starting Imperial Library Scraper ---")
    url = "https://www.imperial-library.info/content/michael-kirkbride-posts"

    soup = get_soup(url, session=session)
    if soup is None:
        return

    content_div: Any = soup.find("div", {"class": "content"}) or soup.find("article")
    if content_div is None:
        print("[ERROR] Could not locate main content block on Imperial Library.")
        return

    title = "Collected Forum Posts and Comments"
    text_content = f"Source: {url}\n\n" + content_div.get_text(separator="\n")
    save_text(title, text_content, subfolder="Imperial_Library_Posts")


# ==========================================
# SCRAPER 3: The Imperial Library (Specific Texts)
# ==========================================

def scrape_imperial_library_texts(session: requests.Session | None = None) -> None:
    print("\n--- Starting Imperial Library Text Archive ---")
    url = "https://www.imperial-library.info/content/michael-kirkbrides-texts"
    base_url = "https://www.imperial-library.info"

    soup = get_soup(url, session=session)
    if soup is None:
        return

    content_div: Any = soup.find("div", {"class": "view-content"})
    if content_div is None:
        content_div = soup.find("div", {"class": "content"})

    if content_div is None:
        print("[ERROR] Could not locate Imperial Library text listings.")
        return

    for link_tag in content_div.find_all("a", href=True):
        href = href_string(link_tag.get("href"))
        if not href or "/content/" not in href:
            continue

        title = link_tag.get_text()
        link = base_url + href

        print(f"Fetching TIL Text: {title}...")
        page_soup = get_soup(link, session=session)
        if page_soup is not None:
            page_content: Any = page_soup.find("div", {"class": "node-content"}) or page_soup.find("article")
            if page_content is not None:
                text_data = f"Source: {link}\n\n" + page_content.get_text(separator="\n\n")
                save_text(title, text_data, subfolder="Imperial_Library_Texts")
        time.sleep(0.5)


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Beginning download of Michael Kirkbride's works...")
    with requests.Session() as http_session:
        scrape_uesp_texts(session=http_session)
        scrape_imperial_library_posts(session=http_session)
        scrape_imperial_library_texts(session=http_session)

    print("\nDone! Check the folder:", OUTPUT_DIR)
