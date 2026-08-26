#@cantarellabots
from curl_cffi import requests
from bs4 import BeautifulSoup
from cantarella.core.proxy import get_random_proxy, get_proxy_dict

# Added more reliable mirrors
DOMAINS = ["https://hianimes.se", "https://hianime.to", "https://aniwaves.ru", "https://zoroxtv.to"]

def get_browser_headers(base_url):
    """Generates perfect Chrome browser headers to trick Cloudflare."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{base_url}/",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

def fetch_with_bypass(url, headers):
    # 1. Try Direct Connection First with Chrome 120 impersonation
    try:
        session = requests.Session(impersonate="chrome120")
        resp = session.get(url, headers=headers, timeout=20)
        
        if resp.status_code == 200:
            if "Just a moment" not in resp.text and "cloudflare" not in resp.text.lower():
                return resp
            else:
                print(f"[-] Cloudflare blocked direct access to {url}")
        else:
            print(f"[-] HTTP {resp.status_code} received from {url}")
    except Exception as e:
        print(f"[-] Direct connection error on {url}: {e}")

    # 2. Fallback to Proxy ONLY if direct connection fails
    proxy = get_random_proxy()
    proxy_dict = get_proxy_dict(proxy)
    if proxy_dict:
        try:
            print(f"[*] Retrying {url} with proxy...")
            session = requests.Session(impersonate="chrome120", proxies=proxy_dict)
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code == 200 and "Just a moment" not in resp.text and "cloudflare" not in resp.text.lower():
                return resp
        except Exception as e:
            print(f"[-] Proxy connection failed: {e}")
            
    return None

def search_anime(query: str):
    results = []
    for base_url in DOMAINS:
        url = f"{base_url}/search?keyword={query.replace(' ', '+')}"
        headers = get_browser_headers(base_url)
        
        print(f"[*] Attempting search on {base_url}...")
        resp = fetch_with_bypass(url, headers)
        if resp:
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = soup.select('.flw-item')
            if not items:
                items = soup.select('.film_list-wrap > div')

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
                print(f"[+] Successfully found {len(results)} results on {base_url}")
                return results
            
    return results
