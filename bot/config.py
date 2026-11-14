"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os


# ---- fine import ----
TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]
TELEGRAM_SESSION_STRING = os.environ["TELEGRAM_SESSION_STRING"]
TELEGRAM_GROUP_ID = int(os.environ["TELEGRAM_GROUP_ID"])

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_OWNER_CHAT_ID = os.environ["TELEGRAM_OWNER_CHAT_ID"]
TELEGRAM_ALERT_CHAT_ID = os.environ.get("TELEGRAM_ALERT_CHAT_ID")
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# VINTED_ACCESS_TOKEN / VINTED_REFRESH_TOKEN: opzionali (cookie di una sessione Vinted); se assenti il bot resta anonimo.
VINTED_ACCESS_TOKEN = os.environ.get("VINTED_ACCESS_TOKEN", "").strip()
VINTED_REFRESH_TOKEN = os.environ.get("VINTED_REFRESH_TOKEN", "").strip()

# VISUAL_SEARCH_ATTIVA: solo per il comando /test_visuale (la ricerca visuale Vinted richiede una sessione autenticata: chiusa, default False).
VISUAL_SEARCH_ATTIVA = os.environ.get("VISUAL_SEARCH_ATTIVA", "false").strip().lower() == "true"

VINTED_TRACKER_NAME_HINTS = ("vinted", "tracker")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Modello Gemini gratuito delle chiamate sulle foto (moda e radar). La cascata di modelli e le chiavi stanno in gemini_stato.
GEMINI_MODEL_OCCHIO = "gemini-3.5-flash-lite"
GEMINI_API_URL_OCCHIO = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL_OCCHIO}:generateContent"

# Prezzi per milione di token (per il conteggio del costo teorico nei log; il piano usato e' gratuito).
PREZZO_OCCHIO_INPUT = 0.30
PREZZO_OCCHIO_OUTPUT = 2.50
PREZZO_GROUNDING_PER_QUERY = 14 / 1000

MAX_GALLERY_PHOTOS = 10

# Marker di versione, loggato all'avvio -- serve SOLO a verificare in modo
# inequivocabile quale codice sta girando su Railway dopo un deploy, senza
# doverlo dedurre dai timestamp dei log. Aggiorna la data quando fai una
# modifica significativa (facoltativo, ma utile per il debug futuro).
# Su Railway e' lo SHA breve del commit in esecuzione (RAILWAY_GIT_COMMIT_SHA); altrove la stringa fissa.
BOT_VERSION = (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "")[:7] or "2026-10-01-fair-value-sottolinee"

# Parametri economici usati dalle stime (semaforo, radar, Jev).
COMMISSIONE_PROTEZIONE_PCT = 0.05      # protezione acquisti Vinted, quota sul prezzo
COMMISSIONE_PROTEZIONE_FISSA = 0.70    # protezione acquisti Vinted, quota fissa
SPEDIZIONE_STIMATA_EUR = 2.50          # tariffa IT, la piu' economica
SCONTO_TIPICO_TRATTATIVA_VENDITA = 0.10  # sconto medio che un acquirente strappa in trattativa sul prezzo di vendita


def _env_float(nome, default):
    try:
        return float(os.environ.get(nome, str(default)).replace(",", "."))
    except ValueError:
        return float(default)


# Jev sui comparabili della moda: UNICA lettura (prima moda_jev.py usava default 0 e fair_value.py default 1). Default acceso (in produzione lo e').
MODA_JEV = os.environ.get("MODA_JEV", "1").strip() not in ("0", "false", "no", "")
