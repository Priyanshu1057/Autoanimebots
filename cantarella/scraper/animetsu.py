#@cantarellabots
from cantarella.core.proxy import get_random_proxy, get_proxy_dict
from curl_cffi import requests as c_requests
import json
import re
import subprocess
import shutil
import os
import html
from urllib.parse import quote_plus
from pathlib import Path

class AniwaveScraper:
    """
    Scraper & Downloader for Aniwave (https://aniwaves.ru)
    Compatible with Cantarella framework and standard anime download pipelines.
    """
    BASE_URL = "https://aniwaves.ru"
    AJAX_URL = f"{BASE_URL}/ajax"
    PROXY_URL = "https://swiftstream.top/proxy"  # Fallback proxy if stream/m3u8 requires proxy

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
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
        Search anime on Aniwave using AJAX search or filter search page.
        Returns list of dicts: {'title', 'id', 'type', 'url'}
        """
        ajax_url = f"{self.AJAX_URL}/anime/search?keyword={quote_plus(query)}"
        results = []
        try:
            resp = self.session.get(ajax_url, headers=self.AJAX_HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    html_content = data.get("html", "") if isinstance(data, dict) else resp.text
                except Exception:
                    html_content = resp.text

                items = re.findall(
                    r'<a[^>]+class=["\'][^"\']*item[^"\']*["\'][^>]+href=["\'](/watch/[^"\']+)["\'][^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL | re.IGNORECASE,
                )
                for href, inner in items:
                    name_match = re.search(r'class=["\']name[^"\']*["\'][^>]*data-jp=["\']?([^"\'>]+)?["\']?[^>]*>([^<]+)<', inner)
                    title = ""
                    if name_match:
                        title = name_match.group(2).strip() or name_match.group(1).strip()
                    else:
                        title_fallback = re.search(r'<h[0-9][^>]*>([^<]+)</h[0-9]>', inner)
                        title = title_fallback.group(1).strip() if title_fallback else href.split("/")[-1]

                    anime_id = href.replace("/watch/", "").strip("/")
                    type_match = re.search(r'class=["\']type[^"\']*["\'][^>]*>([^<]+)<', inner)
                    anime_type = type_match.group(1).strip().upper() if type_match else "ANIME"

                    results.append({
                        "title": html.unescape(title),
                        "id": anime_id,
                        "type": anime_type,
                        "url": f"{self.BASE_URL}{href}",
                    })
                if results:
                    return results
        except Exception as e:
            print(f"Aniwave ajax search error: {e}")

        # Fallback to HTML filter search
        fallback_url = f"{self.BASE_URL}/filter?keyword={quote_plus(query)}"
        try:
            resp = self.session.get(fallback_url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                cards = re.findall(
                    r'<a[^>]+href=["\'](/watch/[^"\']+)["\'][^>]*title=["\']([^"\']+)["\']',
                    resp.text,
                    re.IGNORECASE,
                )
                seen = set()
                for href, title in cards:
                    anime_id = href.replace("/watch/", "").strip("/")
                    if anime_id in seen:
                        continue
                    seen.add(anime_id)
                    results.append({
                        "title": html.unescape(title.strip()),
                        "id": anime_id,
                        "type": "ANIME",
                        "url": f"{self.BASE_URL}{href}",
                    })
        except Exception as e:
            print(f"Aniwave filter fallback search error: {e}")

        return results

    def get_anime_info(self, anime_id):
        """
        Fetch anime metadata (title, synopsis, internal_id, poster) from the watch page.
        """
        if "/" in str(anime_id):
            anime_id = anime_id.split("/")[-1]

        url = f"{self.BASE_URL}/watch/{anime_id}" if not str(anime_id).startswith("http") else anime_id
        try:
            resp = self.session.get(url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                body = resp.text

                title_match = re.search(r'<h1[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h1>', body, re.I)
                if not title_match:
                    title_match = re.search(r'<h2[^>]+class=["\'][^"\']*title[^"\']*["\'][^>]*>([^<]+)</h2>', body, re.I)
                title = title_match.group(1).strip() if title_match else anime_id

                jp_match = re.search(r'data-jp=["\']([^"\']+)["\']', body)
                title_jp = jp_match.group(1).strip() if jp_match else title

                syn_match = re.search(r'<div[^>]+class=["\'][^"\']*synopsis[^"\']*["\'][^>]*>(.*?)</div>', body, re.DOTALL | re.I)
                synopsis = ""
                if syn_match:
                    synopsis = re.sub(r'<[^>]+>', '', syn_match.group(1)).strip()

                id_match = re.search(r'data-id=["\']([0-9a-zA-Z]+)["\']', body)
                internal_id = id_match.group(1) if id_match else None

                poster_match = re.search(r'<div[^>]+class=["\']poster["\'][^>]*>.*?<img[^>]+src=["\']([^"\']+)["\']', body, re.DOTALL | re.I)
                poster = poster_match.group(1) if poster_match else None

                return {
                    "id": anime_id,
                    "internal_id": internal_id,
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
        if "/" in str(anime_id):
            anime_id = anime_id.split("/")[-1]

        info = self.get_anime_info(anime_id)
        internal_id = info.get("internal_id") if info else None

        results = []
        if internal_id:
            ep_url = f"{self.AJAX_URL}/episode/list/{internal_id}"
            try:
                resp = self.session.get(ep_url, headers=self.AJAX_HEADERS, impersonate="chrome120")
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        html_content = data.get("result", "") or data.get("html", "")
                    except Exception:
                        html_content = resp.text

                    ep_tags = re.findall(
                        r'<a[^>]+data-num=["\']([0-9.]+)["\'][^>]+data-ids=["\']([^"\']+)["\'][^>]*title=["\']?([^"\'>]+)?["\']?[^>]*>',
                        html_content,
                    )
                    for num, ids, ep_title in ep_tags:
                        results.append({
                            "title": ep_title.strip() if ep_title else f"Episode {num}",
                            "url": f"{self.BASE_URL}/watch/{anime_id}/ep-{num}",
                            "ep_number": str(num),
                            "ep_id": ids.strip(),
                        })
                    if results:
                        return results
            except Exception as e:
                print(f"Aniwave list episodes ajax error: {e}")

        # Fallback: scrape from HTML
        try:
            url = f"{self.BASE_URL}/watch/{anime_id}"
            resp = self.session.get(url, headers=self.HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                ep_tags = re.findall(
                    r'<a[^>]+href=["\'](/watch/[^/]+/ep-([0-9.]+))["\'][^>]*>(.*?)</a>',
                    resp.text,
                    re.IGNORECASE,
                )
                for href, num, title_text in ep_tags:
                    clean_text = re.sub(r'<[^>]+>', '', title_text).strip()
                    results.append({
                        "title": clean_text or f"Episode {num}",
                        "url": f"{self.BASE_URL}{href}",
                        "ep_number": str(num),
                        "ep_id": num,
                    })
        except Exception as e:
            print(f"Aniwave watch page episode scrape error: {e}")

        return results

    def get_episode_servers(self, anime_id, ep_num):
        """
        Get server sources for a specific episode.
        """
        if "/" in str(anime_id):
            anime_id = anime_id.split("/")[-1]

        ep_list = self.list_episodes(anime_id)
        target_ep = next((e for e in ep_list if e.get("ep_number") == str(ep_num)), None)
        ep_id = target_ep.get("ep_id") if target_ep else str(ep_num)

        url = f"{self.AJAX_URL}/server/list/{ep_id}"
        try:
            resp = self.session.get(url, headers=self.AJAX_HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                try:
                    return resp.json()
                except Exception:
                    return {"html": resp.text}
        except Exception as e:
            print(f"Aniwave servers error: {e}")
        return []

    def get_episode_sources(self, anime_id, ep_num, server='default', source_type='sub'):
        """
        Fetch m3u8 stream sources and subtitle tracks for the episode.
        """
        if "/" in str(anime_id):
            anime_id = anime_id.split("/")[-1]

        ep_list = self.list_episodes(anime_id)
        target_ep = next((e for e in ep_list if e.get("ep_number") == str(ep_num)), None)
        ep_id = target_ep.get("ep_id") if target_ep else str(ep_num)

        url = f"{self.AJAX_URL}/server/{ep_id}?sub={1 if source_type == 'sub' else 0}"
        try:
            resp = self.session.get(url, headers=self.AJAX_HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                data = resp.json()
                embed_url = data.get("url") or data.get("link")
                if embed_url:
                    return {
                        "sources": [
                            {
                                "url": embed_url,
                                "quality": "1080p",
                                "need_proxy": False,
                            }
                        ],
                        "subs": data.get("tracks", []),
                    }
        except Exception as e:
            print(f"Aniwave sources error: {e}")
        return None

    def get_schedule(self, date_str=None):
        """
        Get schedule of airing anime from Aniwave.
        """
        url = f"{self.AJAX_URL}/schedule"
        if date_str:
            url += f"?date={date_str}"
        try:
            resp = self.session.get(url, headers=self.AJAX_HEADERS, impersonate="chrome120")
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    html_content = data.get("html", "")
                except Exception:
                    html_content = resp.text

                results = []
                items = re.findall(
                    r'<a[^>]+href=["\'](/watch/[^"\']+)["\'][^>]*>(.*?)</a>',
                    html_content,
                    re.DOTALL,
                )
                for href, inner in items:
                    title_m = re.search(r'class=["\']name[^"\']*["\'][^>]*>([^<]+)<', inner)
                    time_m = re.search(r'class=["\']time[^"\']*["\'][^>]*>([^<]+)<', inner)
                    ep_m = re.search(r'class=["\']ep[^"\']*["\'][^>]*>([^<]+)<', inner)
                    results.append({
                        "id": href.replace("/watch/", "").strip("/"),
                        "title": title_m.group(1).strip() if title_m else href,
                        "time": time_m.group(1).strip() if time_m else "Unknown",
                        "ep": ep_m.group(1).strip() if ep_m else "",
                    })
                return results
        except Exception as e:
            print(f"Aniwave schedule error: {e}")
        return []

    def fetch_recently_updated(self, page=1, per_page=12):
        """
        Fetch recently updated anime from Aniwave (/updated).
        """
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
                    anime_id = href.replace("/watch/", "").strip("/")
                    results.append({
                        "title": html.unescape(title.strip()),
                        "id": anime_id,
                        "url": f"{self.BASE_URL}{href}",
                    })
                return results
        except Exception as e:
            print(f"Aniwave recently updated error: {e}")
        return []

    def get_home_sections(self):
        """
        Extract featured spotlight, trending, and top anime from the Aniwave homepage.
        """
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
                    items.append({
                        "title": html.unescape(en_title.strip()),
                        "title_jp": html.unescape(jp_title.strip()),
                        "synopsis": html.unescape(syn.strip()),
                        "url": f"{self.BASE_URL}{watch_url}",
                        "id": watch_url.replace("/watch/", "").strip("/"),
                    })
                return {"spotlight": items}
        except Exception as e:
            print(f"Aniwave home sections error: {e}")
        return {}

    def download_episode(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None):
        """
        Downloads the specified episode with N_m3u8DL-RE and ffmpeg audio/subtitle multiplexing.
        URL format: https://aniwaves.ru/watch/anime-slug/ep-1
        """
        parts = url.split('/')
        if "watch" in parts:
            idx = parts.index("watch")
            anime_id = parts[idx + 1]
            ep_str = parts[idx + 2] if len(parts) > idx + 2 else "ep-1"
            ep_num = re.sub(r'[^0-9.]', '', ep_str) or "1"
        else:
            anime_id = parts[-2]
            ep_num = re.sub(r'[^0-9.]', '', parts[-1]) or "1"

        info = self.get_anime_info(anime_id)
        if not info:
            if self.progress_queue:
                self.progress_queue.put({'error': 'Could not fetch anime info from Aniwave.'})
            return False

        title_dict = info.get('title', {})
        anime_name = name_override or title_dict.get('english') or title_dict.get('romaji') or anime_id

        # 1. Fetch Sub & Dub stream data
        sub_data = self.get_episode_sources(anime_id, ep_num, source_type='sub')
        dub_data = self.get_episode_sources(anime_id, ep_num, source_type='dub')

        is_dub_only = False
        if not sub_data or not sub_data.get('sources'):
            if dub_data and dub_data.get('sources'):
                sub_data = dub_data
                dub_data = None
                is_dub_only = True

        if not sub_data or not sub_data.get('sources'):
            if self.progress_queue:
                self.progress_queue.put({'error': 'Could not find video sources on Aniwave.'})
            return False

        # 2. Select Source and Quality
        sources = sub_data['sources']
        selected_source = sources[0]
        if quality != "auto":
            for src in sources:
                if quality in src.get('quality', ''):
                    selected_source = src
                    break

        m3u8_url = selected_source['url']
        qual_str = selected_source.get('quality', 'auto').replace('p', '')

        # 3. Filename Formatting
        def sanitize(name):
            return re.sub(r'[\\/*?:"<>|]', "", name)

        try:
            from config import FORMAT
        except ImportError:
            FORMAT = "[S{season}-E{episode}] {title} [{quality}] [{audio}]"

        if is_dub_only:
            audio_label = "EN"
        elif dub_data and dub_data.get('sources'):
            audio_label = "Dual Audio"
        else:
            audio_label = "JP"

        base_filename = sanitize(FORMAT.format(
            season=season_override or "1",
            episode=ep_num_override or ep_num,
            title=anime_name,
            quality=f"{qual_str}p",
            audio=audio_label,
        ))

        task_dir = self.download_path / f"aniwave_{anime_id}_{ep_num}_{qual_str}"
        task_dir.mkdir(exist_ok=True)

        video_temp = task_dir / f"{base_filename}_sub.mkv"
        audio_temp = task_dir / f"{base_filename}_dub.mkv"
        final_file = self.download_path / f"{base_filename}.mkv"

        if self.progress_queue:
            self.progress_queue.put({'status': f"📥 **Downloading (Aniwave): {anime_name} [{qual_str}p]**\nPlease wait..."})

        # 4. Execute N_m3u8DL-RE
        def run_n_m3u8dl(dl_url, save_name, dl_type='sub'):
            cmd = [
                str(self.binary_path), dl_url,
                "--save-dir", str(task_dir),
                "--save-name", save_name,
                "-H", f"User-Agent: {self.HEADERS['User-Agent']}",
                "-H", f"Referer: {self.BASE_URL}/",
                "--check-segments-count", "False",
                "-mt", "--thread-count", "50",
                "--download-retry-count", "5",
                "--auto-select",
            ]
            if self.proxy:
                cmd.extend(["--custom-proxy", self.proxy])

            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.decode('utf-8', errors='replace').strip()

                if "%" in line and self.progress_queue:
                    percent_match = re.search(r"(\d+(\.\d+)?)%", line)
                    if percent_match:
                        parts = re.split(r"\d+(\.\d+)?%", line)
                        speed_match = None
                        if len(parts) > 1:
                            after_percent = parts[-1]
                            speed_match = re.search(r"(\d+(\.\d+)?\s*[MKG]?i?(B/s|bps|b/s|bit/s))", after_percent, re.I)
                        if not speed_match:
                            speed_match = re.search(r"(\d+(\.\d+)?\s*[MKG]?i?(B/s|bps|b/s|bit/s))", line, re.I)

                        size_match = re.search(r"(\d+(\.\d+)?\s*\S+)\s*/\s*(\d+(\.\d+)?\s*\S+)", line, re.I)

                        self.progress_queue.put({
                            'percent': f"{percent_match.group(1)}%",
                            'speed': speed_match.group(1) if speed_match else "0 MB/s",
                            'downloaded': size_match.group(1) if size_match else "0 MB",
                            'total': size_match.group(3) if size_match else "0 MB",
                            'type': dl_type,
                            'title': f"Episode {ep_num}",
                        })
            process.wait()
            return process.returncode == 0

        # Download Sub (Primary Stream)
        if not run_n_m3u8dl(m3u8_url, f"{base_filename}_sub", 'sub'):
            if self.progress_queue:
                self.progress_queue.put({'error': 'Video download failed'})
            return False

        # Download Dub (Audio Stream if separate)
        dub_downloaded = False
        if dub_data and dub_data.get('sources'):
            dub_m3u8 = dub_data['sources'][0]['url']
            if run_n_m3u8dl(dub_m3u8, f"{base_filename}_dub", 'dub'):
                dub_downloaded = True

        # 5. Extract Subs
        sub_files = []
        if sub_data.get('subs'):
            for i, s in enumerate(sub_data['subs']):
                lang = s.get('lang', f'sub_{i}').lower().replace(' ', '_')
                sub_path = task_dir / f"{base_filename}_{lang}.vtt"
                try:
                    r = self.session.get(s['url'], timeout=10)
                    if r.status_code == 200:
                        with open(sub_path, 'wb') as f:
                            f.write(r.content)
                        sub_files.append((sub_path, lang))
                except Exception:
                    pass

        # 6. Merge with ffmpeg
        for f in task_dir.iterdir():
            if f.name.startswith(f"{base_filename}_sub."):
                f.rename(video_temp)
            elif f.name.startswith(f"{base_filename}_dub."):
                f.rename(audio_temp)

        if not video_temp.exists():
            if self.progress_queue:
                self.progress_queue.put({'error': 'Video file missing after download.'})
            return False

        if not dub_downloaded and not sub_files:
            video_temp.replace(final_file)
        else:
            if self.progress_queue:
                self.progress_queue.put({'status': f"🎬 **Merging Tracks for: Episode {ep_num}**"})
            cmd = ['ffmpeg', '-y', '-i', str(video_temp)]
            if dub_downloaded:
                cmd.extend(['-i', str(audio_temp)])
            for s_path, _ in sub_files:
                cmd.extend(['-i', str(s_path)])

            cmd.extend(['-map', '0:v', '-map', '0:a'])
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
            except Exception:
                video_temp.replace(final_file)

        shutil.rmtree(task_dir, ignore_errors=True)
        if self.progress_queue:
            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
        return True


# Backward-compatible alias
AnimetsuScraper = AniwaveScraper

if __name__ == '__main__':
    scraper = AniwaveScraper()
    print("Testing Aniwave scraper...")
    print(scraper.search_anime('solo leveling'))
