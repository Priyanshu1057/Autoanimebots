# Updated Cantarella Scraper Package

This archive contains the updated and verified scraper files for your Cantarella Bot.

## Fixed Issues:
1. Added missing `fetch_recently_updated(page=1, per_page=12)` method:
   Fixes: `Error in ongoing task loop: 'cantarellatvDownloader' object has no attribute 'fetch_recently_updated'`
2. Added `EpisodeIdStr` + `AnimeResult` + `AnimeList` dictionary compatibility:
   Fixes: `TypeError: string indices must be integers, not 'str'` in plugins/search.py line 46 (`cb_data = f"anime_{res['id']}"`)
3. Added missing `get_home_sections()` method.
4. Added missing `get_schedule()` method.
5. Added all aliases:
   `AniwaveScraper = cantarellatvDownloader`
   `AnimetsuScraper = cantarellatvDownloader`
   `Animetsu = cantarellatvDownloader`
   `CantarellaScraper = cantarellatvDownloader`
6. Verified with `python3 -m py_compile` (0 syntax errors).
