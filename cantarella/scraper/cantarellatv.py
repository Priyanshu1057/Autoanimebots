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
            Path("binary") / "N_m3u8DL-RE",           # Linux (local binary folder)
            Path("binary") / "N_m3u8DL-RE.exe",       # Windows local
            Path("/usr/local/bin/N_m3u8DL-RE"),        # Docker / Heroku container
        ]
        for p in candidates:
            if p.exists():
                print(f"Found N_m3u8DL-RE binary at: {p}")
                return p
        which_path = shutil.which("N_m3u8DL-RE")
        if which_path:
            print(f"Found N_m3u8DL-RE in PATH: {which_path}")
            return Path(which_path)
        raise FileNotFoundError(f"N_m3u8DL-RE binary not found. Checked: {candidates} and PATH")

    def _format_bytes(self, bytes_num):
        if bytes_num == 0:
            return '0 B'
        size_name = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(bytes_num, 1024)))
        p = math.pow(1024, i)
        s = round(bytes_num / p, 2)
        return f"{s} {size_name[i]}"

    def _parse_url_slug(self, url):
        """Extracts slug, numeric anime id, and episode number from any Aniwave/Aniwatch URL."""
        slug = None
        match = re.search(r'watch/([^/?#]+)', url)
        if match:
            slug = match.group(1).strip()
        else:
            match = re.search(r'/([^/]+)-episode-(\d+)', url)
            if match:
                slug = match.group(1)

        numeric_id = slug.split('-')[-1] if slug else None

        # Episode number extraction
        ep_num = "1"
        ep_match = re.search(r'/ep-([0-9.]+)', url) or re.search(r'[?&]ep=([0-9.]+)', url) or re.search(r'episode-([0-9.]+)', url)
        if ep_match:
            ep_num = ep_match.group(1)

        return slug, numeric_id, ep_num

    def get_episode_id(self, url):
        """Returns formatted episode identifier 'anime_id&eps=ep_num' for Aniwave."""
        slug, anime_id, ep_num = self._parse_url_slug(url)
        if anime_id:
            return f"{anime_id}&eps={ep_num}"

        # If passed plain search keyword or title instead of URL
        anime_name_match = re.search(r'/([^/]+)-episode-(\d+)', url) or re.search(r'watch/([^/]+)-(\d+)', url)
        if anime_name_match:
            anime_name = anime_name_match.group(1).replace('-', ' ')
            ep_num = anime_name_match.group(2)
            return self.search_cantarella(anime_name, ep_num)

        match = re.search(r'-(\d+)$', url)
        if match:
            return f"{match.group(1)}&eps=1"
        return None

    def search_cantarella(self, anime_name, ep_num="1"):
        """Searches Aniwave using the working AJAX search endpoint and returns episode ID."""
        search_url = f"{self.ajax_url}/anime/search?keyword={urllib.parse.quote_plus(anime_name)}"
        try:
            resp = self.session.get(search_url, headers=self.ajax_headers, impersonate="chrome")
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
                    r'<a[^>]+class=["\'][^"\']*item[^"\']*["\'][^>]+href=["\'](/watch/[^"\']+)["\'][^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL | re.I
                )
                if items:
                    first_href = items[0][0]
                    slug = first_href.replace("/watch/", "").strip("/")
                    anime_id = slug.split("-")[-1]

                    ep_list_url = f"{self.ajax_url}/episode/list/{anime_id}"
                    headers = {**self.ajax_headers, "Referer": f"{self.base_url}/watch/{slug}"}
                    resp_eps = self.session.get(ep_list_url, headers=headers, impersonate="chrome")
                    if resp_eps.status_code == 200:
                        ep_data = resp_eps.json()
                        ep_html = ep_data.get("result", "") if isinstance(ep_data, dict) else resp_eps.text

                        # Match episode number in data-num
                        ep_match = re.search(rf'data-num=["\']{ep_num}["\'][^>]*data-ids=["\']([^"\']+)["\']', ep_html)
                        if not ep_match:
                            ep_match = re.search(rf'data-ids=["\']([^"\']+)["\'][^>]*data-num=["\']{ep_num}["\']', ep_html)

                        if ep_match:
                            return ep_match.group(1).replace("&amp;", "&")
                        return f"{anime_id}&eps={ep_num}"
        except Exception as e:
            print(f"Error in search_cantarella: {e}")
        return None

    def get_episode_data(self, ep_id, slug=None):
        """
        Fetches server sources for the given episode id ('anime_id&eps=ep_num' or numeric).
        Returns {'sub': sources_dict, 'dub': sources_dict}.
        """
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
                        print(f"Trying server {sname.strip()} (sv-id {sv_id}) for {target_type}...")
                        sources = self._get_sources(link_id, anime_id, ep_num, slug)
                        if sources and sources.get('sources'):
                            print(f"Success! Found sources on {sname.strip()}")
                            return sources
                return None

            result['sub'] = find_sources_for_type('sub')
            result['dub'] = find_sources_for_type('dub')

            return result if result['sub'] or result['dub'] else None
        except Exception as e:
            print(f"Error in get_episode_data: {e}")
        return None

    def _get_sources(self, server_data_id, anime_id=None, ep_num=None, slug=None):
        """Resolves embed and video stream from /ajax/sources?id={link_id}."""
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
                if any(k in embed_url.lower() for k in ["megacloud", "rapid-cloud", "cloud-stream"]):
                    try:
                        scraper = Megacloud(embed_url)
                        extracted = scraper.extract()
                        if isinstance(extracted.get('sources'), list) and extracted['sources']:
                            return extracted
                    except Exception as e:
                        print(f"Megacloud extraction fallback: {e}")

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
        """Fetches real anime title, episode number, episode title, and season."""
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
            print(f"Could not fetch anime title from page: {e}")

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
        """Lists all episodes for the specified anime URL or search term."""
        slug, anime_id, _ = self._parse_url_slug(anime_url)
        if not anime_id:
            search_url = f"{self.ajax_url}/anime/search?keyword={urllib.parse.quote_plus(anime_url)}"
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
                print(f"Error searching for episodes list: {e}")
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
                    results.append({
                        'title': html.unescape(title.strip()) if title else f"Episode {num}",
                        'url': f"{self.base_url}/watch/{slug}/ep-{num}",
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
                if not self._download_with_retry(url, quality=q, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override):
                    success = False
            return success
        else:
            return self._download_with_retry(url, quality=quality, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override)

    def _download_with_retry(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None, max_retries=3):
        for i in range(max_retries):
            try:
                if self._download_single_episode(url, quality=quality, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override):
                    return True
                print(f"Download attempt {i+1} failed. Retrying...")
            except Exception as e:
                print(f"Download error on attempt {i+1}: {e}")
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
        clean_ep_id = sanitize(ep_id.replace('&', '_').replace('=', '_'))
        task_dir = self.download_path / f"{clean_ep_id}_{qual_str}"
        task_dir.mkdir(exist_ok=True)

        video_temp = task_dir / f"{base_filename}_sub.mkv"
        audio_temp = task_dir / f"{base_filename}_dub.mkv"
        final_file = self.download_path / f"{base_filename}.mkv"

        data = all_data.get('sub') or all_data.get('dub')
        source_item = data['sources'][0]
        m3u8_url = source_item.get('file') or source_item.get('url')

        self.progress_queue.put({'status': f"📥 **Downloading: {final_name} [{qual_str}p]**\nPlease wait..."})

        def run_n_m3u8dl(dl_url, save_name, dl_type='sub', quality="auto"):
            cmd = [
                str(self.binary_path),
                dl_url,
                "--save-dir", str(task_dir),
                "--save-name", save_name,
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", f"Referer: {self.base_url}/",
                "--check-segments-count", "False",
          
