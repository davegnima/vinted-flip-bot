"""Archivio dei venduti moda nel SQLite del bot (fase 1 del piano 'archivio venduti moda', 14/11).

Stessa connessione e stesse regole di `bot/db.py`: scrivere non solleva mai, niente segreti. Una riga per venduto,
chiave unica (fonte, id_fonte): rimettere lo stesso venduto non lo duplica.
"""
import time
import traceback

from bot import db
from bot.logger import log
# ---- fine import ----

_SCHEMA = """
CREATE TABLE IF NOT EXISTS venduti (
    fonte TEXT NOT NULL, id_fonte TEXT NOT NULL, url TEXT, brand TEXT NOT NULL, categoria TEXT NOT NULL,
    tipo TEXT, modello TEXT, condizione TEXT, materiale TEXT, prezzo REAL NOT NULL, valuta TEXT NOT NULL,
    prezzo_eur REAL NOT NULL, paese TEXT, data_vendita TEXT, data_osservazione TEXT, certezza TEXT NOT NULL,
    titolo TEXT, nuovo INTEGER NOT NULL DEFAULT 0, inserito REAL NOT NULL,
    PRIMARY KEY (fonte, id_fonte));
CREATE INDEX IF NOT EXISTS venduti_cella ON venduti (brand, categoria);
"""
_COLONNE = ("fonte", "id_fonte", "url", "brand", "categoria", "tipo", "modello", "condizione", "materiale", "prezzo",
            "valuta", "prezzo_eur", "paese", "data_vendita", "data_osservazione", "certezza", "titolo", "nuovo")
_pronto = set()


def _assicura_schema():
    """Crea la tabella nel database corrente (una volta per file; i test cambiano DB_FILE)."""
    with db._lock:
        c = db._connessione()
        if db.DB_FILE not in _pronto:
            c.executescript(_SCHEMA)
            c.commit()
            _pronto.add(db.DB_FILE)
        return c


def inserisci(righe):
    """Inserisce le righe di `venduti_norma.riga_normalizzata` ignorando i doppioni. Ritorna quante sono nuove
    (0 se errore: non solleva mai)."""
    righe = [r for r in (righe or []) if r]
    if not righe:
        return 0
    try:
        c = _assicura_schema()
        with db._lock:
            prima = c.total_changes
            c.executemany(
                f"INSERT OR IGNORE INTO venduti ({', '.join(_COLONNE)}, inserito) "
                f"VALUES ({', '.join('?' for _ in _COLONNE)}, ?)",
                [tuple(int(bool(r.get(k))) if k == "nuovo" else r.get(k) for k in _COLONNE) + (time.time(),)
                 for r in righe])
            c.commit()
            return c.total_changes - prima
    except Exception:
        log.warning("VENDUTI DB: inserimento fallito:\n%s", traceback.format_exc())
        return 0


def leggi(fonte=None, brand=None, categoria=None, solo_usato=True, limite=500000):
    """Righe come dizionari. `solo_usato` toglie i pezzi nuovi (gonfiano la mediana)."""
    try:
        _assicura_schema()
    except Exception:
        log.warning("VENDUTI DB: schema non creato:\n%s", traceback.format_exc())
        return []
    cond, par = [], []
    for nome, val in (("fonte", fonte), ("brand", brand), ("categoria", categoria)):
        if val:
            cond.append(f"{nome} = ?")
            par.append(val)
    if solo_usato:
        cond.append("nuovo = 0")
    sql = (f"SELECT {', '.join(_COLONNE)} FROM venduti" + (" WHERE " + " AND ".join(cond) if cond else "")
           + " LIMIT ?")
    return [dict(zip(_COLONNE, r)) for r in db._leggi(sql, tuple(par) + (limite,))]


def conta_per_fonte():
    """{fonte: righe}."""
    try:
        _assicura_schema()
    except Exception:
        return {}
    return {f: n for f, n in db._leggi("SELECT fonte, COUNT(*) FROM venduti GROUP BY fonte")}
