#@cantarellabots
from curl_cffi import requests
from bs4 import BeautifulSoup
from cantarella.core.proxy import get_random_proxy, get_proxy_dict

# UPDATED: Changed from aniwatchtv.to to the new domain
BASE_URL = "https://hianimes.se"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": f"{BASE_URL}/"
}

def search_anime(query: str):
    session = requests.Session()
    proxy = get_random_proxy()
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        session.proxies.update(proxy_dict)

    url = f"{BASE_URL}/search?keyword={query.replace(' ', '+')}"
    
    results = []
    try:
        resp = session.get(url, headers=HEADERS, impersonate="chrome")
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # The structure for flw-item is standard across the aniwatch clones
            items = soup.select('.flw-item')
            for item in items:
                title_elem = item.select_one('.film-name a')
                if not title_elem: continue
                
                title = title_elem.get('title') or title_elem.text.strip()
                href = title_elem.get('href')
                
                # Extract image if available
                img_elem = item.select_one('.film-poster img')
                img_url = img_elem.get('data-src') or img_elem.get('src') if img_elem else None
                
                # Extract some extra metadata like Sub/Dub/Eps if present
                tick_sub = item.select_one('.tick-sub')
                tick_dub = item.select_one('.tick-dub')
                tick_eps = item.select_one('.tick-eps')
                
                meta_info = []
                if tick_sub: meta_info.append(f"Sub: {tick_sub.text.strip()}")
                if tick_dub: meta_info.append(f"Dub: {tick_dub.text.strip()}")
                if tick_eps: meta_info.append(f"Eps: {tick_eps.text.strip()}")
                
                full_url = f"{BASE_URL}{href}" if href.startswith('/') else f"{BASE_URL}/{href}"
                
                results.append({
                    'title': title,
                    'url': full_url,
                    'image': img_url,
                    'info': " | ".join(meta_info) if meta_info else "Details unavailable"
                })
                
    except Exception as e:
        print(f"Error during search: {e}")
        
    return results
