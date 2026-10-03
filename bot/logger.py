"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import sys
import logging


# ---- fine import ----
# INFO su stdout, WARNING/ERROR su stderr (prima tutto andava su stderr e Railway marcava ogni riga come
# "error", rendendo inutile il filtro per livello). Formato e testi dei messaggi invariati: l'analisi
# giornaliera dei log filtra per testo.
_LOG_FORMATO = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")


class _SoloSottoWarning(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING


_log_out = logging.StreamHandler(sys.stdout)
_log_out.addFilter(_SoloSottoWarning())
_log_out.setFormatter(_LOG_FORMATO)
_log_err = logging.StreamHandler(sys.stderr)
_log_err.setLevel(logging.WARNING)
_log_err.setFormatter(_LOG_FORMATO)
logging.basicConfig(level=logging.INFO, handlers=[_log_out, _log_err])
log = logging.getLogger("vinted_flip_bot")
# httpx logga a INFO l'URL completo di OGNI richiesta ("HTTP Request: POST
# https://api.telegram.org/bot<TOKEN>/sendMessage ..."): con il livello
# globale a INFO il token del bot Telegram finiva in chiaro nei log Railway
# (stesso problema gia' risolto per la key Gemini spostandola nell'header,
# vedi chiama_gemini). A WARNING restano solo gli errori veri di httpx.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
