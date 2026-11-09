"""Analisi dei log del worker con poca spesa di token: legge i file una volta sola in un database locale e stampa un riepilogo fisso.

Uso:
  python3 tools/log_dati.py carica FILE_LOG.json [FILE2.json ...] [--db /tmp/oracle_log.sqlite]   # aggiunge righe nuove (doppioni ignorati)
  python3 tools/log_dati.py riepilogo [--db ...] [--dal 2026-11-05T06:00]                          # numeri fissi del recap
  python3 tools/log_dati.py sql "SELECT ..." [--db ...]                                           # domanda libera (solo SELECT)

I file sono i risultati di Railway get-logs (JSON con la lista `deploy`). Chiedere sempre i log con un filtro largo (es. "TRACCIATO" OR
"MODA JEV" OR "GEMINI_USO" OR "Gemini TIMEOUT") e `limit` 500: oltre ~80.000 caratteri Railway li salva in un file invece di restituirli
nella conversazione, e basta passare il percorso a `carica`. Il database non e' nel repo. Tabelle: tracciato (una riga per annuncio, campi
della riga TRACCIATO), gemini_uso, gemini_timeout, jev (righe MODA JEV)."""
import argparse
import json
import re
import sqlite3
import statistics
import sys

VELOCI = ("AFFARE", "MEDIO AFFARE")   # prenotato nella prima ora conta come veloce (domanda alta), come in aggiorna_velocita.py
_KV = re.compile(r"\| (\w+)=([^|]*?)(?= \||$)")
_USO = re.compile(r"GEMINI_USO \| (\w+) \| ([\w.\-]+) \| (\d+)ms \| tentativo (\d+)")
CAMPI_TRACC = ("item", "brand", "brand_n", "prezzo", "esito", "sem", "sem_base", "lift", "fv", "conf", "categoria", "preavviso",
               "stato", "classe", "venduto_s", "controlli", "incompleto", "storia", "motivo", "legit", "legit_jev", "margine", "roi")


def apri(db):
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS tracciato (item TEXT PRIMARY KEY, ts TEXT, brand_n TEXT, sem TEXT, esito TEXT, motivo TEXT, stato TEXT,
        classe TEXT, venduto_s TEXT, storia TEXT, cieco INTEGER, veloce INTEGER, prezzo REAL, categoria TEXT, preavviso TEXT, dati TEXT);
    CREATE TABLE IF NOT EXISTS gemini_uso (ts TEXT, ruolo TEXT, modello TEXT, ms INTEGER, tentativo INTEGER, UNIQUE(ts, ruolo, modello, ms));
    CREATE TABLE IF NOT EXISTS gemini_timeout (ts TEXT, testo TEXT, UNIQUE(ts, testo));
    CREATE TABLE IF NOT EXISTS jev (ts TEXT, brand TEXT, esito TEXT, motivo TEXT, prezzo REAL, UNIQUE(ts, brand, prezzo, motivo));
    """)
    return c


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def carica(db, percorsi):
    c = apri(db)
    n = {"tracciato": 0, "gemini_uso": 0, "gemini_timeout": 0, "jev": 0}
    for p in percorsi:
        with open(p, encoding="utf-8") as f:
            righe = json.load(f)["deploy"]
        for e in righe:
            ts, m = e["timestamp"], e["message"]
            if "| TRACCIATO |" in m:
                d = dict(_KV.findall(m))
                if not d.get("item"):
                    continue
                storia = d.get("storia", "")
                cieco = int(not any(x.split(":")[-1] in ("attivo", "venduto", "prenotato") for x in storia.split(",") if x))
                veloce = int(d.get("classe") in VELOCI or d.get("stato") == "prenotato")
                brand_n = (d.get("brand_n") or d.get("brand") or "").strip("'\" ").lower().replace("-", " ")
                cur = c.execute("INSERT OR IGNORE INTO tracciato VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (d["item"], ts, brand_n, d.get("sem"), d.get("esito"), d.get("motivo", ""), d.get("stato"), d.get("classe"),
                                 d.get("venduto_s"), storia, cieco, veloce, _num(d.get("prezzo")), d.get("categoria"), d.get("preavviso"),
                                 json.dumps({k: d[k] for k in CAMPI_TRACC if k in d}, ensure_ascii=False)))
                n["tracciato"] += cur.rowcount
            elif "GEMINI_USO |" in m:
                g = _USO.search(m)
                if g:
                    cur = c.execute("INSERT OR IGNORE INTO gemini_uso VALUES (?,?,?,?,?)", (ts, g[1], g[2], int(g[3]), int(g[4])))
                    n["gemini_uso"] += cur.rowcount
            elif "Gemini TIMEOUT" in m:
                cur = c.execute("INSERT OR IGNORE INTO gemini_timeout VALUES (?,?)", (ts, m[:200]))
                n["gemini_timeout"] += cur.rowcount
            elif "| MODA JEV |" in m:
                d = dict(_KV.findall(m))
                cur = c.execute("INSERT OR IGNORE INTO jev VALUES (?,?,?,?,?)", (ts, d.get("brand"), d.get("esito"), d.get("motivo"), _num(d.get("prezzo"))))
                n["jev"] += cur.rowcount
    c.commit()
    return n


def _pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def riepilogo(db, dal=None):
    c = apri(db)
    w, a = (" WHERE ts >= ?", (dal,)) if dal else ("", ())
    wa = (w + " AND" if w else " WHERE")
    tot, ciechi = c.execute(f"SELECT COUNT(*), COALESCE(SUM(cieco),0) FROM tracciato{w}", a).fetchone()
    lo, hi = c.execute(f"SELECT MIN(ts), MAX(ts) FROM tracciato{w}", a).fetchone()
    print(f"TRACCIATO: {tot} annunci ({lo and lo[:16]} -> {hi and hi[:16]} UTC); ciechi (nessun controllo leggibile) {ciechi} = {_pct(ciechi, tot)}")
    print("\nVELOCI per semaforo (solo annunci con almeno un controllo valido)")
    for sem, n, v in c.execute(f"SELECT sem, COUNT(*), SUM(veloce) FROM tracciato{wa} cieco=0 GROUP BY sem ORDER BY sem", a):
        print(f"  {sem or '-':3} n={n:4} veloci={v:3} ({_pct(v, n)})")
    print("\nVELOCI per esito e motivo Jev (indice di sostituibilita': se confermati e scartati hanno la stessa % di veloci, Jev non discrimina la velocita')")
    righe = c.execute(f"""SELECT CASE WHEN esito='SOLO_SEMAFORO' THEN 'jev: confermato'
        WHEN motivo LIKE 'jev:%' THEN 'jev: scartato ' || substr(motivo, 1, 20) WHEN esito='SKIP_ROSSO' THEN 'SKIP_ROSSO'
        ELSE esito || ' (' || COALESCE(sem,'-') || ')' END AS g, COUNT(*), SUM(veloce) FROM tracciato{wa} cieco=0 GROUP BY g ORDER BY 2 DESC""", a).fetchall()
    for g, n, v in righe:
        print(f"  {g:44} n={n:4} veloci={v:3} ({_pct(v, n)})")
    conf = c.execute(f"SELECT COUNT(*), SUM(veloce) FROM tracciato{wa} cieco=0 AND esito='SOLO_SEMAFORO'", a).fetchone()
    scar = c.execute(f"SELECT COUNT(*), SUM(veloce) FROM tracciato{wa} cieco=0 AND motivo LIKE 'jev:%'", a).fetchone()
    if conf[0] and scar[0]:
        print(f"  => Jev confermati {_pct(conf[1], conf[0])} veloci, scartati {_pct(scar[1], scar[0])}: differenza {100 * (conf[1] / conf[0] - scar[1] / scar[0]):+.0f} punti")
    print("\nJEV (righe MODA JEV: esito)")
    for esito, n in c.execute(f"SELECT esito, COUNT(*) FROM jev{w} GROUP BY esito ORDER BY 2 DESC", a):
        print(f"  {esito:16} {n}")
    print("\nGEMINI per ruolo/modello (ms): n, p50, p90, tentativi>1")
    gruppi = {}
    for ruolo, mod, ms, t in c.execute(f"SELECT ruolo, modello, ms, tentativo FROM gemini_uso{w}", a):
        gruppi.setdefault((ruolo, mod), []).append((ms, t))
    for (ruolo, mod), v in sorted(gruppi.items()):
        ms = sorted(x[0] for x in v)
        p90 = ms[min(len(ms) - 1, int(len(ms) * 0.9))]
        print(f"  {ruolo:8} {mod:28} n={len(ms):4} p50={int(statistics.median(ms))} p90={p90} ritentati={sum(1 for x in v if x[1] > 1)}")
    print(f"  Gemini TIMEOUT: {c.execute(f'SELECT COUNT(*) FROM gemini_timeout{w}', a).fetchone()[0]}")


def sql(db, query):
    if not re.match(r"\s*select\b", query, re.I):
        sys.exit("solo SELECT")
    c = apri(db)
    cur = c.execute(query)
    print(" | ".join(d[0] for d in cur.description))
    for r in cur.fetchmany(200):
        print(" | ".join("" if x is None else str(x) for x in r))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["carica", "riepilogo", "sql"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--db", default="/tmp/oracle_log.sqlite")
    ap.add_argument("--dal", default=None)
    o = ap.parse_args()
    if o.comando == "carica":
        print("righe nuove:", carica(o.db, o.args))
    elif o.comando == "riepilogo":
        riepilogo(o.db, o.dal)
    else:
        sql(o.db, " ".join(o.args))


if __name__ == "__main__":
    main()
