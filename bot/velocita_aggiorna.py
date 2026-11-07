"""Aggiornamento della tabella di velocita' (`bot/velocita.py`) dalle vendite tracciate: logica condivisa dallo strumento
`tools/aggiorna_velocita.py` (da file di log) e dal worker (dall'archivio `tracciato` nel DB sul volume /data, 7/11, richiesta
dell'utente: aggiornare con TUTTI i dati senza leggere i log nella conversazione). Pura tranne `aggiorna_da_db`."""
import datetime
import json
import os
import time

VELOCI = ("AFFARE", "MEDIO AFFARE", "PRENOTATO")   # prenotato nella prima ora = domanda alta
# Scarti dell'Occhio/Cervello per falso (campo `motivo` di TRACCIATO) o `legit=probabilmente_falso`: un falso venduto
# subito non e' un affare vero (17/10: Prada a 10 EUR falso, venduto in fretta). Pesa meno nel credito di velocita'.
MOTIVI_FALSO = ("[FALSO CONCLAMATO", "[ANNUNCIO FRAUDOLENTO", "[BRAND NON CORRISPONDENTE", "[TESSUTO NON E' IL BRAND", "[NON ORIGINALE",
                "jev:gemini:replica", "jev:foto:")   # 6/11: scarti Jev/Gemini per replica (17 veloci su 66 scarti: in gran parte falsi venduti in fretta)
PESO_FALSO = 0.25   # stima dichiarata, non misurata: regolabile con --peso-falso


def e_falso(d):
    """True se Occhio o Cervello hanno segnato l'annuncio come falso (riga TRACCIATO gia' in campi)."""
    return d.get("legit") == "probabilmente_falso" or d.get("motivo", "").startswith(MOTIVI_FALSO)
_RANGO = {"NON AFFARE": 0, "PRENOTATO": 1, "NORMALE": 2, "MEDIO AFFARE": 3, "AFFARE": 3}



# Eventi `tracciato` del DB -> {item: {brand, sem, ts, classe, falso, esito}} (stessa forma di costruisci_annunci dello strumento).
def annunci_da_eventi(eventi):
    from bot.fair_value import _brand_fair_value
    out = {}
    for e in eventi:
        classe = e.get("classe")
        if not classe or classe == "-":
            storia = e.get("storia") or []
            from bot.tracciamento import _tracc_esito_finale
            classe = _tracc_esito_finale([tuple(x) for x in storia])[1] if storia else None
        sem = e.get("sem_base")
        if not classe or classe == "-" or sem not in ("🟢", "🟡", "🔴"):
            continue
        brand = e.get("brand_n") or str(e.get("brand") or "").strip("'")
        marca = _brand_fair_value({"brand": brand, "title": e.get("tit") or ""}) or brand.lower()
        ts = datetime.datetime.fromtimestamp(e["ts"], datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out[str(e.get("item_id"))] = {"brand": marca, "sem": sem, "ts": ts, "classe": classe, "falso": e_falso(e),
                                      "esito": e.get("esito", "")}
    return out


def aggiorna(tabella, annunci, decadimento, ultimo_ts, peso_falso=PESO_FALSO):
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
        credito = (peso_falso if a.get("falso") else 1) if v else 0   # veloce ma falso per Occhio/Cervello: credito ridotto
        for sezione, chiave in (("brand", a["brand"]), ("semaforo", a["sem"])):
            c = tabella[sezione].setdefault(chiave, {"n": 0, "veloci": 0})
            c["n"] = round(c["n"] + 1, 2)
            c["veloci"] = round(c["veloci"] + credito, 2)
    n = sum(c["n"] for c in tabella["semaforo"].values())
    f = sum(c["veloci"] for c in tabella["semaforo"].values())
    tabella["base"] = round(f / n, 4) if n else 0.25
    if nuovi:
        tabella["fino_ts"] = max(a["ts"] for a in nuovi.values())
    return len(nuovi)



def aggiorna_da_db(percorso, decadimento=0.97, adesso=None, peso_falso=PESO_FALSO):
    """Legge gli eventi `tracciato` dal DB, aggiorna il file `percorso` (se manca parte dalla tabella del repo) e ritorna
    (annunci aggiunti, tabella). L'esito finale e' noto solo dopo 1 h: si contano gli annunci chiusi 70 minuti prima di adesso."""
    from bot import db, velocita
    adesso = adesso or time.time()
    try:
        with open(percorso, encoding="utf-8") as f:
            tabella = json.load(f)
    except Exception:
        try:
            with open(velocita.VELOCITA_FILE, encoding="utf-8") as f:
                tabella = json.load(f)
        except Exception:
            tabella = {}
    fino = tabella.get("fino_ts") or "1970-01-01T00:00:00Z"
    dal = datetime.datetime.fromisoformat(fino.replace("Z", "+00:00")).timestamp()
    annunci = annunci_da_eventi(db.leggi_eventi("tracciato", dal))
    limite = datetime.datetime.fromtimestamp(adesso - 70 * 60, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = aggiorna(tabella, annunci, decadimento, limite, peso_falso)
    tabella["aggiornato"] = datetime.datetime.fromtimestamp(adesso, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(percorso) or ".", exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(tabella, f, ensure_ascii=False, indent=1, sort_keys=True)
    velocita.ricarica(percorso)
    return n, tabella
