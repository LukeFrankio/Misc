import requests
from bs4 import BeautifulSoup
import re
import os
import time
import json

# Configuration
BASE_URL = "https://pirates.fandom.com"
API_URL = f"{BASE_URL}/api.php"
OUTPUT_DIR = "pirates_wiki_output"
DELAY = 1.0  # Seconds between requests to be polite (and avoid bans)

# Create output directory
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def clean_text(text):
    """Cleans up text: removes non-breaking spaces, strips whitespace."""
    if not text:
        return ""
    # Remove citation brackets like [1], [2]
    text = re.sub(r'\[\d+\]', '', text)
    return text.replace('\xa0', ' ').strip()

def get_all_page_titles(limit=None):
    """
    Uses the Fandom MediaWiki API to get a list of all articles (Namespace 0).
    Yields titles one by one.
    """
    print("Fetching list of all pages from API...")
    
    params = {
        "action": "query",
        "list": "allpages",
        "aplimit": "max",  # Request max allowed per batch (usually 500)
        "apnamespace": "0", # 0 = Main Articles only (ignores Talk, User, Category pages)
        "format": "json"
    }
    
    count = 0
    while True:
        try:
            response = requests.get(API_URL, params=params)
            data = response.json()
            
            if "query" in data and "allpages" in data["query"]:
                for page in data["query"]["allpages"]:
                    yield page["title"]
                    count += 1
                    if limit and count >= limit:
                        return
            
            # Check if there are more results (pagination)
            if "continue" in data:
                params["apcontinue"] = data["continue"]["apcontinue"]
            else:
                break
                
        except Exception as e:
            print(f"Error fetching page list: {e}")
            break

def parse_infobox(soup):
    """
    Extracts key-value pairs from the Fandom 'Portable Infobox'.
    Returns a Markdown formatted string of attributes.
    """
    infobox_md = []
    try:
        infobox = soup.find("aside", class_="portable-infobox")
        if infobox:
            infobox_md.append("## Infobox Data\n")
            
            # Find all data rows
            rows = infobox.find_all("div", class_="pi-item")
            for row in rows:
                # Get Label
                label_div = row.find("h3", class_="pi-data-label")
                # Get Value
                value_div = row.find("div", class_="pi-data-value")
                
                if label_div and value_div:
                    label = clean_text(label_div.get_text())
                    value = clean_text(value_div.get_text())
                    infobox_md.append(f"- **{label}:** {value}")
            
            infobox_md.append("\n---\n")
    except Exception as e:
        pass # Infoboxes are optional
    
    return "\n".join(infobox_md)

def parse_content_to_md(soup):
    """
    Parses the main article content into Markdown.
    Handles headers, paragraphs, and lists.
    """
    content_div = soup.find("div", class_="mw-parser-output")
    if not content_div:
        return "*Error: No content found.*"

    md_lines = []
    
    # Iterate over common content elements
    # We include 'ul' and 'ol' for lists, which are common in wikis
    tags_to_find = ['p', 'h2', 'h3', 'h4', 'ul', 'ol', 'dl']
    
    for element in content_div.find_all(tags_to_find, recursive=False):
        
        # Skip garbage (Ads, Toc, Navboxes, Galleries)
        classes = element.get('class', [])
        if element.name == 'div' and ('navbox' in classes or 'wds-ads-banner-wrapper' in classes):
            continue
        if element.name == 'div' and element.get('id') == 'toc':
            continue

        # Handle Headers
        if element.name in ['h2', 'h3', 'h4']:
            # Remove "Edit" buttons
            for span in element.find_all("span", class_="mw-editsection"):
                span.decompose()
            
            header_text = clean_text(element.get_text())
            level = "#" * int(element.name[1]) # h2 -> ##, h3 -> ###
            md_lines.append(f"\n{level} {header_text}\n")
            continue

        # Handle Lists (Unordered and Ordered)
        if element.name in ['ul', 'ol']:
            for li in element.find_all("li"):
                li_text = clean_text(li.get_text())
                prefix = "-" if element.name == 'ul' else "1."
                if li_text:
                    md_lines.append(f"{prefix} {li_text}")
            md_lines.append("") # Newline after list
            continue

        # Handle Paragraphs
        if element.name == 'p':
            # Handle bold/italics visually using BeautifulSoup
            # (Simplistic approach: just get text, but you could add more complex md conversion)
            text = clean_text(element.get_text())
            if text:
                md_lines.append(f"{text}\n")
            continue
            
        # Handle Definition Lists (often used for dialogue or definitions)
        if element.name == 'dl':
            text = clean_text(element.get_text())
            if text:
                md_lines.append(f"> {text}\n")

    return "\n".join(md_lines)

def save_page(title):
    """
    Fetches a single page by title, parses it, and saves to MD.
    """
    # 1. format URL
    # Fandom URLs use underscores for spaces
    url_slug = title.replace(" ", "_")
    full_url = f"{BASE_URL}/wiki/{url_slug}"
    
    try:
        resp = requests.get(full_url)
        if resp.status_code != 200:
            print(f"  [!] Skipped {title} (Status {resp.status_code})")
            return

        soup = BeautifulSoup(resp.content, "html.parser")
        
        # 2. Extract Data
        infobox_data = parse_infobox(soup)
        article_content = parse_content_to_md(soup)
        
        # 3. Create File Content
        file_content = f"""# {title}
**Source:** [{full_url}]({full_url})

{infobox_data}

{article_content}
"""
        # 4. Sanitize Filename
        # Remove characters invalid in Windows/Linux filenames
        safe_filename = re.sub(r'[\\/*?:"<>|]', "", title)
        # Truncate filename if too long
        safe_filename = safe_filename[:200]
        
        filepath = os.path.join(OUTPUT_DIR, f"{safe_filename}.md")
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        print(f"  [+] Saved: {safe_filename}.md")

    except Exception as e:
        print(f"  [!] Error parsing {title}: {e}")

def main():
    print(f"--- Pirates of the Caribbean Wiki Scraper ---")
    print(f"Saving to: ./{OUTPUT_DIR}/")
    print("This may take a long time due to rate limiting.\n")
    
    # Optional: Set a limit for testing (e.g., limit=10)
    # Set limit=None to scrape everything (Thousands of pages)
    pages = get_all_page_titles(limit=None) 
    
    for i, title in enumerate(pages):
        save_page(title)
        
        # Rate Limiting
        time.sleep(DELAY)
        
        # Optional: Status update every 50 pages
        if (i + 1) % 50 == 0:
            print(f"--- Processed {i + 1} pages ---")

    print("\nScraping Complete!")

if __name__ == "__main__":
    main()