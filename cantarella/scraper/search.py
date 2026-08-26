#@cantarellabots
from curl_cffi import requests

# We use robust, public open-source APIs to completely bypass Cloudflare
APIS = ["https://hianime-api.vercel.app/anime", "https://aniwatch-api-v1-0.onrender.com/anime"]

def search_anime(query: str):
    for api in APIS:
        try:
            print(f"[*] Attempting API search via {api}...")
            resp = requests.get(f"{api}/search?q={query}", impersonate="chrome120", timeout=15)
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("animes", [])
                results = []
                for item in data:
                    eps = item.get("episodes", {})
                    sub = eps.get("sub", 0)
                    dub = eps.get("dub", 0)
                    
                    results.append({
                        'title': item.get('name'),
                        'url': item.get('id'), # We now pass the raw anime ID instead of a URL
                        'image': item.get('poster'),
                        'info': f"Sub: {sub} | Dub: {dub}"
                    })
                if results:
                    print(f"[+] Found {len(results)} results via API.")
                    return results
        except Exception as e:
            print(f"[-] API Error on {api}: {e}")
            
    return []
