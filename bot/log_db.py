"""Storico di tutte le righe strutturate dei log (11/11, utente: storico di sempre in un database, niente Postgres).

Un logging.Handler mette in una coda le righe INFO/WARNING col formato `PREFISSO MAIUSCOLO | ...` (quelle che si cercano
nei log Railway) e un thread le scrive a lotti nella tabella SQLite `log_righe` sul volume /data, che sopravvive ai
deploy. Mai bloccante per il bot: coda limitata (se piena la riga si scarta e si conta), niente richieste di rete.
Lettura: `leggi_righe(prefisso, dal_ts)`; `campi_riga(testo)` ricava i valori `k=v`."""
import logging
import os
import queue
import re
import threading
import time

from bot import db

LOG_DB_ATTIVO = os.environ.get("LOG_DB", "1") != "0"
LOG_DB_MAX_MB = float(os.environ.get("LOG_DB_MAX_MB", "0") or 0)  # 0 = nessun limite (storico di sempre)
LOTTO_MAX = 500
ATTESA_LOTTO_S = 2.0

_RE_PREFISSO = re.compile(r"^([A-Z][A-Z0-9_]*(?: [A-Z][A-Z0-9_]*)*) \| ")
_RE_ITEM = re.compile(r"\bitem=(\d+)")

_coda = queue.Queue(maxsize=50000)
_scartate = [0]
_thread = [None]

_SCHEMA_LOG = """
CREATE TABLE IF NOT EXISTS log_righe (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, prefisso TEXT NOT NULL, item_id TEXT, testo TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS log_righe_prefisso_ts ON log_righe (prefisso, ts);
CREATE INDEX IF NOT EXISTS log_righe_item ON log_righe (item_id);
"""


def estrai_riga(messaggio, ts=None):
    """(ts, prefisso, item_id, testo) se il messaggio e' una riga strutturata, altrimenti None. Pura."""
    m = _RE_PREFISSO.match(messaggio or "")
    if not m:
        return None
    it = _RE_ITEM.search(messaggio)
    return (ts if ts is not None else time.time(), m.group(1), it.group(1) if it else None, messaggio)


def campi_riga(testo):
    """Valori `chiave=valore` di una riga strutturata (separatore ' | '). Pura."""
    out = {}
    for pezzo in (testo or "").split(" | ")[1:]:
        k, sep, v = pezzo.partition("=")
        if sep and k.strip() and " " not in k.strip():
            out[k.strip()] = v.strip()
    return out


class GestoreLogDb(logging.Handler):
    def emit(self, record):
        try:
            if record.levelno < logging.INFO or record.levelno > logging.WARNING:
                return
            r = estrai_riga(record.getMessage(), record.created)
            if r is None:
                return
            _coda.put_nowait(r)
        except queue.Full:
            _scartate[0] += 1
        except Exception:
            pass


def _scrivi_lotto(righe):
    try:
        with db._lock:
            c = db._connessione()
            c.executescript(_SCHEMA_LOG)
            c.executemany("INSERT INTO log_righe (ts, prefisso, item_id, testo) VALUES (?, ?, ?, ?)", righe)
            c.commit()
        return True
    except Exception:
        return False


def _ciclo():
    lotto = []
    while True:
        try:
            lotto.append(_coda.get(timeout=ATTESA_LOTTO_S))
            while len(lotto) < LOTTO_MAX:
                lotto.append(_coda.get_nowait())
        except queue.Empty:
            pass
        if lotto and _scrivi_lotto(lotto):
            lotto = []
        elif len(lotto) > 20000:
            lotto = lotto[-10000:]  # DB non raggiungibile da molto: tiene le righe piu' recenti
        if LOG_DB_MAX_MB:
            _pota_se_serve()


def _pota_se_serve():
    """Se il file del DB supera LOG_DB_MAX_MB cancella le righe di log piu' vecchie (il 10%). Solo se il limite e' impostato."""
    try:
        if os.path.getsize(db.DB_FILE) / 1048576 > LOG_DB_MAX_MB:
            with db._lock:
                c = db._connessione()
                c.execute("DELETE FROM log_righe WHERE id IN (SELECT id FROM log_righe ORDER BY id LIMIT "
                          "(SELECT COUNT(*) / 10 + 1 FROM log_righe))")
                c.commit()
    except Exception:
        pass


def avvia(logger=None):
    """Aggancia il gestore al logger radice e avvia il thread di scrittura (una volta sola)."""
    if not LOG_DB_ATTIVO or _thread[0] is not None:
        return False
    logging.getLogger().addHandler(GestoreLogDb())
    t = threading.Thread(target=_ciclo, name="log_db", daemon=True)
    t.start()
    _thread[0] = t
    return True


def leggi_righe(prefisso=None, dal_ts=0.0, limite=100000):
    """[(ts, prefisso, item_id, testo)] in ordine di tempo; prefisso esatto o None per tutte."""
    try:
        with db._lock:
            c = db._connessione()
            c.executescript(_SCHEMA_LOG)
            if prefisso:
                cur = c.execute("SELECT ts, prefisso, item_id, testo FROM log_righe WHERE prefisso = ? AND ts >= ? "
                                "ORDER BY ts LIMIT ?", (prefisso, dal_ts, limite))
            else:
                cur = c.execute("SELECT ts, prefisso, item_id, testo FROM log_righe WHERE ts >= ? ORDER BY ts LIMIT ?",
                                (dal_ts, limite))
            return cur.fetchall()
    except Exception:
        return []
