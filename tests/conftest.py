"""Ambiente di prova: il modulo del bot legge le variabili d'ambiente e crea il client Telegram all'importazione,
quindi le variabili finte vanno impostate PRIMA di importarlo. I file di archivio puntano a una cartella
temporanea (mai a /data)."""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="vinted-bot-test-")
os.environ.update({
    "TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "x", "TELEGRAM_SESSION_STRING": "",
    "TELEGRAM_GROUP_ID": "-100", "TELEGRAM_BOT_TOKEN": "1:x", "TELEGRAM_OWNER_CHAT_ID": "1",
    "GEMINI_API_KEY": "k",
    "TRACCIAMENTO_FILE": os.path.join(_TMP, "tracciamento.jsonl"),
    "FAIR_VALUE_LOG_FILE": os.path.join(_TMP, "fair_value_log.jsonl"),
    "FAIR_VALUE_APPRESO_FILE": os.path.join(_TMP, "fair_value_appreso.json"),
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
