#@cantarellabots
from curl_cffi import requests
from bs4 import BeautifulSoup
from cantarella.core.proxy import get_random_proxy, get_proxy_dict

# Try multiple domains in case one is heavily rate-limited by Cloudflare
DOMAINS = ["https://hianimes.se", "https://aniwaves.ru", "https://hianime.to"]

def search_anime(query: str):
    session = requests.Session()
    
    proxy = get_random_proxy()
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        session.proxies.update(proxy_dict)
        
    for base_url in DOMAINS:
        url = f"{base_url}/search?keyword={query.replace(' ', '+')}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": f"{base_url}/"
        }
        
        try:
            # Using chrome110 for better Cloudflare bypass
            resp = session.get(url, headers=headers, impersonate="chrome110", timeout=15)
            
            if resp.status_code == 200:
                # Detect Cloudflare challenge
                if "Just a moment..." in resp.text or "cloudflare" in resp.text.lower():
                    print(f"Cloudflare blocked search on {base_url}. Trying next domain...")
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                
                items = soup.select('.flw-item')
                if not items:
                    items = soup.select('.film_list-wrap > div')

                results = []
                for item in items:
                    title_elem = item.select_one('.film-name a') or item.select_one('a.dynamic-name') or item.select_one('a')
                    if not title_elem: continue
                    
                    title = title_elem.get('title') or title_elem.text.strip()
                    href = title_elem.get('href')
                    if not href: continue
                    
                    img_elem = item.select_one('img')
                    img_url = img_elem.get('data-src') or img_elem.get('src') if img_elem else None
                    
                    tick_sub = item.select_one('.tick-sub')
                    tick_dub = item.select_one('.tick-dub')
                    tick_eps = item.select_one('.tick-eps')
                    
                    meta_info = []
                    if tick_sub: meta_info.append(f"Sub: {tick_sub.text.strip()}")
                    if tick_dub: meta_info.append(f"Dub: {tick_dub.text.strip()}")
                    if tick_eps: meta_info.append(f"Eps: {tick_eps.text.strip()}")
                    
                    full_url = f"{base_url}{href}" if href.startswith('/') else f"{base_url}/{href}"
                    
                    results.append({
                        'title': title,
                        'url': full_url,
                        'image': img_url,
                        'info': " | ".join(meta_info) if meta_info else "Details unavailable"
                    })
                
                if results:
                    return results
        except Exception as e:
            print(f"Error searching on {base_url}: {e}")
            
    return []
