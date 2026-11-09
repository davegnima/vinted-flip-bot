"""Controllo di autenticita' con Gemini GRATUITO sulla moda (02/11, richiesta dell'utente).

Quando la foto letta da Jev non basta a dire "sembra originale" (replica sospetta, marca diversa, foto poco chiara o prezzo molto sotto i
comparabili) Gemini guarda TUTTE le foto dell'annuncio (etichette, cuciture, serigrafie, hardware, codici) e dice se il capo e' coerente
con la marca del titolo. E' un indizio dalle foto, non una certificazione. Gemini NON calcola margini ne' decide l'avviso da solo:
solo una replica con confidenza alta scarta (come Jev), il resto diventa una riga nel messaggio.
Solo Gemini gratuito (cascata e chiavi di GEMINI_API_KEYS, ruolo 'occhio'); nessun servizio a pagamento. Mai eccezioni.
"""
import json
import re
import os
import time

from bot.gemini_api import chiama_gemini
from bot.logger import log
from bot.prompts import GEMINI_CERVELLO_SYSTEM_PROMPT

MODA_GEMINI = os.environ.get("MODA_GEMINI", "1").strip() not in ("0", "false", "no", "")
# 5/11 (utente): il legit check approfondito su tutte le foto vale per OGNI avviso, non solo quando Jev dubita. MODA_GEMINI_SEMPRE=0 torna a "solo se serve".
MODA_GEMINI_SEMPRE = os.environ.get("MODA_GEMINI_SEMPRE", "1").strip() not in ("0", "false", "no", "")
try:
    MODA_GEMINI_MAX_ORA = int(os.environ.get("MODA_GEMINI_MAX_ORA", "60") or 60)
    MODA_GEMINI_FOTO = max(1, int(os.environ.get("MODA_GEMINI_FOTO", "8") or 8))
except ValueError:
    MODA_GEMINI_MAX_ORA, MODA_GEMINI_FOTO = 60, 8
# 7/11 (utente: 'recupera il prompt del Cervello'): la stima di rivendita di Gemini segue le regole di prezzo del Cervello (linee ed ere da non
# mischiare, calibrazioni per brand, ANCORAGGIO PREZZI con sconto sugli ASK e filtro outlier, liquidita' per segmento), prese dallo stesso testo
# di bot/prompts.py: un'unica fonte. MODA_GEMINI_REGOLE_PREZZO=0 le toglie (prompt piu' corto).
MODA_GEMINI_REGOLE_PREZZO = os.environ.get("MODA_GEMINI_REGOLE_PREZZO", "1").strip() not in ("0", "false", "no", "")


def _regole_prezzo_cervello():
    t = GEMINI_CERVELLO_SYSTEM_PROMPT
    a, b = t.find("# LINEE E ERE"), t.find("# COSA DEVI PRODURRE")
    return t[a:b].strip() if 0 <= a < b else ""


CONF_REPLICA_MIN = 0.7   # sotto questa confidenza una "replica" resta un dubbio nel messaggio, non uno scarto
RAPPORTO_PREZZO_SOSPETTO = 0.25   # prezzo sotto il 25% della rivendita dei comparabili: troppo bello per essere vero

SYSTEM_PROMPT = """Sei un esperto di autenticazione di capi e accessori di moda usati (Vinted, Vestiaire, Grailed, eBay). Ricevi titolo, marca dichiarata, prezzo,
descrizione e TUTTE le foto di un annuncio. Guardale una per una e dici se quello che vedi e' coerente con la marca dichiarata, SOLO sui fatti visibili.

REGOLE
- Il prezzo non e' mai una prova: un prezzo basso con etichette coerenti e' un affare, non un falso. Non citarlo.
- Trascrivi solo cio' che si legge davvero; mai completare a memoria una dicitura. Nel dubbio campo vuoto o "non_leggibile".
- Se il venditore scrive "replica", "riproduzione", "ispirato a", "stile", "tipo": e' una dichiarazione di non originalita', prevale sulle foto.
- Elenca i riscontri coerenti, non solo i sospetti: un giudizio negativo su un solo dettaglio, ignorandone cinque coerenti, e' un errore.

COSA CERCARE (in ogni foto)
1. Etichetta principale (collo/interno): font, proporzioni, materiale, cucitura, linea (mainline o diffusion: MM6, See by Chloe, McQ, Weekend, Love Moschino...).
2. Etichetta di lavaggio/composizione: paese dopo "Made in", composizione, codice prodotto; etichetta taglia (stile ed epoca).
3. Logo, ricami, serigrafie, cuciture, zip e hardware (peso, incisioni, finitura), fodera, codici a rilievo o numeri di serie.
4. Documenti e accessori: fattura, scontrino, cartellino, certificato, dustbag, scatola. Registra solo cio' che si vede; non sono mai una prova da soli.
5. Linea: scrivi in "linea_etichetta" la sottolinea stampata sull'etichetta principale (es. "Weekend", "Marella", "Sportmax", "MM6", "See by Chloe",
   "M Missoni"); "principale" se si legge solo il marchio madre; "non_leggibile" se l'etichetta non si legge. Il titolo puo' dire solo "Max Mara" anche
   se l'etichetta e' Weekend: conta l'etichetta, non il titolo.
6. Marchio diverso: se l'etichetta mostra un nome diverso o non correlato al brand dichiarato (non una sottolinea della stessa maison) -> autenticita "altra_marca".
7. Il nome di un tessuto (es. Loro Piana, Cerruti) non e' il brand del capo.

PAESE DI PRODUZIONE
- Prada, Miu Miu, Loro Piana, Brunello Cucinelli, Bottega Veneta, Fendi producono l'abbigliamento in Italia: "Made in" asiatico (Cina, Bangladesh, Vietnam, India...) e' un'incoerenza forte,
  non puoi dire "probabile" (almeno "dubbia").
- Marchi con produzione mista (Max Mara, Zegna, Loewe, Missoni, Marni, Jil Sander, Helmut Lang, Westwood, JPG...): un paese insolito per linea o epoca e' un'incoerenza media.
- Se non conosci la produzione abituale del brand, il paese da solo non e' un segnale.
Prada e Miu Miu: il logo esterno non basta; serve il cartellino interno con layout e font tipici, altrimenti al massimo "dubbia".

ESITO
- "probabile": i dettagli visibili sono coerenti, nessuna incoerenza.
- "dubbia": qualche incoerenza o elementi chiave non visibili (cartellino interno, wash tag).
- "replica": indizi concreti e multipli (logo/font sbagliato, cuciture grossolane, hardware economico, etichetta incoerente). Non sospettare senza un indizio.
- "altra_marca": l'etichetta e' di un marchio diverso.
- "non_verificabile": nessuna etichetta o dettaglio leggibile nelle foto.

CONDIZIONI E VALORE (7/11, utente: non solo autenticita')
- capo: cos'e' (tipo, modello o variante, linea/stagione se la leggi o la riconosci), 2-8 parole. Se non lo riconosci scrivi "non_riconosciuto".
- materiale: composizione letta sull'etichetta (es. "100% cashmere", "lana 70% seta 30%"); "non_leggibile" se non la leggi. Non dedurla dal brand: il materiale cambia molto il prezzo.
- condizione: "come_nuovo" (cartellino o mai usato), "ottima", "buona", "usurata".
- difetti: macchie, aloni, buchi, strappi, scuciture, pilling forte, cerniere o bottoni rotti, odori dichiarati, tessuto sformato o scolorito, SOLO se li vedi nelle foto o il venditore li dichiara. Per ognuno tipo, POSIZIONE e DIMENSIONE (es. "alone ~3 cm sul petto", "foro piccolo sulla manica"). "nessuno" se non ne vedi. Non inventarli: una foto sfocata non e' un difetto.
- gravita_difetti: "nessuno"; "lieve" (macchia lavabile, pilling, piccola scucitura riparabile); "moderata" (macchia dubbia o visibile, piccolo foro, usura evidente); "grave" (strappi, fori multipli o estesi, macchie estese permanenti, tessuto compromesso).
- sconto_difetti_pct: di quanto i difetti abbassano il prezzo di rivendita rispetto allo STESSO capo in buone condizioni, 0-60 (0 se nessuno). Non scontare due volte quello che e' gia' nella condizione.
- rivendita_gemini_eur: il prezzo realistico a cui QUESTO capo, nelle condizioni che vedi, si rivende usato in Italia in tempi brevi (non il prezzo di listino ne' quello chiesto da altri). Usa modello, materiale e stato. Se non conosci abbastanza il capo scrivi 0.
- rivendita_confidenza: 0-1, quanto sei sicuro di quella stima (sotto 0,4 se il capo e' poco noto o le foto non bastano).
- da_chiedere: se l'autenticita' non e' "probabile" o mancano dettagli chiave, cosa chiedere al venditore per sciogliere il dubbio, in modo concreto (es. "foto dell'etichetta di lavaggio con il made in", "foto delle cuciture interne", "foto del numero di serie"), max 110 caratteri. Vuoto se non serve.
- rivendita_base: max 100 caratteri, su cosa si basa (es. 'maglione base mainline, cashmere, prezzi usati tipici 80-120').
CONSIGLIERE DI FLIP (9/11, utente: Gemini fa anche il lavoro del vecchio Cervello)
- tipo_oggetto: "moda" se e' un capo, un paio di scarpe, una borsa o un accessorio di moda; "non_moda" se foto o testo mostrano ALTRO (profumo, cosmetici, giocattolo, libro, oggetto per la casa, ecc.) anche se il titolo cita un brand di moda (es. "Issey Miyake" era un profumo). Se hai dubbi scrivi "moda".
- consiglio: UNA riga (max 110 caratteri, in italiano) da consigliere di rivendita: cosa noti nelle foto e nel testo che conta per comprare o no (cosa e' davvero, taglia o variante rara, stato, dettagli che alzano o abbassano il prezzo, cosa manca). Fatti concreti, niente frasi generiche. Vuoto se non noti nulla di utile.
REGOLE PER LA STIMA DI RIVENDITA (`rivendita_gemini_eur`): se ricevi i comparabili Vinted sono prezzi ASK (annunci attivi, non vendite), spesso con linee o capi diversi
mescolati: usa le regole qui sotto del valutatore (linee ed ere, ancoraggio prezzi, filtro outlier, liquidita'), scarta i comparabili di un'altra linea o categoria e
non superare mai il comparabile ASK piu' alto dopo lo sconto. Senza comparabili stima dal modello e dalle condizioni che vedi, con confidenza bassa.
Non calcolare margini, ROI o decisioni. Risposta breve: campi a poche parole, "motivo" una frase italiana (max 120 caratteri) con il fatto che ha deciso."""

SCHEMA = {
    "type": "OBJECT",
    "propertyOrdering": ["autenticita", "confidenza", "linea_etichetta", "etichetta_letta", "made_in", "prova_acquisto", "indizi", "motivo",
                         "capo", "materiale", "condizione", "difetti", "gravita_difetti", "sconto_difetti_pct",
                         "rivendita_gemini_eur", "rivendita_confidenza", "rivendita_base", "da_chiedere", "tipo_oggetto", "consiglio"],
    "properties": {
        "autenticita": {"type": "STRING", "enum": ["probabile", "dubbia", "replica", "altra_marca", "non_verificabile"]},
        "confidenza": {"type": "NUMBER"},
        "linea_etichetta": {"type": "STRING"},
        "etichetta_letta": {"type": "STRING"},
        "made_in": {"type": "STRING"},
        "prova_acquisto": {"type": "STRING", "enum": ["nessuna", "cartellino", "scontrino", "fattura", "certificato", "scatola_dustbag"]},
        "indizi": {"type": "STRING"},
        "motivo": {"type": "STRING"},
        "capo": {"type": "STRING"},
        "materiale": {"type": "STRING"},
        "condizione": {"type": "STRING", "enum": ["come_nuovo", "ottima", "buona", "usurata"]},
        "difetti": {"type": "STRING"},
        "gravita_difetti": {"type": "STRING", "enum": ["nessuno", "lieve", "moderata", "grave"]},
        "sconto_difetti_pct": {"type": "NUMBER"},
        "rivendita_gemini_eur": {"type": "NUMBER"},
        "rivendita_confidenza": {"type": "NUMBER"},
        "rivendita_base": {"type": "STRING"},
        "da_chiedere": {"type": "STRING"},
        "tipo_oggetto": {"type": "STRING", "enum": ["moda", "non_moda"]},
        "consiglio": {"type": "STRING"},
    },
    "required": ["autenticita", "confidenza", "etichetta_letta", "made_in", "prova_acquisto", "indizi", "motivo",
                 "capo", "materiale", "condizione", "difetti", "gravita_difetti", "sconto_difetti_pct",
                 "rivendita_gemini_eur", "rivendita_confidenza", "rivendita_base", "da_chiedere"],
}

if MODA_GEMINI_REGOLE_PREZZO:
    SYSTEM_PROMPT = SYSTEM_PROMPT + "\n\n" + _regole_prezzo_cervello()

_chiamate = []   # istanti delle chiamate dell'ultima ora: tetto MODA_GEMINI_MAX_ORA


def _entro_il_tetto(adesso=None):
    adesso = adesso if adesso is not None else time.time()
    while _chiamate and adesso - _chiamate[0] > 3600:
        _chiamate.pop(0)
    return len(_chiamate) < MODA_GEMINI_MAX_ORA


def serve_controllo(autenticita_jev, prezzo, rivendita):
    """True se vale la pena far guardare tutte le foto a Gemini: Jev non dice con sicurezza "originale", oppure il prezzo e' molto sotto la
    rivendita dei comparabili (il caso classico del falso). `autenticita_jev` = (scelta, confidenza) o None. Pura."""
    if not MODA_GEMINI:
        return False
    if MODA_GEMINI_SEMPRE:
        return True
    if not autenticita_jev or autenticita_jev[0] != "originale_plausibile" or (autenticita_jev[1] or 0) < 0.6:
        return True
    return bool(rivendita and prezzo and prezzo < RAPPORTO_PREZZO_SOSPETTO * rivendita)


def leggi_risposta(testo):
    """Dict valido {autenticita, confidenza, indizi, motivo} dalla risposta di Gemini, o None. Pura."""
    if not testo or testo.lstrip().startswith("[ERRORE"):
        return None
    try:
        d = json.loads(testo)
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("autenticita") not in ("probabile", "dubbia", "replica", "altra_marca", "non_verificabile"):
        return None
    try:
        d["confidenza"] = max(0.0, min(1.0, float(d.get("confidenza"))))
    except (TypeError, ValueError):
        d["confidenza"] = None
    for campo in ("etichetta_letta", "made_in", "linea_etichetta"):
        d[campo] = str(d.get(campo) or "")[:60]
    d["prova_acquisto"] = d.get("prova_acquisto") if d.get("prova_acquisto") in ("cartellino", "scontrino", "fattura", "certificato", "scatola_dustbag") else "nessuna"
    d["indizi"] = str(d.get("indizi") or "")[:160]
    d["motivo"] = str(d.get("motivo") or "")[:140]
    # condizioni e valore (7/11): campi opzionali, una risposta senza (modelli piu' deboli della cascata) resta valida
    d["capo"] = str(d.get("capo") or "")[:80]
    d["materiale"] = str(d.get("materiale") or "")[:60]
    d["condizione"] = d.get("condizione") if d.get("condizione") in ("come_nuovo", "ottima", "buona", "usurata") else None
    d["difetti"] = str(d.get("difetti") or "")[:200]
    d["gravita_difetti"] = d.get("gravita_difetti") if d.get("gravita_difetti") in GRAVITA_SCONTO_MAX else None
    try:
        d["sconto_difetti_pct"] = max(0.0, min(60.0, float(d.get("sconto_difetti_pct"))))
    except (TypeError, ValueError):
        d["sconto_difetti_pct"] = None
    try:
        r = float(d.get("rivendita_gemini_eur"))
        d["rivendita_gemini_eur"] = round(r, 2) if r > 0 else None   # 0 = "non conosco il capo": nessuna stima
    except (TypeError, ValueError):
        d["rivendita_gemini_eur"] = None
    try:
        d["rivendita_confidenza"] = max(0.0, min(1.0, float(d.get("rivendita_confidenza"))))
    except (TypeError, ValueError):
        d["rivendita_confidenza"] = None
    d["rivendita_base"] = str(d.get("rivendita_base") or "")[:110]
    d["da_chiedere"] = str(d.get("da_chiedere") or "")[:120]
    d["tipo_oggetto"] = "non_moda" if d.get("tipo_oggetto") == "non_moda" else "moda"
    d["consiglio"] = re.sub(r"\s+", " ", str(d.get("consiglio") or "")).strip()[:120]
    return d


# Quanto i difetti possono abbassare la rivendita dei comparabili (che sono in genere in buone condizioni): il tetto per gravita' evita che una
# stima fantasiosa di Gemini azzeri un affare. Il numero e' una stima di Gemini limitata dal codice, non un dato misurato.
GRAVITA_SCONTO_MAX = {"nessuno": 0.0, "lieve": 15.0, "moderata": 35.0, "grave": 60.0}
SCONTO_PREDEFINITO = {"lieve": 8.0, "moderata": 20.0, "grave": 40.0}   # se Gemini segnala il difetto ma non dice di quanto


def sconto_difetti(d):
    """Percentuale (0-60) di cui abbassare la rivendita dei comparabili per i difetti letti da Gemini, 0 se nessuno o non affidabile. Pura."""
    if not d or d.get("gravita_difetti") in (None, "nessuno") or not d.get("difetti"):
        return 0.0
    tetto = GRAVITA_SCONTO_MAX[d["gravita_difetti"]]
    pct = d.get("sconto_difetti_pct")
    if not pct:
        pct = SCONTO_PREDEFINITO[d["gravita_difetti"]]
    return min(float(pct), tetto)


def riga_condizioni(d):
    """Riga (testo semplice) con capo, materiale, condizione e difetti letti da Gemini, o None. Pura."""
    if not d or not (d.get("capo") or d.get("materiale") or d.get("difetti") or d.get("condizione")):
        return None
    parti = []
    if d.get("capo") and d["capo"] != "non_riconosciuto":
        parti.append(d["capo"])
    if d.get("materiale") and d["materiale"] != "non_leggibile":
        parti.append(d["materiale"])
    cond = {"come_nuovo": "come nuovo", "ottima": "condizione ottima", "buona": "condizione buona", "usurata": "usurato"}.get(d.get("condizione"))
    if cond:
        parti.append(cond)
    riga = "🔍 " + (", ".join(parti) if parti else "n/d")
    if d.get("gravita_difetti") and d["gravita_difetti"] != "nessuno" and d.get("difetti"):
        riga += f" · ⚠️ difetti {d['gravita_difetti']}: {d['difetti']}"
    elif d.get("gravita_difetti") == "nessuno":
        riga += " · nessun difetto visibile"
    return riga


def riga_stima_gemini(d, rivendita_codice=None):
    """Riga con la stima di rivendita di Gemini (solo informativa: non cambia margine ne' decisione) e, se molto piu' bassa dei comparabili con
    confidenza sufficiente, un avviso. None se Gemini non ha stimato. Pura."""
    if not d or not d.get("rivendita_gemini_eur"):
        return None
    rc = d.get("rivendita_confidenza")
    riga = f"💶 Gemini stima ~{d['rivendita_gemini_eur']:g} €" + (f" (confidenza {rc:.0%})" if rc is not None else "")
    if rivendita_codice and (rc or 0) >= 0.6 and d["rivendita_gemini_eur"] < 0.6 * rivendita_codice:
        riga += f"\n⚠️ molto meno dei comparabili (~{rivendita_codice:.0f} €): controllare modello e materiale"
    return riga


def e_replica(d):
    """True se Gemini dice replica (o marchio diverso) con confidenza sufficiente a scartare l'avviso. Pura."""
    return bool(d and d.get("autenticita") in ("replica", "altra_marca") and (d.get("confidenza") or 0) >= CONF_REPLICA_MIN)


def e_non_moda(d):
    """True se Gemini vede che l'oggetto NON e' moda (profumo, cosmetici, ecc.) con confidenza sufficiente a scartare. Pura."""
    return bool(d and d.get("tipo_oggetto") == "non_moda" and (d.get("confidenza") or 0) >= CONF_REPLICA_MIN)


def riga_consiglio(d):
    """Riga '💬' del consigliere di flip (testo semplice), o None. Pura."""
    if not d:
        return None
    if d.get("tipo_oggetto") == "non_moda":
        return "💬 Non è moda" + (f": {d['consiglio']}" if d.get("consiglio") else " (profumo, cosmetici o altro)")
    return f"💬 {d['consiglio']}" if d.get("consiglio") else None


def riga_messaggio(d):
    """Riga (testo semplice) per il messaggio: esito del controllo Gemini sulle foto. Pura."""
    if not d:
        return None
    etichetta = {"probabile": "coerente con la marca", "dubbia": "qualche dubbio", "replica": "indizi di replica",
                 "altra_marca": "etichetta di un altro marchio", "non_verificabile": "non verificabile dalle foto"}[d["autenticita"]]
    conf = f" ({d['confidenza']:.0%})" if d.get("confidenza") is not None else ""
    extra = []
    if d.get("made_in"):
        extra.append(f"made in {d['made_in']}")
    if d.get("prova_acquisto") and d["prova_acquisto"] != "nessuna":
        extra.append(f"visibile: {d['prova_acquisto'].replace('_', '/')}")
    dettagli = f" [{'; '.join(extra)}]" if extra else ""
    return f"👁 Gemini: {etichetta}{conf}" + (f", {d['motivo'][:90]}" if d.get("motivo") else "") + dettagli


async def controlla(titolo, brand, prezzo, descrizione, foto, item_id=None, comps=None):
    """Controllo Gemini su tutte le foto (al massimo MODA_GEMINI_FOTO). Ritorna il dict di leggi_risposta o None (spento, oltre il tetto
    orario, senza foto o senza risposta). Mai eccezioni."""
    if not (MODA_GEMINI and foto):
        return None
    try:
        if not _entro_il_tetto():
            log.info("MODA GEMINI | item=%s | oltre il tetto orario (%s/h): niente controllo", item_id, MODA_GEMINI_MAX_ORA)
            return None
        _chiamate.append(time.time())
        t0 = time.time()
        utente = (f"Titolo: {titolo}\nMarca dichiarata: {brand or 'n/d'}\n"
                  + (f"Prezzo richiesto: {prezzo:g} EUR\n" if isinstance(prezzo, (int, float)) else "")
                  + "Descrizione del venditore: " + ((descrizione or "").strip()[:1200] or "(vuota)")
                  + (("\nComparabili Vinted (prezzi ASK, gia' filtrati per brand e categoria, possono contenere linee diverse):\n"
                      + "\n".join(f"- {p:g} EUR | {str(t)[:70]}" for t, p in list(comps)[:12])) if comps else "\nComparabili Vinted: nessuno trovato."))
        testo, _costo, _n = await chiama_gemini(SYSTEM_PROMPT, utente, list(foto)[:MODA_GEMINI_FOTO], grounding=False,
                                                response_schema=SCHEMA, ruolo="occhio")
        d = leggi_risposta(testo)
        log.info("MODA GEMINI | item=%s | brand=%s | autenticita=%s | conf=%s | foto=%s | %.1fs | etichetta=%s | made_in=%s | prova=%s | indizi=%s | motivo=%s | capo=%s | materiale=%s | cond=%s | difetti=%s | grav=%s | sconto=%s | riv_gem=%s | conf_riv=%s | titolo=%s",
                 item_id or "-", brand, (d or {}).get("autenticita", "nessuna_risposta"), (d or {}).get("confidenza", "-"),
                 min(len(foto), MODA_GEMINI_FOTO), time.time() - t0, (d or {}).get("etichetta_letta", "-"), (d or {}).get("made_in", "-"), (d or {}).get("prova_acquisto", "-"),
                 (d or {}).get("indizi", "-"), (d or {}).get("motivo", (testo or "")[:80]),
                 (d or {}).get("capo", "-"), (d or {}).get("materiale", "-"), (d or {}).get("condizione", "-"), (d or {}).get("difetti", "-"),
                 (d or {}).get("gravita_difetti", "-"), (d or {}).get("sconto_difetti_pct", "-"), (d or {}).get("rivendita_gemini_eur", "-"),
                 (d or {}).get("rivendita_confidenza", "-"), (titolo or "")[:60])
        return d
    except Exception as e:  # noqa: BLE001 - il controllo non deve mai fermare l'avviso
        log.warning("MODA GEMINI | item=%s | errore: %s", item_id or "-", e)
        return None
