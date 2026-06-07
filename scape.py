import requests
from bs4 import BeautifulSoup

def scrape_chapter(url):
    # Spoof user-agent to avoid getting blocked by basic anti-bot walls
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching the page: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 1. Extract the Title
    # Often inside an <h1> or specific class like .chapter-title
    title_element = soup.find('h1') or soup.select_one('.title, .chapter-title')
    title = title_element.get_text(strip=True) if title_element else "Chapter Content"
    
    # 2. Extract the Story Content
    # Novel sites usually wrap the main body in an article, .chapter-content, or .ep-content div
    content_div = soup.find('article') or soup.select_one('.chapter-content, .ep-content, #chapter-container')
    
    if not content_div:
        # Fallback if specific containers aren't found: grab text paragraphs from the body
        paragraphs = soup.find_all('p')
    else:
        paragraphs = content_div.find_all('p')
        
    # Clean and filter empty/advertisement paragraphs efficiently
    story_paragraphs = []
    for p in paragraphs:
        text = p.get_text(strip=True)
        # Skip empty strings or known ad placeholders
        if text and not any(ad in text.lower() for ad in ["loading...", "ads by", "click here"]):
            story_paragraphs.append(text)
            
    return {
        "title": title,
        "content": "\n\n".join(story_paragraphs)
    }

if __name__ == "__main__":
    target_url = "https://skydemonorder.com/projects/3801994495-return-of-the-mount-hua-sect/172-once-they-get-hit-they-are-bound-to-move-2"
    
    print("Scraping started...")
    result = scrape_chapter(target_url)
    
    if result:
        print(f"\n--- {result['title']} ---\n")
        print(result['content'][:1000]) # Preview first 1000 chars
        print("\n... (Truncated for preview) ...")
        
        # Save to a local text file
        filename = "mount_hua_sect_172.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"{result['title']}\n\n{result['content']}\n")
        print(f"\nSuccess! Full text saved to {filename}")
