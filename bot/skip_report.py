"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


from bot.testo import _escapa_markdown_legacy
from bot.occhio import calcola_scarto_occhio
from bot.logger import log
# ---- fine import ----
def _estrai_margine_e_roi_da_blocco(blocco_testo):
    """Estrae margine netto e ROI da un blocco di testo. Gestisce anche i
    range (es. '€27-40 (ROI 110-165%)'), prendendo sempre il valore piu'
    basso come stima prudente -- il regex precedente si fermava sul primo
    numero e falliva silenziosamente quando seguito da un range invece che
    direttamente da 'ROI', lasciando margine=None e bypassando le reti di
    sicurezza a valle."""
    margine_m = re.search(r"€\s*(-?[\d.,]+)(?:\s*[-–]\s*[\d.,]+)?\s*\)?\s*\(?ROI", blocco_testo, re.IGNORECASE)
    roi_m = re.search(r"ROI\s*~?\s*(-?\d+)", blocco_testo, re.IGNORECASE)

    margine = None
    if margine_m:
        try:
            margine = float(margine_m.group(1).replace(",", "."))
        except ValueError:
            pass

    roi = None
    if roi_m:
        try:
            roi = int(roi_m.group(1))
        except ValueError:
            pass

    return margine, roi


def estrai_margine_preliminare(output_occhi_testo):
    """Estrae margine netto e ROI dalla valutazione finanziaria preliminare
    che l'occhio produce (best-effort: i formati variano leggermente)."""
    return _estrai_margine_e_roi_da_blocco(output_occhi_testo or "")


def check_skip_pre_cervello(output_occhi_testo, listing_info=None, occhio_json=None):
    """occhio_json: presente solo con OCCHIO_OUTPUT_JSON=true. In quel caso
    lo scarto si calcola da campi tipizzati invece che cercando sottostringhe
    nella prosa, e tutto il resto di questa funzione non viene eseguito.

    Il ramo su prosa qui sotto resta invariato: e' il comportamento di
    default, quello che gira oggi in produzione."""
    if occhio_json is not None:
        solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
        return calcola_scarto_occhio(occhio_json, solo_cover_photo=solo_cover, listing_info=listing_info)

    testo = (output_occhi_testo or "").lower()

    # NOTA (caso reale osservato): un Dries Van Noten a €5,95 e' stato
    # scartato qui come "falso palese, Confidenza Alta" con dettagli che
    # sembravano inventati, mentre 3 legit check esterni indipendenti sullo
    # stesso capo hanno concluso "Probabilmente autentico" 82-85%. La causa
    # probabile e' un bias "prezzo troppo basso = deve essere falso"
    # nell'occhio. Soluzione scelta: RINFORZARE il prompt dell'occhio (non
    # rimuovere questo filtro, che resta utile per risparmiare token sui
    # falsi genuinamente conclamati).
    # Corretto il 2026-09-19 (caso reale Miu Miu pull cour): DUE bug distinti
    # facevano si' che questo skip non scattasse mai per il formato che
    # l'occhio produce davvero in produzione.
    # 1. Il prompt canonizza solo "Probabilmente falso" tra i 4 verdetti
    #    possibili, ma il modello a volte scrive varianti equivalenti
    #    ("Falso palese", "Falso evidente") per enfatizzare la certezza --
    #    non matchavano nessuna delle stringhe cercate qui sotto.
    # 2. Il template del prompt per la riga finale e' sempre "Confidenza:
    #    [A/M/B]" (vedi riga "Confidenza: [B]"/"Confidenza: [A/M/B]" nel
    #    prompt), cioe' CON i due punti -- "Confidenza: Alta" nel testo
    #    reale, mentre il filtro cercava "confidenza alta" SENZA i due
    #    punti. Il pattern non ha mai potuto matchare il formato standard,
    #    a meno che il testo non contenesse anche "molto alto" o una
    #    percentuale esplicita altrove (raro). Questo era il bug root:
    #    anche un "Probabilmente falso" testuale puro con "Confidenza: Alta"
    #    non veniva riconosciuto. Risultato pratico osservato in produzione:
    #    il cervello veniva comunque consultato e tutte le ricerche di
    #    prezzo (Resellbot/Serper) partivano inutilmente su un verdetto
    #    gia' scontato (NON COMPRARE), sprecando query a pagamento.
    ha_falso_alta_confidenza = (
        "probabilmente falso" in testo
        or "falso conclamato" in testo
        or "falso palese" in testo
        or "falso evidente" in testo
    )
    ha_confidenza_alta = any(c in testo for c in (
        "confidenza alta", "confidenza: alta", "confidenza:alta",
        "90%", "95%", "100%", "molto alto",
    ))
    if ha_falso_alta_confidenza and ha_confidenza_alta:
        return True, "[FALSO CONCLAMATO] Rilevato da analisi visiva con alta confidenza."

    # Skip su brand completamente estraneo (non una sottolinea/diffusion --
    # un marchio diverso e non correlato, es. l'annuncio dichiara "Kapital"
    # ma l'etichetta reale e' "Kapitales", brand francese di souvenir senza
    # alcun legame col Kapital giapponese monitorato). Il prompt dell'occhio
    # istruisce a scrivere la frase esatta "BRAND NON CORRISPONDENTE" solo
    # quando e' sicuro che sia un marchio diverso, non per semplici dubbi --
    # quindi qui e' sicuro fidarsi del match testuale senza ulteriori
    # controlli di confidenza (a differenza del "falso conclamato" sopra,
    # dove il bias prezzo-basso rendeva la sola dichiarazione del modello
    # inaffidabile). Risparmia la ricerca comp del cervello: il verdetto
    # e' gia' scontato (NON COMPRARE) indipendentemente da prezzo/comp.
    if "brand non corrispondente" in testo:
        return True, (
            "[BRAND NON CORRISPONDENTE] L'analisi visiva ha rilevato un marchio diverso "
            "e non correlato rispetto a quello dichiarato nell'annuncio -- cervello non "
            "consultato, il capo non ha valore nel segmento monitorato indipendentemente dal prezzo."
        )

    segnali_danno_fisico = sum([
        "buchi" in testo or "buco" in testo,
        "strappi gravi" in testo or "strappo grave" in testo,
        "bruciature" in testo or "bruciatura" in testo,
        "da riparare" in testo and "non riparabile" in testo,
        "condizione pessima" in testo,
        "indossabile" in testo and "non" in testo,
    ])
    if segnali_danno_fisico >= 2:
        return True, "[CONDIZIONE DISTRUTTA] Danni fisici gravi multipli rilevati dall'analisi visiva."

    # Skip su nessuna etichetta visibile: senza nessuna etichetta il cervello
    # non ha nulla in piu' da aggiungere sull'autenticita' -- l'unico passo
    # utile e' chiedere altre foto, cosa che l'occhio ha gia' suggerito.
    #
    # ECCEZIONE IMPORTANTE: se le foto reali dell'annuncio non sono state
    # scaricate e l'analisi si basa solo sulla cover photo di Telegram, un
    # "nessuna etichetta visibile" e' quasi certamente un falso negativo
    # dovuto allo scraping fallito, non al capo -- in quel caso NON si
    # scarta, si lascia proseguire al cervello.
    solo_cover = bool(listing_info and listing_info.get("fallback_solo_cover_photo"))
    BLOCCO_VERDETTO_INIZIALE = testo[:250]
    ETICHETTA_KEYWORDS_ESPLICITE = [
        "nessuna etichetta visibile", "assenza totale di etichette",
        "etichette non visibili", "zero etichette", "senza etichette visibili",
        "non sono visibili etichette", "nessuna etichetta è visibile",
    ]
    nessuna_etichetta = (
        "non verificabile" in BLOCCO_VERDETTO_INIZIALE
        or any(kw in testo for kw in ETICHETTA_KEYWORDS_ESPLICITE)
    )
    if nessuna_etichetta and not solo_cover:
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] L'analisi visiva non ha trovato etichette "
            "per verificare l'autenticita' -- cervello non consultato, servono piu' foto "
            "(main label + wash tag) prima di procedere."
        )
    if nessuna_etichetta and solo_cover:
        log.info(
            "Skip 'nessuna etichetta' NON applicato: analisi basata solo sulla cover photo "
            "(scraping foto fallito), probabile falso negativo -- si prosegue col cervello."
        )

    # Skip su margine preliminare chiaramente negativo: se anche la stima
    # dell'occhio (di solito ottimistica, senza comp reali) indica gia' una
    # perdita netta o ROI negativo, e' molto improbabile che il cervello,
    # con dati di mercato reali, trovi un risultato migliore.
    margine_prelim, roi_prelim = estrai_margine_preliminare(output_occhi_testo)
    margine_esplicitamente_nullo = any(k in testo for k in (
        "margine nullo", "margine negativo", "nessun valore di rivendita",
        "valore di rivendita non significativo", "non c'è valore di rivendita",
        "non vale il tempo",
    ))
    if margine_esplicitamente_nullo or (margine_prelim is not None and margine_prelim < 0) or (roi_prelim is not None and roi_prelim < 0):
        return True, (
            f"[MARGINE PRELIMINARE NEGATIVO] Stima preliminare dell'occhio indica "
            f"perdita netta (margine={margine_prelim}, ROI={roi_prelim}%) -- "
            "cervello non consultato per risparmiare token."
        )

    return False, None


def build_skip_report(listing_info, motivo_skip, output_occhi_testo=None):
    if motivo_skip.startswith("[MARGINE INSUFFICIENTE"):
        riga_legit = "Non valutato — filtro pre-cervello su margine insufficiente. Autenticita' non in dubbio."
        riga_rischio = "BASSO — margine insufficiente (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[FALSO CONCLAMATO"):
        riga_legit = "Probabilmente falso — rilevato da analisi visiva con alta confidenza."
        if output_occhi_testo:
            dettaglio = None

            # Tentativo 1: formato atteso con intestazione "**Analisi visiva**"
            m_analisi = re.search(
                r"\*\*Analisi visiva\*\*[^\n]*\n+(.+?)(?=\n---|\n##|\n📨|\Z)",
                output_occhi_testo, re.IGNORECASE | re.DOTALL,
            )
            if m_analisi and m_analisi.group(1).strip():
                dettaglio = m_analisi.group(1).strip()

            # Tentativo 2: posizionale -- qualunque cosa segua il primo
            # separatore "---" (che nel template segue sempre il Verdetto).
            if not dettaglio:
                m_pos = re.search(r"\n---\s*\n+(.+?)(?=\n---|\n📨|\Z)", output_occhi_testo, re.DOTALL)
                if m_pos and m_pos.group(1).strip():
                    dettaglio = m_pos.group(1).strip()

            # Tentativo 3 (ultima risorsa): tutto il testo grezzo troncato.
            if not dettaglio:
                testo_grezzo = output_occhi_testo.strip()
                dettaglio = testo_grezzo[:600] + ("..." if len(testo_grezzo) > 600 else "")

            if dettaglio:
                riga_legit = f"Probabilmente falso. Motivo specifico: {dettaglio}"
        riga_rischio = "ALTO — falso conclamato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[BRAND NON CORRISPONDENTE"):
        riga_legit = "Brand non corrispondente — marchio reale sull'etichetta diverso e non correlato a quello dichiarato."
        if output_occhi_testo:
            m_legit = re.search(r"🏷️\s*Legit:\s*([^\n]+)", output_occhi_testo, re.IGNORECASE)
            if m_legit and m_legit.group(1).strip():
                riga_legit = m_legit.group(1).strip()
        riga_rischio = "N/A — brand estraneo al segmento monitorato (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[ANNUNCIO FRAUDOLENTO"):
        # BUG reale trovato il 2026-09-22 rileggendo lo storico Telegram: 12
        # skip su 51 (23%) di questo tipo mostravano tutti il placeholder
        # generico "Motivo di skip automatico non categorizzato" nel
        # messaggio finale, perche' mancava questo branch -- il motivo
        # SPECIFICO (i segnali di rischio annuncio elencati da
        # calcola_scarto_occhio, es. "screenshot_di_altro_annuncio",
        # "watermark_di_altro_sito"...) veniva gia' calcolato correttamente
        # ma andava perso al momento di renderizzare il messaggio, cadendo
        # nel ramo "else" generico invece che in un caso dedicato. Qui si
        # riusa motivo_skip stesso, che contiene gia' l'elenco dei segnali.
        riga_legit = motivo_skip.replace("[ANNUNCIO FRAUDOLENTO] ", "", 1)
        riga_rischio = "ALTO — segnali di frode sull'annuncio stesso (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[TESSUTO NON E' IL BRAND"):
        riga_legit = "Nome citato e' il fornitore del tessuto, non il produttore del capo — comp del brand del tessuto non validi per questo capo."
        riga_rischio = "N/A — produttore reale del capo ignoto (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[MAX MARA SOTTOLINEA SENZA VALORE"):
        riga_legit = "Autenticita' non in dubbio — sottolinea Max Mara non-mainline senza modello iconico ne' materiale pregiato dichiarato, valore strutturalmente troppo basso."
        riga_rischio = "N/A — sottolinea Max Mara sotto soglia (filtro automatico, cervello non consultato)"
    elif motivo_skip.startswith("[CONDIZIONE DISTRUTTA"):
        riga_legit = "Autentico ma condizione fisica gravemente compromessa — non rivendibile."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — cervello non consultato"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE"):
        riga_legit = "Nessuna etichetta visibile nelle foto fornite — autenticita' non verificabile allo stato attuale."
        riga_rischio = "ALTO (non verificabile) — servono piu' foto (filtro pre-cervello, risparmio token)"
    elif motivo_skip.startswith("[NESSUNA ETICHETTA INTERNA - MIU MIU T-SHIRT"):
        riga_legit = "Main label (etichetta interna) non leggibile — su questa categoria non si valuta senza, anche con altre etichette visibili."
        riga_rischio = "ALTO (non verificabile) — regola severa Miu Miu t-shirt, servono foto della main label (filtro pre-cervello)"
    elif motivo_skip.startswith("[MARGINE PRELIMINARE NEGATIVO"):
        riga_legit = "Non valutato nel dettaglio — la stima preliminare indicava gia' una perdita netta."
        riga_rischio = "N/A — margine preliminare negativo (cervello non consultato per risparmiare token)"
    elif motivo_skip.startswith("[CATEGORIA GENERICA NON FLIPPABILE"):
        riga_legit = "Categoria strutturalmente senza mercato — nessun valore di rivendita."
        riga_rischio = "BASSO — categoria non flippabile (filtro pre-Gemini)"
    elif motivo_skip.startswith("[DANNO GRAVE DICHIARATO NEL TESTO"):
        riga_legit = "Non valutato — venditore dichiara esplicitamente un danno grave nel testo."
        riga_rischio = "BASSO (autenticita') / ALTO (condizione) — danno dichiarato dal venditore (filtro pre-Gemini)"
    elif motivo_skip.startswith("[NON ORIGINALE DICHIARATO"):
        riga_legit = "Venditore dichiara esplicitamente che il capo non e' originale."
        riga_rischio = "MOLTO ALTO — non originale per dichiarazione diretta (filtro pre-Gemini)"
    elif motivo_skip.startswith("[TITOLO CON STRINGA DI RICERCA RESIDUA"):
        riga_legit = "Titolo contiene una stringa di ricerca residua ('gilet -blanc') — annuncio non valutato."
        riga_rischio = "BASSO — titolo malformato (filtro pre-Gemini)"
    elif motivo_skip.startswith("[LINEA/VARIANTE ESCLUSA PER BRAND"):
        riga_legit = "Linea o variante esclusa esplicitamente dalle regole di valutazione."
        riga_rischio = "ALTO / SCONVENIENTE — linea esclusa (filtro pre-Gemini)"
    elif motivo_skip.startswith("[VENDITORE IN BLOCKLIST"):
        riga_legit = "Venditore in blocklist (possibile truffatore o perditempo)."
        riga_rischio = "MOLTO ALTO — venditore bloccato (filtro pre-Gemini)"
    elif motivo_skip.startswith("[BRAND IN BLOCKLIST"):
        riga_legit = "Brand escluso in modo permanente dalle regole di valutazione."
        riga_rischio = "N/A — brand bloccato su richiesta esplicita (filtro pre-Gemini)"
    else:
        riga_legit = "Motivo di skip automatico non categorizzato."
        riga_rischio = "N/A — filtro automatico"

    motivo_breve = motivo_skip[:117].rsplit(" ", 1)[0] + "..." if len(motivo_skip) > 120 else motivo_skip

    # Per il caso "nessuna etichetta", riusa il messaggio che l'occhio ha gia'
    # suggerito (di solito chiede foto di main label + wash tag).
    messaggio_skip = "Non necessario."
    if motivo_skip.startswith("[NESSUNA ETICHETTA VISIBILE") and output_occhi_testo:
        m = re.search(
            r"📨\s*\*\*Messaggio da inviare:?\*\*\s*\n\"?([^\n\"]+)",
            output_occhi_testo, re.IGNORECASE,
        )
        if m:
            messaggio_skip = m.group(1).strip()

    # Sfuggiti QUI, tutti insieme e appena prima dell'assemblaggio finale,
    # invece che nei singoli punti sopra dove vengono valorizzati: piu'
    # facile garantire che nessun punto di uscita della funzione se ne
    # dimentichi. riga_rischio non serve escaparla (e' sempre una delle
    # stringhe fisse nel blocco elif qui sopra, mai testo del modello).
    riga_legit = _escapa_markdown_legacy(riga_legit)
    motivo_breve = _escapa_markdown_legacy(motivo_breve)
    messaggio_skip = _escapa_markdown_legacy(messaggio_skip)

    return (
        "## Verdetto operativo\n"
        "- **Decisione:** NON COMPRARE · N/A\n"
        "- **Costo pieno richiesto:** N/A — filtro automatico\n"
        "- **Costo pieno trattato:** N/A\n"
        "- **Vendita probabile:** N/A\n"
        "- **Margine netto:** N/A\n"
        f"- **Deal:** 0/10 · **Margine:** 0/10 · **Liquidita':** Bassa · **Rischio:** {riga_rischio} · **Confidenza:** Alta\n"
        f"- **In una riga:** {motivo_breve}\n\n"
        f"## Legit check\n{riga_legit}\n\n"
        "## Da chiedere\nNon rilevante: filtro automatico attivato.\n\n"
        f"## Messaggio da inviare\n{messaggio_skip}"
    )
