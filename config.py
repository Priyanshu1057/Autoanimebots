#@cantarellabots
import os
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ.get("API_ID", ))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

SET_INTERVAL = int(os.environ.get("SET_INTERVAL", 60))  # in seconds, default 1 hour
TARGET_CHAT_ID = os.environ.get("TARGET_CHAT_ID", "-1004458950694")
MAIN_CHANNEL = os.environ.get("MAIN_CHANNEL", "-1001648037641") # Change as needed
LOG_CHANNEL = os.environ.get("LOG_CHANNEL", "-1004483212997")
MONGO_URL = os.environ.get("MONGO_URL", "")
MONGO_NAME = os.environ.get("MONGO_NAME", "Cluster0")
OWNER_ID = int(os.environ.get("OWNER_ID", "1018033649"))
ADMIN_URL = os.environ.get("ADMIN_URL", "@Matt_4565")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "@Autoanime_flixbot")
FSUB_PIC = os.environ.get("FSUB_PIC", "https://files.catbox.moe/bli70r.jpg")
FSUB_LINK_EXPIRY = int(os.environ.get("FSUB_LINK_EXPIRY", 600))
START_PIC =os.environ.get("START_PIC", "https://files.catbox.moe/4b8jvw.jpg")
PROXY = "http://wbjpkohe:8m4vxoauzbg2@31.59.20.176:6754/"
# ─── Filename & Caption Formats ───
FORMAT = os.environ.get("FORMAT", "[S{season}-E{episode}] {title} [{quality}] [{audio}]")
CAPTION = os.environ.get("CAPTION", "[ @cantarellabots {FORMAT}]")

# ─── Progress Bar Settings ───
PROGRESS_BAR = os.environ.get("PROGRESS_BAR", """
<blockquote> {bar} </blockquote>
<blockquote>📁 <b>{title}</b>
⚡ Speed: {speed}
📦 {current} / {total}</blockquote>
""")

# ─── Response Images ───
# Rotating anime images sent with every bot reply. Add as many as you like.
RESPONSE_IMAGES = [
    "https://files.catbox.moe/5oonsm.jpg",
    "https://files.catbox.moe/9ufgme.jpg",
    "https://files.catbox.moe/4b8jvw.jpg",
    "https://files.catbox.moe/bli70r.jpg",
    "https://files.catbox.moe/uce0lw.jpg",
    "https://files.catbox.moe/is7q4q.jpg"
]
