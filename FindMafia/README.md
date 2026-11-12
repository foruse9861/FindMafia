# 🎭 MAFIA WORLD (Telegram bot)

Python 3.11+ and **python-telegram-bot 22.x** (async). Rich messages (tables, colored pills, details) are sent through
`bot.do_api_request("sendRichMessage")` because PTB 22.x has no wrapper yet; if rich fails 3 times the bot falls back to plain HTML automatically.

## Run locally
```
pip install -r requirements.txt
cp .env.example .env      # set BOT_TOKEN and OWNER_IDS
python main.py
```
## Deploy on Railway
1. Push this folder to GitHub, create a Railway project from it (it uses the `Procfile` / `Dockerfile`).
2. Variables: `BOT_TOKEN`, `OWNER_IDS`, `DB_PATH=/data/mafia.db`.
3. Add a **Volume** mounted at `/data` so the database survives restarts. Daily backups go to `/data/backups`.
## BotFather
Disable privacy mode (`/setprivacy` -> Disable) and add the bot to your group as admin with **Delete Messages**.
## GIFs
Edit `gif_config.py` (file_ids or URLs). Empty = skipped, nothing breaks.
## Commands
Players: `/start /play /help /cancelgame` · Group admins: `/admin /startgame /stopgame /setplayers /settimer /setmode hardcore|normal /setroles advanced|basic /richtest` · Owners: `/ban /unban /announce /resetstats`.
## Tests (no Telegram needed)
`python -m tests.test_lobby_flow` and `python -m tests.test_full_game`
