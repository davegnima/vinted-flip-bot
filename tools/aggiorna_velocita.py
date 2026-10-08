"""Aggiorna `bot/dati/velocita.json` (tasso di vendite veloci per brand e per semaforo) dai log del worker.

Uso:  python3 tools/aggiorna_velocita.py FILE_LOG.json [FILE_LOG2.json ...] [--out bot/dati/velocita.json] [--decadimento 0.97]
I file sono i risultati di Railway get-logs (JSON con la lista `deploy`) con le righe PREAVVISO, ESITO e RICONTROLLO LAMPO
(stato=venduto o offset=3600s) o, dal 8/10, le righe TRACCIATO. Un annuncio conta una volta sola: quando ha il semaforo e
l'esito finale (venduto entro 15 min = veloce; ancora invenduto a 1 h o venduto dopo 15 min = non veloce; sparito o senza
risposta = non conta). I conteggi gia' presenti nel file si moltiplicano per il fattore di decadimento (i dati vecchi
pesano meno) e si aggiungono solo gli annunci piu' recenti di `fino_ts`. Stampa un riepilogo."""
import argparse
import collections
import json
import os
import re
import sys

os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_SESSION_STRING", "")
os.environ.setdefault("TELEGRAM_API_HASH", "x")
os.environ.setdefault("TELEGRAM_GROUP_ID", "-100")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1:x")
os.environ.setdefault("TELEGRAM_OWNER_CHAT_ID", "1")
os.environ.setdefault("GEMINI_API_KEY", "k")
os.environ.setdefault("DB_FILE", "/tmp/aggiorna_velocita.sqlite3")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.fair_value import _brand_fair_value  # noqa: E402

VELOCI = ("AFFARE", "MEDIO AFFARE")


def _kv(riga):
    return dict(re.findall(r"\| (\w+)=([^|]*?)(?= \||$)", riga))


def leggi_righe(percorsi):
    viste, righe = set(), []
    for p in percorsi:
        with open(p, encoding="utf-8") as f:
            for e in json.load(f)["deploy"]:
                k = (e["timestamp"], e["message"])
                if k not in viste:
                    viste.add(k)
                    righe.append(k)
    return sorted(righe)


def costruisci_annunci(righe):
    """{item: {brand, semaforo, ts, classe}} per gli annunci con semaforo ed esito finale chiaro."""
    titoli, prev, esiti = {}, {}, {}
    for ts, m in righe:
        if "| TRACCIATO |" in m:
            d = _kv(m)
            if d.get("classe") not in (None, "-") and d.get("sem_base", "-") != "-":
                prev[d["item"]] = {"ts": ts, "brand": d.get("brand_n") or d.get("brand", ""), "sem": d["sem_base"]}
                esiti[d["item"]] = d["classe"]
        elif "| ESITO |" in m:
            d = _kv(m)
            t = re.search(r"titolo='([^']*)'", m)
            titoli[d.get("item")] = t.group(1) if t else ""
        elif "PREAVVISO | item" in m:
            d = _kv(m)
            b = re.search(r"brand='([^']*)'", m)
            sem = d.get("sem_base") if d.get("sem_base") not in (None, "-") else d.get("semaforo")
            if sem in ("🟢", "🟡", "🔴"):
                prev.setdefault(d["item"], {"ts": ts, "brand": d.get("brand_n") if d.get("brand_n") not in (None, "-") else (b.group(1) if b else ""), "sem": sem})
        elif "RICONTROLLO LAMPO" in m and ("stato=venduto" in m or "offset=3600s" in m):
            d = _kv(m)
            if d.get("esito", "").startswith("RADAR"):
                continue
            if d.get("stato") == "venduto" or (d.get("stato") in ("attivo", "prenotato") and d.get("classe") == "NON AFFARE"):
                esiti.setdefault(d["item"], d["classe"])
    out = {}
    for item, p in prev.items():
        if item in esiti:
            marca = _brand_fair_value({"brand": p["brand"], "title": titoli.get(item, "")}) or p["brand"].lower()
            out[item] = {"brand": marca, "sem": p["sem"], "ts": p["ts"], "classe": esiti[item]}
    return out


def aggiorna(tabella, annunci, decadimento, ultimo_ts):
    fino = tabella.get("fino_ts") or ""
    nuovi = {i: a for i, a in annunci.items() if a["ts"] > fino and a["ts"] <= ultimo_ts}
    for sezione in ("brand", "semaforo"):
        for k, v in tabella.get(sezione, {}).items():
            v["n"] = round(v["n"] * decadimento, 2)
            v["veloci"] = round(v["veloci"] * decadimento, 2)
    tabella.setdefault("brand", {})
    tabella.setdefault("semaforo", {})
    for a in nuovi.values():
        v = a["classe"] in VELOCI
        for sezione, chiave in (("brand", a["brand"]), ("semaforo", a["sem"])):
            c = tabella[sezione].setdefault(chiave, {"n": 0, "veloci": 0})
            c["n"] = round(c["n"] + 1, 2)
            c["veloci"] = round(c["veloci"] + (1 if v else 0), 2)
    n = sum(c["n"] for c in tabella["semaforo"].values())
    f = sum(c["veloci"] for c in tabella["semaforo"].values())
    tabella["base"] = round(f / n, 4) if n else 0.25
    if nuovi:
        tabella["fino_ts"] = max(a["ts"] for a in nuovi.values())
    return len(nuovi)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="+")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot", "dati", "velocita.json"))
    ap.add_argument("--decadimento", type=float, default=1.0)
    a = ap.parse_args()
    righe = leggi_righe(a.log)
    annunci = costruisci_annunci(righe)
    try:
        with open(a.out, encoding="utf-8") as f:
            tabella = json.load(f)
    except Exception:
        tabella = {}
    ultimo = righe[-1][0]
    # esito finale noto solo dopo 1 h: si contano gli annunci di almeno 70 minuti prima dell'ultima riga
    import datetime
    limite = (datetime.datetime.fromisoformat(ultimo[:19]) - datetime.timedelta(minutes=70)).isoformat()
    n = aggiorna(tabella, annunci, a.decadimento, limite + "Z")
    tabella["aggiornato"] = ultimo
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(tabella, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"annunci aggiunti: {n}  base veloci: {tabella['base']:.1%}")
    for k, v in sorted(tabella["semaforo"].items()):
        print(f"  {k} n={v['n']:.0f} veloci={v['veloci']:.0f} ({v['veloci'] / v['n']:.0%})" if v["n"] else k)
    top = sorted(tabella["brand"].items(), key=lambda x: -x[1]["n"])[:15]
    for k, v in top:
        print(f"  {k:22s} n={v['n']:.0f} veloci={v['veloci']:.0f} ({v['veloci'] / v['n']:.0%})")


if __name__ == "__main__":
    main()
