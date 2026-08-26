#@cantarellabots
from pyrogram.enums import ParseMode
import asyncio
from curl_cffi import requests
import json
import re
from pyrogram import Client
from cantarella.telegram.download import _handle_download
from cantarella.scraper.cantarellatv import cantarellatvDownloader
from cantarella.core.database import db
from cantarella.telegram.pages import post_to_main_channel
from cantarella.core.anilist import TextEditor
from config import SET_INTERVAL, TARGET_CHAT_ID, MAIN_CHANNEL, LOG_CHANNEL
from datetime import datetime

APIS = ["https://hianime-api.vercel.app/anime", "https://aniwatch-api-v1-0.onrender.com/anime"]

def api_get(endpoint):
    """Helper to fetch data from the public APIs."""
    for api in APIS:
        try:
            r = requests.get(f"{api}{endpoint}", impersonate="chrome120", timeout=15)
            if r.status_code == 200: 
                return r.json().get("data", {})
        except Exception: 
            pass
    return {}

def fetch_schedule_list():
    date_str = datetime.now().strftime("%Y-%m-%d")
    data = api_get(f"/schedule?date={date_str}")
    results = []
    for item in data.get("scheduledAnimes", []):
        results.append({
            'id': item.get('id'),
            'title': item.get('name'),
            'time': item.get('time')
        })
    return results

def fetch_recently_updated():
    data = api_get("/recently-updated")
    results = []
    for item in data.get("animes", []):
        results.append({
            'title': item.get('name'),
            'id': item.get('id'),
            'url': item.get('id') # Using ID instead of URL
        })
    return results

async def check_and_download_ongoing(client: Client, chat_id: int):
    print("\n--- Starting Ongoing Check Cycle via API ---")
    recent_animes = await asyncio.to_thread(fetch_recently_updated)
    
    if not recent_animes:
        print("[-] No recently updated anime found this cycle (API returned empty).")
        return

    downloader = cantarellatvDownloader()
    scheduled_data = await asyncio.to_thread(fetch_schedule_list)
    scheduled_ids = {item['id'] for item in scheduled_data}

    for idx, anime in enumerate(recent_animes):
        try:
            # We now pass the anime ID to list_episodes
            entries = await asyncio.to_thread(downloader.list_episodes, anime['url'])
            if not entries: continue

            latest_ep = entries[-1]
            ep_url = latest_ep['url'] # This is now the raw episode ID (e.g. anime-name?ep=123)
            ep_num = latest_ep.get('ep_number')
            ep_id = latest_ep.get('ep_id')

            if ep_num:
                ep_identifier = f"{anime['id']}_ep_{ep_num}"
            else:
                ep_identifier = f"{anime['id']}_{latest_ep.get('title', 'Unknown')}"

            old_ep_identifier = f"{anime['id']}_{latest_ep.get('title', 'Unknown')}"
            legacy_ep_identifier = None
            if ep_num and ep_id:
                legacy_ep_identifier = f"{anime['id']}_{ep_num}_{ep_id}"

            if (await db.is_processed(ep_identifier) or 
                await db.is_processed(old_ep_identifier) or 
                (legacy_ep_identifier and await db.is_processed(legacy_ep_identifier))):
                if not await db.is_processed(ep_identifier):
                    await db.mark_processed(ep_identifier)
                continue

            clean_search_title = re.sub(r'\s+', ' ', anime['title']).strip()
            te = TextEditor(clean_search_title)
            await te.load_anilist()
            data = te.adata

            romaji_title = data.get('title', {}).get('romaji')
            english_title = data.get('title', {}).get('english')
            anime_name = english_title or romaji_title or anime['title']

            if not (romaji_title or english_title):
                    anime_name = re.sub(r'\s+\d+$', '', anime_name).strip()

            ani_season = "1"
            ani_ep_num = "0"

            match_s = re.search(r'Season (\d+)', anime['title'], re.I)
            if not match_s: match_s = re.search(r'\s+(\d+)$', anime['title'])

            if match_s: ani_season = match_s.group(1)
            else:
                te_season = te.pdata.get('anime_season')
                if te_season: ani_season = str(te_season)
                else:
                    match_s2 = re.search(r'Season (\d+)', anime_name, re.I)
                    if match_s2: ani_season = match_s2.group(1)

            if data.get('nextAiringEpisode'):
                ani_ep_num = str(data['nextAiringEpisode']['episode'] - 1)
            else:
                match_ep = re.search(r'Episode (\d+)', latest_ep.get('title', ''))
                if match_ep: ani_ep_num = match_ep.group(1)
                else:
                    from guessit import guessit
                    g = guessit(latest_ep.get('title', ''))
                    if g.get('episode'): ani_ep_num = str(g['episode'])

            if "Dr. Stone" in anime_name:
                if "New World" in anime['title']: ani_season = "3"
                if "Science Future" in anime['title'] or "Season 4" in anime['title']: ani_season = "4"

            universal_ep_identifier = f"{anime_name}_S{ani_season}_E{ani_ep_num}"
            if await db.is_processed(universal_ep_identifier):
                await db.mark_processed(ep_identifier)
                continue

            print(f"[+] New episode found: {anime['title']} - {latest_ep.get('title', 'Unknown')}")

            is_scheduled = anime['id'] in scheduled_ids
            country_of_origin = data.get("countryOfOrigin", "")
            is_chinese = country_of_origin == "CN"

            if is_chinese and not is_scheduled:
                await db.mark_processed(ep_identifier)
                await db.mark_processed(universal_ep_identifier)
                continue

            log_id = int(LOG_CHANNEL) if LOG_CHANNEL else chat_id
            status_msg = await client.send_message(log_id, f"<blockquote>🔄 ᴀᴜᴛᴏ-ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ ɴᴇᴡ ᴇᴘɪꜱᴏᴅᴇ: {anime_name} - ꜱ{ani_season}ᴇ{ani_ep_num}...</blockquote>", parse_mode=ParseMode.HTML)

            uploaded_msgs = await _handle_download(
                client, None, ep_url, status_msg,
                is_playlist=False, quality="all", chat_id=chat_id,
                name_override=anime_name,
                season_override=str(ani_season),
                ep_num_override=str(ani_ep_num) if ani_ep_num else None
            )

            if uploaded_msgs:
                quality_map = {re.search(r'\[(\d+p)\]', msg.caption or "").group(1): msg.id for msg in uploaded_msgs if re.search(r'\[(\d+p)\]', msg.caption or "")}
                await post_to_main_channel(client, ep_url, uploaded_msgs, quality_map, None, str(ani_season), str(ani_ep_num) if ani_ep_num else "1")

            await db.mark_processed(ep_identifier)
            await db.mark_processed(universal_ep_identifier)

        except Exception as e:
            print(f"Error processing {anime['title']}: {e}")

async def ongoing_task(client: Client):
    if not TARGET_CHAT_ID: return
    try: target_chat_id = int(TARGET_CHAT_ID)
    except ValueError: return

    while True:
        if await db.get_user_setting(0, "ongoing_enabled", False):
            try: await check_and_download_ongoing(client, target_chat_id)
            except Exception as e: print(f"Error in ongoing task loop: {e}")
        await asyncio.sleep(SET_INTERVAL)
