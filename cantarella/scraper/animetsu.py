#@cantarellabots
from cantarella.core.proxy import get_random_proxy, get_proxy_dict
from curl_cffi import requests as c_requests
import json
import re
import subprocess
import shutil
import os
import html
import urllib.parse
from pathlib import Path

class AniwaveScraper:
    """
    Scraper & Downloader for Aniwave (https://aniwaves.ru)
    Compatible with Cantarella framework and telegram bot plugins.
    """
    BASE_URL = "https://aniwaves.ru"
    AJAX_URL = f"{BASE_URL}/ajax"
    PROXY_URL = "https://swiftstream.top/proxy"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
    }

    AJAX_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/",
    }

    def __init__(self, download_path="anime_downloads", progress_queue=None):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True)
        self.progress_queue = progress_queue
        self.binary_path = self._get_binary_path()
        self.proxy = get_random_proxy()
        self.session = c_requests.Session()
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
        return None

    def search_anime(self, query):
        """
        Search anime on Aniwave using AJAX search endpoint.
        Returns list of dicts: {'title', 'id', 'slug', 'type', 'url', 'poster'}
        """
        ajax_url = f"{self.AJAX_URL}/anime/search?keyword={urllib.parse.quote_plus(query)}"
        results = []
        try:
            resp = self.session.get(ajax_url, headers=self.AJAX_HEADERS, impersonate="chrome120")
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
                        re.DOTALL | re.IGNORECASE,
                    )
                    for href, inner in items:
                        name_match = re.search(
                            r'class=["\']name[^"\']*["\'][^>]*data-jp=["\']?([^"\'>]+)?["\']?[^>]*>([^<]+)<',
                            inner
                        )
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

                        results.append({
                            "title": html.unescape(title),
                            "id": anime_id,
                            "slug": slug,
                            "type": anime_type,
                            "poster": poster,
                            "url": f"{self.BASE_URL}{href}",
                        })
                    if results:
                        return results
        except Exception as e:
            print(f"Aniwave ajax search error: {e}")

        return results

    def get_anime_info(self, anime_id):
        """
        Fetch anime metadata (title, synopsis, internal_id, poster) from the watch page.
        """
        slug = str(anime_id).replace(self.BASE_URL, "").replace("/watch/", "").strip("/")
        url = f"{self.BASE_URL}/watch/{slug}"
        try:
            resp = self.session.get(url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                body = resp.text

                title_match = re.search(r'<h1[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h1>', body, re.I)
                if not title_match:
                    title_match = re.search(r'<h2[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h2>', body, re.I)
                title = title_match.group(1).strip() if title_match else slug

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

                return {
                    "id": internal_id,
                    "slug": slug,
                    "title": {
                        "english": html.unescape(title),
                        "romaji": html.unescape(title_jp),
                        "native": html.unescape(title_jp),
                    },
                    "synopsis": html.unescape(synopsis),
                    "poster": poster,
                    "url": url,
                }
        except Exception as e:
            print(f"Aniwave info error: {e}")
        return None

    def list_episodes(self, anime_id):
        """
        List all available episodes for an anime using Aniwave's episode list endpoint.
        """
        slug = str(anime_id).replace(self.BASE_URL, "").replace("/watch/", "").strip("/")
        numeric_id = slug.split("-")[-1]

        ep_url = f"{self.AJAX_URL}/episode/list/{numeric_id}"
        headers = dict(self.AJAX_HEADERS)
        headers["Referer"] = f"{self.BASE_URL}/watch/{slug}"

        results = []
        try:
            resp = self.session.get(ep_url, headers=headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                html_content = data.get("result", "") if isinstance(data, dict) else resp.text

                ep_tags = re.findall(
                    r'<a[^>]+data-ids=["\']([^"\']+)["\'][^>]+data-num=["\']([0-9.]+)["\'][^>]*title=["\']?([^"\'>]+)?["\']?[^>]*>',
                    html_content,
                )
                for ids, num, ep_title in ep_tags:
                    results.append({
                        "title": ep_title.strip() if ep_title else f"Episode {num}",
                        "url": f"{self.BASE_URL}/watch/{slug}/ep-{num}",
                        "ep_number": str(num),
                        "ep_id": ids.replace("&amp;", "&"),
                        "anime_id": numeric_id,
                        "slug": slug,
                    })
                if results:
                    return results
        except Exception as e:
            print(f"Aniwave list episodes ajax error: {e}")

        return results

    def get_episode_servers(self, anime_id, ep_num):
        """
        Get server options (Vidplay, BYFMS, DGHG, etc.) for a specific episode.
        """
        slug = str(anime_id).replace(self.BASE_URL, "").replace("/watch/", "").strip("/")
        numeric_id = slug.split("-")[-1]

        srv_url = f"{self.AJAX_URL}/server/list?servers={numeric_id}&eps={ep_num}"
        headers = dict(self.AJAX_HEADERS)
        headers["Referer"] = f"{self.BASE_URL}/watch/{slug}/ep-{ep_num}"

        try:
            resp = self.session.get(srv_url, headers=headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                html_content = data.get("result", "") if isinstance(data, dict) else resp.text

                servers = []
                types = re.findall(r'<div[^>]+class=["\']type["\'][^>]+data-type=["\']([^"\']+)["\'][^>]*>(.*?)</div>\s*(?=<div class=["\']type["\']|</div>|$)', html_content, re.DOTALL)
                for stype, block in types:
                    lis = re.findall(r'<li[^>]+data-sv-id=["\']([^"\']+)["\'][^>]+data-link-id=["\']([^"\']+)["\'][^>]*>([^<]+)<', block)
                    for sv_id, link_id, sname in lis:
                        servers.append({
                            "type": stype,
                            "server_id": sv_id,
                            "name": sname.strip(),
                            "link_id": link_id.strip(),
                        })
                return servers
        except Exception as e:
            print(f"Aniwave servers error: {e}")
        return []

    def get_episode_sources(self, anime_id, ep_num, server='default', source_type='sub'):
        """
        Fetch stream embed URL and skip metadata for an episode.
        """
        servers = self.get_episode_servers(anime_id, ep_num)
        if not servers:
            return None

        matching_servers = [s for s in servers if s['type'] == source_type]
        if not matching_servers:
            matching_servers = servers

        target_server = matching_servers[0]
        if server != 'default':
            for s in matching_servers:
                if server.lower() in s['name'].lower():
                    target_server = s
                    break

        link_id = target_server['link_id']
        enc_id = urllib.parse.quote(link_id)
        sources_url = f"{self.AJAX_URL}/sources?id={enc_id}&asi=0&autoPlay=0"

        slug = str(anime_id).replace(self.BASE_URL, "").replace("/watch/", "").strip("/")
        headers = dict(self.AJAX_HEADERS)
        headers["Referer"] = f"{self.BASE_URL}/watch/{slug}/ep-{ep_num}"

        try:
            resp = self.session.get(sources_url, headers=headers, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == 200:
                    res = data.get("result", {})
                    embed_url = res.get("url")
                    return {
                        "server": target_server['name'],
                        "server_type": target_server['type'],
                        "embed_url": embed_url,
                        "skip_data": res.get("skip_data"),
                        "sources": [
                            {
                                "url": embed_url,
                                "quality": "1080p",
                                "need_proxy": False,
                            }
                        ],
                        "subs": res.get("tracks", []),
                    }
        except Exception as e:
            print(f"Aniwave sources error: {e}")
        return None

    def get_schedule(self, date_str=None):
        """
        Get schedule of airing anime from Aniwave (/ajax/schedule).
        Returns list of dicts with all keys expected by Cantarella decorators and handlers.
        """
        url = f"{self.AJAX_URL}/schedule"
        if date_str:
            url += f"?date={date_str}"
        try:
            resp = self.session.get(url, headers=self.AJAX_HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                raw_html = data.get("result", "") or data.get("html", "")

                pattern = re.compile(
                    r'<a[^>]+href=[\'\"]([^\'\"]+)[\'\"][^>]*>.*?'
                    r'<div[^>]+class=[\'\"]time[^\'\"]*[\'\"][^>]*>([^<]+)</div>.*?'
                    r'<span>([^<]+)</span>.*?'
                    r'<div[^>]+class=[\'\"][^\'\"]*(?:title|name)[^\'\"]*[\'\"][^>]*>([^<]+)</div>',
                    re.DOTALL
                )

                schedule_list = []
                for href, time_str, ep_str, title in pattern.findall(raw_html):
                    clean_title = html.unescape(title.strip())
                    slug = href.replace('/watch/', '').strip('/')
                    anime_id = slug.split('/')[0].split('-')[-1]
                    ep_num = re.sub(r'[^\d.]', '', ep_str).strip()
                    schedule_list.append({
                        "id": anime_id,
                        "anime_id": anime_id,
                        "slug": slug,
                        "title": clean_title,
                        "name": clean_title,
                        "time": time_str.strip(),
                        "episode": ep_str.strip(),
                        "ep": ep_str.strip(),
                        "ep_number": ep_num,
                        "url": f"{self.BASE_URL}{href}",
                        "link": f"{self.BASE_URL}{href}",
                    })
                return schedule_list
        except Exception as e:
            print(f"Aniwave schedule error: {e}")
        return []

    def fetch_recently_updated(self, page=1, per_page=12):
        url = f"{self.BASE_URL}/updated?page={page}"
        try:
            resp = self.session.get(url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                results = []
                cards = re.findall(
                    r'<a[^>]+href=["\'](/watch/[^"\']+)["\'][^>]*class=["\']name[^"\']*["\'][^>]*>([^<]+)</a>',
                    resp.text,
                    re.I,
                )
                for href, title in cards[:per_page]:
                    slug = href.replace("/watch/", "").strip("/")
                    results.append({
                        "title": html.unescape(title.strip()),
                        "id": slug.split("-")[-1],
                        "slug": slug,
                        "url": f"{self.BASE_URL}{href}",
                    })
                return results
        except Exception as e:
            print(f"Aniwave recently updated error: {e}")
        return []

    def get_home_sections(self):
        url = f"{self.BASE_URL}/home"
        try:
            resp = self.session.get(url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                spotlights = re.findall(
                    r'<div[^>]+class=["\']swiper-slide item["\'][^>]*>.*?<h2[^>]+class=["\']title d-title["\'][^>]*data-jp=["\']([^"\']*)["\']>([^<]+)</h2>.*?<div[^>]+class=["\']synopsis["\']>([^<]+)</div>.*?href=["\'](/watch/[^"\']+)["\']',
                    resp.text,
                    re.DOTALL,
                )
                items = []
                for jp_title, en_title, syn, watch_url in spotlights:
                    slug = watch_url.replace("/watch/", "").strip("/")
                    items.append({
                        "title": html.unescape(en_title.strip()),
                        "title_jp": html.unescape(jp_title.strip()),
                        "synopsis": html.unescape(syn.strip()),
                        "url": f"{self.BASE_URL}{watch_url}",
                        "id": slug.split("-")[-1],
                        "slug": slug,
                    })
                return {"spotlight": items}
        except Exception as e:
            print(f"Aniwave home sections error: {e}")
        return {}


# Backward-compatible alias for Cantarella
AnimetsuScraper = AniwaveScraper
