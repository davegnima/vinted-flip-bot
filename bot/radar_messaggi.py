"""Testi dei messaggi del radar (spostati da bot/radar.py senza cambiare la logica): motivi leggibili, pallino del semaforo, riga del costo,
escape Markdown, didascalia della foto (spezza/compatta), motivo di un annuncio saltato. Solo funzioni pure che non leggono configurazione
modificabile dai test.
Restano in radar.py testo_avviso_v2, testo_risposta_gruppo e _righe_v2: leggono RADAR_VERIFICA, RADAR_SEMAFORI e RADAR_GEMINI di radar.py
(i test li cambiano con monkeypatch su bot.radar.X, che non avrebbe piu' effetto se le funzioni stessero qui)."""

import re


SEMAFORO_EMOJI = {"verde": "🟢", "giallo": "🟡", "rosso": "🔴"}


_MOTIVI_LEGGIBILI = {
    "parola_vietata": "parola vietata nel titolo (rotto, replica, solo scatola...)",
    "pezzo_o_accessorio": "accessorio o ricambio, non l'oggetto intero",
    "titolo_generico": "titolo troppo generico",
    "prezzo_segnaposto": "prezzo segnaposto",
    "sopra_riferimento": "prezzo sopra il limite di acquisto della ricerca",
    "comparabili_non_disponibili": "comparabili non disponibili",
    "pochi_comparabili": "pochi comparabili",
    "margine_basso": "margine troppo basso",
    "roi_basso": "ROI troppo basso",
    "quasi_roi": "ROI poco sotto 100%, margine e Jev reggono",
}


def _motivo_leggibile(motivo):
    chiave = (motivo or "").split(":")[0]
    return _MOTIVI_LEGGIBILI.get(chiave, motivo or "motivo non noto")


def pallino_semaforo(v2, predefinito="🔎"):
    """Pallino del semaforo v2 per l'intestazione del messaggio (richiesta dell'utente, 31/10). Pura."""
    return SEMAFORO_EMOJI.get((v2 or {}).get("semaforo"), predefinito)


def _righe_link_comps(v2):
    """Link dei comparabili che reggono la stima (gialli e verdi), per controllarli a occhio. Vuote se non ci sono. Pura."""
    link = (v2 or {}).get("link_comps") or []
    if not link:
        return []
    return ["Comparabili da controllare:"] + [f"• {p:g} € {u}" for _t, p, u in link]


_STATO_SPEDIZIONE = {"VERIFIED": "verificata", "ESTIMATED": "stimata", "UNKNOWN": "sconosciuta, base"}


def _riga_costo_totale(v2):
    """'Costo totale: prezzo + spedizione (stato) + protezione = totale' (01/11). Vuota se il v2 non ha il costo. Pura."""
    tot, sped = v2.get("costo_totale"), v2.get("spedizione_eur")
    if tot is None or sped is None:
        return ""
    stato = _STATO_SPEDIZIONE.get(v2.get("spedizione_stato"), "n.d.")
    paese = f" da {v2['paese']}" if v2.get("paese") else ""
    if paese and v2.get("paese_fonte") == "jev":
        paese += " (paese stimato da Jev)"
    return f"Costo totale: {tot:.2f} € (spedizione {sped:.2f} € {stato}{paese}, protezione acquisti inclusa)"


def _md(testo):
    """Escape del Markdown di Telegram (_ * ` [) nei testi che arrivano da fuori (titolo, motivi): un trattino basso non deve rompere il messaggio. Pura."""
    return re.sub(r"([_*`\[])", r"\\\1", str(testo or ""))


def _dettaglio_comp(v2):
    """' (X trovati in tutto, ricerca allargata)' per capire dove si perdono i comparabili. Pura."""
    g = v2.get("n_grezzi")
    extra = ", ricerca allargata" if v2.get("allargata") else ""
    return f" ({g} grezzi{extra})" if g is not None else (" (ricerca allargata)" if extra else "")


def motivo_saltato_leggibile(motivo):
    """Frase italiana per il motivo con cui `radar_v2.analizza` ha saltato un annuncio (8/11, richiesta utente). Pura."""
    parti = (motivo or "").split(":")
    chiave = parti[0]
    if chiave == "fuori_famiglia":
        return "il titolo non cita nessun modello monitorato della ricerca (il margine di 50 € non e' raggiungibile)"
    if chiave == "sopra_tetto_modello":
        modello = parti[1] if len(parti) > 1 else "?"
        tetto = f" di {parti[2]} €" if len(parti) > 2 else ""
        return f"prezzo sopra il tetto{tetto} del modello {modello}: con quel prezzo il margine di 50 € non e' raggiungibile"
    if chiave == "prezzo_fuori":
        return f"prezzo {parti[1]} € fuori dalla spesa massima del radar" if len(parti) > 1 else "prezzo fuori dalla spesa massima del radar"
    return {"gia_visto": "annuncio gia' valutato in precedenza", "pausa_notturna": "radar in pausa notturna",
            "ombra_spenta": "radar v2 spento", "senza_id": "link senza numero annuncio",
            "prezzo_assente": "prezzo non letto dal messaggio"}.get(chiave, "motivo non registrato")


_RE_URL_VINTED = re.compile(r"https://www\.vinted\.[a-z.]+/items/\S+")


MAX_DIDASCALIA = 1000


def spezza_didascalia(testo, massimo=MAX_DIDASCALIA):
    """(didascalia, resto): Telegram taglia le didascalie delle foto a 1024 caratteri, e il taglio mangiava i comparabili e il link.
    Si spezza sull'ultimo a capo entro `massimo`; il resto va in un secondo messaggio. Pura."""
    if len(testo) <= massimo:
        return testo, ""
    taglio = testo.rfind("\n", 0, massimo)
    taglio = taglio if taglio > 0 else massimo
    return testo[:taglio], testo[taglio:].strip("\n")


def compatta_didascalia(testo, massimo=MAX_DIDASCALIA):
    """Fa stare l'avviso nella didascalia della foto (5/11, richiesta dell'utente: niente secondo messaggio): accorcia con '…' le righe
    di testo piu' lunghe (giudizi di Jev e Gemini, motivi) senza mai toccare i link ('•' e url), poi toglie le righe 💡 e 📊 se serve.
    Se non basta, il testo resta com'e' e lo spezza `spezza_didascalia`. Pura."""
    if len(testo) <= massimo:
        return testo
    righe = testo.split("\n")
    protetta = lambda r: r.startswith(("•", "http", "🔗", "💶", "🟢", "🟡", "🔴")) or not r
    MIN_RIGA = 90
    for _ in range(len(righe) * 3 + 5):
        totale = len("\n".join(righe))
        if totale <= massimo:
            return "\n".join(righe)
        cand = [k for k, r in enumerate(righe) if not protetta(r) and len(r) > MIN_RIGA]
        if not cand:
            break
        i = max(cand, key=lambda k: len(righe[k]))
        tenuti = max(MIN_RIGA, len(righe[i]) - (totale - massimo) - 1)
        righe[i] = righe[i][:tenuti].rstrip(" \\_*") + "…"
    for marca in ("💡", "📊", "🔁", "🔎"):       # in ordine di importanza crescente: prima cade la stima di Gemini
        if len("\n".join(righe)) <= massimo:
            break
        righe = [r for r in righe if not r.startswith(marca)]
    return "\n".join(righe)


def url_annuncio_nel_testo(testo, url=None):
    """Link dell'annuncio per il bottone: quello passato, altrimenti l'ULTIMA url Vinted del testo (le precedenti sono i comparabili). Pura."""
    if url:
        return url
    trovati = _RE_URL_VINTED.findall(testo or "")
    return trovati[-1] if trovati else None
