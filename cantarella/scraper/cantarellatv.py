#@cantarellabots
from curl_cffi import requests
import math
import re
import shutil
import subprocess
import os as _os
from pathlib import Path
from queue import Queue
from threading import Thread

APIS = ["https://hianime-api.vercel.app/anime", "https://aniwatch-api-v1-0.onrender.com/anime"]

def api_get(endpoint):
    for api in APIS:
        try:
            r = requests.get(f"{api}{endpoint}", impersonate="chrome120", timeout=15)
            if r.status_code == 200: 
                return r.json().get("data", {})
        except Exception: 
            pass
    return {}

class cantarellatvDownloader:
    def __init__(self, download_path="anime_downloads", progress_queue=None):
        self.download_path = Path(download_path)
        self.download_path.mkdir(exist_ok=True)
        self.binary_path = self._get_binary_path()
        self.progress_queue = progress_queue or Queue()
        self.proxy = None

    def _get_binary_path(self):
        candidates = [
            Path("binary") / "N_m3u8DL-RE",           
            Path("binary") / "N_m3u8DL-RE.exe",       
            Path("/usr/local/bin/N_m3u8DL-RE"),
            Path("/app/binary/N_m3u8DL-RE")
        ]
        for p in candidates:
            if p.exists():
                print(f"Found N_m3u8DL-RE binary at: {p}")
                return p
        which_path = shutil.which("N_m3u8DL-RE")
        if which_path:
            return Path(which_path)
        raise FileNotFoundError(f"N_m3u8DL-RE binary not found. Checked: {candidates} and PATH")

    def _format_bytes(self, bytes_num):
        if bytes_num == 0: return '0 B'
        size_name = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(bytes_num, 1024)))
        p = math.pow(1024, i)
        s = round(bytes_num / p, 2)
        return f"{s} {size_name[i]}"

    def get_episode_id(self, url):
        return url

    def list_episodes(self, anime_id):
        if "hianime" in anime_id or "aniwatch" in anime_id or "zoroxtv" in anime_id:
            anime_id = anime_id.split('/')[-1].split('?')[0]
            
        data = api_get(f"/episodes/{anime_id}")
        eps = data.get("episodes", [])
        results = []
        for ep in eps:
            ep_url_raw = ep.get('episodeId', '')
            results.append({
                'title': ep.get('title'),
                'url': ep_url_raw, 
                'ep_number': str(ep.get('number')),
                'ep_id': ep_url_raw.split('?ep=')[-1] if '?ep=' in ep_url_raw else ep_url_raw
            })
        return results

    def get_episode_data(self, ep_id):
        result = {'sub': None, 'dub': None}
        
        sub_data = api_get(f"/episode-srcs?id={ep_id}&server=hd-1&category=sub")
        if sub_data and sub_data.get("sources"):
            result['sub'] = {'sources': [{'file': s['url']} for s in sub_data['sources']], 'tracks': sub_data.get('tracks', [])}
            
        dub_data = api_get(f"/episode-srcs?id={ep_id}&server=hd-1&category=dub")
        if dub_data and dub_data.get("sources"):
            result['dub'] = {'sources': [{'file': s['url']} for s in dub_data['sources']], 'tracks': dub_data.get('tracks', [])}
            
        return result if result['sub'] or result['dub'] else None

    def get_episode_info(self, ep_id):
        if "hianime" in ep_id or "aniwatch" in ep_id:
            match = re.search(r'watch/([^?]+)\?ep=(\d+)', ep_id)
            if match: ep_id = f"{match.group(1)}?ep={match.group(2)}"
            else: return "Anime", "0", "Unknown", "1"

        anime_id = ep_id.split('?ep=')[0]
        
        info = api_get(f"/info/{anime_id}")
        anime_name = info.get("anime", {}).get("info", {}).get("name", anime_id.replace('-', ' ').title())
        
        eps = self.list_episodes(anime_id)
        ep_num = "0"
        ep_title = "Unknown"
        for ep in eps:
            if ep['url'] == ep_id:
                ep_num = ep['ep_number']
                ep_title = ep['title']
                break
                
        season_match = re.search(r'Season (\d+)', anime_name, re.I)
        if season_match:
            season = season_match.group(1)
            anime_name = re.sub(r'\s+', ' ', anime_name.replace(season_match.group(0), '')).strip()
        else:
            season = "1"
            
        return anime_name, ep_num, ep_title, season

    def download_episode(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None):
        if quality == "all":
            success = True
            for q in ["360", "720", "1080"]:
                if not self._download_single_episode(url, quality=q, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override):
                    success = False
            return success
        else:
            return self._download_single_episode(url, quality=quality, name_override=name_override, season_override=season_override, ep_num_override=ep_num_override)

    def _download_single_episode(self, url, quality="auto", name_override=None, season_override=None, ep_num_override=None):
        ep_id = url 
        if not ep_id:
            self.progress_queue.put({'error': 'Could not find episode ID.'})
            return False

        all_data = self.get_episode_data(ep_id)
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

        task_dir = self.download_path / f"{ep_id.replace('?','_').replace('=','_')}_{qual_str}"
        task_dir.mkdir(exist_ok=True)

        video_temp = task_dir / f"{base_filename}_sub.mkv"
        audio_temp = task_dir / f"{base_filename}_dub.mkv"
        final_file = self.download_path / f"{base_filename}.mkv"

        data = all_data.get('sub') or all_data.get('dub')
        if not data or not data.get('sources'):
             self.progress_queue.put({'error': 'Video sources missing from API response.'})
             return False
             
        m3u8_url = data['sources'][0]['file']

        self.progress_queue.put({'status': f"📥 **Downloading: {final_name} [{qual_str}p]**\nPlease wait..."})

        def run_n_m3u8dl(url, save_name, dl_type='sub', quality="auto"):
            cmd = [
                str(self.binary_path),
                url,
                "--save-dir", str(task_dir),
                "--save-name", save_name,
                "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Referer: https://megacloud.tv/",
                "--check-segments-count", "False",
                "-mt",
                "--thread-count", "50",
                "--download-retry-count", "5"
            ]

            if quality == "1080": cmd.extend(["-sv", "res='1080':for=best"])
            elif quality == "720": cmd.extend(["-sv", "res='720':for=best"])
            elif quality == "360": cmd.extend(["-sv", "res='360':for=best"])
            else: cmd.extend(["--auto-select"])

            try:
                print(f"[{dl_type.upper()}] Running: {' '.join(cmd[:3])}... (binary: {cmd[0]})", flush=True)

                if not _os.path.isfile(cmd[0]):
                    print(f"Binary not found at: {cmd[0]}", flush=True)
                    return False

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=0
                )

                last_lines = []
                buffer = b""
                while True:
                    char = process.stdout.read(1)
                    if not char: break
                    if char in (b'\r', b'\n'):
                        try:
                            line = buffer.decode('utf-8', errors='replace').strip()
                        except:
                            line = ""

                        if line:
                            line = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', line)
                            last_lines.append(line)
                            if len(last_lines) > 5: last_lines.pop(0)

                            if "%" in line:
                                print(f"[{dl_type.upper()}] {line}", flush=True)
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
                exit_code = process.returncode
                return exit_code == 0
            except Exception as e:
                print(f"Error running N_m3u8DL-RE: {e}", flush=True)
                return False

        dub_downloaded = [False]
        dub_thread = None
        if all_data.get('sub') and all_data.get('dub'):
             dub_url = all_data['dub']['sources'][0]['file']

             def download_dub():
                 save_name = f"{base_filename}_dub"
                 if run_n_m3u8dl(dub_url, save_name, dl_type='dub', quality=quality):
                     for ext in ['.mp4', '.m4a', '.mkv', '.ts']:
                         p = task_dir / f"{save_name}{ext}"
                         if p.exists():
                             p.rename(audio_temp)
                             dub_downloaded[0] = True
                             break
                 else:
                     self.progress_queue.put({'status': f"⚠️ **Dub download failed**\nProceeding with Japanese only."})

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
            if dub_thread: dub_thread.join()
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
                    r = requests.get(s['file'], timeout=10)
                    if r.status_code == 200:
                        with open(sub_path, 'wb') as f:
                            f.write(r.content)
                        sub_files.append((sub_path, lang))
                except: pass

        ffmpeg_exe = 'ffmpeg'

        if not video_temp.exists():
             for f in task_dir.iterdir():
                  if f.name.startswith(f"{base_filename}_sub."):
                       f.replace(video_temp)
                       break

        if not shutil.which(ffmpeg_exe) or (not sub_files and not dub_downloaded):
            if video_temp.exists():
                 video_temp.replace(final_file)
            try: shutil.rmtree(task_dir)
            except: pass
            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True

        self.progress_queue.put({'status': f"🎬 **Merging Tracks for: {ep_title}**\nPlease wait..."})

        cmd = [ffmpeg_exe, '-y']

        if video_temp.exists(): cmd.extend(['-i', str(video_temp)])
        else: return False

        if dub_downloaded and audio_temp.exists(): cmd.extend(['-i', str(audio_temp)])
        else: dub_downloaded = False

        valid_subs = []
        for sub_path, lang in sub_files:
            if sub_path.exists():
                 cmd.extend(['-i', str(sub_path)])
                 valid_subs.append((sub_path, lang))
        sub_files = valid_subs

        cmd.extend(['-map', '0:v', '-map', '0:a']) 
        if dub_downloaded: cmd.extend(['-map', '1:a:0']) 

        sub_offset = 2 if dub_downloaded else 1
        for i in range(len(sub_files)): cmd.extend(['-map', f'{i + sub_offset}:s'])

        cmd.extend(['-c', 'copy', '-c:s', 'srt'])
        cmd.extend(['-metadata:s:a:0', 'language=jpn', '-metadata:s:a:0', 'title=Japanese'])
        if dub_downloaded: cmd.extend(['-metadata:s:a:1', 'language=eng', '-metadata:s:a:1', 'title=English'])
        if sub_files: cmd.extend(['-disposition:s:0', 'default'])

        cmd.append(str(final_file))

        try:
            subprocess.run(cmd, check=True, capture_output=True)
            try: shutil.rmtree(task_dir)
            except: pass
            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True
        except Exception as e:
            if video_temp.exists(): video_temp.replace(final_file)
            try: shutil.rmtree(task_dir)
            except: pass
            self.progress_queue.put({'finished': True, 'filename': str(final_file), 'title': base_filename})
            return True
