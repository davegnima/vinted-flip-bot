"""Archivio SQLite del bot (stdlib, nessuna dipendenza nuova), in /data (volume Railway).

Cosa contiene, in due famiglie:
- stato che deve sopravvivere ai riavvii: cooldown di quota per (key, modello) di Gemini e modelli esclusi.
  Prima si perdevano a ogni deploy e il bot rispendeva chiamate per riscoprire le quote finite;
- eventi: una riga per ESITO, per riga del PANNELLO e per evento di TRACCIAMENTO (JSON in `dati`), per poter
  fare statistiche dentro il bot senza rileggere i log. I log restano la fonte del recap mattutino: qui si
  scrive IN PIU', mai al posto dei log.

Regole: scrivere non solleva mai (un errore del DB non deve fermare un verdetto), nessuna chiave in chiaro
(le key Gemini sono salvate solo come hash troncato)."""
import hashlib
import json
import os
import sqlite3
import threading
import time
import traceback

from bot.logger import log

DB_FILE = os.environ.get("DB_FILE", "/data/vinted_bot.sqlite3")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quota_gemini (
    chiave_hash TEXT NOT NULL, modello TEXT NOT NULL, fino REAL NOT NULL,
    PRIMARY KEY (chiave_hash, modello));
CREATE TABLE IF NOT EXISTS modelli_gemini_esclusi (modello TEXT PRIMARY KEY, fino REAL NOT NULL);
CREATE TABLE IF NOT EXISTS eventi (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, tipo TEXT NOT NULL,
    item_id TEXT, brand TEXT, dati TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS eventi_tipo_ts ON eventi (tipo, ts);
CREATE INDEX IF NOT EXISTS eventi_item ON eventi (item_id);
CREATE TABLE IF NOT EXISTS pagamento_giorno (giorno TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""

_conn = None
_lock = threading.Lock()


def hash_chiave(chiave):
    """Impronta troncata di una API key: mai salvare la key."""
    return hashlib.sha256(str(chiave).encode("utf-8")).hexdigest()[:16]


def _connessione():
    global _conn
    if _conn is None:
        cartella = os.path.dirname(DB_FILE)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        c = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(_SCHEMA)
        c.commit()
        _conn = c
    return _conn


def chiudi():
    """Chiude la connessione (test e arresto)."""
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            finally:
                _conn = None


def _esegui(sql, parametri=()):
    """Esegue una scrittura. Ritorna True/False, non solleva mai."""
    try:
        with _lock:
            c = _connessione()
            c.execute(sql, parametri)
            c.commit()
        return True
    except Exception:
        log.warning("DB: scrittura fallita (%s):\n%s", sql.split()[0:3], traceback.format_exc())
        return False


def _leggi(sql, parametri=()):
    try:
        with _lock:
            return _connessione().execute(sql, parametri).fetchall()
    except Exception:
        log.warning("DB: lettura fallita:\n%s", traceback.format_exc())
        return []


# ---- eventi -----------------------------------------------------------------------------------------------
def scrivi_evento(tipo, item_id=None, brand=None, dati=None, ts=None):
    return _esegui(
        "INSERT INTO eventi (ts, tipo, item_id, brand, dati) VALUES (?, ?, ?, ?, ?)",
        (ts if ts is not None else time.time(), tipo, None if item_id is None else str(item_id), brand,
         json.dumps(dati or {}, ensure_ascii=False, default=str)))


def leggi_eventi(tipo, dal_ts=0.0, limite=100000):
    righe = _leggi("SELECT ts, item_id, brand, dati FROM eventi WHERE tipo = ? AND ts >= ? ORDER BY ts LIMIT ?",
                   (tipo, dal_ts, limite))
    out = []
    for ts, item_id, brand, dati in righe:
        try:
            out.append({"ts": ts, "item_id": item_id, "brand": brand, **json.loads(dati)})
        except ValueError:
            continue
    return out


def conta_eventi(tipo):
    r = _leggi("SELECT COUNT(*) FROM eventi WHERE tipo = ?", (tipo,))
    return r[0][0] if r else 0


# ---- riserva a pagamento: richieste del giorno (UTC), cosi' il tetto regge ai riavvii -----------------------
def salva_pagamento(giorno, n):
    return _esegui("INSERT OR REPLACE INTO pagamento_giorno (giorno, n) VALUES (?, ?)", (giorno, int(n)))


def carica_pagamento(giorno):
    r = _leggi("SELECT n FROM pagamento_giorno WHERE giorno = ?", (giorno,))
    return int(r[0][0]) if r else 0


# ---- stato Gemini ----------------------------------------------------------------------------------------
def salva_quota_gemini(chiave, modello, fino):
    return _esegui("INSERT OR REPLACE INTO quota_gemini (chiave_hash, modello, fino) VALUES (?, ?, ?)",
                   (hash_chiave(chiave), modello or "", float(fino)))


def salva_modello_escluso(modello, fino):
    return _esegui("INSERT OR REPLACE INTO modelli_gemini_esclusi (modello, fino) VALUES (?, ?)",
                   (modello, float(fino)))


def carica_stato_gemini(chiavi, adesso=None):
    """Cooldown ancora validi: ({(chiave, modello): fino}, {modello: fino}). Le key tornano dall'hash cercando
    tra quelle configurate; le righe scadute o di key non piu' configurate si ignorano."""
    adesso = adesso if adesso is not None else time.time()
    per_hash = {hash_chiave(k): k for k in chiavi}
    quote = {}
    for h, modello, fino in _leggi("SELECT chiave_hash, modello, fino FROM quota_gemini WHERE fino > ?", (adesso,)):
        if h in per_hash:
            quote[(per_hash[h], modello)] = fino
    esclusi = {m: f for m, f in _leggi("SELECT modello, fino FROM modelli_gemini_esclusi WHERE fino > ?", (adesso,))}
    return quote, esclusi
