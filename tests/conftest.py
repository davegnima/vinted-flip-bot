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
    "VELOCITA_ATTIVA": "0",   # la correzione del semaforo dalla velocita' si prova a parte, con una tabella finta
    "RADAR_PAUSA_DA": "",   # niente pausa notturna nei test (altrimenti falliscono se girano di notte)
    "TRACCIAMENTO_FILE": os.path.join(_TMP, "tracciamento.jsonl"),
    "FAIR_VALUE_LOG_FILE": os.path.join(_TMP, "fair_value_log.jsonl"),
    "FAIR_VALUE_APPRESO_FILE": os.path.join(_TMP, "fair_value_appreso.json"),
    "DB_FILE": os.path.join(_TMP, "vinted_bot.sqlite3"),
    "CATALOGO_CATEGORIE_FILE": os.path.join(_TMP, "catalogo_categorie.json"),
})
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
