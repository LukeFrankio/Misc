import requests
from bs4 import BeautifulSoup
import os
import re
import time

# Configuration
OUTPUT_DIR = "Michael_Kirkbride_Writings"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

def clean_filename(title):
    """Removes invalid characters from filenames."""
    # Remove special chars and limit length
    clean = re.sub(r'[\\/*?:"<>|]', "", title)
    return clean.strip()[:100]

def save_text(title, content, subfolder=""):
    """Saves content to a text file."""
    folder = os.path.join(OUTPUT_DIR, subfolder)
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    filename = f"{clean_filename(title)}.txt"
    filepath = os.path.join(folder, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"[SAVED] {filename}")

def get_soup(url):
    """Fetches a URL and returns a BeautifulSoup object."""
    try:
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except Exception as e:
        print(f"[ERROR] Could not fetch {url}: {e}")
        return None

# ==========================================
# SCRAPER 1: UESP Wiki (The Major Texts)
# ==========================================
def scrape_uesp_texts():
    print("\n--- Starting UESP Wiki Scraper ---")
    base_url = "https://en.uesp.net"
    list_url = "https://en.uesp.net/wiki/General:Michael_Kirkbride%27s_Texts"
    
    soup = get_soup(list_url)
    if not soup:
        return

    # Find the main content div
    content_div = soup.find('div', {'id': 'mw-content-text'})
    
    # Find all lists in the content
    # We look for links specifically under the "Texts" section
    # This usually resides in <ul> tags.
    links_to_scrape = []
    
    for ul in content_div.find_all('ul'):
        for li in ul.find_all('li'):
            a_tag = li.find('a', href=True)
            if a_tag:
                # Filter to ensure we only get 'General:' or 'Lore:' namespace links
                # which contain the actual texts
                if "/wiki/General:" in a_tag['href'] or "/wiki/Lore:" in a_tag['href']:
                    full_link = base_url + a_tag['href']
                    title = a_tag.get_text()
                    links_to_scrape.append((title, full_link))

    print(f"Found {len(links_to_scrape)} texts to download...")

    for title, link in links_to_scrape:
        if "Michael Kirkbride" in title: # Skip self-referential links
            continue

        print(f"Fetching: {title}...")
        text_soup = get_soup(link)
        
        if text_soup:
            # UESP content resides in .mw-parser-output
            article_body = text_soup.find('div', {'class': 'mw-parser-output'})
            
            if article_body:
                # Cleanup: Remove Table of Contents, Edit buttons, and navigation boxes
                for remove_tag in article_body.find_all(['div', 'table'], {'class': ['toc', 'navbox', 'infobox']}):
                    remove_tag.decompose()
                for edit_section in article_body.find_all('span', {'class': 'mw-editsection'}):
                    edit_section.decompose()

                text_content = f"Source: {link}\n\n" + article_body.get_text(separator='\n\n')
                save_text(title, text_content, subfolder="UESP_Texts")
        
        # Be polite to the server
        time.sleep(0.5)

# ==========================================
# SCRAPER 2: The Imperial Library (The Forum Posts)
# ==========================================
def scrape_imperial_library_posts():
    print("\n--- Starting Imperial Library Scraper ---")
    # This URL contains the massive collection of forum posts
    url = "https://www.imperial-library.info/content/michael-kirkbride-posts"
    
    soup = get_soup(url)
    if not soup:
        return

    # The content is usually in a div with region-content or specific node classes
    # For TIL, it's often nested deep.
    content_div = soup.find('div', {'class': 'content'}) or soup.find('article')
    
    if content_div:
        # Since this is one massive page with hundreds of posts, 
        # it is safer to download it as one giant "Collected Works" file
        # rather than trying to split it programmatically and risking data loss.
        
        title = "Collected Forum Posts and Comments"
        
        # Simple cleanup
        text_content = f"Source: {url}\n\n" + content_div.get_text(separator='\n')
        
        save_text(title, text_content, subfolder="Imperial_Library_Posts")
    else:
        print("[ERROR] Could not locate main content block on Imperial Library.")

# ==========================================
# SCRAPER 3: The Imperial Library (Specific Texts)
# ==========================================
# Note: Most of these are covered by UESP, but we check the specific directory just in case
def scrape_imperial_library_texts():
    print("\n--- Starting Imperial Library Text Archive ---")
    url = "https://www.imperial-library.info/content/michael-kirkbrides-texts"
    base_url = "https://www.imperial-library.info"
    
    soup = get_soup(url)
    if not soup:
        return
        
    content_div = soup.find('div', {'class': 'view-content'})
    if not content_div:
        # Fallback to general content div
        content_div = soup.find('div', {'class': 'content'})

    if content_div:
        links = content_div.find_all('a', href=True)
        for a in links:
            # Basic filter to avoid navigation links
            if "/content/" in a['href']:
                title = a.get_text()
                link = base_url + a['href']
                
                print(f"Fetching TIL Text: {title}...")
                page_soup = get_soup(link)
                if page_soup:
                    page_content = page_soup.find('div', {'class': 'node-content'}) or page_soup.find('article')
                    if page_content:
                        text_data = f"Source: {link}\n\n" + page_content.get_text(separator='\n\n')
                        save_text(title, text_data, subfolder="Imperial_Library_Texts")
                time.sleep(0.5)

if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    print("Beginning download of Michael Kirkbride's works...")
    
    # 1. Download the major texts listed on UESP
    scrape_uesp_texts()
    
    # 2. Download the massive forum post collection from Imperial Library
    scrape_imperial_library_posts()
    
    # 3. Download texts hosted specifically on Imperial Library
    scrape_imperial_library_texts()
    
    print("\nDone! Check the folder:", OUTPUT_DIR)