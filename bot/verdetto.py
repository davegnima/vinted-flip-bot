"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
import statistics


from bot.config import COMMISSIONE_PROTEZIONE_FISSA, COMMISSIONE_PROTEZIONE_PCT, COMP_DA_MEMORIA_AMMESSI, SCONTO_MAX_TRATTATIVA, SCONTO_TIPICO_TRATTATIVA_VENDITA, SOGLIA_GIORNI_VENDITA_LAMPO, SOGLIA_MARGINE_COMPRA, SOGLIA_MARGINE_COMPRA_ALTA, SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE, SOGLIA_MARGINE_URGENZA, SOGLIA_PREZZO_FURTO_ISTANTANEO, SOGLIA_ROI_COMPRA, SOGLIA_ROI_COMPRA_RIDOTTA, SOGLIA_ROI_FURTO_ISTANTANEO, SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE, SOGLIA_ROI_URGENZA, SPEDIZIONE_STIMATA_EUR, TOLLERANZA_COMP_EUR, _env_float
from bot.testo import _escapa_markdown_legacy, _etichetta_piattaforma_da_url, _normalizza_titolo_per_link
from bot.logger import log
# ---- fine import ----
def _estrai_item_id_da_url(url):
    if not url:
        return None
    m = re.search(r"/items/(\d+)", url)
    return m.group(1) if m else None


def _estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo):
    """Estrae tutti i numeri che compaiono vicino a un simbolo di prezzo
    (€ prima o dopo, o 'EUR') nel testo grezzo dei risultati di ricerca
    (comp pre-raccolti + eventuali cerca_comp_prezzo on-demand). Sono gli
    UNICI numeri che il cervello puo' legittimamente citare come prezzi nel
    blocco Analisi -- qualunque altro prezzo citato non ha una fonte
    verificabile in questa conversazione.

    BUG corretto il 2026-09-19: il ramo "numero PRIMA del simbolo" (es.
    '105 €', '400€' -- il formato piu' comune negli snippet Vestiaire/eBay
    europei) non ha MAI matchato nulla, perche' il pattern terminava con
    "(?:€|EUR)\\b" e \\b (word boundary) non esiste subito dopo '€' (non e'
    un carattere di parola, quindi non crea un confine con cio' che segue).
    Risultato pratico: questa funzione vedeva SOLO i prezzi scritti come
    '€105', perdendo silenziosamente tutti quelli in formato '105€' -- cioe'
    sottostimava il pool reale, con rischio di falsi "comp inventato" da
    verifica_comp_citati_sono_reali quando il prezzo citato dal cervello
    corrispondeva in realta' a un prezzo vero scritto in quel formato."""
    prezzi = set()
    for m in re.finditer(r"€\s*([\d]+(?:[.,]\d+)?)|([\d]+(?:[.,]\d+)?)\s*(?:€|EUR\b)", pool_ricerca_grezzo, re.IGNORECASE):
        valore = m.group(1) or m.group(2)
        try:
            prezzi.add(round(float(valore.replace(",", ".")), 2))
        except ValueError:
            continue
    return prezzi


def _prezzi_per_fonte_da_pool(pool_ricerca_grezzo):
    """Come _riepilogo_comp_per_fonte ma restituisce i dati grezzi invece del
    testo: dict {chiave_fonte_normalizzata: set(prezzi)}, dove chiave_fonte
    e' il nome della fonte in minuscolo senza spazi/punteggiatura (es.
    'ebaysold', 'vestiairecollective', 'vinted') -- pensato per essere
    confrontato con un nome di fonte estratto dal testo del cervello con la
    stessa normalizzazione, cosi' da tollerare piccole differenze di
    formattazione ('eBay SOLD' vs 'ebay sold' vs 'eBay-SOLD'). Usato da
    verifica_comp_citati_sono_reali per il controllo di secondo livello
    'la fonte dichiarata dal cervello corrisponde a dove il prezzo si trova
    davvero nel pool'.

    Corretto il 2026-09-19 (caso reale Jil Sander): un blocco 'RICERCA
    ON-DEMAND CERVELLO' e' sempre una query Google generica (Serper), mai
    taggata col nome di un marketplace specifico -- ma i suoi risultati
    spesso SONO risultati eBay/Vestiaire/Vinted/Depop/Grailed (lo snippet
    cita il dominio, es. 'ebay.it', o il titolo lo rende ovvio). Quando il
    cervello scrive nell'Analisi 'comp eBay SOLD €100.00' basandosi su un
    risultato che ha visto in quella ricerca on-demand, l'attribuzione e'
    corretta nella sostanza -- ma il controllo di secondo livello la
    respingeva sempre come 'fonte mal attribuita' perche' il prezzo era
    presente solo sotto la chiave 'ricercaondemandcervello', mai sotto
    'ebaysold'. Ora ogni riga del pool (non solo i blocchi RICERCA
    ON-DEMAND) viene scansionata anche per menzioni esplicite di dominio
    marketplace vicino a un prezzo, e quel prezzo viene aggiunto ANCHE
    alla fonte del dominio, in aggiunta alla fonte del blocco."""
    risultato = {}
    if not pool_ricerca_grezzo or not pool_ricerca_grezzo.strip():
        return risultato
    blocchi = re.split(r"\n?📍\s*FONTE:\s*", pool_ricerca_grezzo)
    for blocco in blocchi:
        blocco = blocco.strip()
        if not blocco:
            continue
        prima_riga, _, resto = blocco.partition("\n")
        if prima_riga.upper().startswith("RICERCA WEB PRE-RACCOLTA"):
            continue
        nome_fonte = prima_riga.split("(")[0].strip().rstrip(":—-").strip() or prima_riga.strip()
        chiave = re.sub(r"[^a-z0-9]", "", nome_fonte.lower())
        blocco_dati = resto or blocco
        if chiave:
            prezzi_fonte = _estrai_prezzi_da_pool_ricerca(blocco_dati)
            risultato.setdefault(chiave, set()).update(prezzi_fonte)

        # Riconoscimento dominio per-riga (vedi nota sopra): per ogni riga
        # del blocco, se compare un dominio marketplace esplicito, i prezzi
        # DI QUELLA RIGA vanno anche sotto la chiave del dominio, non solo
        # sotto la chiave del blocco.
        for riga in blocco_dati.split("\n"):
            riga_lower = riga.lower()
            chiave_dominio = None
            if "ebay." in riga_lower or "ebay.it" in riga_lower or "ebay.com" in riga_lower:
                chiave_dominio = "ebaysold"
            elif "vestiairecollective." in riga_lower:
                chiave_dominio = "vestiairecollective"
            elif "vinted." in riga_lower:
                chiave_dominio = "vinted"
            elif "depop." in riga_lower:
                chiave_dominio = "depop"
            elif "grailed." in riga_lower:
                chiave_dominio = "grailed"
            if chiave_dominio:
                prezzi_riga = _estrai_prezzi_da_pool_ricerca(riga)
                if prezzi_riga:
                    risultato.setdefault(chiave_dominio, set()).update(prezzi_riga)
    return risultato


def _motivo_nessun_prezzo(blocco_fonte):
    """Quando una fonte non ha prodotto prezzi, va a leggere il motivo che
    le funzioni di estrazione (_estrai_articoli_vinted, _estrai_articoli_ebay,
    _serper_batch_query_vestiaire) ora incorporano nel loro stesso testo di
    ritorno quando non trovano nulla -- distingue 'Serper non ha trovato
    proprio niente' da 'Serper ha trovato risultati ma senza un prezzo
    riconoscibile' da 'la richiesta a Serper e' fallita (rete/crediti)'.
    Aggiunto il 2026-09-19 su richiesta esplicita: sapere solo 'nessun
    prezzo' non bastava, serviva vedere se la ricerca aveva davvero
    restituito qualcosa di scartato dopo, o se era vuota dall'inizio."""
    testo = blocco_fonte.strip()
    testo_lower = testo.lower()
    # Controlli sull'INIZIO della stringa (non substring generica): i
    # messaggi di errore vero (rete/crediti) iniziano sempre cosi', mentre
    # "scrape fallito"/"fallito" possono comparire anche DENTRO la spiegazione
    # di uno scenario "0 risultati" (es. "...probabile scrape fallito o
    # pagina bloccata" dentro il messaggio di pagina vuota) -- un controllo
    # a substring qui darebbe falsi positivi "query FALLITA" per quel caso.
    if (
        testo_lower.startswith("serper fallito")
        or testo_lower.startswith("scrape fallito")
        or testo_lower.startswith("ricerca fallita")
        or testo_lower.startswith("ricerca non eseguita")
    ):
        return f"query Serper FALLITA -- {testo}"
    if "categoria non rilevata" in testo_lower:
        return "query saltata (categoria non rilevata dal titolo)"
    if testo_lower == "nessun risultato trovato.":
        return "query Google (site:vestiairecollective.com) interrogata, 0 risultati organici trovati"
    if "pagina scrapata vuota" in testo_lower or testo_lower.startswith("nessun risultato trovato") or testo_lower.startswith("nessun risultato sold trovato"):
        return f"Serper interrogato, 0 risultati -- {testo}"
    if "righe di contenuto scrapate" in testo_lower or "titoli o prezzi trovati singolarmente" in testo_lower:
        return f"Serper ha trovato contenuto ma nessun prezzo utilizzabile -- {testo}"
    # Fallback: testo diagnostico non riconosciuto in uno dei pattern noti
    # (es. "Fonte non disponibile", messaggi futuri) -- lo mostriamo cosi'
    # com'e' invece di nasconderlo dietro un generico "nessun prezzo".
    return testo if testo else "nessun prezzo, motivo non disponibile"


def _riepilogo_comp_per_fonte(pool_ricerca_grezzo):
    """Riassume pool_ricerca_grezzo in UNA riga per fonte (conteggio + range
    di prezzo quando ci sono prezzi, motivo diagnostico quando non ce ne
    sono), invece di riportare gli snippet grezzi Serper per intero --
    pensata per il blocco debug Telegram (DEBUG_CONFRONTO_COMP_TELEGRAM).
    Riconosce i blocchi gia' etichettati "📍 FONTE: <nome>" (comp pre-raccolti
    E ricerche on-demand, entrambi taggati cosi', vedi search_comps_completo/
    chiama_*_cervello_forzato) e spacca il pool su quell'etichetta.

    Aggiornato il 2026-09-19: il ramo 'nessun prezzo' ora richiama
    _motivo_nessun_prezzo per dire ANCHE se Serper ha trovato qualcosa (poi
    scartato/senza prezzo) o non ha trovato proprio nulla -- prima
    'nessun prezzo' copriva indistintamente entrambi i casi, nascondendo se
    la ricerca stessa avesse funzionato."""
    if not pool_ricerca_grezzo or not pool_ricerca_grezzo.strip():
        return "(pool vuoto)"

    blocchi = re.split(r"\n?📍\s*FONTE:\s*", pool_ricerca_grezzo)
    righe = []
    for blocco in blocchi:
        blocco = blocco.strip()
        if not blocco:
            continue
        # Primo blocco (prima della prima 📍) e' l'header "RICERCA WEB
        # PRE-RACCOLTA (...)" senza fonte propria -- non contiene mai prezzi
        # utili, lo saltiamo.
        prima_riga, _, resto = blocco.partition("\n")
        if prima_riga.upper().startswith("RICERCA WEB PRE-RACCOLTA"):
            continue
        nome_fonte = prima_riga.split("(")[0].strip().rstrip(":—-").strip() or prima_riga.strip()
        blocco_dati = resto or blocco
        prezzi_fonte = sorted(_estrai_prezzi_da_pool_ricerca(blocco_dati))
        if not prezzi_fonte:
            righe.append(f"• {nome_fonte}: {_motivo_nessun_prezzo(blocco_dati)}")
        elif len(prezzi_fonte) == 1:
            righe.append(f"• {nome_fonte}: 1 prezzo (€{prezzi_fonte[0]:.2f})")
        else:
            righe.append(
                f"• {nome_fonte}: {len(prezzi_fonte)} prezzi (€{min(prezzi_fonte):.2f}–€{max(prezzi_fonte):.2f})"
            )
    return "\n".join(righe) if righe else "(nessuna fonte con prezzi)"


# URGENZA_RICHIEDE_COMP_REALE: "Alta urgenza" e' l'unico livello che fa
# scattare i bottoni di azione rapida su Telegram, cioe' l'unico che chiede
# all'utente di muoversi subito. Per quel livello si pretende almeno un comp
# realmente presente nel pool di ricerca, non solo comp ricordati dal
# modello (vedi COMP_DA_MEMORIA_AMMESSI): i comp da memoria restano validi
# per calcolare la stima e per COMPRA/TRATTA, ma non bastano da soli a
# dichiarare un'urgenza. Mettere a False per togliere anche questo vincolo.
URGENZA_RICHIEDE_COMP_REALE = True

EMOJI_DECISIONE = {
    "COMPRA": "🟢",
    "TRATTA": "🟡",
    "NON COMPRARE": "🔴",
    "CHIEDI ALTRE FOTO": "🔵",
    "DATI INSUFFICIENTI": "🔵",
}

ETICHETTA_LEGIT = {
    "probabilmente_autentico": "Probabilmente autentico",
    "sospetto_servono_altre_foto": "Sospetto, servono altre foto",
    "probabilmente_falso": "Probabilmente falso",
    "non_verificabile": "Non verificabile",
}

ETICHETTA_RISCHIO = {"basso": "B", "medio": "M", "alto": "A", "molto_alto": "MA"}
ETICHETTA_CONFIDENZA = {"alta": "A", "media": "M", "bassa": "B"}
ETICHETTA_FONTE_COMP = {
    "vinted_testo": "Vinted",
    "vinted_visuale": "Vinted visuale",
    "ebay_poshmark": "eBay/Poshmark",
    "memoria_modello": "memoria modello",
}

# Traduzione dalle chiavi-fonte normalizzate del pool (prodotte da
# _prezzi_per_fonte_da_pool a partire dalle etichette "📍 FONTE: ...") alle
# diciture mostrate accanto a ogni comp nel messaggio Telegram. L'ordine
# conta: si applica il primo prefisso che combacia, e "vintedricercavisuale"
# va controllato PRIMA di "vinted", che ne e' un prefisso.
PREFISSI_FONTE_POOL = [
    ("vintedricercavisuale", "Vinted visuale"),
    ("ricercaondemand", "ricerca on-demand"),
    ("vinted", "Vinted"),
    ("ebayposhmark", "eBay/Poshmark"),
    ("ebaysold", "eBay"),
    ("vestiairecollective", "Vestiaire"),
    ("depop", "Depop"),
    ("grailed", "Grailed"),
]


def _etichetta_fonte_pool(chiave):
    for prefisso, etichetta in PREFISSI_FONTE_POOL:
        if chiave.startswith(prefisso):
            return etichetta
    return "ricerca"


def _a_float(valore, default=None):
    """Conversione tollerante: il JSON strutturato garantisce il TIPO
    dichiarato nello schema, non che il valore sia sensato. Un modello puo'
    comunque restituire una stringa dove lo schema chiede un numero se il
    provider allenta il vincolo, quindi la conversione resta difensiva."""
    if valore is None:
        return default
    if isinstance(valore, bool):
        return default
    if isinstance(valore, (int, float)):
        return float(valore)
    try:
        return float(str(valore).replace("€", "").replace(",", ".").strip())
    except (ValueError, TypeError):
        return default


def valida_payload_cervello(verdetto):
    """Normalizza e mette in sicurezza il JSON ricevuto dal cervello.

    Lo schema garantisce la FORMA (quali campi, di che tipo), non la
    SENSATEZZA dei valori: uno sconto del 95%, un deal score di 47 o un
    prezzo target negativo sono tutti conformi allo schema. I limiti
    numerici si applicano qui, non nello schema, perche' un vincolo
    dichiarato al modello viene rispettato quasi sempre mentre uno
    applicato in codice viene rispettato sempre.

    Ritorna (verdetto_normalizzato, elenco_problemi). I problemi non
    bloccano l'elaborazione: vengono mostrati in coda al messaggio, cosi'
    un campo compilato male resta visibile invece di sparire dietro un
    valore di default silenzioso.
    """
    problemi = []
    v = dict(verdetto or {})

    # --- enum: un valore fuori lista diventa il default piu' prudente
    def _enum(campo, ammessi, default):
        valore = (v.get(campo) or "").strip().lower() if isinstance(v.get(campo), str) else None
        if valore in ammessi:
            v[campo] = valore
            return
        if v.get(campo) is not None:
            problemi.append(f"{campo}='{v.get(campo)}' non riconosciuto, uso '{default}'")
        v[campo] = default

    _enum("corrispondenza_brand",
          {"corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "non_verificabile"},
          "non_verificabile")
    _enum("legit_verdetto",
          {"probabilmente_autentico", "sospetto_servono_altre_foto", "probabilmente_falso", "non_verificabile"},
          "non_verificabile")
    _enum("rischio_fake", {"basso", "medio", "alto", "molto_alto"}, "medio")
    _enum("confidenza", {"alta", "media", "bassa"}, "bassa")
    _enum("profilo_venditore", {"privato_genuino", "reseller_esperto", "non_determinabile"}, "non_determinabile")
    _enum("domanda_mercato", {"alta", "media", "bassa"}, "media")
    _enum("fascia_taglia", {"centrale", "estrema", "ignota"}, "ignota")

    # --- numeri
    v["prezzo_target_vendita_eur"] = _a_float(v.get("prezzo_target_vendita_eur"), 0.0) or 0.0
    if v["prezzo_target_vendita_eur"] <= 0:
        problemi.append("prezzo_target_vendita_eur assente o non positivo")

    v["comp_riferimento_eur"] = _a_float(v.get("comp_riferimento_eur"), None)
    v["tetto_prezzo_linea_eur"] = _a_float(v.get("tetto_prezzo_linea_eur"), None)

    sconto = _a_float(v.get("sconto_ask_applicato_pct"), 25.0) or 25.0
    if not (20 <= sconto <= 30):
        problemi.append(f"sconto ASK {sconto:.0f}% fuori dal range 20-30, riportato nel range")
        sconto = min(30.0, max(20.0, sconto))
    v["sconto_ask_applicato_pct"] = sconto

    # --- sconto difetto: clamp a 0-50, coerente con difetto_significativo.
    v["difetto_significativo"] = bool(v.get("difetto_significativo"))
    v["difetto_strutturale"] = bool(v.get("difetto_strutturale"))
    if v["difetto_strutturale"] and not v["difetto_significativo"]:
        # Un difetto strutturale e' per definizione significativo: la
        # combinazione opposta e' una contraddizione, si tiene la piu' grave.
        v["difetto_significativo"] = True

    # gravita_difetto_strutturale: solo 'grave' blocca automaticamente (vedi
    # calcola_verdetto). Un difetto_strutturale=true senza gravita' valida e'
    # trattato come 'grave' per prudenza -- e' lo stesso principio degli enum
    # dell'Occhio: il default su un campo di rischio e' sempre quello che
    # blocca di piu', mai quello che lascia passare.
    gravita_struct = v.get("gravita_difetto_strutturale")
    gravita_struct = gravita_struct.strip().lower() if isinstance(gravita_struct, str) else None
    if v["difetto_strutturale"]:
        if gravita_struct not in ("lieve", "moderata", "grave"):
            if gravita_struct is not None:
                problemi.append(
                    f"gravita_difetto_strutturale='{v.get('gravita_difetto_strutturale')}' "
                    "non riconosciuta, uso 'grave' (default prudente)"
                )
            gravita_struct = "grave"
    else:
        gravita_struct = None
    v["gravita_difetto_strutturale"] = gravita_struct

    sconto_difetto = _a_float(v.get("sconto_difetto_pct"), 0.0) or 0.0
    if sconto_difetto < 0 or sconto_difetto > 50:
        problemi.append(f"sconto_difetto_pct {sconto_difetto:.0f}% fuori dal range 0-50, riportato nel range")
        sconto_difetto = min(50.0, max(0.0, sconto_difetto))
    if not v["difetto_significativo"] and sconto_difetto > 0:
        problemi.append(f"sconto_difetto_pct={sconto_difetto:.0f}% ignorato: difetto_significativo=false")
        sconto_difetto = 0.0
    if v["difetto_significativo"] and sconto_difetto == 0:
        # dichiarato un difetto ma nessuno sconto: prudenza minima di default
        # invece di lasciarlo a zero come se il difetto non pesasse nulla.
        sconto_difetto = 10.0
        problemi.append("difetto_significativo=true senza sconto_difetto_pct: applicato 10% di default")
    v["sconto_difetto_pct"] = sconto_difetto
    v["descrizione_difetto"] = (v.get("descrizione_difetto") or "").strip() or None

    giorni = _a_float(v.get("giorni_stimati_vendita"), 30.0) or 30.0
    v["giorni_stimati_vendita"] = int(min(365, max(1, giorni)))

    deal = _a_float(v.get("deal_score"), 5.0) or 5.0
    v["deal_score"] = int(min(10, max(1, deal)))

    # --- legit: il motivo deve essere circostanziato quando accusa un falso.
    # Sostituisce verifica_falso_ha_motivazione, che doveva indovinare dal
    # testo se una motivazione fosse presente: qui il campo e' isolato e si
    # controlla direttamente.
    motivo = (v.get("legit_motivo_specifico") or "").strip()
    if v["legit_verdetto"] == "probabilmente_falso" and len(motivo) < 40:
        problemi.append(
            "verdetto 'probabilmente falso' senza motivazione circostanziata: "
            "verificare a mano le foto prima di scartare l'annuncio"
        )
    v["legit_motivo_specifico"] = motivo or "Nessun dettaglio fornito dall'analisi."

    # --- liste
    comp_validi = []
    for grezzo in (v.get("comp_candidati") or []):
        if not isinstance(grezzo, dict):
            continue
        prezzo = _a_float(grezzo.get("prezzo_eur"), None)
        if prezzo is None or prezzo <= 0:
            continue
        comp = dict(grezzo)
        comp["prezzo_eur"] = round(prezzo, 2)
        fonte = (comp.get("fonte") or "").strip().lower()
        comp["fonte"] = fonte if fonte in ETICHETTA_FONTE_COMP else "memoria_modello"
        comp["escluso"] = bool(comp.get("escluso"))
        comp["stessa_categoria"] = bool(comp.get("stessa_categoria", True))
        comp["stessa_linea"] = bool(comp.get("stessa_linea", True))
        comp["titolo_verbatim"] = (comp.get("titolo_verbatim") or "senza titolo").strip()
        comp_validi.append(comp)
    v["comp_candidati"] = comp_validi

    v["segnali_domanda"] = [s for s in (v.get("segnali_domanda") or []) if isinstance(s, str) and s.strip()]
    v["domande_al_venditore"] = [
        d.strip() for d in (v.get("domande_al_venditore") or [])
        if isinstance(d, str) and d.strip()
    ][:2]

    for campo in ("note_analista", "motivo_profilo_venditore", "linea_o_era_rilevata"):
        if not (v.get(campo) or "").strip():
            v[campo] = "non specificato"

    return v, problemi


def classifica_provenienza_comp(v, pool_ricerca_grezzo):
    """Confronta ogni prezzo dichiarato dal cervello con i prezzi realmente
    presenti nel pool di ricerca e ne stabilisce la provenienza REALE.

    Questa funzione sostituisce verifica_comp_citati_sono_reali, e la
    differenza e' tutta nel tipo di dato su cui lavora. Prima il controllo
    doveva ricostruire, da un paragrafo di prosa, quali numeri fossero comp
    citati e quali invece aritmetica del calcolo (fee, spedizione, margine,
    importi scontati), indovinando la fonte dichiarata dalla vicinanza
    testuale di una parola: 300 righe di euristiche, e comunque 4 falsi
    positivi in poche ore. Ora i comp sono una lista di numeri isolati e
    gia' etichettati, quindi il controllo e' una differenza tra insiemi:
    il prezzo compare nel pool oppure no.

    Cosa NON fa piu', per scelta esplicita dell'utente (2026-09-19): non
    declassa nulla e non scarta l'item. Un prezzo che non risulta nel pool
    viene semplicemente marcato 'memoria_modello' e mostrato come tale nel
    messaggio. Vedi COMP_DA_MEMORIA_AMMESSI per la versione stretta.
    """
    prezzi_pool = _estrai_prezzi_da_pool_ricerca(pool_ricerca_grezzo or "")
    # Mappa {chiave_fonte: set(prezzi)}: permette di dire non solo SE un
    # comp e' reale, ma DA QUALE fonte del pool proviene (Vinted testo,
    # ricerca visuale, ricerca on-demand del cervello), cosi' l'etichetta
    # accanto al prezzo nel messaggio Telegram e' quella vera e non quella
    # dichiarata dal modello.
    prezzi_per_fonte = _prezzi_per_fonte_da_pool(pool_ricerca_grezzo or "")

    riclassificati = 0
    for comp in v.get("comp_candidati", []):
        nel_pool = any(
            abs(comp["prezzo_eur"] - reale) <= TOLLERANZA_COMP_EUR for reale in prezzi_pool
        )
        comp["nel_pool"] = nel_pool
        if nel_pool:
            # Se il modello l'aveva marcato come ricordato ma il prezzo c'e'
            # davvero, si fida del dato oggettivo: e' un comp reale.
            comp["fonte_reale"] = comp["fonte"] if comp["fonte"] != "memoria_modello" else "vinted_testo"
            fonti_trovate = [
                _etichetta_fonte_pool(chiave)
                for chiave, prezzi in prezzi_per_fonte.items()
                if any(abs(comp["prezzo_eur"] - prezzo) <= TOLLERANZA_COMP_EUR for prezzo in prezzi)
            ]
            # Lo stesso prezzo puo' comparire in piu' blocchi del pool (es.
            # un risultato Vinted che appare sia nella ricerca testuale sia
            # in quella visuale): si mostrano tutte le fonti in cui e' stato
            # trovato, senza duplicati e in ordine stabile.
            comp["etichetta_fonte"] = " + ".join(dict.fromkeys(fonti_trovate)) or "ricerca"
        else:
            if comp["fonte"] != "memoria_modello":
                riclassificati += 1
            comp["fonte_reale"] = "memoria_modello"
            comp["etichetta_fonte"] = "memoria modello"

    n_memoria = sum(1 for c in v.get("comp_candidati", []) if c["fonte_reale"] == "memoria_modello")
    if riclassificati:
        log.info(
            "classifica_provenienza_comp: %d comp dichiarati come risultati di ricerca non "
            "compaiono nel pool, riclassificati come memoria del modello (pool: %d prezzi).",
            riclassificati, len(prezzi_pool),
        )
    return {
        "n_comp": len(v.get("comp_candidati", [])),
        "n_memoria": n_memoria,
        "n_riclassificati": riclassificati,
        "n_prezzi_pool": len(prezzi_pool),
    }


def _comp_utilizzabili(v):
    """I comp che entrano nel calcolo della stima: non esclusi dal modello,
    stessa categoria, stessa linea, e - solo se COMP_DA_MEMORIA_AMMESSI e'
    False - realmente presenti nel pool."""
    utilizzabili = []
    for comp in v.get("comp_candidati", []):
        if comp.get("escluso") or not comp.get("stessa_categoria") or not comp.get("stessa_linea"):
            continue
        if not COMP_DA_MEMORIA_AMMESSI and comp.get("fonte_reale") == "memoria_modello":
            continue
        utilizzabili.append(comp)
    return utilizzabili


def _percentile(valori_ordinati, p):
    """Percentile p (0-100) su una lista GIA' ordinata, interpolazione
    lineare tra i due valori piu' vicini. Con un solo valore ritorna quello;
    con lista vuota ritorna 0.0 (il chiamante gestisce comunque il caso
    'nessun comp' a monte, qui e' solo per non esplodere)."""
    n = len(valori_ordinati)
    if n == 0:
        return 0.0
    if n == 1:
        return valori_ordinati[0]
    posizione = (p / 100.0) * (n - 1)
    indice_basso = int(posizione)
    indice_alto = min(indice_basso + 1, n - 1)
    frazione = posizione - indice_basso
    return valori_ordinati[indice_basso] + (valori_ordinati[indice_alto] - valori_ordinati[indice_basso]) * frazione


def _filtra_outlier(prezzi):
    """Scarta i comp oltre 3x la mediana o sotto 1/3 della mediana: quasi
    sempre appartengono a un capo diverso (categoria, materiale o edizione)
    o sono un ASK irrealistico finito per errore nei risultati.

    Era una procedura descritta a parole nel prompt e quindi applicata "di
    solito"; ora e' aritmetica e viene applicata sempre. Sotto i 3 prezzi
    non si filtra: con due soli valori la mediana non distingue un outlier
    da un campione piccolo, e scartarne uno lascerebbe la stima appesa a un
    unico comp isolato.
    """
    if len(prezzi) < 3:
        return list(prezzi), []
    mediana = statistics.median(prezzi)
    tenuti = [p for p in prezzi if mediana / 3 <= p <= mediana * 3]
    scartati = [p for p in prezzi if p not in tenuti]
    if len(tenuti) < 2:
        return list(prezzi), []  # il filtro lascerebbe troppo poco: meglio non filtrare
    return tenuti, scartati


def calcola_verdetto(v, prezzo_prodotto):
    """Trasforma i dati del cervello nel verdetto finale. Unico punto del
    bot dove si decide COMPRA/TRATTA/NON COMPRARE e dove si calcolano
    margine, ROI e obiettivo di trattativa."""
    limiti_applicati = []
    # Conta SOLO gli step che riducono davvero il target (limite 1-4 qui
    # sotto), non le note puramente informative aggiunte piu' avanti
    # (vendita lampo, furto istantaneo, taglia estrema, difetto strutturale
    # lieve/moderata non bloccante). Usato in render_messaggio_verdetto per
    # decidere se mostrare il riepilogo "Stima del modello X ridotta a Y":
    # con un solo step il riepilogo e' un doppione esatto della singola riga
    # di dettaglio qui sotto (bug segnalato dall'utente il 2026-09-23 --
    # sembrava un doppio sconto quando era lo stesso identico step mostrato
    # due volte).
    riduzioni_prezzo_target = 0

    if prezzo_prodotto is None or prezzo_prodotto <= 0:
        # Senza il prezzo dell'annuncio non esiste nessun calcolo economico
        # possibile. Meglio dirlo che produrre un NON COMPRARE che sembra un
        # giudizio sul capo quando e' solo un dato mancante.
        return {
            "decisione": "DATI INSUFFICIENTI",
            "urgenza": "Bassa",
            "prezzo_prodotto": prezzo_prodotto,
            "acquisto_pieno": None, "incasso": None, "margine": None, "roi": None,
            "prezzo_target": v.get("prezzo_target_vendita_eur"),
            "vendita_attesa": None, "minimo_accettabile_rivendita": None, "prezzo_da_listare": None,
            "tratta_costo": None, "tratta_margine": None, "tratta_roi": None,
            "comp_usati": [], "comp_scartati_outlier": [],
            "limiti_applicati": ["prezzo dell'annuncio non disponibile: nessun calcolo economico eseguito"],
        }

    acquisto_pieno = (
        prezzo_prodotto * (1 + COMMISSIONE_PROTEZIONE_PCT)
        + COMMISSIONE_PROTEZIONE_FISSA
        + SPEDIZIONE_STIMATA_EUR
    )

    target = v["prezzo_target_vendita_eur"]
    target_dichiarato = target

    # --- limite 1: tetto di linea (es. JEAN'S PAUL GAULTIER)
    tetto = v.get("tetto_prezzo_linea_eur")
    if tetto and target > tetto:
        target = tetto
        limiti_applicati.append(f"tetto di linea €{tetto:.2f} ({v.get('linea_o_era_rilevata')})")
        riduzioni_prezzo_target += 1

    # --- limite 2: ancoraggio al comp di riferimento, gia' scontato
    # (era verifica_ancoraggio_prezzo_comp, 140 righe di regex sul testo)
    fattore_sconto = 1 - v["sconto_ask_applicato_pct"] / 100.0
    riferimento = v.get("comp_riferimento_eur")
    if riferimento and riferimento > 0:
        massimo_consentito = riferimento * fattore_sconto
        if target > massimo_consentito:
            limiti_applicati.append(
                f"ancoraggio al comp di riferimento €{riferimento:.2f} "
                f"scontato {v['sconto_ask_applicato_pct']:.0f}% = €{massimo_consentito:.2f}"
            )
            target = massimo_consentito
            riduzioni_prezzo_target += 1

    # --- limite 3: filtro outlier sui comp utilizzabili
    utilizzabili = _comp_utilizzabili(v)
    prezzi = sorted(c["prezzo_eur"] for c in utilizzabili)
    prezzi_tenuti, prezzi_scartati = _filtra_outlier(prezzi)

    if prezzi_tenuti:
        if v.get("materiale_confermato"):
            # Materiale noto: il tetto e' il comp piu' alto rimasto dopo il
            # filtro, scontato.
            massimo_consentito = max(prezzi_tenuti) * fattore_sconto
            descrizione_limite = f"comp piu' alto €{max(prezzi_tenuti):.2f}"
        else:
            # Materiale non confermato: tetto sul 75* percentile dei comp
            # validi, non piu' sulla mediana. Storia della regola: prima
            # usava il comp piu' economico (troppo punitiva: bastava che il
            # cervello marcasse materiale_confermato a false per prudenza
            # eccessiva -- anche con titolo/etichetta che lo dichiaravano
            # gia' esplicitamente -- per far crollare la stima su un singolo
            # comp isolato in fondo alla forchetta). Corretta alla mediana,
            # che pero' si e' rivelata a sua volta troppo severa: tagliava
            # fuori meta' dei comp e, sommata allo sconto ASK del 25-30%
            # gia' applicato altrove, portava spesso un affare con margine
            # sano vicino al pareggio (caso reale: gonna Marni, mediana
            # comp €59 -> tetto €44.25, quando la stima ragionata del
            # cervello era €55 e i comp arrivavano fino a €100).
            # Il 75* percentile resta piu' prudente del "comp piu' caro"
            # riservato al materiale confermato (non si fida del singolo
            # comp piu' alto, spesso un outlier residuo), ma non scarta piu'
            # a priori la meta' superiore della forchetta: lascia passare la
            # stima del cervello quando e' gia' in linea con il grosso dei
            # comp, e interviene solo quando la supera davvero.
            percentile_75 = _percentile(prezzi_tenuti, 75)
            massimo_consentito = percentile_75 * fattore_sconto
            descrizione_limite = f"materiale non confermato, 75* percentile comp €{percentile_75:.2f}"
        if target > massimo_consentito:
            limiti_applicati.append(
                f"{descrizione_limite} scontato {v['sconto_ask_applicato_pct']:.0f}% = €{massimo_consentito:.2f}"
            )
            target = massimo_consentito
            riduzioni_prezzo_target += 1

    # --- limite 4: sconto per difetto dichiarato sul capo. Si applica DOPO
    # tetto di linea/ancoraggio/materiale perche' riguarda le condizioni di
    # QUESTO esemplare, non il valore di mercato del modello in generale --
    # un difetto va scontato sul prezzo gia' corretto per tutto il resto,
    # non al posto degli altri limiti. Prima non esisteva nessun controllo
    # numerico qui: un difetto descritto a parole in note_analista poteva
    # non riflettersi affatto nel prezzo finale.
    sconto_difetto_pct = v.get("sconto_difetto_pct") or 0.0
    if sconto_difetto_pct > 0:
        target_prima_difetto = target
        target = target * (1 - sconto_difetto_pct / 100.0)
        descrizione_difetto = v.get("descrizione_difetto")
        limiti_applicati.append(
            f"difetto dichiarato ({descrizione_difetto or 'non specificato'}): "
            f"sconto {sconto_difetto_pct:.0f}% da €{target_prima_difetto:.2f} a €{target:.2f}"
        )
        riduzioni_prezzo_target += 1

    # Difetto strutturale 'lieve'/'moderata' (vedi schema): non forza NON
    # COMPRARE (lo fa solo 'grave', piu' sotto), ma la nota resta visibile
    # per una decisione informata invece di sparire dentro il generico
    # "difetto dichiarato" qui sopra.
    if v.get("difetto_strutturale") and v.get("gravita_difetto_strutturale") in ("lieve", "moderata"):
        limiti_applicati.append(
            f"difetto strutturale {v['gravita_difetto_strutturale']} "
            f"({v.get('descrizione_difetto') or 'non specificato'}): non bloccante, "
            "gia' scontato nel prezzo target qui sopra"
        )

    target = max(0.0, round(target, 2))

    # --- incasso = vendita attesa, senza sconto forfettario (tolto il
    # 2026-09-20 su richiesta esplicita dell'utente: il -20% di
    # QUOTA_INCASSO_NETTO sommato alla soglia ROI>=100% rendeva il "minimo
    # accettabile" assurdamente piu' alto della vendita attesa reale, es.
    # caso Missoni: vendita attesa 29.75 ma minimo accettabile 81.50. Da qui
    # in poi compra/tratta si valutano sulla vendita attesa cosi' com'e'.
    # QUOTA_INCASSO_NETTO resta definita sopra ma non e' piu' usata qui.
    vendita_attesa = target
    incasso = vendita_attesa
    margine = incasso - acquisto_pieno
    roi = (margine / acquisto_pieno * 100) if acquisto_pieno > 0 else 0.0

    # minimo prezzo di vendita sotto il quale l'affare non rispetta piu' il
    # margine minimo. Volutamente SENZA il floor ROI>=100% (SOGLIA_ROI_COMPRA)
    # che invece la decisione compra/tratta qui sotto continua a usare:
    # chiarito il 2026-09-20 su richiesta esplicita dell'utente. Nella
    # decisione il floor ROI resta perche' serve a scartare acquisti
    # economici con margine risicato in percentuale; qui invece lo si vuole
    # fuori perche' gonfiava il "minimo accettabile" mostrato in chat ben
    # oltre la vendita attesa reale (es. caso Missoni: vendita attesa 29.75,
    # minimo accettabile arrivava a 81.50 col floor ROI incluso).
    #   margine >= SOGLIA_MARGINE_COMPRA  =>  vendita_attesa >= acquisto_pieno + SOGLIA_MARGINE_COMPRA
    minimo_accettabile_rivendita = round(max(acquisto_pieno + SOGLIA_MARGINE_COMPRA, 0.0), 2)

    # prezzo consigliato in annuncio: vendita_attesa maggiorata di
    # SCONTO_TIPICO_TRATTATIVA_VENDITA, cosi' che dopo la trattativa tipica
    # con l'acquirente si incassi comunque circa vendita_attesa. Non e' il
    # tetto SCONTO_MAX_TRATTATIVA (quello e' lo sconto massimo che NOI
    # accettiamo di offrire quando compriamo, concetto diverso).
    if vendita_attesa > 0 and SCONTO_TIPICO_TRATTATIVA_VENDITA < 1:
        prezzo_da_listare = round(vendita_attesa / (1 - SCONTO_TIPICO_TRATTATIVA_VENDITA), 2)
    else:
        prezzo_da_listare = vendita_attesa

    # --- trattativa: SEMPRE al massimo sconto consentito sul solo prodotto,
    # mai sulla spedizione. Sostituisce applica_soglia_trattativa_40_percento,
    # che correggeva l'offerta ma lasciava dichiaratamente incoerenti margine
    # e ROI della riga corretta (la vecchia nota diceva all'utente di
    # verificarli a mano). Qui sono ricalcolati sullo stesso incasso.
    prezzo_trattato = prezzo_prodotto * (1 - SCONTO_MAX_TRATTATIVA)
    tratta_costo = (
        prezzo_trattato * (1 + COMMISSIONE_PROTEZIONE_PCT)
        + COMMISSIONE_PROTEZIONE_FISSA
        + SPEDIZIONE_STIMATA_EUR
    )
    tratta_margine = incasso - tratta_costo
    tratta_roi = (tratta_margine / tratta_costo * 100) if tratta_costo > 0 else 0.0

    # --- decisione: due vie alternative (richiesto dall'utente il
    # 2026-09-22, dopo un primo tentativo -- rimuovere del tutto il floor
    # ROI -- che l'utente ha corretto subito: il ROI resta rilevante, ma un
    # margine molto alto lo puo' compensare). Via standard: margine>=
    # SOGLIA_MARGINE_COMPRA E roi>=SOGLIA_ROI_COMPRA. Via alternativa: un
    # margine molto piu' alto (SOGLIA_MARGINE_COMPRA_ALTA) con un floor ROI
    # piu' basso (SOGLIA_ROI_COMPRA_RIDOTTA). Esempi confermati dall'utente:
    # margine €30/roi 40% -> NON COMPRA; margine €30/roi 120% -> COMPRA (via
    # standard); margine €100/roi 70% -> COMPRA (via alternativa); margine
    # €80/roi 45% -> NON COMPRA (roi troppo basso anche per la via
    # alternativa). Il -20% forfettario (QUOTA_INCASSO_NETTO) resta tolto:
    # margine/roi qui sono calcolati sull'incasso = vendita attesa piena,
    # senza sconto.
    supera_soglia = (
        (margine >= SOGLIA_MARGINE_COMPRA and roi >= SOGLIA_ROI_COMPRA)
        or (margine >= SOGLIA_MARGINE_COMPRA_ALTA and roi >= SOGLIA_ROI_COMPRA_RIDOTTA)
    )
    tratta_supera_soglia = (
        (tratta_margine >= SOGLIA_MARGINE_COMPRA and tratta_roi >= SOGLIA_ROI_COMPRA)
        or (tratta_margine >= SOGLIA_MARGINE_COMPRA_ALTA and tratta_roi >= SOGLIA_ROI_COMPRA_RIDOTTA)
    )

    # --- eccezione "vendita lampo" (richiesta dall'utente il 2026-09-22):
    # sotto il floor di margine assoluto, un acquisto resta comunque un
    # COMPRA se il capo si vende quasi certamente in 48 ore -- capitale che
    # gira in 2 giorni vale anche con un margine piccolo. Stessa cautela
    # anti-allucinazione gia' usata per l'urgenza "Alta" qui sotto: mai
    # fidarsi di domanda_mercato=='alta' senza segnali_domanda concreti a
    # supporto, altrimenti basterebbe al modello dichiarare "vendo in 2
    # giorni" per bypassare il floor su qualunque cosa. Il margine deve
    # comunque restare positivo: questa e' una scorciatoia sulla VELOCITA'
    # di rientro del capitale, mai una licenza a comprare in perdita.
    vendita_lampo = (
        margine > 0
        and v["giorni_stimati_vendita"] <= SOGLIA_GIORNI_VENDITA_LAMPO
        and v["domanda_mercato"] == "alta"
        and v["segnali_domanda"]
    )

    if v["corrispondenza_brand"] == "brand_estraneo":
        decisione = "NON COMPRARE"
        limiti_applicati.append("brand reale estraneo al segmento monitorato")
    elif v["legit_verdetto"] == "probabilmente_falso":
        decisione = "NON COMPRARE"
    elif v.get("difetto_strutturale") and v.get("gravita_difetto_strutturale") == "grave":
        # Regola di dominio che finora viveva solo come frase nel prompt
        # ("Difetti strutturali = NON COMPRARE sempre, invendibili") e quindi
        # veniva applicata solo se il modello se ne ricordava. Dopo
        # l'introduzione di sconto_difetto_pct il rischio era anzi aumentato:
        # un capo con uno strappo riceveva uno sconto percentuale sul target e,
        # se il prezzo d'acquisto era basso, tornava comunque COMPRA.
        # Qui la regola e' aritmetica e non dipende piu' dal buon senso del
        # modello, a cui resta solo il compito di dire se il difetto c'e'.
        #
        # CORRETTO il 2026-09-20 (caso reale: t-shirt Jean Paul Gaultier
        # d'archivio con un piccolo foro isolato su una manica in tessuto a
        # rete, comprata comunque dall'utente in trattativa): il blocco
        # automatico incondizionato era troppo rigido, stesso difetto della
        # regola "materiale non confermato" prima di essere corretta. Ora
        # blocca solo la gravita' 'grave'; 'lieve' e 'moderata' restano un
        # capo normalmente valutabile, gia' scontato da sconto_difetto_pct
        # qualche riga sopra.
        decisione = "NON COMPRARE"
        limiti_applicati.append(
            f"difetto strutturale grave ({v.get('descrizione_difetto') or 'non specificato'}): "
            "capo invendibile, decisione forzata a NON COMPRARE"
        )
    elif supera_soglia or vendita_lampo:
        # "non_verificabile" NON puo' cadere nel ramo COMPRA. Significa che
        # non c'e' stata nessuna prova di autenticita' da esaminare (nessuna
        # etichetta leggibile), quindi il margine alto e' calcolato su un capo
        # che potrebbe essere qualsiasi cosa: la risposta giusta e' chiedere
        # altre foto, non comprare.
        #
        # Due percorsi lo rendono raggiungibile, entrambi verificati:
        # 1. scraping foto fallito (fallback_solo_cover_photo): lo skip
        #    "nessuna etichetta" viene deliberatamente bypassato per non
        #    perdere l'annuncio, e il Cervello risponde "non_verificabile";
        # 2. payload malformato: valida_payload_cervello usa proprio
        #    "non_verificabile" come default prudente quando l'enum non e'
        #    riconosciuto -- prima di questa correzione un JSON sformato del
        #    Cervello si trasformava in un COMPRA.
        if not supera_soglia:
            limiti_applicati.append(
                f"margine €{margine:.2f} sotto la soglia standard €{SOGLIA_MARGINE_COMPRA:.0f}, ma COMPRA "
                f"confermato per eccezione 'vendita lampo' (~{v['giorni_stimati_vendita']}gg stimati, "
                "domanda alta con segnali concreti)"
            )
        if v["legit_verdetto"] in ("sospetto_servono_altre_foto", "non_verificabile"):
            decisione = "CHIEDI ALTRE FOTO"
        else:
            decisione = "COMPRA"
    elif tratta_supera_soglia:
        decisione = "TRATTA"
    else:
        decisione = "NON COMPRARE"

    # --- "furto istantaneo": elimina la fase di trattativa sotto un prezzo
    # pagato irrisorio con ROI enorme (richiesto dall'utente il 2026-09-22)
    # -- rischiare di perdere un capo del genere per pochi euro di sconto in
    # piu' non vale il tempo della trattativa. Tocca SOLO il ramo TRATTA:
    # non scavalca mai un NON COMPRARE/CHIEDI ALTRE FOTO deciso sopra per
    # motivi di autenticita' o difetto strutturale grave, quella e' sicurezza
    # non economia.
    if decisione == "TRATTA" and prezzo_prodotto < SOGLIA_PREZZO_FURTO_ISTANTANEO and roi >= SOGLIA_ROI_FURTO_ISTANTANEO:
        decisione = "COMPRA"
        limiti_applicati.append(
            f"'furto istantaneo': prezzo pagato €{prezzo_prodotto:.2f} sotto €{SOGLIA_PREZZO_FURTO_ISTANTANEO:.0f} "
            f"con ROI {roi:.0f}% -- trattativa saltata, comprato a prezzo pieno subito"
        )

    # --- taglia estrema/non liquida: normalmente niente COMPRA a prezzo
    # pieno, qualunque sia il brand (richiesto dall'utente il 2026-09-22,
    # "anche se Loro Piana e' Tier-1, una taglia 54 non liquida non paga le
    # bollette") -- il rischio non e' l'autenticita' ma il capitale
    # bloccato troppo a lungo su un capo difficile da rivendere.
    #
    # AFFINATA il 2026-09-24 (utente, caso reale Rick Owens taglia estrema
    # con margine €157.90/ROI 714% declassato comunque a TRATTA): il blocco
    # incondizionato era troppo rigido su un affare fuori scala. Ora
    # l'eccezione margine/ROI di SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE /
    # SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE (vedi sopra) lascia passare il
    # COMPRA quando l'affare e' davvero eccezionale; sotto quella soglia
    # resta il declassamento automatico di prima. Applicata per ULTIMA,
    # dopo anche il 'furto istantaneo' qui sopra: ha sempre l'ultima parola
    # su qualunque altra logica economica, salvo l'eccezione qui sotto.
    taglia_estrema_eccezione = (
        margine >= SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE and roi >= SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE
    )
    if v["fascia_taglia"] == "estrema" and decisione == "COMPRA" and not taglia_estrema_eccezione:
        decisione = "TRATTA" if tratta_supera_soglia else "NON COMPRARE"
        limiti_applicati.append(
            "taglia estrema/non liquida: niente COMPRA a prezzo pieno con margine/ROI ordinari -- "
            "capitale bloccato troppo a lungo su un capo difficile da vendere"
        )
    elif v["fascia_taglia"] == "estrema" and decisione == "COMPRA" and taglia_estrema_eccezione:
        limiti_applicati.append(
            f"taglia estrema/non liquida, ma margine €{margine:.2f}/ROI {roi:.0f}% fuori scala "
            f"(oltre €{SOGLIA_MARGINE_TAGLIA_ESTREMA_ECCEZIONE:.0f}/{SOGLIA_ROI_TAGLIA_ESTREMA_ECCEZIONE:.0f}%): "
            "COMPRA confermato, vale il rischio di liquidita' sulla taglia"
        )

    # --- urgenza: mai dedotta dai soli numeri, serve domanda di mercato reale
    comp_reali = [c for c in utilizzabili if c.get("fonte_reale") != "memoria_modello"]
    urgenza = "Bassa"
    if decisione in ("COMPRA", "TRATTA"):
        urgenza = "Media"
    if (
        decisione == "COMPRA"
        and margine >= SOGLIA_MARGINE_URGENZA
        and roi >= SOGLIA_ROI_URGENZA
        and v["domanda_mercato"] == "alta"
        and v["segnali_domanda"]
        and v["fascia_taglia"] != "estrema"
        and len(prezzi_tenuti) >= 2
        and (not URGENZA_RICHIEDE_COMP_REALE or comp_reali)
    ):
        urgenza = "Alta"

    return {
        "decisione": decisione,
        "urgenza": urgenza,
        "prezzo_prodotto": prezzo_prodotto,
        "acquisto_pieno": acquisto_pieno,
        "incasso": incasso,
        "margine": margine,
        "roi": roi,
        "prezzo_target": target,
        "prezzo_target_dichiarato": target_dichiarato,
        "vendita_attesa": vendita_attesa,
        "minimo_accettabile_rivendita": minimo_accettabile_rivendita,
        "prezzo_da_listare": prezzo_da_listare,
        "tratta_prezzo_prodotto": prezzo_trattato,
        "tratta_costo": tratta_costo,
        "tratta_margine": tratta_margine,
        "tratta_roi": tratta_roi,
        "comp_usati": prezzi_tenuti,
        "comp_scartati_outlier": prezzi_scartati,
        "n_comp_reali": len(comp_reali),
        "limiti_applicati": limiti_applicati,
        "riduzioni_prezzo_target": riduzioni_prezzo_target,
    }


def render_messaggio_verdetto(v, verdetto, problemi=None, stats_comp=None, item_id=None, cover_photo_id=None, brand=None, catalog_id=None, mappa_url_comp=None):
    """Costruisce il messaggio Telegram dal verdetto calcolato. E' l'unico
    posto del bot dove si scrivono emoji di decisione e cifre: il modello
    non produce piu' nessuna delle due, quindi non esiste piu' il caso
    'testo e numeri si contraddicono'.

    Layout riprogettato il 2026-09-20 su indicazione dell'utente (tempo di
    lettura su notifica Telegram ~3 secondi): 3 blocchi ad alto contrasto
    (Deal, Rischio&Liquidita', Azioni con testo copiabile in un tocco via
    singolo backtick) seguiti da un blocco unico di dettaglio/debug in
    fondo ("seminterrato": note analista, motivazioni estese, comp, avvisi).
    Nessuna informazione tolta rispetto a prima, solo riordinata: la vecchia
    versione mischiava dati finanziari e motivazioni discorsive nello stesso
    blocco.

    mappa_url_comp: {(titolo_normalizzato, prezzo_2f): url}, costruita da
    search_comps_completo SOLO sui comp arrivati via scrape diretto (vedi
    _estrai_mappa_url_comp_vinted) e passata qui per riattaccare un link
    cliccabile ai comp elencati sotto -- MAI passata al Cervello, che vede
    solo '- titolo — €prezzo' senza URL (Punto 3 concordato il 2026-09-25:
    rimappare in Python al rendering finale evita sia le allucinazioni di
    link del modello sia la rottura del link quando il titolo viene troncato
    a 60 caratteri o sfuggito da _escapa_markdown_legacy)."""
    dec = verdetto["decisione"]
    emoji = EMOJI_DECISIONE.get(dec, "🔵")

    # === 1. IL DEAL ===
    righe = [f"{emoji} **{dec}** · {verdetto['urgenza']} urgenza"]

    if verdetto["margine"] is None:
        righe.append("💰 Calcolo economico non disponibile: prezzo dell'annuncio non rilevato.")
    else:
        righe.append(
            f"💰 €{verdetto['acquisto_pieno']:.2f} → €{verdetto['incasso']:.2f} = "
            f"**€{verdetto['margine']:.2f} (ROI {verdetto['roi']:.0f}%)**"
        )
        righe.append(
            f"📈 Attesa €{verdetto['vendita_attesa']:.2f} · Listino €{verdetto['prezzo_da_listare']:.2f} "
            f"· Minimo €{verdetto['minimo_accettabile_rivendita']:.2f} · "
            f"{_escapa_markdown_legacy(v.get('linea_o_era_rilevata'))}"
        )
        # --- obiettivo trattativa: mostrato solo quando e' la decisione
        # presa. L'importo e' quello calcolato al massimo sconto consentito,
        # non una proposta del modello, quindi margine e ROI qui sotto sono
        # coerenti con l'incasso del verdetto principale per costruzione.
        if dec == "TRATTA":
            righe.append(
                f"🤝 Offri €{verdetto['tratta_prezzo_prodotto']:.2f} (costo pieno €{verdetto['tratta_costo']:.2f}) "
                f"→ **€{verdetto['tratta_margine']:.2f} (ROI {verdetto['tratta_roi']:.0f}%)**"
            )

    # === 2. RISCHIO & LIQUIDITA' ===
    righe.append("")
    legit = ETICHETTA_LEGIT.get(v["legit_verdetto"], v["legit_verdetto"])
    righe.append(
        f"🏷️ {legit} · Rischio fake {ETICHETTA_RISCHIO.get(v['rischio_fake'], '?')} "
        f"· Conf {ETICHETTA_CONFIDENZA.get(v['confidenza'], '?')}"
    )
    stagione = f" · 📅 fuori stagione, pubblica da {v['mese_consigliato_pubblicazione']}" if v.get("mese_consigliato_pubblicazione") else ""
    righe.append(f"🎯 Deal {v['deal_score']}/10{stagione}")

    # === 3. AZIONI (testo copiabile in un tocco: backtick singolo) ===
    # Il vecchio backstop a colpi di regex (rimozione dei blocchi "Messaggio
    # da inviare"/"Da chiedere" da un testo gia' generato) non serve piu':
    # qui i blocchi si aggiungono, non si tolgono. Il backtick (invece del
    # link Markdown o del testo nudo) fa si' che Telegram lo mostri come
    # blocco monospazio "tocca per copiare" -- comodo per incollarlo diretto
    # nella chat col venditore, richiesto dall'utente il 2026-09-20.
    serve_messaggio = dec in ("TRATTA", "CHIEDI ALTRE FOTO")
    template = (v.get("messaggio_venditore_template") or "").strip()
    messaggio_sostituito = False
    testo_messaggio = None
    domande = v.get("domande_al_venditore") if serve_messaggio else None
    # BUG TROVATO IN PRODUZIONE il 2026-09-21 (log utente, crash totale su un
    # annuncio -- UnboundLocalError, annuncio perso senza notifica): il ramo
    # "if dec == 'TRATTA' and template:" qui sotto non inizializzava
    # domande_incorporate, che pero' viene letta piu' sotto ("if domande and
    # not domande_incorporate"). Bastava un TRATTA con template E domande
    # valorizzate insieme per andarci a sbattere. Gli altri due rami
    # (CHIEDI ALTRE FOTO, else) la inizializzavano gia' entrambi -- qui basta
    # un default prima del blocco if/elif/else invece di doverlo ripetere in
    # ognuno.
    domande_incorporate = False
    if dec == "TRATTA" and template:
        if "{OFFERTA}" in template:
            testo_messaggio = template.replace("{OFFERTA}", f"€{verdetto['tratta_prezzo_prodotto']:.2f}")
        else:
            # Il cervello scrive messaggio_venditore_template SENZA sapere
            # quale decisione prendera' il sistema (la calcola solo dopo,
            # in calcola_verdetto): puo' quindi scrivere un messaggio che
            # da' per scontato l'acquisto a prezzo pieno ("lo prendo
            # subito") anche quando poi la decisione risulta TRATTA.
            # Mandare quel testo contraddirebbe la trattativa mostrata
            # sopra, quindi si sostituisce con un'apertura generica che
            # propone davvero l'offerta calcolata.
            testo_messaggio = (
                f"Ciao! Molto interessato, te lo prenderei subito a "
                f"€{verdetto['tratta_prezzo_prodotto']:.2f}. Fammi sapere se puo' andare, grazie!"
            )
            messaggio_sostituito = True
    elif dec == "CHIEDI ALTRE FOTO":
        # Costruito in Python da un saluto fisso + le domande, IGNORANDO
        # messaggio_venditore_template (bug segnalato dall'utente il
        # 2026-09-20: il template del cervello ripete in prosa le stesse
        # richieste gia' elencate in domande_al_venditore -- caso reale,
        # 3 richieste di foto quasi identiche nello stesso messaggio). Le
        # domande sono gia' testo diretto e completo, non serve altro
        # attorno se non un saluto e un ringraziamento -- stesso principio
        # del resto del sistema ("l'occhio osserva, Python decide"): il
        # modello fornisce i contenuti (le domande), Python decide come
        # assemblarli, cosi' niente piu' duplicazioni.
        domande_incorporate = False
        if domande:
            testo_messaggio = "Ciao! Mi interessa molto questo capo. " + " ".join(domande) + " Grazie!"
            domande_incorporate = True
        elif template:
            testo_messaggio = template.replace("{OFFERTA}", "").strip()
    else:
        domande_incorporate = False
    if testo_messaggio or domande:
        righe.append("")
        righe.append("💬 **Azioni (tocca per copiare):**")
        if testo_messaggio:
            # Dentro un backtick singolo Telegram non scansiona _, *, [ per
            # marcatori di formattazione (e' gia' protetto), ma un backtick
            # LETTERALE nel testo del modello chiuderebbe lo span in anticipo
            # -- tolto invece di sfuggito, un backtick a meta' frase non si
            # legge comunque bene in un messaggio Telegram.
            righe.append(f"`{testo_messaggio.replace('`', chr(39))}`")
            if messaggio_sostituito:
                righe.append(
                    "_⚠️ messaggio del cervello sostituito: proponeva l'acquisto a prezzo pieno "
                    "senza nessuna offerta, in contraddizione con la decisione TRATTA._"
                )
        # Su CHIEDI ALTRE FOTO le domande sono gia' dentro testo_messaggio
        # (vedi sopra): mostrarle di nuovo qui le duplicherebbe una terza
        # volta, esattamente il difetto di verbosita' segnalato il
        # 2026-09-20. Restano mostrate separatamente solo su TRATTA, dove
        # testo_messaggio non le include.
        if domande and not domande_incorporate:
            domande_pulite = [d.replace("`", chr(39)) for d in domande]
            righe.append(f"`{' '.join(domande_pulite)}`")

    # === 4. SEMINTERRATO: analisi, comp, link, avvisi -- tutto cio' che non
    # serve alla decisione immediata ma resta consultabile scorrendo giu' ===
    righe += ["", "---", "🧠 **Analisi dell'analista:**", _escapa_markdown_legacy(v["note_analista"])]
    righe.append(f"_{_escapa_markdown_legacy(v['legit_motivo_specifico'])}_")
    # Il profilo del venditore (nome, recensioni) e' gia' nella riga 👤 in alto: qui resta solo il giudizio
    # dell'analista quando segnala qualcosa (reseller, negozio, account sospetto), non la ripetizione.
    motivo_venditore = v.get("motivo_profilo_venditore")
    if motivo_venditore and motivo_venditore != "non specificato" and re.search(
            r"reseller|rivendit|professional|negozio|commerciant|sospett|bot\b|nuovo account|poche recension|fake",
            motivo_venditore, re.IGNORECASE):
        righe.append(f"👤 {_escapa_markdown_legacy(motivo_venditore)}")

    # --- comp usati, con la provenienza dichiarata accanto a ogni prezzo
    comp_utilizzabili = [c for c in v.get("comp_candidati", []) if not c.get("escluso")]
    comp_visibili = comp_utilizzabili[:6]
    if comp_visibili:
        righe += ["", "📊 **Comp considerati:**"]
        for comp in comp_visibili:
            etichetta = comp.get("etichetta_fonte") or ETICHETTA_FONTE_COMP.get(
                comp.get("fonte_reale", comp["fonte"]), "?")
            titolo = comp["titolo_verbatim"]
            # il titolo copiato dal pool finisce spesso con ' — €120.00': il prezzo e' gia' all'inizio della riga
            titolo = re.sub(r"\s*[—–-]\s*€\s*\d+(?:[.,]\d+)?\s*$", "", titolo)
            titolo = titolo[:60] + "…" if len(titolo) > 60 else titolo
            titolo = _escapa_markdown_legacy(titolo)
            # Link cliccabile al comp (Punto 3, 2026-09-25): lookup deterministico
            # nella mappa costruita da search_comps_completo, MAI un URL scritto
            # dal Cervello. _escapa_markdown_legacy sfugge anche '[' nel titolo,
            # quindi il '[' aggiunto qui sotto per il link resta l'unico non
            # sfuggito -- niente rischio che il titolo stesso apra un altro link.
            url_comp = None
            if mappa_url_comp:
                chiave = (
                    _normalizza_titolo_per_link(comp["titolo_verbatim"]),
                    f"{comp['prezzo_eur']:.2f}",
                )
                url_comp = mappa_url_comp.get(chiave)
            titolo_reso = f"[{titolo}]({url_comp})" if url_comp else titolo
            # Raffina l'etichetta generica ('eBay/Poshmark', 'ricerca
            # on-demand') con la piattaforma reale letta dal dominio
            # dell'URL, quando disponibile -- vedi _etichetta_piattaforma_da_url.
            # Le etichette gia' specifiche (es. 'Vinted visuale') restano
            # invariate: qui si vuole solo togliere ambiguita', non
            # sostituire un'informazione gia' piu' precisa.
            if url_comp and etichetta in ("eBay/Poshmark", "ricerca on-demand"):
                etichetta = _etichetta_piattaforma_da_url(url_comp) or etichetta
            prezzo_comp = f"{comp['prezzo_eur']:.0f}" if float(comp["prezzo_eur"]).is_integer() else f"{comp['prezzo_eur']:.2f}"
            righe.append(f"• €{prezzo_comp} · {titolo_reso} _[{etichetta}]_")
        # Split per fonte calcolato su TUTTI i comp utilizzabili (non solo i
        # primi 6 mostrati sopra in dettaglio) -- richiesto dall'utente il
        # 2026-09-20 per vedere a colpo d'occhio quanto pesa ciascuna fonte
        # (Vinted testo/Serper, Vinted ricerca visuale, ragionamento/memoria
        # del modello) senza dover attivare DEBUG_CONFRONTO_COMP_TELEGRAM,
        # che aggiunge un blocco diagnostico molto piu' verboso e pensato
        # per un altro scopo (confrontare i prezzi citati dal Cervello con
        # quelli davvero ricevuti in pool).
        conteggio_fonti = {}
        for c in comp_utilizzabili:
            fonte = c.get("fonte_reale", c["fonte"])
            conteggio_fonti[fonte] = conteggio_fonti.get(fonte, 0) + 1
        split_txt = " · ".join(
            f"{ETICHETTA_FONTE_COMP.get(fonte, fonte)}: {conteggio_fonti[fonte]}"
            for fonte in ("vinted_testo", "vinted_visuale", "ebay_poshmark", "memoria_modello")
            if conteggio_fonti.get(fonte)
        )
        if split_txt:
            righe.append(f"_Fonti ({len(comp_utilizzabili)} comp, {len(comp_visibili)} mostrati): {split_txt}_")

    # Link manuale alla ricerca visuale: rimosso il 2026-09-25 su richiesta
    # dell'utente (non usa piu' la ricerca visuale per ora, quindi anche il
    # link "fai da te" nel messaggio Telegram non serve). item_id/cover_photo_id
    # restano nella firma della funzione: non fanno piu' nulla qui, ma non e'
    # stato tolto il parametro per non toccare i call site -- coerente con la
    # scelta di lasciare VISUAL_SEARCH_ATTIVA=false innocuo invece di buttare
    # codice.

    if stats_comp and stats_comp.get("n_memoria"):
        n_memoria = stats_comp["n_memoria"]
        n_pool = stats_comp["n_prezzi_pool"]
        quanti = "Tutti i" if n_memoria == stats_comp["n_comp"] else f"{n_memoria} dei"
        quanti_comp = "comp" if n_memoria == stats_comp["n_comp"] else f"{stats_comp['n_comp']} comp"
        if n_pool == 0:
            dove = "la ricerca non ha restituito nessun prezzo"
        elif n_pool == 1:
            dove = "l'unico prezzo trovato dalla ricerca e' diverso"
        else:
            dove = f"non compaiono tra i {n_pool} prezzi trovati dalla ricerca"
        righe.append(
            f"\n_ℹ️ {quanti} {quanti_comp} vengono dalla conoscenza del modello, non da annunci "
            f"verificati: {dove}._"
        )

    if verdetto.get("comp_scartati_outlier"):
        scartati = ", ".join(f"€{p:.2f}" for p in verdetto["comp_scartati_outlier"])
        righe.append(f"_🔎 Scartati dal filtro outlier (oltre 3x o sotto 1/3 della mediana): {scartati}_")

    # --- limiti applicati al prezzo: sostituisce le note "⚠️ corretto
    # automaticamente" che le vecchie reti iniettavano nel testo. Stessa
    # informazione, ma dichiarata prima del calcolo invece che rattoppata dopo.
    if verdetto.get("limiti_applicati"):
        righe.append("")
        # Il riepilogo "Stima del modello X ridotta a Y" ha senso solo come
        # somma di PIU' step in cascata (es. tetto di linea + difetto): con
        # un solo step che ha ridotto il prezzo, la riga di dettaglio
        # qui sotto gia' mostra lo stesso identico prima/dopo con anche il
        # motivo -- ripeterlo qui sembra un secondo sconto separato (bug
        # segnalato dall'utente il 2026-09-23: caso con un solo sconto per
        # difetto, mostrato due volte, letto come due sconti in cascata).
        if (
            verdetto.get("prezzo_target_dichiarato") and verdetto.get("prezzo_target") is not None
            and verdetto.get("riduzioni_prezzo_target", 0) > 1
        ):
            if verdetto["prezzo_target_dichiarato"] > verdetto["prezzo_target"] + 0.01:
                righe.append(
                    f"⚠️ _Stima del modello €{verdetto['prezzo_target_dichiarato']:.2f} "
                    f"ridotta a €{verdetto['prezzo_target']:.2f}._"
                )
        for limite in verdetto["limiti_applicati"]:
            # limite spesso incorpora testo libero del modello (es.
            # v.get('descrizione_difetto') dentro calcola_verdetto), quindi
            # stessa protezione delle altre stringhe grezze qui sopra.
            righe.append(f"⚠️ _{_escapa_markdown_legacy(limite)}_")

    if problemi:
        righe.append("")
        for problema in problemi:
            righe.append(f"⚠️ _Dato anomalo dal cervello: {_escapa_markdown_legacy(problema)}_")

    return "\n".join(righe)


# Stima del prezzo target piu' stabile (richiesto dall'utente il 2026-10-03). Il 2026-10-02 lo stesso
# annuncio (titolo e prezzo identici) e' uscito con target 52 e 160 EUR (abito Dries van Noten), 30 e 75
# (marinière), 45/55/90 (pantalone Gaultier): il Cervello da' numeri diversi alla stessa domanda. Per gli
# annunci che arrivano a COMPRA/TRATTA si chiede il target una o due volte in piu' e si usa la mediana. Non
# e' un tetto al ROI: un'eccezione vera da' sempre numeri alti e coerenti, e resta alta. Se le valutazioni
# divergono molto il messaggio lo dice ("stima instabile").
CERVELLO_CAMPIONI_EXTRA = int(_env_float("CERVELLO_CAMPIONI_EXTRA", 1))  # in parallelo: stessa latenza di 1
CERVELLO_SPREAD_MAX = _env_float("CERVELLO_SPREAD_MAX", 1.35)


def consolida_target_cervello(targets, spread_max=None):
    """Da piu' valutazioni del target al valore da usare. Ritorna (valore, spread, instabile).
    Con 3+ campioni la mediana; con 2 la media se concordano, il piu' basso se divergono."""
    spread_max = CERVELLO_SPREAD_MAX if spread_max is None else spread_max
    validi = sorted(float(t) for t in targets if isinstance(t, (int, float)) and t > 0)
    if not validi:
        return None, None, False
    spread = validi[-1] / validi[0]
    instabile = spread > spread_max
    if len(validi) >= 3:
        valore = statistics.median(validi)
    elif len(validi) == 2:
        valore = validi[0] if instabile else sum(validi) / 2
    else:
        valore = validi[0]
    return valore, spread, instabile
