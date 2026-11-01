"""Giudizio di Jev (TypeSafe AI) su un annuncio del radar: Jev risponde a tre domande chiuse sui fatti dell'annuncio,
il codice (verdetto_jev) decide l'esito. Jev non decide mai da solo.

Attivo con JEV_GIUDICE=1 e la chiave in TYPESAFE_API_KEY. Chiamata bloccante: usarla con asyncio.to_thread.
Il risultato va nel messaggio Telegram e nei log. Mai decisioni automatiche: il filtro e' RADAR_SEMAFORI.
Schema da docs.typesafe.ai/introduction/quickstart (domande di tipo choice con criteria).
"""
import base64
import json
import os
import urllib.request

from bot.logger import log

JEV_GIUDICE = os.environ.get("JEV_GIUDICE", "0").strip() in ("1", "true", "si")
# Prova sulle foto (25/10): Jev vede anche la prima foto, solo per gli annunci con semaforo verde. Anteprima di TypeSafe
# (header TypeSafe-Danger-Zone-Images): i token per immagine si misurano dal log "JEV DOMANDE ... input_tokens=".
JEV_FOTO = os.environ.get("JEV_FOTO", "0").strip() in ("1", "true", "si")
# Giudizio per singolo comparabile (01/11): Jev dice, titolo per titolo, se e' lo stesso modello dell'annuncio. In ombra: la rivendita
# ricalcolata sui soli "stesso modello" si scrive nel log e nell'evento, il semaforo non cambia.
JEV_COMPS = os.environ.get("JEV_COMPS", "0").strip() in ("1", "true", "si")
# Foto dei comparabili (01/11): Jev confronta la foto dell'annuncio con 3 miniature di comparabili. Solo ombra: log ed evento, nessun effetto
# sul semaforo. Spenta di default (banda e token da misurare prima).
JEV_FOTO_COMPS = os.environ.get("JEV_FOTO_COMPS", "0").strip() in ("1", "true", "si")
MAX_FOTO_COMPS = 3
DOMANDA_FOTO_COMP = {
    "instructions": "L'oggetto di questa miniatura e' lo stesso modello dell'oggetto di foto1 (stessa linea, stessa versione)?",
    "criteria": {
        "stesso_modello": "e' chiaramente lo stesso modello",
        "diverso": "e' un altro modello, un'altra versione, un accessorio o un altro oggetto",
        "non_chiaro": "dalle foto non si capisce",
    },
}
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODELLO = "jev-latest"
HEADER_IMMAGINI = "TypeSafe-Danger-Zone-Images"
RIFERIMENTO_FOTO = "foto1"
DOMANDA_FOTO = {
    "instructions": "La foto dell'annuncio mostra l'oggetto descritto nel titolo?",
    "criteria": {
        "corrisponde": "la foto mostra l'oggetto descritto, riconoscibile",
        "non_corrisponde": "la foto mostra un altro oggetto, un ricambio, una replica o un lotto diverso dal titolo",
        "non_chiaro": "la foto non permette di dirlo",
    },
}
# Domande chiuse sui fatti dell'annuncio (25/10): ogni risposta e' un fatto, non un giudizio complessivo.
DOMANDE = {
    "tipo": {
        "instructions": "Che cosa vende l'annuncio?",
        "criteria": {
            "oggetto_principale": "l'oggetto stesso, come descritto nel titolo",
            "ricambio_accessorio": "solo una parte, un accessorio, un cavo o una custodia",
            "lotto": "piu' oggetti venduti insieme, senza un valore chiaro del singolo",
            "replica_o_dubbio": "replica, falso, o una descrizione che non fa capire cosa vende",
        },
    },
    "completo": {
        "instructions": "Il titolo o la descrizione dicono che l'oggetto e' completo o funzionante?",
        "criteria": {
            "si": "dicono completo, funzionante, in scatola o con accessori",
            "no": "dicono che manca qualcosa, che non funziona, che e' bloccato (iCloud, codice), venduto per ricambi o da riparare",
            "non_dichiarato": "non dicono nulla in proposito",
        },
    },
    "prezzo": {
        "instructions": "Il prezzo chiesto rispetto alla stima di rivendita dei simili?",
        "criteria": {
            "sotto": "chiaramente sotto la stima di rivendita",
            "in_linea": "vicino alla stima di rivendita",
            "sopra": "sopra la stima di rivendita",
        },
    },
}
# Prova in ombra (31/10): i titoli dei comparabili vanno a Jev, che dice se sono lo stesso modello dell'annuncio. La risposta
# NON entra in verdetto_jev: finisce solo nel log e nell'evento, per tarare dopo una promozione dei gialli da ricerca allargata.
DOMANDA_SIMILI = {
    "instructions": "I titoli degli annunci simili sono lo stesso modello e la stessa versione dell'annuncio?",
    "criteria": {
        "stesso_modello": "quasi tutti i simili sono lo stesso modello e la stessa versione",
        "in_parte": "alcuni simili sono lo stesso modello, altri una versione o un modello diverso",
        "diverso": "i simili sono per lo piu' un altro modello, una serie diversa o oggetti diversi",
    },
}
CRITERI_COMP = {
    "stesso_modello": "e' lo stesso modello (la versione puo' cambiare di poco, es. colore o capacita')",
    "simile": "e' della stessa famiglia ma un altro modello o un'altra generazione",
    "altro": "e' un altro oggetto, un accessorio, un ricambio o un lotto",
}
CONF_COMP_MIN = 0.6
MAX_COMPS_VERIFICA = 20
MAX_DESCRIZIONE = 600
MAX_TITOLI_SIMILI = 15
# Esiti del radar: stessa lista di prima, ora decisa dal codice.
ESITI = ("affare_vero", "non_affare", "falso_o_ricambio")
TIPI_NON_VENDIBILI = ("ricambio_accessorio", "lotto", "replica_o_dubbio")
FORMATI_FOTO = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpeg"}


def verdetto_jev(risposte):
    """Esito e confidenza dalle risposte di Jev. `risposte` = {domanda: (scelta, confidenza)}.
    Regole fisse, in ordine: se una risposta manca, nessun esito (None, None). Un oggetto che non e' l'oggetto
    principale e' falso_o_ricambio. Mancanza o prezzo sopra la stima e' non_affare. Solo oggetto principale, completo
    (o non dichiarato) e prezzo sotto la stima e' affare_vero. La confidenza e' la piu' bassa delle tre. Pura."""
    scelte = {k: risposte.get(k, (None, None))[0] for k in DOMANDE}
    if any(v is None for v in scelte.values()):
        return None, None
    confidenze = [v[1] for k, v in risposte.items() if k in DOMANDE or k == "foto"]
    confidenze = [c for c in confidenze if c is not None]
    conf = min(confidenze) if confidenze else None
    if risposte.get("foto", (None, None))[0] == "non_corrisponde":
        return "falso_o_ricambio", conf
    if scelte["tipo"] in TIPI_NON_VENDIBILI:
        return "falso_o_ricambio", conf
    if scelte["completo"] == "no" or scelte["prezzo"] == "sopra":
        return "non_affare", conf
    if scelte["prezzo"] == "sotto" and scelte["completo"] in ("si", "non_dichiarato"):
        return "affare_vero", conf
    return "non_affare", conf


ETICHETTE_ESITO = {"affare_vero": "affare", "non_affare": "non e' un affare", "falso_o_ricambio": "falso o ricambio"}
FRASI_MOTIVO = {
    "foto_diversa": "la foto non corrisponde al titolo",
    "ricambio": "e' solo un ricambio o un accessorio",
    "lotto": "e' un lotto di piu' oggetti",
    "replica_dubbio": "replica o descrizione poco chiara",
    "guasto_incompleto": "dichiarato rotto, incompleto, bloccato o per ricambi",
    "prezzo_alto": "prezzo sopra la stima di rivendita",
    "prezzo_in_linea": "prezzo in linea con la stima, nessuno sconto",
    "ok": "oggetto vero, non dichiarato guasto, prezzo sotto la stima",
}
_MOTIVO_TIPO = {"ricambio_accessorio": "ricambio", "lotto": "lotto", "replica_o_dubbio": "replica_dubbio"}


def motivo_jev(risposte):
    """(codice, frase) del perche' dell'esito, dalle stesse risposte di verdetto_jev (stesso ordine delle regole), oppure
    (None, None) se manca una risposta. Con `simili` diverso o in_parte la frase avverte che la stima poggia su altri modelli.
    Non cambia l'esito. Pura."""
    scelte = {k: risposte.get(k, (None, None))[0] for k in DOMANDE}
    if any(v is None for v in scelte.values()):
        return None, None
    if risposte.get("foto", (None, None))[0] == "non_corrisponde":
        codice = "foto_diversa"
    elif scelte["tipo"] in TIPI_NON_VENDIBILI:
        codice = _MOTIVO_TIPO[scelte["tipo"]]
    elif scelte["completo"] == "no":
        codice = "guasto_incompleto"
    elif scelte["prezzo"] == "sopra":
        codice = "prezzo_alto"
    elif scelte["prezzo"] == "sotto" and scelte["completo"] in ("si", "non_dichiarato"):
        codice = "ok"
    else:
        codice = "prezzo_in_linea"
    frase = FRASI_MOTIVO[codice]
    if risposte.get("simili", (None, None))[0] in ("diverso", "in_parte"):
        frase += ", ma i simili non sono lo stesso modello"
    return codice, frase


def comparabili_stesso_modello(comps, etichette, conf_min=CONF_COMP_MIN):
    """Coppie (titolo, prezzo) che Jev giudica 'stesso_modello' con confidenza >= conf_min. `comps` = [(titolo, prezzo)],
    `etichette` = [(scelta, confidenza)] nello stesso ordine (puo' essere piu' corta: i comparabili oltre non sono giudicati). Pura."""
    return [(t, p) for (t, p), (scelta, conf) in zip(comps, etichette or [])
            if scelta == "stesso_modello" and (conf is None or conf >= conf_min)]


def prezzi_stesso_modello(comps, etichette, conf_min=CONF_COMP_MIN):
    """Prezzi dei comparabili 'stesso_modello' (vedi comparabili_stesso_modello). Pura."""
    return [p for _t, p in comparabili_stesso_modello(comps, etichette, conf_min)]


def comparabili_simili(comps, etichette, conf_min=CONF_COMP_MIN):
    """Coppie (titolo, prezzo) che Jev giudica 'simile' (stessa famiglia, altro modello o generazione) con confidenza >= conf_min.
    Servono quando gli 'stesso_modello' sono pochi (01/11, utente: buon senso, la comparabilita' va verificata ma non serve lo stesso modello). Pura."""
    return [(t, p) for (t, p), (scelta, conf) in zip(comps, etichette or [])
            if scelta == "simile" and (conf is None or conf >= conf_min)]


def descrizione_jev(esito, conf, frase):
    """Riga per il messaggio: 'non e' un affare, dichiarato rotto... (confidenza 0,9)'. Pura."""
    testo = ETICHETTE_ESITO.get(esito, esito)
    if frase:
        testo += f", {frase}"
    return f"{testo} (confidenza {conf})"


# Fasce di confidenza (31/10): sopra SOGLIA_PASSA l'esito vale; tra le due soglie e' un caso limite da valutare a mano con i
# bottoni (taratura di soglie e domande); sotto SOGLIA_RIVEDERE e' scartato. Ipotesi iniziali, da tarare sui dati.
SOGLIA_PASSA = 0.85
SOGLIA_RIVEDERE = 0.70


def fascia(confidenza):
    """'passa', 'da_rivedere' o 'scartato' dalla confidenza di Jev (None = scartato). Pura."""
    if confidenza is None or confidenza < SOGLIA_RIVEDERE:
        return "scartato"
    return "passa" if confidenza >= SOGLIA_PASSA else "da_rivedere"


def _formato_foto(foto):
    """'png' o 'jpeg' dai primi byte del file, None se non e' una foto utilizzabile. Pura."""
    for firma, formato in FORMATI_FOTO.items():
        if foto and foto.startswith(firma):
            return formato
    return None


def _chiama_jev(corpo):
    """Risposta JSON di Jev. Solleva eccezioni: il chiamante decide il fallback."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    intestazioni = {"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"}
    if "assets" in corpo:
        intestazioni[HEADER_IMMAGINI] = "true"
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST", headers=intestazioni)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def giudica(titolo, prezzo, prezzi_simili, rivendita, foto=None):
    """(esito, confidenza) oppure (None, None). Versione senza descrizione ne' titoli dei simili: vedi giudica_completo."""
    return giudica_completo(titolo, prezzo, prezzi_simili, rivendita, foto)[:2]


def giudica_completo(titolo, prezzo, prezzi_simili, rivendita, foto=None, descrizione=None, titoli_simili=None):
    """(esito, confidenza, simili, motivo) oppure quattro None se Jev non e' attivo o non risponde. Bloccante.
    Con `foto` (bytes) e JEV_FOTO=1 Jev riceve anche la prima foto; se la richiesta con la foto fallisce, riprova solo testo.
    `descrizione` (tagliata a MAX_DESCRIZIONE caratteri) entra nello stato. Con `titoli_simili` Jev risponde anche a DOMANDA_SIMILI:
    la risposta ('stesso_modello', 'in_parte', 'diverso', confidenza) e' il terzo valore e non influisce sull'esito.
    Il quarto valore e' (codice, frase) da motivo_jev: il perche' dell'esito."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and chiave):
        return None, None, None, None
    simili = ", ".join(f"{p:g}" for p in sorted(prezzi_simili)[:20]) or "nessuno"
    formato = _formato_foto(foto) if JEV_FOTO else None
    stato = (f"Annuncio Vinted: {titolo}\nPrezzo chiesto: {prezzo} EUR\n"
             f"Prezzi chiesti di annunci simili usati: {simili}\n"
             f"Stima di rivendita (25 percentile): {rivendita} EUR")
    desc = " ".join((descrizione or "").split())[:MAX_DESCRIZIONE]
    if desc:
        stato += f"\nDescrizione del venditore: {desc}"
    titoli = [t for t in (titoli_simili or []) if t][:MAX_TITOLI_SIMILI]
    if titoli:
        stato += "\nTitoli degli annunci simili:\n" + "\n".join(f"- {t[:100]}" for t in titoli)
    domande = {k: {"type": "choice", "instructions": d["instructions"], "criteria": d["criteria"]}
               for k, d in DOMANDE.items()}
    corpo = {"model": MODELLO, "state": stato, "questions": dict(domande)}
    if titoli:
        corpo["questions"]["simili"] = {"type": "choice", **DOMANDA_SIMILI}
    if formato:
        corpo["state"] += f"\nFoto dell'annuncio: {RIFERIMENTO_FOTO}"
        corpo["assets"] = {RIFERIMENTO_FOTO: {"type": "image", "data_base64": base64.b64encode(foto).decode(),
                                              "format": formato}}
        corpo["questions"]["foto"] = {"type": "choice", **DOMANDA_FOTO}
    try:
        risposta = _chiama_jev(corpo)
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        if not formato:
            log.warning("JEV | giudizio non disponibile: %s", str(e)[:200])
            return None, None, None, None
        log.warning("JEV FOTO | richiesta con foto non riuscita, riprovo solo testo: %s", str(e)[:200])
        return giudica_completo(titolo, prezzo, prezzi_simili, rivendita, None, descrizione, titoli_simili)
    try:
        risposte = {k: (risposta["answers"][k].get("choice"), risposta["answers"][k].get("confidence"))
                    for k in domande}
    except Exception as e:  # noqa: BLE001
        log.warning("JEV | risposta non leggibile: %s", str(e)[:200])
        return None, None, None, None
    if formato:
        risposte["foto"] = (risposta["answers"]["foto"].get("choice"), risposta["answers"]["foto"].get("confidence"))
    simili_risp = None
    if titoli:
        try:
            r = risposta["answers"]["simili"]
            simili_risp = (r.get("choice"), r.get("confidence"))
        except Exception:  # noqa: BLE001 - e' solo una prova in ombra
            simili_risp = None
    token = (risposta.get("usage") or {}).get("input_tokens")
    log.info("JEV DOMANDE | titolo=%s | foto=%s | desc=%s | simili=%s | input_tokens=%s | %s", titolo[:60], formato or "no",
             len(desc), simili_risp[0] if simili_risp else "-", token,
             " | ".join(f"{k}={v[0]}({v[1]})" for k, v in risposte.items()))
    esito, conf = verdetto_jev(risposte)
    motivo = motivo_jev({**risposte, "simili": simili_risp or (None, None)})
    log.info("JEV MOTIVO | titolo=%s | esito=%s | motivo=%s", titolo[:60], esito, motivo[0])
    return esito, conf, simili_risp, motivo


JEV_PRECONTROLLO = os.environ.get("JEV_PRECONTROLLO", "1").strip() == "1"
CONF_PRECONTROLLO = 0.6


def precontrollo_tipo(titolo):
    """Codice del motivo (come motivo_jev) se dal solo titolo l'annuncio e' un ricambio, un lotto, una replica o e' dichiarato
    rotto/incompleto, con confidenza >= CONF_PRECONTROLLO; altrimenti None (anche se Jev e' spento o non risponde).
    Serve a non cercare comparabili per cio' che non si puo' rivendere come oggetto. Bloccante, poche decine di token."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and JEV_PRECONTROLLO and chiave):
        return None
    domande = {k: {"type": "choice", "instructions": DOMANDE[k]["instructions"], "criteria": DOMANDE[k]["criteria"]}
               for k in ("tipo", "completo")}
    try:
        risposta = _chiama_jev({"model": MODELLO, "state": f"Annuncio Vinted: {titolo}", "questions": domande})
        r = {k: (risposta["answers"][k].get("choice"), risposta["answers"][k].get("confidence")) for k in domande}
    except Exception as e:  # noqa: BLE001 - il precontrollo non deve bloccare il radar
        log.warning("JEV PRECONTROLLO | non disponibile: %s", str(e)[:200])
        return None
    codice = None
    if r["tipo"][0] in TIPI_NON_VENDIBILI and (r["tipo"][1] or 0) >= CONF_PRECONTROLLO:
        codice = _MOTIVO_TIPO[r["tipo"][0]]
    elif r["completo"][0] == "no" and (r["completo"][1] or 0) >= CONF_PRECONTROLLO:
        codice = "guasto_incompleto"
    log.info("JEV PRECONTROLLO | titolo=%s | tipo=%s(%s) | completo=%s(%s) | scartato=%s", titolo[:60],
             r["tipo"][0], r["tipo"][1], r["completo"][0], r["completo"][1], codice or "no")
    return codice


PAESI_JEV = ("italia", "francia", "germania", "spagna")
CONF_PAESE_MIN = 0.6


def stima_paese(titolo, descrizione=None):
    """(paese, confidenza) del venditore stimato da Jev leggendo titolo e descrizione (lingua, valuta, citta', spedizioni), oppure None
    se Jev e' spento, non risponde, il paese non e' chiaro o la confidenza e' < CONF_PAESE_MIN. Solo quando l'HTML non lo da'
    (01/11, richiesta dell'utente). E' una stima: il chiamante la dichiara. Bloccante, poche decine di token."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and chiave):
        return None
    stato = f"Annuncio Vinted: {titolo}"
    desc = " ".join((descrizione or "").split())[:MAX_DESCRIZIONE]
    if desc:
        stato += f"\nDescrizione del venditore: {desc}"
    criteri = {"italia": "scritto in italiano o con riferimenti all'Italia", "francia": "scritto in francese o con riferimenti alla Francia",
               "germania": "scritto in tedesco o con riferimenti alla Germania", "spagna": "scritto in spagnolo o con riferimenti alla Spagna",
               "non_chiaro": "altra lingua o nessun indizio sul paese del venditore"}
    domanda = {"paese": {"type": "choice", "instructions": "In quale paese si trova probabilmente il venditore, dalla lingua e dai riferimenti del testo?",
                         "criteria": criteri}}
    try:
        risposta = _chiama_jev({"model": MODELLO, "state": stato, "questions": domanda})
        r = risposta["answers"]["paese"]
        scelta, conf = r.get("choice"), r.get("confidence")
    except Exception as e:  # noqa: BLE001 - la stima del paese non deve bloccare il radar
        log.warning("JEV PAESE | non disponibile: %s", str(e)[:200])
        return None
    log.info("JEV PAESE | titolo=%s | paese=%s(%s) | desc=%s", titolo[:60], scelta, conf, len(desc))
    if scelta in PAESI_JEV and (conf or 0) >= CONF_PAESE_MIN:
        return scelta, conf
    return None


def confronta_foto_comparabili(titolo, foto, miniature):
    """[(scelta, confidenza), ...] una per miniatura, oppure None se Jev e' spento o non risponde. Bloccante.
    `foto` e `miniature` sono byte di immagini png/jpeg (max MAX_FOTO_COMPS miniature). Non influisce sull'esito."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not (JEV_GIUDICE and JEV_FOTO_COMPS and chiave):
        return None
    immagini = [("foto1", foto)] + [(f"comp{i}", m) for i, m in enumerate(miniature[:MAX_FOTO_COMPS], 1)]
    assets = {}
    for nome, dati in immagini:
        formato = _formato_foto(dati)
        if not formato:
            continue
        assets[nome] = {"type": "image", "data_base64": base64.b64encode(dati).decode(), "format": formato}
    comp = [n for n in assets if n != "foto1"]
    if "foto1" not in assets or not comp:
        return None
    corpo = {"model": MODELLO, "assets": assets,
             "state": f"Annuncio Vinted: {titolo}\nFoto dell'annuncio: foto1\nMiniature di annunci simili: {', '.join(comp)}",
             "questions": {n: {"type": "choice", **DOMANDA_FOTO_COMP, "instructions": DOMANDA_FOTO_COMP["instructions"].replace("questa miniatura", n)}
                           for n in comp}}
    try:
        risposta = _chiama_jev(corpo)
        risultati = [(risposta["answers"][n].get("choice"), risposta["answers"][n].get("confidence")) for n in comp]
    except Exception as e:  # noqa: BLE001 - e' solo una prova in ombra
        log.warning("JEV FOTO COMPS | non disponibile: %s", str(e)[:200])
        return None
    token = (risposta.get("usage") or {}).get("input_tokens")
    log.info("JEV FOTO COMPS | titolo=%s | miniature=%s | input_tokens=%s | %s", titolo[:60], len(comp), token,
             " | ".join(f"{n}={c}({p})" for n, (c, p) in zip(comp, risultati)))
    return risultati


def classifica_comparabili(titolo, titoli, descrizione=None):
    """[(scelta, confidenza)] uno per titolo (al massimo MAX_TITOLI_SIMILI) oppure None se Jev non e' attivo o non risponde.
    Scelte: stesso_modello / simile / altro. Bloccante: usarla con asyncio.to_thread."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    titoli = [(t or "(senza titolo)") for t in (titoli or [])][:MAX_COMPS_VERIFICA]
    if not (JEV_GIUDICE and JEV_COMPS and chiave and titoli):
        return None
    stato = f"Annuncio Vinted: {titolo}"
    desc = " ".join((descrizione or "").split())[:MAX_DESCRIZIONE]
    if desc:
        stato += f"\nDescrizione del venditore: {desc}"
    stato += "\nAnnunci simili da giudicare:\n" + "\n".join(f"{i + 1}. {t[:100]}" for i, t in enumerate(titoli))
    domande = {f"c{i}": {"type": "choice", "instructions": f"L'annuncio simile numero {i + 1} e' lo stesso modello dell'annuncio?",
                         "criteria": CRITERI_COMP} for i in range(len(titoli))}
    try:
        risposta = _chiama_jev({"model": MODELLO, "state": stato, "questions": domande})
        out = []
        for i in range(len(titoli)):
            r = risposta["answers"][f"c{i}"]
            out.append((r.get("choice"), r.get("confidence")))
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        log.warning("JEV COMPS | giudizio non disponibile: %s", str(e)[:200])
        return None
    token = (risposta.get("usage") or {}).get("input_tokens")
    log.info("JEV COMPS | titolo=%s | n=%s | stesso=%s | input_tokens=%s", titolo[:60], len(out),
             sum(1 for c, _ in out if c == "stesso_modello"), token)
    return out


def riconosci_prodotto(titolo, candidati, descrizione=None):
    """(candidato scelto, confidenza) oppure None. Jev sceglie, tra nomi candidati presi dal titolo, quello che e' il PRODOTTO
    venduto (es. 'Wash Buckler + Skylanders Swap Force' -> 'skylanders swap force'); 'nessuno' se non e' chiaro.
    Bloccante: usarla con asyncio.to_thread."""
    chiave = os.environ.get("TYPESAFE_API_KEY", "").strip()
    candidati = [c for c in (candidati or []) if c][:6]
    if not (JEV_GIUDICE and JEV_COMPS and chiave and len(candidati) >= 2):
        return None
    criteri = {f"n{i}": f"il prodotto venduto e' '{c}'" for i, c in enumerate(candidati)}
    criteri["nessuno"] = "nessuno di questi nomi e' il prodotto principale venduto"
    stato = f"Annuncio Vinted: {titolo}"
    desc = " ".join((descrizione or "").split())[:MAX_DESCRIZIONE]
    if desc:
        stato += f"\nDescrizione del venditore: {desc}"
    domanda = {"prodotto": {"type": "choice", "instructions": "Qual e' il nome del prodotto principale venduto in questo annuncio?",
                            "criteria": criteri}}
    try:
        risposta = _chiama_jev({"model": MODELLO, "state": stato, "questions": domanda})
        r = risposta["answers"]["prodotto"]
        scelta, conf = r.get("choice"), r.get("confidence")
    except Exception as e:  # noqa: BLE001 - Jev non deve bloccare il radar
        log.warning("JEV PRODOTTO | non disponibile: %s", str(e)[:200])
        return None
    token = (risposta.get("usage") or {}).get("input_tokens")
    nome = candidati[int(scelta[1:])] if isinstance(scelta, str) and scelta.startswith("n") and scelta[1:].isdigit() and int(scelta[1:]) < len(candidati) else None
    log.info("JEV PRODOTTO | titolo=%s | scelto=%s(%s) | candidati=%s | input_tokens=%s", titolo[:60], nome or "nessuno", conf, candidati, token)
    return (nome, conf) if nome else None
