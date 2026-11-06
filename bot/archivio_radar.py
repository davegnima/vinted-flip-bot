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


def velocita_per_semaforo(eventi_tracciati, dal_ts=0.0):
    """{semaforo: {validi, venduti, mediana_s}} sugli esiti chiusi: venduti = etichetta 'venduto' entro 1 h. Il tempo e' quello del
    controllo che l'ha visto (60/300/900/3600 s dall'arrivo del bot, non dalla pubblicazione). Pura."""
    r = {}
    for ev in eventi_tracciati:
        if ev.get("ts", 0) < dal_ts or not con_esito_valido(ev):
            continue
        d = r.setdefault(ev.get("semaforo") or "rosso", {"validi": 0, "venduti": 0, "tempi": []})
        d["validi"] += 1
        if ev.get("stato") == "venduto" and _venduto_entro(ev):
            d["venduti"] += 1
            d["tempi"].append(ev["venduto_s"])
    out = {}
    for k, d in r.items():
        t = sorted(d["tempi"])
        out[k] = {"validi": d["validi"], "venduti": d["venduti"], "mediana_s": t[len(t) // 2] if t else None}
    return out


def report_giornaliero(eventi_v2, eventi_tracciati, ore=24, adesso=None, min_potatura=12):
    """Report per ricerca sulle ultime `ore`. Ritorna (righe, candidati, velocita): righe = dict per ricerca (nome, tot, verdi, gialli,
    motivo, motivo_n, gv, gv_venduti); candidati = ricerche con >= min_potatura verdetti e 0 gialli/verdi; velocita = velocita_per_semaforo.
    Pura: lavora su eventi `radar_v2` e `tracciato_radar` gia' letti dal DB."""
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
        top = max(d["motivi"].items(), key=lambda kv: kv[1]) if d["motivi"] else ("", 0)
        e = esiti.get(nome, {})
        righe.append({"nome": nome, "tot": tot, "verdi": d["verde"], "gialli": d["giallo"], "motivo": top[0], "motivo_n": top[1],
                      "gv": e.get("gialli_verdi", 0), "gv_venduti": e.get("gialli_verdi_venduti", 0)})
        if tot >= min_potatura and d["giallo"] + d["verde"] == 0:
            candidati.append(nome)
    return righe, candidati, velocita_per_semaforo(eventi_tracciati, dal)


def _tempo(s):
    if s is None:
        return "-"
    return f"{int(s // 60)}m" if s < 3600 else f"{s / 3600:.1f}h"


def testo_report(righe, candidati, velocita, ore=24, max_righe=22):
    """Testo Telegram in blocco monospace (tabella allineata, Markdown ```): una riga per ricerca, poi la velocita' di vendita."""
    def pct(d):
        return f"{100 * d['venduti'] // d['validi']}%" if d and d["validi"] else "-"
    t = [f"Radar ultime {ore} h", "```", f"{'ricerca':<15}{'tot':>4}{'V':>3}{'G':>3} {'venduti':>7}  scarto"]
    for r in righe[:max_righe]:
        vend = f"{r['gv_venduti']}/{r['gv']}" if r["gv"] else "-"
        t.append(f"{r['nome'][:14]:<15}{r['tot']:>4}{r['verdi']:>3}{r['gialli']:>3} {vend:>7}  {r['motivo'][:15]}")
    if len(righe) > max_righe:
        t.append(f"... altre {len(righe) - max_righe} ricerche")
    t.append("```")
    t.append("V verdi, G gialli. 'venduti' = gialli/verdi venduti entro 1 h su quelli con esito chiuso.")
    if velocita:
        t.append("Velocita' di vendita (esiti chiusi, entro 1 h):")
        for sem in ("verde", "giallo", "rosso"):
            d = velocita.get(sem)
            if d:
                t.append(f"- {sem}: {d['venduti']}/{d['validi']} venduti ({pct(d)}), mediana {_tempo(d['mediana_s'])}")
    if candidati:
        t.append("Da potare (0 gialli/verdi): " + ", ".join(candidati))
    return "\n".join(t)
