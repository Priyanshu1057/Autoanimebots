"""
AniWatch / HiAnime Anime Searcher
Fixed with BeautifulSoup parsing, multiple domain failover, and structured metadata output.
"""

from typing import List, Dict, Any, Optional
import json
import sys

try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False

from bs4 import BeautifulSoup

# Proxy helper with fallback
try:
    from cantarella.core.proxy import get_random_proxy, get_proxy_dict
except ImportError:
    def get_random_proxy():
        return None
    def get_proxy_dict(proxy):
        if not proxy:
            return None
        return {"http": proxy, "https": proxy} if isinstance(proxy, str) else proxy


DOMAINS = [
    "https://hianime.to",
    "https://aniwatchtv.to",
    "https://aniwatch.se"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_anime(query: str, limit: int = 10, proxy: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Searches for anime across AniWatch / HiAnime mirrors.
    Returns structured list of anime with title, ID, poster, type, duration, and episode counts.
    """
    if not query.strip():
        return []

    session = requests.Session()
    active_proxy = proxy or get_random_proxy()
    proxy_dict = get_proxy_dict(active_proxy)
    if proxy_dict:
        session.proxies.update(proxy_dict)

    search_path = f"/search?keyword={query.replace(' ', '+')}"

    for base_url in DOMAINS:
        search_url = f"{base_url}{search_path}"
        try:
            kwargs = {"headers": {**HEADERS, "Referer": f"{base_url}/"}, "timeout": 30}
            if HAS_CURL_CFFI:
                kwargs["impersonate"] = "chrome"

            resp = session.get(search_url, **kwargs)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')
            results = []

            items = soup.select('.film_list-wrap .flw-item')
            if not items:
                # Try fallback selector
                items = soup.select('.film-poster')

            for item in items:
                title_elem = item.select_one('.film-name a')
                if not title_elem:
                    continue

                title = title_elem.get('title') or title_elem.text.strip()
                href = title_elem.get('href', '')

                # Poster image
                poster_img = item.select_one('.film-poster-img')
                poster_url = ""
                if poster_img:
                    poster_url = poster_img.get('data-src') or poster_img.get('src', '')

                # Extract anime_id / slug
                slug = href.replace("/watch/", "").replace("/", "").split("?")[0]
                anime_id = slug.split("-")[-1]

                # Metadata tags
                type_elem = item.select_one('.fdi-item')
                anime_type = type_elem.text.strip() if type_elem else "TV"

                duration_elem = item.select_one('.fdi-duration, .fdi-item.fdi-duration')
                duration = duration_elem.text.strip() if duration_elem else ""

                # Episode numbers (sub, dub, total)
                sub_el = item.select_one('.tick-sub')
                dub_el = item.select_one('.tick-dub')
                eps_el = item.select_one('.tick-eps')

                results.append({
                    'title': title,
                    'id': anime_id,
                    'slug': slug,
                    'type': anime_type,
                    'duration': duration,
                    'poster': poster_url,
                    'episodes': {
                        'sub': sub_el.text.strip() if sub_el else None,
                        'dub': dub_el.text.strip() if dub_el else None,
                        'total': eps_el.text.strip() if eps_el else None,
                    },
                    'url': f"{base_url}{href}" if href.startswith('/') else f"{base_url}/{href}"
                })

                if len(results) >= limit:
                    break

            if results:
                return results

        except Exception as e:
            print(f"[Warning] Search failed on {base_url}: {e}")
            continue

    return []


if __name__ == '__main__':
    query_term = sys.argv[1] if len(sys.argv) > 1 else 'naruto'
    print(f"Searching anime for: '{query_term}'...")
    res = search_anime(query_term)
    print(json.dumps(res, indent=2))
