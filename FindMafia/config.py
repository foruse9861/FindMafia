"""Central configuration. Values come from environment variables (.env)."""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DB_PATH", "data/mafia.db")
RICH_MESSAGES = os.getenv("RICH_MESSAGES", "on").strip().lower() != "off"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---- Game defaults (admins can change per group in the database) ----
MIN_PLAYERS = 5
MAX_PLAYERS = 30
LOBBY_SECONDS = 60
NIGHT_SECONDS = 60
DISCUSSION_SECONDS = 90
VOTING_SECONDS = 45

# ---- Rich message limits ----
# Telegram hard limits: 32768 chars, 500 blocks, 16 nesting, 20 table cols,
# 1-8 buttons per row, callback_data 1-64 BYTES. Below: our SAFE budgets.
RICH_MAX_CHARS = 20000
RICH_MAX_BLOCKS = 300
RICH_MAX_NESTING = 6
RICH_TABLE_MAX_COLS = 5
RICH_PILLS_PER_ROW = 4
RICH_PILLS_PER_PAGE = 16
RICH_TABLE_ROWS_PER_PAGE = 15
PLAIN_MAX_CHARS = 3800  # plain HTML fallback (Telegram allows 4096)

# Minimum seconds between two edits of the same live message (flood safety)
EDIT_INTERVAL = 5.0
