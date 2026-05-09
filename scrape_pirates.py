from __future__ import annotations

import os
import re
import time
from typing import Any, Iterator

import requests
from bs4 import BeautifulSoup


# Configuration
BASE_URL = "https://pirates.fandom.com"
API_URL = f"{BASE_URL}/api.php"
OUTPUT_DIR = "pirates_wiki_output"
DELAY = 1.0
REQUEST_TIMEOUT_SECONDS = 20.0

os.makedirs(OUTPUT_DIR, exist_ok=True)


def clean_text(text: str | None) -> str:
    """Cleans up text: removes non-breaking spaces, strips whitespace."""
    if not text:
        return ""

    cleaned = re.sub(r"\[\d+\]", "", text)
    return cleaned.replace("\xa0", " ").strip()


def fetch_json(
    session: requests.Session,
    url: str,
    params: dict[str, str],
) -> dict[str, Any] | None:
    """Fetches JSON data with an explicit timeout."""
    try:
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as error:
        print(f"Error fetching JSON from {url}: {error}")
        return None
    except ValueError as error:
        print(f"Error decoding JSON from {url}: {error}")
        return None

    if isinstance(payload, dict):
        return payload
    return None


def fetch_soup(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetches HTML and parses it into BeautifulSoup."""
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return BeautifulSoup(response.content, "html.parser")
    except requests.RequestException as error:
        print(f"  [!] Error fetching {url}: {error}")
        return None


def get_all_page_titles(
    limit: int | None = None,
    session: requests.Session | None = None,
) -> Iterator[str]:
    """Yields article titles from the Fandom MediaWiki API."""
    print("Fetching list of all pages from API...")

    params: dict[str, str] = {
        "action": "query",
        "list": "allpages",
        "aplimit": "max",
        "apnamespace": "0",
        "format": "json",
    }

    def yield_titles(active_session: requests.Session) -> Iterator[str]:
        count = 0
        while True:
            data = fetch_json(active_session, API_URL, params)
            if data is None:
                break

            query_data = data.get("query")
            if isinstance(query_data, dict):
                all_pages = query_data.get("allpages")
                if isinstance(all_pages, list):
                    for page in all_pages:
                        if not isinstance(page, dict):
                            continue

                        title = page.get("title")
                        if isinstance(title, str):
                            yield title
                            count += 1
                            if limit is not None and count >= limit:
                                return

            continuation = data.get("continue")
            if isinstance(continuation, dict):
                apcontinue = continuation.get("apcontinue")
                if isinstance(apcontinue, str):
                    params["apcontinue"] = apcontinue
                    continue
            break

    if session is not None:
        yield from yield_titles(session)
        return

    with requests.Session() as active_session:
        yield from yield_titles(active_session)


def parse_infobox(soup: BeautifulSoup) -> str:
    """Extracts key-value pairs from the Fandom portable infobox."""
    infobox_md: list[str] = []
    infobox: Any = soup.find("aside", class_="portable-infobox")
    if infobox is None:
        return ""

    infobox_md.append("## Infobox Data\n")
    for row in infobox.find_all("div", class_="pi-item"):
        label_div: Any = row.find("h3", class_="pi-data-label")
        value_div: Any = row.find("div", class_="pi-data-value")
        if label_div and value_div:
            label = clean_text(label_div.get_text())
            value = clean_text(value_div.get_text())
            infobox_md.append(f"- **{label}:** {value}")

    infobox_md.append("\n---\n")
    return "\n".join(infobox_md)


def parse_content_to_md(soup: BeautifulSoup) -> str:
    """Parses the main article content into Markdown."""
    content_div: Any = soup.find("div", class_="mw-parser-output")
    if content_div is None:
        return "*Error: No content found.*"

    md_lines: list[str] = []
    tags_to_find = ["p", "h2", "h3", "h4", "ul", "ol", "dl"]

    for element in content_div.find_all(tags_to_find, recursive=False):
        classes = element.get("class", [])
        if element.name == "div" and (
            "navbox" in classes or "wds-ads-banner-wrapper" in classes
        ):
            continue
        if element.name == "div" and element.get("id") == "toc":
            continue

        if element.name in ["h2", "h3", "h4"]:
            for span in element.find_all("span", class_="mw-editsection"):
                span.decompose()

            header_text = clean_text(element.get_text())
            level = "#" * int(element.name[1])
            md_lines.append(f"\n{level} {header_text}\n")
            continue

        if element.name in ["ul", "ol"]:
            for item in element.find_all("li"):
                item_text = clean_text(item.get_text())
                prefix = "-" if element.name == "ul" else "1."
                if item_text:
                    md_lines.append(f"{prefix} {item_text}")
            md_lines.append("")
            continue

        if element.name == "p":
            paragraph_text = clean_text(element.get_text())
            if paragraph_text:
                md_lines.append(f"{paragraph_text}\n")
            continue

        if element.name == "dl":
            definition_text = clean_text(element.get_text())
            if definition_text:
                md_lines.append(f"> {definition_text}\n")

    return "\n".join(md_lines)


def save_page(title: str, session: requests.Session | None = None) -> None:
    """Fetches a single page by title, parses it, and saves it as Markdown."""
    url_slug = title.replace(" ", "_")
    full_url = f"{BASE_URL}/wiki/{url_slug}"

    def save_with_session(active_session: requests.Session) -> None:
        soup = fetch_soup(active_session, full_url)
        if soup is None:
            return

        infobox_data = parse_infobox(soup)
        article_content = parse_content_to_md(soup)
        file_content = f"""# {title}
**Source:** [{full_url}]({full_url})

{infobox_data}

{article_content}
"""

        safe_filename = re.sub(r'[\\/*?:"<>|]', "", title)[:200]
        filepath = os.path.join(OUTPUT_DIR, f"{safe_filename}.md")
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(file_content)
        print(f"  [+] Saved: {safe_filename}.md")

    try:
        if session is not None:
            save_with_session(session)
            return

        with requests.Session() as active_session:
            save_with_session(active_session)
    except OSError as error:
        print(f"  [!] Error writing {title}: {error}")


def main() -> None:
    print("--- Pirates of the Caribbean Wiki Scraper ---")
    print(f"Saving to: ./{OUTPUT_DIR}/")
    print("This may take a long time due to rate limiting.\n")

    with requests.Session() as active_session:
        pages = get_all_page_titles(limit=None, session=active_session)
        for index, title in enumerate(pages, start=1):
            save_page(title, session=active_session)
            time.sleep(DELAY)
            if index % 50 == 0:
                print(f"--- Processed {index} pages ---")

    print("\nScraping Complete!")


if __name__ == "__main__":
    main()
