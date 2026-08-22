"""
AniWatch / HiAnime Anime Downloader with MegaCloud HLS & Dual Audio Merging
Fixed and enhanced with BeautifulSoup parsing, resilient stream extraction, and ffmpeg muxing.
"""

from pathlib import Path
from queue import Queue
import math
import re
import json
import time
import subprocess
import shutil
import os as _os
import sys
from threading import Thread
from typing import Optional, Dict, Any, List

# Imports with fallback
try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False

from bs4 import BeautifulSoup

# Try local or module Megacloud
try:
    from megacloud import Megacloud
except ImportError:
    try:
        from cantarella.scraper.megacloud import Megacloud
    except ImportError:
        Megacloud = None

# Proxy fallbacks
try:
    from cantarella.core.proxy import get_random_proxy, get_proxy_dict
except ImportError:
    def get_random_proxy():
        return None
    def get_proxy_dict(proxy):
        if not proxy:
            return None
        return {"http": proxy, "https": proxy} if isinstance(proxy, str) else proxy


class AniwatchDownloader:
    """
    Downloader for AniWatch / HiAnime anime episodes.
    Fetches video streams (Sub & Dub), subtitles, and merges using ffmpeg or N_m3u8DL-RE.
    """
    DOMAINS = [
        "https://hianime.ro",
        "https://aniwatch.co.at",
        "https://hianime.to",
        "https://aniwatchtv.to",
        "https://aniwatch.se"
    ]

    def __init__(self, download_path: str = "anime_downloads", progress_queue: Optional[Queue] = None, proxy: Optional[str] = None):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True, parents=True)
        self.binary_path = self._get_binary_path()
        self.progress_queue = progress_queue or Queue()
        self.base_url = "https://hianime.ro"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.proxy = proxy or get_random_proxy()
        self.session = requests.Session()
        proxy_dict = get_proxy_dict(self.proxy)
        if proxy_dict:
            self.session.proxies.update(proxy_dict)

    def _get_binary_path(self) -> Optional[Path]:
        """Finds N_m3u8DL-RE binary executable."""
        candidates = [
            Path("binary") / "N_m3u8DL-RE",
            Path("binary") / "N_m3u8DL-RE.exe",
            Path("N_m3u8DL-RE"),
            Path("N_m3u8DL-RE.exe"),
            Path("/usr/local/bin/N_m3u8DL-RE"),
            Path("/usr/bin/N_m3u8DL-RE"),
        ]
        for p in candidates:
            if p.exists():
                print(f"[Info] Found N_m3u8DL-RE binary at: {p}")
                return p

        which_path = shutil.which("N_m3u8DL-RE") or shutil.which("n-m3u8dl-re")
        if which_path:
            print(f"[Info] Found N_m3u8DL-RE in PATH: {which_path}")
            return Path(which_path)

        print("[Warning] N_m3u8DL-RE binary not found. Will fallback to ffmpeg or direct download.")
        return None

    def _format_bytes(self, bytes_num: int) -> str:
        if bytes_num == 0:
            return "0 B"
        size_name = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(bytes_num, 1024)))
        p = math.pow(1024, i)
        s = round(bytes_num / p, 2)
        return f"{s} {size_name[i]}"

    def _safe_get(self, url_or_path: str, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        """Fetches URL with automatic domain fallbacks and error tolerance."""
        h = self.headers.copy()
        if headers:
            h.update(headers)

        urls_to_try = []
        if url_or_path.startswith("http"):
            urls_to_try.append(url_or_path)
            for d in self.DOMAINS:
                if not url_or_path.startswith(d):
                    # Replace domain
                    parts = url_or_path.split("/", 3)
                    path = "/" + parts[3] if len(parts) > 3 else ""
                    urls_to_try.append(f"{d}{path}")
        else:
            for d in self.DOMAINS:
                urls_to_try.append(f"{d}{url_or_path}")

        for u in urls_to_try:
            try:
                kwargs = {"headers": h, "params": params, "timeout": 12}
                if HAS_CURL_CFFI:
                    kwargs["impersonate"] = "chrome"
                resp = self.session.get(u, **kwargs)
                if resp.status_code == 200:
                    return resp
            except Exception:
                continue
        return None

    def get_episode_id(self, url: str) -> Optional[str]:
        """Extracts numerical episode ID from URL or searches for it."""
        # 1. Check ?ep=12345 parameter
        ep_param = re.search(r'ep=(\d+)', url)
        if ep_param:
            return ep_param.group(1)

        # 2. Check path slug
        slug_match = re.search(r'/([^/]+)-episode-(\d+)', url) or re.search(r'watch/([^/]+)-(\d+)', url)
        if slug_match:
            anime_name = slug_match.group(1).replace('-', ' ')
            ep_num = slug_match.group(2)
            return self.search_and_get_ep_id(anime_name, ep_num)

        # 3. Trailing ID
        end_match = re.search(r'-(\d+)$', url.split('?')[0])
        if end_match:
            return end_match.group(1)

        return None

    def search_and_get_ep_id(self, anime_name: str, ep_num: str) -> Optional[str]:
        """Searches anime title and retrieves episode ID for a given episode number."""
        search_path = f"/search?keyword={anime_name.replace(' ', '+')}"
        resp = self._safe_get(search_path)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')
        first_item = soup.select_one('.film_list-wrap .flw-item .film-name a')
        if not first_item:
            return None

        href = first_item.get('href', '')
        anime_id = href.split('/')[-1].split('?')[0].split('-')[-1]

        ep_list_resp = self._safe_get(f"/ajax/v2/episode/list/{anime_id}", headers={"X-Requested-With": "XMLHttpRequest"})
        if ep_list_resp:
            try:
                html = ep_list_resp.json().get('html', '')
                ep_soup = BeautifulSoup(html, 'html.parser')
                ep_anchor = ep_soup.select_one(f'a[data-number="{ep_num}"], a[data-number="{int(float(ep_num))}"]')
                if ep_anchor and ep_anchor.get('data-id'):
                    return ep_anchor.get('data-id')
            except Exception:
                pass
        return None

    def get_episode_data(self, ep_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches server list for an episode ID and extracts Sub & Dub stream sources.
        Uses BeautifulSoup to avoid regex attribute ordering bugs.
        """
        server_path = f"/ajax/v2/episode/servers?episodeId={ep_id}"
        resp_servers = self._safe_get(server_path, headers={"X-Requested-With": "XMLHttpRequest"})
        if not resp_servers:
            return None

        try:
            html = resp_servers.json().get('html', '')
            soup = BeautifulSoup(html, 'html.parser')

            def find_sources_for_type(track_type: str) -> Optional[Dict[str, Any]]:
                # Priority: MegaCloud (1), then VidStreaming (4)
                servers = []
                for el in soup.select('.server-item, .btn-server, [data-server-id]'):
                    el_type = (el.get('data-type') or '').lower()
                    if not el_type:
                        # Check container class
                        if el.find_parent(class_=re.compile(r'servers-dub|dub', re.I)):
                            el_type = "dub"
                        else:
                            el_type = "sub"

                    if el_type == track_type:
                        data_id = el.get('data-id')
                        server_id = el.get('data-server-id', '99')
                        if data_id:
                            servers.append((data_id, server_id))

                # Sort by preferred server ID: 1 (MegaCloud), 4 (VidStream)
                priority_map = {"1": 1, "4": 2}
                servers.sort(key=lambda s: priority_map.get(str(s[1]), 99))

                for data_id, s_id in servers:
                    print(f"[Info] Attempting server #{s_id} (data-id={data_id}) for {track_type.upper()}...")
                    sources = self._get_sources(data_id)
                    if sources and sources.get('sources'):
                        print(f"[Success] Successfully resolved {track_type.upper()} stream on server #{s_id}")
                        return sources

                return None

            result = {
                'sub': find_sources_for_type('sub'),
                'dub': find_sources_for_type('dub')
            }

            return result if (result['sub'] or result['dub']) else None

        except Exception as e:
            print(f"[Error] get_episode_data failed: {e}")
            return None

    def _get_sources(self, server_data_id: str) -> Optional[Dict[str, Any]]:
        """Resolves embed link and extracts decrypted m3u8 playlist."""
        try:
            sources_path = f"/ajax/v2/episode/sources?id={server_data_id}"
            resp = self._safe_get(sources_path, headers={"X-Requested-With": "XMLHttpRequest"})
            if not resp:
                return None

            sources_data = resp.json()
            embed_url = sources_data.get('link')
            if not embed_url:
                return sources_data

            # Use MegaCloud extractor for megacloud, rapidcloud, or rabbitstream
            if any(k in embed_url.lower() for k in ["megacloud", "rapid-cloud", "rabbitstream", "cloud-stream", "dokicloud"]):
                if Megacloud:
                    scraper = Megacloud(embed_url, custom_proxy=self.proxy)
                    extracted = scraper.extract()
                    if isinstance(extracted.get('sources'), list) and extracted['sources']:
                        return extracted
                else:
                    print("[Warning] Megacloud extractor module not found.")

            return sources_data
        except Exception as e:
            print(f"[Error] _get_sources failed: {e}")
            return None

    def get_episode_info(self, url: str) -> tuple:
        """Extracts anime name, episode number, episode title, and season."""
        anime_id = None
        ep_id = None

        match = re.search(r'watch/([^?]+)\?ep=(\d+)', url)
        if match:
            anime_id = match.group(1)
            ep_id = match.group(2)

        if not anime_id:
            slug_m = re.search(r'watch/([^/?#]+)', url)
            if slug_m:
                anime_id = slug_m.group(1)

        if not anime_id:
            return "Anime", "1", "Episode 1", "1"

        numeric_id = anime_id.split('-')[-1]
        anime_name = None

        # Fetch anime title from page
        try:
            resp_page = self._safe_get(f"/watch/{anime_id}")
            if resp_page:
                soup = BeautifulSoup(resp_page.text, 'html.parser')
                title_el = soup.select_one('h2.film-name, h2.dynamic-name, .anis-watch-detail .film-name')
                if title_el:
                    anime_name = title_el.get_text(strip=True)
                else:
                    og_title = soup.select_one('meta[property="og:title"]')
                    if og_title and og_title.get('content'):
                        anime_name = og_title['content'].split(' - ')[0].strip()
        except Exception:
            pass

        # Fetch episode list HTML
        try:
            resp_eps = self._safe_get(f"/ajax/v2/episode/list/{numeric_id}", headers={"X-Requested-With": "XMLHttpRequest"})
            if resp_eps:
                html = resp_eps.json().get('html', '')
                soup = BeautifulSoup(html, 'html.parser')

                target_anchor = None
                if ep_id:
                    target_anchor = soup.select_one(f'a[data-id="{ep_id}"]')
                if not target_anchor:
                    num_match = re.search(r'episode-(\d+)', url)
                    if num_match:
                        target_anchor = soup.select_one(f'a[data-number="{num_match.group(1)}"]')
                if not target_anchor:
                    target_anchor = soup.select_one('.ep-item')

                if target_anchor:
                    ep_num = target_anchor.get('data-number', '1')
                    ep_title = target_anchor.get('title', f'Episode {ep_num}').replace('&#39;', "'")

                    if not anime_name:
                        anime_name = re.sub(r' \d+$', '', anime_id.replace('-', ' ').title())

                    # Season detection
                    season = "1"
                    season_match = re.search(r'Season (\d+)', anime_name, re.I)
                    if season_match:
                        season = season_match.group(1)
                        anime_name = re.sub(r'Season \d+', '', anime_name, flags=re.I).strip()

                    return anime_name, ep_num, ep_title, season
        except Exception:
            pass

        return anime_name or "Anime", "1", "Episode 1", "1"

    def download_episode(self, url: str, quality: str = "auto", name_override: str = None, season_override: str = None, ep_num_override: str = None) -> bool:
        """Downloads an episode, with multi-quality or specific resolution support."""
        if quality == "all":
            success = True
            for q in ["360", "720", "1080"]:
                if not self._download_single_episode(url, quality=q, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override):
                    success = False
            return success
        return self._download_single_episode(url, quality=quality, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override)

    def _download_single_episode(self, url: str, quality: str = "auto", name_override: str = None, season_override: str = None, ep_num_override: str = None) -> bool:
        ep_id = self.get_episode_id(url)
        if not ep_id:
            self.progress_queue.put({'error': f'Could not determine episode ID from URL: {url}'})
            return False

        all_data = self.get_episode_data(ep_id)
        if not all_data or (not all_data.get('sub') and not all_data.get('dub')):
            self.progress_queue.put({'error': 'Could not extract video stream source.'})
            return False

        anime_name, ep_num, ep_title, season = self.get_episode_info(url)
        final_name = name_override or anime_name
        final_season = season_override or season
        final_ep_num = ep_num_override or ep_num

        audio_label = "Dual Audio" if (all_data.get('sub') and all_data.get('dub')) else ("EN" if all_data.get('dub') else "JP")
        qual_str = quality if quality in ["360", "720", "1080"] else "auto"

        # Sanitize filename
        safe_title = re.sub(r'[\\/*?:"<>|]', '', final_name).strip()
        base_filename = f"[S{final_season}-E{final_ep_num}] {safe_title} [{qual_str}p] [{audio_label}]"

        task_dir = self.download_path / f"{ep_id}_{qual_str}"
        task_dir.mkdir(exist_ok=True, parents=True)

        video_temp = task_dir / f"{base_filename}_sub.mkv"
        audio_temp = task_dir / f"{base_filename}_dub.mkv"
        final_file = self.download_path / f"{base_filename}.mkv"

        sub_data = all_data.get('sub') or all_data.get('dub')
        sub_sources = sub_data.get('sources', [])
        if not sub_sources:
            self.progress_queue.put({'error': 'Source playlist is empty.'})
            return False

        m3u8_url = sub_sources[0].get('file')
        self.progress_queue.put({'status': f"Downloading: {final_name} - Ep {final_ep_num} [{qual_str}p]"})

        # 1. Download Video with N_m3u8DL-RE or ffmpeg
        def run_downloader(stream_url: str, save_name: str, dl_type: str = 'sub'):
            if self.binary_path and self.binary_path.exists():
                cmd = [
                    str(self.binary_path),
                    stream_url,
                    "--save-dir", str(task_dir),
                    "--save-name", save_name,
                    "-H", f"User-Agent: {self.headers['User-Agent']}",
                    "-H", "Referer: https://megacloud.tv/",
                    "--check-segments-count", "False",
                    "-mt",
                    "--thread-count", "16",
                    "--download-retry-count", "3"
                ]
                if self.proxy:
                    cmd.extend(["--custom-proxy", self.proxy])
                if quality in ["1080", "720", "360"]:
                    cmd.extend(["-sv", f"res='{quality}':for=best"])
                else:
                    cmd.append("--auto-select")

                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    return proc.returncode == 0
                except Exception as e:
                    print(f"N_m3u8DL-RE execution error: {e}")

            # Fallback: ffmpeg direct copy
            if shutil.which("ffmpeg"):
                out_path = task_dir / f"{save_name}.mp4"
                cmd = [
                    "ffmpeg", "-y",
                    "-headers", f"Referer: https://megacloud.tv/\r\nUser-Agent: {self.headers['User-Agent']}\r\n",
                    "-i", stream_url,
                    "-c", "copy",
                    str(out_path)
                ]
                proc = subprocess.run(cmd, capture_output=True)
                return proc.returncode == 0

            return False

        # Execute video download
        success_sub = run_downloader(m3u8_url, f"{base_filename}_sub", 'sub')
        for ext in ['.mp4', '.mkv', '.ts']:
            p = task_dir / f"{base_filename}_sub{ext}"
            if p.exists():
                p.rename(video_temp)
                break

        if not video_temp.exists() and not success_sub:
            self.progress_queue.put({'error': 'Failed to download main video track.'})
            return False

        # 2. Download subtitles (.vtt) with correct Referer header
        sub_files = []
        if sub_data.get('tracks'):
            for i, trk in enumerate(sub_data['tracks']):
                if trk.get('kind') == 'captions' and trk.get('file'):
                    lang = trk.get('label', f'sub_{i}').lower().replace(' ', '_')
                    sub_file_path = task_dir / f"{base_filename}_{lang}.vtt"
                    try:
                        # CRITICAL FIX: include Referer & User-Agent
                        r = self.session.get(trk['file'], headers={"Referer": "https://megacloud.tv/", "User-Agent": self.headers["User-Agent"]}, timeout=10)
                        if r.status_code == 200:
                            sub_file_path.write_bytes(r.content)
                            sub_files.append((sub_file_path, lang))
                    except Exception:
                        pass

        # 3. Final Muxing with ffmpeg if available
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin and (sub_files or audio_temp.exists()):
            self.progress_queue.put({'status': f"Merging Audio & Subtitles for: {ep_title}"})
            mux_cmd = [ffmpeg_bin, '-y', '-i', str(video_temp)]
            for s_path, _ in sub_files:
                mux_cmd.extend(['-i', str(s_path)])

            mux_cmd.extend(['-map', '0:v', '-map', '0:a:0'])
            for i in range(len(sub_files)):
                mux_cmd.extend(['-map', f'{i+1}:s'])

            mux_cmd.extend(['-c', 'copy', '-c:s', 'srt'])
            mux_cmd.extend(['-metadata:s:a:0', 'language=jpn', '-metadata:s:a:0', 'title=Japanese'])
            if sub_files:
                mux_cmd.extend(['-disposition:s:0', 'default'])

            mux_cmd.append(str(final_file))
            try:
                subprocess.run(mux_cmd, check=True, capture_output=True)
                shutil.rmtree(task_dir, ignore_errors=True)
                self.progress_queue.put({'finished': True, 'filename': str(final_file)})
                return True
            except Exception:
                pass

        # Fallback without muxing
        if video_temp.exists():
            shutil.move(str(video_temp), str(final_file))
        shutil.rmtree(task_dir, ignore_errors=True)
        self.progress_queue.put({'finished': True, 'filename': str(final_file)})
        return True

    def list_episodes(self, anime_url: str) -> List[Dict[str, str]]:
        """Lists all episodes with titles and stream URLs for an anime."""
        slug = anime_url.split('/')[-1].split('?')[0]
        anime_id = slug.split('-')[-1]

        resp = self._safe_get(f"/ajax/v2/episode/list/{anime_id}", headers={"X-Requested-With": "XMLHttpRequest"})
        if not resp:
            return []

        try:
            html = resp.json().get('html', '')
            soup = BeautifulSoup(html, 'html.parser')
            episodes = []
            for el in soup.select('.ep-item, a.ssl-item.ep-item'):
                ep_id = el.get('data-id')
                ep_num = el.get('data-number', '0')
                title = el.get('title', f'Episode {ep_num}')
                if ep_id:
                    episodes.append({
                        'title': title,
                        'url': f"{self.base_url}/watch/{slug}?ep={ep_id}",
                        'ep_number': ep_num,
                        'ep_id': ep_id
                    })
            return episodes
        except Exception as e:
            print(f"Error listing episodes: {e}")
            return []


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <anime_watch_url> [quality] [download_dir]")
        print("Example: python downloader.py 'https://hianime.ro/watch/naruto-shippuden-355?ep=7910' 1080 downloads")
        sys.exit(0)

    url_arg = sys.argv[1]
    qual_arg = sys.argv[2] if len(sys.argv) > 2 else "auto"
    dl_dir = sys.argv[3] if len(sys.argv) > 3 else "anime_downloads"

    dl = AniwatchDownloader(download_path=dl_dir)
    print(f"Starting download for {url_arg} at quality {qual_arg}...")
    dl.download_episode(url_arg, quality=qual_arg)
