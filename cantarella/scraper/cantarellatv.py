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


class cantarellatvDownloader:
    def __init__(self, download_path="anime_downloads", progress_queue=None):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True)
        self.binary_path = self._get_binary_path()
        self.progress_queue = progress_queue or Queue()
        self.base_url = "https://aniwaves.ru"
        self.ajax_url = f"{self.base_url}/ajax"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
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
        raise FileNotFoundError("N_m3u8DL-RE binary not found")

    def _format_bytes(self, bytes_num):
        if bytes_num == 0:
            return '0 B'
        size_name = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(bytes_num, 1024)))
        p = math.pow(1024, i)
        s = round(bytes_num / p, 2)
        return f"{s} {size_name[i]}"

    def _parse_url_slug(self, url):
        slug = None
        match = re.search(r'watch/([^/?#]+)', url)
        if match:
            slug = match.group(1).strip()
        else:
            match = re.search(r'/([^/]+)-episode-(\d+)', url)
            if match:
                slug = match.group(1)

        numeric_id = slug.split('-')[-1] if slug else None

        ep_num = "1"
        ep_match = (
            re.search(r'/ep-([0-9.]+)', url)
            or re.search(r'[?&]ep=([0-9.]+)', url)
            or re.search(r'episode-([0-9.]+)', url)
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
            return self.search_cantarella(anime_name, ep_num)

        match = re.search(r'-(\d+)$', url)
        if match:
            return f"{match.group(1)}&eps=1"
        return None

    def search_cantarella(self, anime_name, ep_num="1"):
        kw = urllib.parse.quote_plus(anime_name)
        search_url = f"{self.ajax_url}/anime/search?keyword={kw}"
        try:
            resp = self.session.get(
                search_url,
                headers=self.ajax_headers,
                impersonate="chrome120"
            )
            if resp.status_code == 200:
                data = resp.json()
                html_content = ""
                if isinstance(data, dict):
                    res_val = data.get("result", "")
                    if isinstance(res_val, dict):
                        html_content = res_val.get("html", "")
                    elif isinstance(res_val, str):
                        html_content = res_val

                items = re.findall(
                    r'<a[^>]+class=[\'"][^\'"]*item[^\'"]*[\'"][^>]+'
                    r'href=[\'"](/watch/[^\'"]+)[\'"][^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL | re.I
                )
                if items:
                    first_href = items[0][0]
                    slug = first_href.replace("/watch/", "").strip("/")
                    anime_id = slug.split("-")[-1]

                    ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
                    headers = {
                        **self.ajax_headers,
                        "Referer": f"{self.base_url}/watch/{slug}"
                    }
                    resp_eps = self.session.get(
                        ep_list_url,
                        headers=headers,
                        impersonate="chrome120"
                    )
                    if resp_eps.status_code == 200:
                        ep_data = resp_eps.json()
                        ep_html = (
                            ep_data.get("result", "")
                            if isinstance(ep_data, dict)
                            else resp_eps.text
                        )

                        ep_match = re.search(
                            rf'data-num=[\'"]{ep_num}[\'"][^>]*'
                            rf'data-ids=[\'"]([^\'"]+)[\'"]',
                            ep_html
                        )
                        if not ep_match:
                            ep_match = re.search(
                                rf'data-ids=[\'"]([^\'"]+)[\'"][^>]*'
                                rf'data-num=[\'"]{ep_num}[\'"]',
                                ep_html
                            )

                        if ep_match:
                            return ep_match.group(1).replace("&amp;", "&")
                        return f"{anime_id}&eps={ep_num}"
        except Exception as e:
            print(f"Error in search_cantarella: {e}")
        return None

    def search_anime(self, query):
        return self.search_cantarella(query)

    def get_schedule(self, date_str=None):
        url = f"{self.ajax_url}/schedule"
        if date_str:
            url += f"?date={date_str}"
        try:
            resp = self.session.get(
                url,
                headers=self.ajax_headers,
                impersonate="chrome120"
            )
            if resp.status_code == 200:
                data = resp.json()
                raw_html = data.get("result", "") or data.get("html", "")

                pattern = re.compile(
                    r'<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*>.*?'
                    r'<div[^>]+class=[\'"]time[^\'"]*[\'"][^>]*>([^<]+)</div>.*?'
                    r'<span>([^<]+)</span>.*?'
                    r'<div[^>]+class=[\'"][^\'"]*(?:title|name)[^\'"]*[\'"][^>]*>([^<]+)</div>',
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
                        "url": f"{self.base_url}{href}",
                        "link": f"{self.base_url}{href}",
                    })
                return schedule_list
        except Exception as e:
            print(f"Error fetching schedule: {e}")
        return []

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
            resp_servers = self.session.get(
                server_url,
                headers=headers,
                impersonate="chrome120"
            )
            if resp_servers.status_code != 200:
                return None

            data = resp_servers.json()
            srv_html = (
                data.get("result", "")
                if isinstance(data, dict)
                else resp_servers.text
            )

            type_blocks = re.findall(
                r'<div[^>]+class=[\'"]type[\'"][^>]+data-type=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</div>\s*(?=<div class=[\'"]type[\'"]|</div>|$)',
                srv_html,
                re.DOTALL
            )

            server_priority = {"4": 1, "1": 2, "2": 3}

            def find_sources_for_type(target_type):
                for stype, block in type_blocks:
                    if stype.lower() != target_type.lower():
                        continue
                    lis = re.findall(
                        r'<li[^>]+data-sv-id=[\'"]([^\'"]+)[\'"][^>]+data-link-id=[\'"]([^\'"]+)[\'"][^>]*>([^<]+)<',
                        block
                    )
                    sorted_lis = sorted(
                        lis,
                        key=lambda x: server_priority.get(x[0], 99)
                    )
                    for sv_id, link_id, sname in sorted_lis:
                        sources = self._get_sources(
                            link_id, anime_id, ep_num, slug
                        )
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

            resp_sources = self.session.get(
                sources_url,
                headers=headers,
                impersonate="chrome120"
            )
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
                        if (
                            isinstance(extracted.get('sources'), list)
                            and extracted['sources']
                        ):
                            return extracted
                    except Exception as e:
                        print(f"Megacloud fallback: {e}")

                return {
                    "sources": [
                        {
                            "file": embed_url,
                            "url": embed_url,
                            "type": "hls"
                        }
                    ],
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
            resp_page = self.session.get(
                page_url,
                headers=self.headers,
                impersonate="chrome120"
            )
            if resp_page.status_code == 200:
                body = resp_page.text
                title_match = re.search(
                    r'<h1[^>]+class=[\'"][^\'"]*title[^\'"]*[\'"][^>]*>([^<]+)</h1>',
                    body,
                    re.I
                )
                if not title_match:
                    title_match = re.search(
                        r'<h2[^>]+class=[\'"][^\'"]*title[^\'"]*[\'"][^>]*>([^<]+)</h2>',
                        body,
                        re.I
                    )
                if title_match:
                    anime_name = html.unescape(title_match.group(1).strip())
                else:
                    jp_match = re.search(
                        r'data-jp=[\'"]([^\'"]+)[\'"]',
                        body
                    )
                    if jp_match:
                        anime_name = html.unescape(jp_match.group(1).strip())
        except Exception as e:
            print(f"Could not fetch title: {e}")

        ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
        headers = {
            **self.ajax_headers,
            "Referer": f"{self.base_url}/watch/{slug}"
        }

        try:
            resp_eps = self.session.get(
                ep_list_url,
                headers=headers,
                impersonate="chrome120"
            )
            if resp_eps.status_code == 200:
                ep_data = resp_eps.json()
                ep_html = (
                    ep_data.get("result", "")
                    if isinstance(ep_data, dict)
                    else resp_eps.text
                )

                ep_match = re.search(
                    rf'data-num=[\'"]{ep_num}[\'"][^>]*title=[\'"]?([^\'">]+)?[\'"]?',
                    ep_html
                )
                if not ep_match:
                    ep_match = re.search(
                        rf'title=[\'"]?([^\'">]+)?[\'"]?[^>]*data-num=[\'"]{ep_num}[\'"]',
                        ep_html
                    )

                ep_title = (
                    ep_match.group(1).strip()
                    if ep_match and ep_match.group(1)
                    else f"Episode {ep_num}"
                )
                ep_title = html.unescape(ep_title)

                if not anime_name:
                    anime_name = slug.replace('-', ' ').title()
                    anime_name = re.sub(r' \d+$', '', anime_name)

                season_match = re.search(r'Season (\d+)', anime_name, re.I)
                if season_match:
                    season = season_match.group(1)
                    clean_name = anime_name.replace(
                        season_match.group(0), ''
                    ).strip()
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
                resp = self.session.get(
                    search_url,
                    headers=self.ajax_headers,
                    impersonate="chrome120"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    html_content = (
                        data.get("result", {}).get("html", "")
                        if isinstance(data.get("result"), dict)
                        else data.get("result", "")
                    )
                    items = re.findall(
                        r'<a[^>]+href=[\'"](/watch/[^\'"]+)[\'"]',
                        html_content
                    )
                    if items:
                        slug = items[0].replace("/watch/", "").strip("/")
                        anime_id = slug.split("-")[-1]
            except Exception as e:
                print(f"Error searching episodes: {e}")
                return []

        if not anime_id:
            return []

        ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
        headers = {
            **self.ajax_headers,
            "Referer": f"{self.base_url}/watch/{slug}"
        }

        try:
            resp_eps = self.session.get(
                ep_list_url,
                headers=headers,
                impersonate="chrome120"
            )
            if resp_eps.status_code == 200:
                data = resp_eps.json()
                ep_html = (
                    data.get("result", "")
                    if isinstance(data, dict)
                    else resp_eps.text
                )

                results = []
                ep_tags = re.findall(
                    r'<a[^>]+data-ids=[\'"]([^\'"]+)[\'"][^>]+data-num=[\'"]([0-9.]+)[\'"][^>]*'
                    r'title=[\'"]?([^\'">]+)?[\'"]?',
                    ep_html
                )
                for ids, num, title in ep_tags:
                    clean_t = (
                        html.unescape(title.strip())
                        if title
                        else f"Episode {num}"
                    )
                    results.append({
                        'title': clean_t,
                        'url': f"{self.base_url}/watch/{slug}/ep-{num}",
                        'ep_number': str(num),
                        'ep_id': ids.replace("&amp;", "&"),
                    })
                return results
        except Exception as e:
            print(f"Error fetching episodes: {e}")
        return []

    def download_episode(
        self, url, quality="auto",
        name_override=None, season_override=None, ep_num_override=None
    ):
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
                    
