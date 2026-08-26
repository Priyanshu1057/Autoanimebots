#@cantarellabots
from curl_cffi import requests
from bs4 import BeautifulSoup
from cantarella.core.proxy import get_random_proxy, get_proxy_dict

# A mix of the official domain, proxies, and clones
DOMAINS = ["https://hianime.to", "https://hianimes.se", "https://hianime.sx", "https://zoroxtv.to", "https://kaido.to"]

def fetch_with_bypass(url, referer):
    # Let curl_cffi handle ALL browser headers natively to maintain perfect CF fingerprint
    headers = {"Referer": referer}
    
    # Strategy 1: Direct Chrome 120
    try:
        session = requests.Session(impersonate="chrome120")
        resp = session.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and "Just a moment" not in resp.text and "cloudflare" not in resp.text.lower():
            return resp
    except Exception: pass

    # Strategy 2: Direct Safari 15.5 (Often bypasses CF if Chrome is flagged)
    try:
        session = requests.Session(impersonate="safari15_5")
        resp = session.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and "Just a moment" not in resp.text and "cloudflare" not in resp.text.lower():
            return resp
    except Exception: pass

    # Strategy 3: Proxy Fallback
    proxy = get_random_proxy()
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        try:
            print(f"[*] Retrying {url} with proxy...")
            session = requests.Session(impersonate="chrome120", proxies=proxy_dict)
            resp = session.get(url, headers=headers, timeout=15)
            if resp.status_code == 200 and "Just a moment" not in resp.text and "cloudflare" not in resp.text.lower():
                return resp
        except Exception: pass
            
    return None

def search_anime(query: str):
    results = []
    for base_url in DOMAINS:
        url = f"{base_url}/search?keyword={query.replace(' ', '+')}"
        print(f"[*] Attempting search on {base_url}...")
        
        resp = fetch_with_bypass(url, f"{base_url}/")
        if resp:
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Broad selectors to catch different Zoro clone templates
            items = soup.select('.flw-item, .film_list-wrap .item, .film-detail')
            
            for item in items:
                title_elem = item.select_one('.film-name a') or item.select_one('a.dynamic-name') or item.select_one('h3 a') or item.select_one('a')
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
                print(f"[+] Successfully found {len(results)} results on {base_url}")
                return results
            else:
                print(f"[-] Loaded {base_url} but found no items (HTML structure might be different).")
            
    return results
