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


def _motivo_base(m):
    """Motivo senza dettaglio ('parola_vietata:xyz' -> 'parola_vietata')."""
    return str(m or "-").split(":")[0].split("(")[0]


def report_giornaliero(eventi_v2, eventi_tracciati, ore=24, adesso=None, min_potatura=12):
    """Report per ricerca sulle ultime `ore`: verdetti (rosso/giallo/verde), motivo di scarto piu' frequente, gialli/verdi
    venduti entro 1 h (dagli esiti chiusi) e candidati alla potatura (>= min_potatura verdetti e 0 gialli/verdi). Pura:
    lavora su eventi `radar_v2` e `tracciato_radar` gia' letti dal DB. Ritorna (righe, candidati)."""
    dal = (adesso or time.time()) - ore * 3600
    r = {}
    for ev in eventi_v2:
        if ev.get("ts", 0) < dal or ev.get("rivalutata"):
            continue
        d = r.setdefault(ev.get("ricerca") or "-", {"rosso": 0, "giallo": 0, "verde": 0, "motivi": {}})
        sem = ev.get("semaforo") or "rosso"
        d[sem if sem in ("rosso", "giallo", "verde") else "rosso"] += 1
        if sem not in ("giallo", "verde"):
            m = _motivo_base(ev.get("motivo"))
            d["motivi"][m] = d["motivi"].get(m, 0) + 1
    esiti = riepilogo_per_ricerca(eventi_tracciati, dal)
    righe, candidati = [], []
    for nome, d in sorted(r.items(), key=lambda kv: -(kv[1]["rosso"] + kv[1]["giallo"] + kv[1]["verde"])):
        tot = d["rosso"] + d["giallo"] + d["verde"]
        top = max(d["motivi"].items(), key=lambda kv: kv[1]) if d["motivi"] else None
        e = esiti.get(nome, {})
        righe.append(f"{nome}: {tot} verdetti, {d['verde']} verdi, {d['giallo']} gialli"
                     + (f", scarto piu' frequente {top[0]} ({top[1]})" if top else "")
                     + (f", gv venduti 1h {e.get('gialli_verdi_venduti', 0)}/{e.get('gialli_verdi', 0)}" if e.get("gialli_verdi") else ""))
        if tot >= min_potatura and d["giallo"] + d["verde"] == 0:
            candidati.append(nome)
    return righe, candidati


def testo_report(righe, candidati, ore=24, max_righe=25):
    """Testo Telegram (senza Markdown) del report giornaliero."""
    t = [f"Report radar ultime {ore} h ({len(righe)} ricerche con verdetti)"]
    t += righe[:max_righe]
    if len(righe) > max_righe:
        t.append(f"... e altre {len(righe) - max_righe}")
    if candidati:
        t.append("Candidate alla potatura (0 gialli/verdi): " + ", ".join(candidati))
    return "\n".join(t)
