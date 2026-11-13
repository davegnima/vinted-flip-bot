"""Client Telethon del userbot (spostato da main_telethon.py, nessun cambio: stessa creazione). Sta qui perche' i cicli periodici
(bot/cicli.py) e i comandi (bot/comandi.py) lo usano e non possono importare main_telethon (import circolare)."""

from telethon import TelegramClient
from telethon.sessions import StringSession

from bot.config import TELEGRAM_API_HASH, TELEGRAM_API_ID, TELEGRAM_SESSION_STRING

client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
