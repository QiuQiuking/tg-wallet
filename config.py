import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
INFURA_HTTP = os.getenv("INFURA_HTTP")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1"))
GROUP_ID = int(os.getenv("GROUP_ID", "-1"))
CHANNEL_URL = os.getenv("CHANNEL_URL")
GROUP_URL = os.getenv("GROUP_URL")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 30))  # 默认 30 秒