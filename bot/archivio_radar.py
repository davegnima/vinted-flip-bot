"""Archivio degli esiti del radar: lettura dal DB (volume /data), niente richieste ai log. Funzioni pure sugli eventi `tracciato_radar`."""
import csv
import io
import time

COLONNE = ("ts", "item_id", "ricerca", "brand", "prezzo", "semaforo", "motivo", "rivendita", "margine", "roi", "n_comp",
           "jev", "jev_motivo", "stato", "classe", "venduto_s", "prenotato_s", "controlli", "incompleto")


def _venduto_entro(ev, secondi=3600):
    v = ev.get("venduto_s")
    return isinstance(v, (int, float)) and v <= secondi


def _storia(ev):
    s = ev.get("storia")
    return s if isinstance(s, list) else []


def con_esito_valido(ev):
    """Serie arrivata in fondo (non incompleta) e con almeno un controllo."""
    return str(ev.get("incompleto")) != "si" and len(_storia(ev)) > 0


def righe_csv(eventi):
    """CSV (testo) di tutti gli eventi, una riga per annuncio, colonne fisse."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLONNE)
    for ev in eventi:
        w.writerow([ev.get(c, "") for c in COLONNE])
    return out.getvalue()


def riepilogo_per_ricerca(eventi, dal_ts=0.0):
    """{ricerca: {n, validi, venduti_1h, gialli_verdi, gialli_verdi_venduti}} sugli eventi con ts >= dal_ts."""
    r = {}
    for ev in eventi:
        if ev.get("ts", 0) < dal_ts:
            continue
        d = r.setdefault(ev.get("ricerca") or "-", {"n": 0, "validi": 0, "venduti_1h": 0, "gialli_verdi": 0, "gialli_verdi_venduti": 0})
        d["n"] += 1
        if not con_esito_valido(ev):
            continue
        d["validi"] += 1
        vend = _venduto_entro(ev) and ev.get("stato") == "venduto"
        d["venduti_1h"] += int(vend)
        if ev.get("semaforo") in ("verde", "giallo"):
            d["gialli_verdi"] += 1
            d["gialli_verdi_venduti"] += int(vend)
    return r


def righe_riepilogo(eventi, giorni=7, adesso=None):
    dal = (adesso or time.time()) - giorni * 86400
    r = riepilogo_per_ricerca(eventi, dal)
    return [f"RIEPILOGO RICERCHE ({giorni} g) | {k} | annunci={d['n']} | validi={d['validi']} | venduti_1h={d['venduti_1h']} | gialli_verdi={d['gialli_verdi']} | gv_venduti={d['gialli_verdi_venduti']}"
            for k, d in sorted(r.items(), key=lambda kv: -kv[1]["n"])]
