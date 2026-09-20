#@cantarellabots
from cantarella.core.proxy import get_random_proxy, get_proxy_dict
from pathlib import Path
from queue import Queue
import math
from curl_cffi import requests
import re
import json
import time
import subprocess
import shutil
import os as _os
import html
import urllib.parse
from threading import Thread
from cantarella.scraper.megacloud import Megacloud


class AnimeResult(dict):
    """
    Robust dictionary representing an anime result.
    Supports dict key access: res['id'], res['title'], etc.
    Supports attribute access: res.id, res.title.
    Supports string methods & conversion: str(res) returns id, res.split(), etc.
    Supports integer index: res[0] returns first char of id without crashing.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._str_val = str(self.get('id', ''))

    def __str__(self):
        return self._str_val

    def __repr__(self):
        return super().__repr__()

    def __getattr__(self, name):
        if name in self:
            return self[name]
        if hasattr(self._str_val, name):
            return getattr(self._str_val, name)
        raise AttributeError(f"'AnimeResult' object has no attribute '{name}'")

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._str_val[key] if key < len(self._str_val) else ""
        return super().get(key, None)

    def get(self, key, default=None):
        return super().get(key, default)


class AnimeList(list):
    """
    Robust list of AnimeResult objects.
    Supports iteration (for res in results:),
    direct dict-style key access (results['id']) if caller didn't loop,
    and safe .get() method.
    """
    def __getitem__(self, key):
        if isinstance(key, str):
            if len(self) > 0 and isinstance(self[0], dict):
                return self[0].get(key)
            return None
        return super().__getitem__(key)

    def get(self, key, default=None):
        if len(self) > 0 and isinstance(self[0], dict):
            return self[0].get(key, default)
        return default


class cantarellatvDownloader:
    def __init__(self, download_path="anime_downloads", progress_queue=None):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True)
        self.binary_path = self._get_binary_path()
        self.progress_queue = progress_queue or Queue()
        self.base_url = "https://aniwaves.ru"
        self.ajax_url = f"{self.base_url}/ajax"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{self.base_url}/",
        }
        self.ajax_headers = {
            **self.headers,
            "X-Requested-With": "XMLHttpRequest",
        }
        self.proxy = get_random_proxy()
        self.session = requests.Session()
        proxy_dict = get_proxy_dict(self.proxy)
        if proxy_dict:
            self.session.proxies.update(proxy_dict)

    def _get_binary_path(self):
        candidates = [
            Path("binary") / "N_m3u8DL-RE",
            Path("binary") / "N_m3u8DL-RE.exe",
            Path("/usr/local/bin/N_m3u8DL-RE"),
        ]
        for p in candidates:
            if p.exists():
                return p
        which_path = shutil.which("N_m3u8DL-RE")
        if which_path:
            return Path(which_path)
        return Path("N_m3u8DL-RE")

    def _format_bytes(self, bytes_num):
        if bytes_num == 0:
            return '0 B'
        size_name = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(bytes_num, 1024)))
        p = math.pow(1024, i)
        s = round(bytes_num / p, 2)
        return f"{s} {size_name[i]}"

    def _parse_url_slug(self, url):
        url_str = str(url).strip()
        slug = None
        match = re.search(r'watch/([^/?#]+)', url_str)
        if match:
            slug = match.group(1).strip()
        else:
            match = re.search(r'/([^/]+)-episode-(\d+)', url_str)
            if match:
                slug = match.group(1).strip()

        numeric_id = slug.split('-')[-1] if slug else None

        ep_num = "1"
        ep_match = (
            re.search(r'/ep-([0-9.]+)', url_str)
            or re.search(r'[?&]ep=([0-9.]+)', url_str)
            or re.search(r'episode-([0-9.]+)', url_str)
        )
        if ep_match:
            ep_num = ep_match.group(1)

        return slug, numeric_id, ep_num

    def get_episode_id(self, url):
        slug, anime_id, ep_num = self._parse_url_slug(url)
        if anime_id:
            return f"{anime_id}&eps={ep_num}"

        anime_name_match = (
            re.search(r'/([^/]+)-episode-(\d+)', url)
            or re.search(r'watch/([^/]+)-(\d+)', url)
        )
        if anime_name_match:
            anime_name = anime_name_match.group(1).replace('-', ' ')
            ep_num = anime_name_match.group(2)
            return self._find_ep_id_by_name(anime_name, ep_num)

        match = re.search(r'-(\d+)$', url)
        if match:
            return f"{match.group(1)}&eps=1"
        return None

    def search_anime(self, query):
        """
        Search anime on Aniwave using AJAX search endpoint or URL.
        Returns list of dicts: [{'title', 'name', 'id', 'slug', 'type', 'poster', 'image', 'url', 'link'}]
        """
        if not query:
            return []

        query_str = str(query).strip()

        # Handle URL input directly in search
        if "watch/" in query_str or "aniwaves" in query_str or query_str.startswith("http"):
            slug, anime_id, _ = self._parse_url_slug(query_str)
            if slug:
                info = self.get_anime_info(slug)
                if info:
                    title_str = info['title']['english'] if isinstance(info.get('title'), dict) else str(info.get('title', slug))
                    return AnimeList([AnimeResult({
                        "id": str(info.get('id') or anime_id or slug.split('-')[-1]),
                        "title": title_str,
                        "name": title_str,
                        "slug": slug,
                        "type": info.get('type', 'TV'),
                        "poster": info.get('poster'),
                        "image": info.get('poster'),
                        "url": f"{self.base_url}/watch/{slug}",
                        "link": f"{self.base_url}/watch/{slug}",
                    })])
                clean_title = re.sub(r'-\d+$', '', slug).replace('-', ' ').title()
                return AnimeList([AnimeResult({
                    "id": str(anime_id or slug.split('-')[-1]),
                    "title": clean_title,
                    "name": clean_title,
                    "slug": slug,
                    "type": "TV",
                    "poster": None,
                    "image": None,
                    "url": f"{self.base_url}/watch/{slug}",
                    "link": f"{self.base_url}/watch/{slug}",
                })])

        search_url = f"{self.ajax_url}/anime/search?keyword={urllib.parse.quote_plus(query_str)}"
        results = []
        try:
            resp = self.session.get(search_url, headers=self.ajax_headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                html_content = ""
                if isinstance(data, dict):
                    res_val = data.get("result", "")
                    if isinstance(res_val, dict):
                        html_content = res_val.get("html", "")
                    elif isinstance(res_val, str):
                        html_content = res_val

                if html_content:
                    items = re.findall(
                        r'<a[^>]+class=["\'][^"\']*item[^"\']*["\'][^>]+href=["\'](/watch/[^"\']+)["\'][^>]*>(.*?)</a>',
                        html_content,
                        re.DOTALL | re.I
                    )
                    for href, inner in items:
                        name_match = re.search(r'class=["\']name[^"\']*["\'][^>]*data-jp=["\']?([^"\'>]+)?["\']?[^>]*>([^<]+)<', inner)
                        title = ""
                        if name_match:
                            title = name_match.group(2).strip() or name_match.group(1).strip()
                        else:
                            title = href.split('/')[-1]

                        poster_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', inner)
                        poster = poster_match.group(1) if poster_match else None

                        type_match = re.search(r'<span[^>]+class=["\']dot["\']>([^<]+)</span>', inner)
                        anime_type = type_match.group(1).strip().upper() if type_match else "TV"

                        slug = href.replace("/watch/", "").strip("/")
                        anime_id = slug.split("-")[-1]
                        clean_title = html.unescape(title)

                        results.append(AnimeResult({
                            "title": clean_title,
                            "name": clean_title,
                            "id": str(anime_id),
                            "slug": slug,
                            "type": anime_type,
                            "poster": poster,
                            "image": poster,
                            "url": f"{self.base_url}{href}",
                            "link": f"{self.base_url}{href}",
                        }))
                    if results:
                        return AnimeList(results)
        except Exception as e:
            print(f"Error in search_anime: {e}")
        return AnimeList(results)

    def search(self, query):
        """Alias for search_anime."""
        return self.search_anime(query)

    def _find_ep_id_by_name(self, anime_name, ep_num="1"):
        """Internal helper to resolve episode ID for a given anime title and episode number."""
        search_results = self.search_anime(anime_name)
        if search_results:
            first = search_results[0]
            slug = first['slug']
            anime_id = first['id']

            ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
            headers = {**self.ajax_headers, "Referer": f"{self.base_url}/watch/{slug}"}
            try:
                resp_eps = self.session.get(ep_list_url, headers=headers, impersonate="chrome")
                if resp_eps.status_code == 200:
                    ep_data = resp_eps.json()
                    ep_html = ep_data.get("result", "") if isinstance(ep_data, dict) else resp_eps.text

                    ep_match = re.search(rf'data-num=["\']{ep_num}["\'][^>]*data-ids=["\']([^"\']+)["\']', ep_html)
                    if not ep_match:
                        ep_match = re.search(rf'data-ids=["\']([^"\']+)["\'][^>]*data-num=["\']{ep_num}["\']', ep_html)

                    if ep_match:
                        return ep_match.group(1).replace("&amp;", "&")
                    return f"{anime_id}&eps={ep_num}"
            except Exception as e:
                print(f"Error resolving episode ID: {e}")
        return None

    def search_cantarella(self, query, ep_num=None):
        """
        Searches anime.
        If ep_num is provided, returns the episode ID string for backward compatibility.
        If ep_num is None, returns the list of anime dictionaries.
        """
        if ep_num is not None:
            return self._find_ep_id_by_name(query, ep_num)
        return self.search_anime(query)

    def get_anime_info(self, anime_id_or_url):
        """
        Fetch anime metadata (title, synopsis, internal_id, poster) from the watch page.
        Returns dict with: id, slug, title, name, synopsis, poster, image, url, link, type
        """
        slug = str(anime_id_or_url).replace(self.base_url, "").replace("/watch/", "").strip("/")
        url = f"{self.base_url}/watch/{slug}"
        try:
            resp = self.session.get(url, headers=self.headers, impersonate="chrome120")
            if resp.status_code == 200:
                body = resp.text
                title_match = re.search(r'<h1[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h1>', body, re.I)
                if not title_match:
                    title_match = re.search(r'<h2[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h2>', body, re.I)
                if not title_match:
                    title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', body, re.I)
                title = title_match.group(1).strip() if title_match else re.sub(r'-\d+$', '', slug).replace('-', ' ').title()

                jp_match = re.search(r'data-jp=["\']([^"\']+)["\']', body)
                title_jp = jp_match.group(1).strip() if jp_match else title

                syn_match = re.search(r'<div[^>]+class=["\'][^"\']*synopsis[^"\']*["\'][^>]*>(.*?)</div>', body, re.DOTALL | re.I)
                synopsis = ""
                if syn_match:
                    synopsis = re.sub(r'<[^>]+>', '', syn_match.group(1)).strip()

                id_match = re.search(r'data-id=["\']([0-9a-zA-Z]+)["\']', body)
                internal_id = id_match.group(1) if id_match else slug.split("-")[-1]

                poster_match = re.search(r'<div[^>]+class=["\']poster["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', body, re.DOTALL | re.I)
                poster = poster_match.group(1) if poster_match else None

                type_match = re.search(r'<span[^>]+class=["\']dot["\']>([^<]+)</span>', body)
                anime_type = type_match.group(1).strip().upper() if type_match else "TV"

                clean_title = html.unescape(title)
                clean_jp = html.unescape(title_jp)

                return AnimeResult({
                    "id": str(internal_id),
                    "slug": slug,
                    "title": {
                        "english": clean_title,
                        "romaji": clean_jp,
                        "native": clean_jp,
                    },
                    "name": clean_title,
                    "type": anime_type,
                    "synopsis": html.unescape(synopsis),
                    "poster": poster,
                    "image": poster,
                    "url": url,
                    "link": url,
                })
        except Exception as e:
            print(f"Anime info error: {e}")
        return None

    def get_anime(self, anime_id_or_url):
        """Alias for get_anime_info."""
        return self.get_anime_info(anime_id_or_url)

    def get_schedule(self, date_str=None):
        url = f"{self.ajax_url}/schedule"
        if date_str:
            url += f"?date={date_str}"
        try:
            resp = self.session.get(url, headers=self.ajax_headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                html_content = data.get("html", "") or data.get("result", "")
                results = []
                items = re.findall(
                    r'<a[^>]+href=["\'](/watch/[^"\']+)["\'][^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL
                )
                for href, inner in items:
                    title_m = re.search(r'class=["\']name[^"\']*["\'][^>]*>([^<]+)<', inner)
                    time_m = re.search(r'class=["\']time[^"\']*["\'][^>]*>([^<]+)<', inner)
                    ep_m = re.search(r'class=["\']ep[^"\']*["\'][^>]*>([^<]+)<', inner)
                    slug = href.replace("/watch/", "").strip("/")
                    title = title_m.group(1).strip() if title_m else slug
                    results.append(AnimeResult({
                        "id": str(slug.split("-")[-1]),
                        "slug": slug,
                        "title": title,
                        "name": title,
                        "time": time_m.group(1).strip() if time_m else "Unknown",
                        "ep": ep_m.group(1).strip() if ep_m else "",
                        "episode": ep_m.group(1).strip() if ep_m else "",
                        "url": f"{self.base_url}{href}",
                        "link": f"{self.base_url}{href}",
                    }))
                return AnimeList(results)
        except Exception as e:
            print(f"Error fetching schedule: {e}")
        return AnimeList([])

    def get_episode_servers(self, anime_id, ep_num):
        """Get server options for a specific episode."""
        slug = str(anime_id).replace(self.base_url, "").replace("/watch/", "").strip("/")
        numeric_id = slug.split("-")[-1]
        srv_url = f"{self.ajax_url}/server/list?servers={numeric_id}&eps={ep_num}"
        headers = {**self.ajax_headers, "Referer": f"{self.base_url}/watch/{slug}/ep-{ep_num}"}

        try:
            resp = self.session.get(srv_url, headers=headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                srv_html = data.get("result", "") if isinstance(data, dict) else resp.text

                servers = []
                types = re.findall(r'<div[^>]+class=["\']type["\'][^>]+data-type=["\']([^"\']+)["\'][^>]*>(.*?)</div>\s*(?=<div class=["\']type["\']|</div>|$)', srv_html, re.DOTALL)
                for stype, block in types:
                    lis = re.findall(r'<li[^>]+data-sv-id=["\']([^"\']+)["\'][^>]+data-link-id=["\']([^"\']+)["\'][^>]*>([^<]+)<', block)
                    for sv_id, link_id, sname in lis:
                        servers.append({
                            "type": stype,
                            "server_id": sv_id,
                            "link_id": link_id,
                            "server_name": sname.strip(),
                        })
                return servers
        except Exception as e:
            print(f"Error fetching servers: {e}")
        return []

    def get_episode_sources(self, anime_id, ep_num, server='default', source_type='sub'):
        """Fetch stream embed URL and skip metadata for an episode."""
        servers = self.get_episode_servers(anime_id, ep_num)
        if not servers:
            return None

        candidates = [s for s in servers if s['type'].lower() == source_type.lower()]
        if not candidates:
            candidates = servers

        chosen = None
        server_priority = {"4": 1, "1": 2, "2": 3}
        sorted_candidates = sorted(candidates, key=lambda s: server_priority.get(s['server_id'], 99))
        chosen = sorted_candidates[0] if sorted_candidates else None

        if not chosen:
            return None

        slug = str(anime_id).replace(self.base_url, "").replace("/watch/", "").strip("/")
        return self._get_sources(chosen['link_id'], anime_id=slug.split("-")[-1], ep_num=ep_num, slug=slug)

    def get_episode_data(self, ep_id, slug=None):
        ep_id_str = str(ep_id).replace("&amp;", "&")
        if "&eps=" in ep_id_str:
            anime_id, ep_num = ep_id_str.split("&eps=")
        else:
            anime_id, ep_num = ep_id_str, "1"

        server_url = f"{self.ajax_url}/server/list?servers={anime_id}&eps={ep_num}"
        referer = f"{self.base_url}/watch/{slug or anime_id}/ep-{ep_num}"
        headers = {**self.ajax_headers, "Referer": referer}

        result = {'sub': None, 'dub': None}
        try:
            resp_servers = self.session.get(server_url, headers=headers, impersonate="chrome")
            if resp_servers.status_code != 200:
                return None

            data = resp_servers.json()
            srv_html = data.get("result", "") if isinstance(data, dict) else resp_servers.text

            type_blocks = re.findall(
                r'<div[^>]+class=["\']type["\'][^>]+data-type=["\']([^"\']+)["\'][^>]*>(.*?)</div>\s*(?=<div class=["\']type["\']|</div>|$)',
                srv_html,
                re.DOTALL
            )

            server_priority = {"4": 1, "1": 2, "2": 3}

            def find_sources_for_type(target_type):
                for stype, block in type_blocks:
                    if stype.lower() != target_type.lower():
                        continue
                    lis = re.findall(
                        r'<li[^>]+data-sv-id=["\']([^"\']+)["\'][^>]+data-link-id=["\']([^"\']+)["\'][^>]*>([^<]+)<',
                        block
                    )
                    sorted_lis = sorted(lis, key=lambda x: server_priority.get(x[0], 99))
                    for sv_id, link_id, sname in sorted_lis:
                        sources = self._get_sources(link_id, anime_id, ep_num, slug)
                        if sources and sources.get('sources'):
                            return sources
                return None

            result['sub'] = find_sources_for_type('sub')
            result['dub'] = find_sources_for_type('dub')

            return result if result['sub'] or result['dub'] else None
        except Exception as e:
            print(f"Error in get_episode_data: {e}")
        return None

    def _get_sources(self, server_data_id, anime_id=None, ep_num=None, slug=None):
        try:
            enc_id = urllib.parse.quote(server_data_id)
            sources_url = f"{self.ajax_url}/sources?id={enc_id}&asi=0&autoPlay=0"
            referer = f"{self.base_url}/watch/{slug or anime_id or 'anime'}/ep-{ep_num or 1}"
            headers = {**self.ajax_headers, "Referer": referer}

            resp_sources = self.session.get(sources_url, headers=headers, impersonate="chrome")
            if resp_sources.status_code != 200:
                return None

            sources_data = resp_sources.json()
            if sources_data.get("status") != 200:
                return None

            res = sources_data.get("result", {})
            embed_url = res.get("url")
            tracks = res.get("tracks", [])

            if embed_url:
                cloud_keys = ["megacloud", "rapid-cloud", "cloud-stream"]
                if any(k in embed_url.lower() for k in cloud_keys):
                    try:
                        scraper = Megacloud(embed_url)
                        extracted = scraper.extract()
                        if isinstance(extracted.get('sources'), list) and extracted['sources']:
                            return extracted
                    except Exception as e:
                        print(f"Megacloud fallback: {e}")

                return {
                    "sources": [{"file": embed_url, "url": embed_url, "type": "hls"}],
                    "tracks": tracks,
                    "skip_data": res.get("skip_data"),
                    "server": res.get("server"),
                }
        except Exception as e:
            print(f"Error in _get_sources: {e}")
        return None

    def get_episode_info(self, url):
        slug, anime_id, ep_num = self._parse_url_slug(url)
        if not anime_id:
            return "Anime", "0", "Unknown", "1"

        anime_name = None
        try:
            page_url = f"{self.base_url}/watch/{slug}"
            resp_page = self.session.get(page_url, headers=self.headers, impersonate="chrome")
            if resp_page.status_code == 200:
                body = resp_page.text
                title_match = re.search(r'<h1[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h1>', body, re.I)
                if not title_match:
                    title_match = re.search(r'<h2[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h2>', body, re.I)
                if title_match:
                    anime_name = html.unescape(title_match.group(1).strip())
                else:
                    jp_match = re.search(r'data-jp=["\']([^"\']+)["\']', body)
                    if jp_match:
                        anime_name = html.unescape(jp_match.group(1).strip())
        except Exception as e:
            print(f"Could not fetch title: {e}")

        ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
        headers = {**self.ajax_headers, "Referer": f"{self.base_url}/watch/{slug}"}

        try:
            resp_eps = self.session.get(ep_list_url, headers=headers, impersonate="chrome")
            if resp_eps.status_code == 200:
                ep_data = resp_eps.json()
                ep_html = ep_data.get("result", "") if isinstance(ep_data, dict) else resp_eps.text

                ep_match = re.search(rf'data-num=["\']{ep_num}["\'][^>]*title=["\']?([^"\'>]+)?["\']?', ep_html)
                if not ep_match:
                    ep_match = re.search(rf'title=["\']?([^"\'>]+)?["\']?[^>]*data-num=["\']{ep_num}["\']', ep_html)

                ep_title = ep_match.group(1).strip() if ep_match and ep_match.group(1) else f"Episode {ep_num}"
                ep_title = html.unescape(ep_title)

                if not anime_name:
                    anime_name = slug.replace('-', ' ').title()
                    anime_name = re.sub(r' \d+$', '', anime_name)

                season_match = re.search(r'Season (\d+)', anime_name, re.I)
                if season_match:
                    season = season_match.group(1)
                    clean_name = anime_name.replace(season_match.group(0), '').strip()
                    anime_name = re.sub(r'\s+', ' ', clean_name)
                else:
                    season = "1"

                return anime_name, str(ep_num), ep_title, season
        except Exception as e:
            print(f"Error in get_episode_info: {e}")

        if anime_name:
            return anime_name, str(ep_num), f"Episode {ep_num}", "1"
        return slug.replace('-', ' ').title(), str(ep_num), f"Episode {ep_num}", "1"

    def list_episodes(self, anime_url):
        slug, anime_id, _ = self._parse_url_slug(anime_url)
        if not anime_id:
            kw = urllib.parse.quote_plus(anime_url)
            search_url = f"{self.ajax_url}/anime/search?keyword={kw}"
            try:
                resp = self.session.get(search_url, headers=self.ajax_headers, impersonate="chrome")
                if resp.status_code == 200:
                    data = resp.json()
                    html_content = data.get("result", {}).get("html", "") if isinstance(data.get("result"), dict) else data.get("result", "")
                    items = re.findall(r'<a[^>]+href=["\'](/watch/[^"\']+)["\']', html_content)
                    if items:
                        slug = items[0].replace("/watch/", "").strip("/")
                        anime_id = slug.split("-")[-1]
            except Exception as e:
                print(f"Error searching episodes: {e}")
                return []

        if not anime_id:
            return []

        ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
        headers = {**self.ajax_headers, "Referer": f"{self.base_url}/watch/{slug}"}

        try:
            resp_eps = self.session.get(ep_list_url, headers=headers, impersonate="chrome")
            if resp_eps.status_code == 200:
                data = resp_eps.json()
                ep_html = data.get("result", "") if isinstance(data, dict) else resp_eps.text

                results = []
                ep_tags = re.findall(
                    r'<a[^>]+data-ids=["\']([^"\']+)["\'][^>]+data-num=["\']([0-9.]+)["\'][^>]*title=["\']?([^"\'>]+)?["\']?',
                    ep_html
                )
                for ids, num, title in ep_tags:
                    clean_t = html.unescape(title.strip()) if title else f"Episode {num}"
                    results.append({
                        'title': clean_t,
                        'name': clean_t,
                        'url': f"{self.base_url}/watch/{slug}/ep-{num}",
                        'link': f"{self.base_url}/watch/{slug}/ep-{num}",
                        'ep_number': str(num),
                        'ep_id': ids.replace("&amp;", "&"),
                    })
                return results
        except Exception as e:
            print(f"Error fetching episodes: {e}")
        return []

    def download_episode(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None):
        if quality == "all":
            success = True
            for q in ["360", "720", "1080"]:
                ok = self._download_with_retry(
                    url,
                    quality=q,
                    name_override=name_override,
                    season_override=season_override,
                    ep_num_override=ep_num_override
                )
                if not ok:
                    success = False
            return success
        else:
            return self._download_with_retry(
                url,
                quality=quality,
                name_override=name_override,
                season_override=season_override,
                ep_num_override=ep_num_override
            )

    def _download_with_retry(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None, max_retries=3):
        for i in range(max_retries):
            try:
                ok = self._download_single_episode(
                    url,
                    quality=quality,
                    name_override=name_override,
                    season_override=season_override,
                    ep_num_override=ep_num_override
                )
                if ok:
                    return True
            except Exception as e:
                print(f"Attempt {i+1} failed: {e}")
            time.sleep(5)
        return False

    def _download_single_episode(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None):
        slug, _, _ = self._parse_url_slug(url)
        ep_id = self.get_episode_id(url)
        if not ep_id:
            self.progress_queue.put({'error': 'Could not find episode ID.'})
            return False

        all_data = self.get_episode_data(ep_id, slug=slug)
        if not all_data or (not all_data.get('sub') and not all_data.get('dub')):
            self.progress_queue.put({'error': 'Could not find video source.'})
            return False

        anime_name, ep_num, ep_title, season = self.get_episode_info(url)

        final_name = name_override if name_override else anime_name
        final_season = season_override if season_override else season
        final_ep_num = ep_num_override if ep_num_override else ep_num

        audio = "JP"
        if all_data.get('sub') and all_data.get('dub'):
            audio = "Dual Audio"
        elif all_data.get('dub'):
            audio = "EN"

        qual_str = quality if quality in ["360", "720", "1080"] else "auto"

        def sanitize(name):
            return re.sub(r'[\\/*?:"<>|]', "", name)

        try:
            from config import FORMAT
        except ImportError:
            FORMAT = "[S{season}-E{episode}] {title} [{quality}] [{audio}]"

        base_filename_str = FORMAT.format(
            season=final_season,
            episode=final_ep_num,
            title=final_name,
            quality=f"{qual_str}p",
            audio=audio
        )

        base_filename = sanitize(base_filename_str)
        safe_id = ep_id.replace('&', '_').replace('=', '_')
        clean_ep_id = sanitize(safe_id)
        task_dir = self.download_path / f"{clean_ep_id}_{qual_str}"
        task_dir.mkdir(exist_ok=True)

        video_temp = task_dir / f"{base_filename}_sub.mkv"
        audio_temp = task_dir / f"{base_filename}_dub.mkv"
        final_file = self.download_path / f"{base_filename}.mkv"

        data = all_data.get('sub') or all_data.get('dub')
        source_item = data['sources'][0]
        m3u8_url = source_item.get('file') or source_item.get('url')

        status_msg = f"📥 **Downloading: {final_name} [{qual_str}p]**\nPlease wait..."
        self.progress_queue.put({'status': status_msg})

        def run_n_m3u8dl(dl_url, save_name, dl_type='sub', quality="auto"):
            ua_header = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ref_header = f"Referer: {self.base_url}/"
            cmd = []
            cmd.append(str(self.binary_path))
            cmd.append(dl_url)
            cmd.append("--save-dir")
            cmd.append(str(task_dir))
            cmd.append("--save-name")
            cmd.append(save_name)
            cmd.append("-H")
            cmd.append(ua_header)
            cmd.append("-H")
            cmd.append(ref_header)
            cmd.append("--check-segments-count")
            cmd.append("False")
            cmd.append("-mt")
            cmd.append("--thread-count")
            cmd.append("50")
            cmd.append("--download-retry-count")
            cmd.append("5")

            if self.proxy:
                cmd.append("--custom-proxy")
                cmd.append(self.proxy)

            if quality == "1080":
                cmd.extend(["-sv", "res='1080':for=best"])
            elif quality == "720":
                cmd.extend(["-sv", "res='720':for=best"])
            elif quality == "360":
                cmd.extend(["-sv", "res='360':for=best"])
            else:
                cmd.append("--auto-select")

            try:
                bin_preview = ' '.join(cmd[:3])
                print(f"[{dl_type.upper()}] Running: {bin_preview}", flush=True)

                if not _os.path.isfile(cmd[0]):
                    print(f"Binary not found: {cmd[0]}", flush=True)
                    return False

                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
                last_lines = []
                buffer = b""
                while True:
                    char = process.stdout.read(1)
                    if not char:
                        break
                    if char in (b'\r', b'\n'):
                        try:
                            line = buffer.decode('utf-8', errors='replace').strip()
                        except:
                            line = ""

                        if line:
                            line = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line)
                            last_lines.append(line)
                            if len(last_lines) > 5:
                                last_lines.pop(0)

                            if "%" in line:
                                percent_match = re.search(r"(\d+(\.\d+)?)%", line)
                                parts = re.split(r"\d+(\.\d+)?%", line)
                                speed_match = None
                                if len(parts) > 1:
                                    after_percent = parts[-1]
                                    speed_match = re.search(r"(\d+(\.\d+)?\s*[MKG]?i?(B/s|bps|b/s|bit/s))", after_percent, re.I)
                                    if not speed_match:
                                        speed_match = re.search(r"(\d+(\.\d+)?\s*\S+/(s|sec))", after_percent, re.I)

                                if not speed_match:
                                    speed_match = re.search(r"(\d+(\.\d+)?\s*[MKG]?i?(B/s|bps|b/s|bit/s))", line, re.I)

                                size_match = re.search(r"(\d+(\.\d+)?\s*\S+)\s*/\s*(\d+(\.\d+)?\s*\S+)", line, re.I)

                                if percent_match:
                                    pct_val = percent_match.group(1)
                                    speed_val = speed_match.group(1) if speed_match else "0 MB/s"
                                    progress_data = {
                                        'percent': f"{pct_val}%",
                                        'speed': speed_val,
                                        'downloaded': size_match.group(1) if size_match else "0 MB",
                                        'total': size_match.group(3) if size_match else "0 MB",
                                        'type': dl_type,
                                        'title': ep_title
                                    }
                                    self.progress_queue.put(progress_data)
                        buffer = b""
                    else:
                        buffer += char

                process.wait()
                return process.returncode == 0
            except Exception as e:
                print(f"Error running N_m3u8DL-RE: {e}", flush=True)
                return False

        dub_downloaded = [False]
        dub_thread = None
        if all_data.get('sub') and all_data.get('dub'):
            dub_source_item = all_data['dub']['sources'][0]
            dub_url = dub_source_item.get('file') or dub_source_item.get('url')

            def download_dub():
                save_name = f"{base_filename}_dub"
                if run_n_m3u8dl(dub_url, save_name, dl_type='dub', quality=quality):
                    for ext in ['.mp4', '.m4a', '.mkv', '.ts']:
                        p = task_dir / f"{save_name}{ext}"
                        if p.exists():
                            p.rename(audio_temp)
                            dub_downloaded[0] = True
                            break

            dub_thread = Thread(target=download_dub)
            dub_thread.start()

        save_name_sub = f"{base_filename}_sub"
        if run_n_m3u8dl(m3u8_url, save_name_sub, dl_type='sub', quality=quality):
            for ext in ['.mp4', '.mkv', '.ts']:
                p = task_dir / f"{save_name_sub}{ext}"
                if p.exists():
                    p.rename(video_temp)
                    break
        else:
            self.progress_queue.put({'error': "Video download failed"})
            if dub_thread:
                dub_thread.join()
            return False

        if dub_thread:
            dub_thread.join()

        dub_downloaded = dub_downloaded[0]

        sub_files = []
        if data.get('tracks'):
            subs = [t for t in data['tracks'] if t.get('kind') == 'captions']
            for i, s in enumerate(subs):
                lang = s.get('label', f'sub_{i}').lower().replace(' ', '_')
                sub_path = task_dir / f"{base_filename}_{lang}.vtt"
                try:
                    r = self.session.get(s['file'], timeout=10)
                    if r.status_code == 200:
                        with open(sub_path, 'wb') as f:
                            f.write(r.content)
                        sub_files.append((sub_path, lang))
                except:
                    pass

        ffmpeg_exe = 'ffmpeg'
        if not video_temp.exists():
            for f in task_dir.iterdir():
                if f.name.startswith(f"{base_filename}_sub."):
                    f.replace(video_temp)
                    break

        if not shutil.which(ffmpeg_exe) or (not sub_files and not dub_downloaded):
            if video_temp.exists():
                video_temp.replace(final_file)
            try:
                shutil.rmtree(task_dir)
            except:
                pass
            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True

        self.progress_queue.put({'status': f"🎬 **Merging Tracks for: {ep_title}**\nPlease wait..."})

        cmd = [ffmpeg_exe, '-y']
        if video_temp.exists():
            cmd.extend(['-i', str(video_temp)])
        else:
            self.progress_queue.put({'error': 'Video file disappeared before merge.'})
            return False

        if dub_downloaded and audio_temp.exists():
            cmd.extend(['-i', str(audio_temp)])
        else:
            dub_downloaded = False

        valid_subs = []
        for sub_path, lang in sub_files:
            if sub_path.exists():
                cmd.extend(['-i', str(sub_path)])
                valid_subs.append((sub_path, lang))

        sub_files = valid_subs

        cmd.extend(['-map', '0:v'])
        cmd.extend(['-map', '0:a'])
        if dub_downloaded:
            cmd.extend(['-map', '1:a:0'])

        sub_offset = 2 if dub_downloaded else 1
        for i in range(len(sub_files)):
            cmd.extend(['-map', f'{i + sub_offset}:s'])

        cmd.extend(['-c', 'copy', '-c:s', 'srt'])
        cmd.extend(['-metadata:s:a:0', 'language=jpn', '-metadata:s:a:0', 'title=Japanese'])
        if dub_downloaded:
            cmd.extend(['-metadata:s:a:1', 'language=eng', '-metadata:s:a:1', 'title=English'])

        if sub_files:
            cmd.extend(['-disposition:s:0', 'default'])

        cmd.append(str(final_file))

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            try:
                shutil.rmtree(task_dir)
            except:
                pass

            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True
        except Exception:
            if video_temp.exists():
                video_temp.replace(final_file)
            elif not final_file.exists():
                for f in task_dir.iterdir():
                    if f.name.startswith(f"{base_filename}_sub."):
                        f.replace(final_file)
                        break

            try:
                shutil.rmtree(task_dir)
            except:
                pass

            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True

    def download_all_episodes(self, anime_url, quality="auto"):
        eps = self.list_episodes(anime_url)
        for ep in eps:
            self.download_episode(ep['url'], quality=quality)
        return True

    def download_range(self, anime_url, start, end, quality="auto"):
        eps = self.list_episodes(anime_url)
        for ep in eps:
            try:
                num = int(float(ep.get('ep_number', 0)))
                if not num:
                    match = re.search(r'Episode (\d+)', ep['title'])
                    if match:
                        num = int(match.group(1))

                if start <= num <= end:
                    self.download_episode(ep['url'], quality=quality)
            except:
                pass
        return True


# Backward-compatible aliases
AniwaveScraper = cantarellatvDownloader
AnimetsuScraper = cantarellatvDownloader
