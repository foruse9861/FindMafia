"""
GIF CONFIGURATION
=================
Paste Telegram animation file_ids OR direct https URLs of GIF/MP4 files between the quotes.
Leave a value as "" (empty) to skip that GIF - the bot will NOT crash, it just sends the text.

How to get a file_id: send your GIF to the bot @RawDataBot or forward it to your own bot and
log message.animation.file_id.  You can replace any value later without touching the game code.
"""

WELCOME_GIF = ""        # shown with /start
LOBBY_GIF = ""          # when a lobby opens
GAME_START_GIF = ""     # when the game starts
NIGHT_GIF = ""          # every night
MAFIA_ACTION_GIF = ""   # night kill announced
DOCTOR_SAVE_GIF = ""    # doctor saved someone
DETECTIVE_GIF = ""      # detective moment (optional)
DAY_GIF = ""            # every morning
VOTING_GIF = ""         # voting starts
ELIMINATION_GIF = ""    # someone is voted out
MAFIA_WIN_GIF = ""
TOWN_WIN_GIF = ""
NEUTRAL_WIN_GIF = ""
GAME_OVER_GIF = ""
