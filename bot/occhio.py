"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


# ---- fine import ----
# PAESE DI PRODUZIONE incoerente col brand (richiesto dall'utente l'8/10: un maglione Prada con etichetta perfetta ma
# "Made in China" era stato giudicato originale; poi esteso a tutti i brand). Due livelli, perche' la conoscenza dei luoghi
# di produzione non e' uguale per tutti i brand:
#  - "forte": il brand produce l'abbigliamento in Italia (o in Europa): un paese lontano (Cina, Bangladesh, Vietnam, India...)
#    e' un falso -> scarto come FALSO CONCLAMATO;
#  - "medio": il brand ha anche linee o periodi con produzione altrove: il paese lontano non scarta, ma l'annuncio non puo'
#    risultare "probabilmente autentico" (il verdetto scende a "sospetto, servono altre foto").
# Gli altri brand (Acne, Jacquemus, Dries Van Noten, Courreges...) producono anche in Asia o in Paesi vari: nessuna regola
# nel codice, ci pensa il giudizio del modello (vedi il prompt: epoca, linea e paese). La tabella e' una stima di chi
# scrive: si corregge o si estende qui, mai dedurre un falso da un paese dubbio.
PRODUZIONE_BRAND = {
    "prada": "forte", "miu miu": "forte", "loro piana": "forte", "brunello cucinelli": "forte",
    "bottega veneta": "forte", "fendi": "forte",
    "max mara": "medio", "zegna": "medio", "loewe": "medio", "missoni": "medio", "marni": "medio",
}
PAESI_LONTANI = (
    "china", "cina", "chine", "prc", "hong kong", "bangladesh", "vietnam", "viet nam", "india", "inde", "cambodia",
    "cambogia", "cambodge", "pakistan", "indonesia", "indonesie", "myanmar", "sri lanka", "thailand", "thailandia",
    "taiwan", "philippines", "filippine",
)
_RE_MADE_IN = re.compile(
    r"(?:made\s+in|fabriqu[eé]e?\s+en|hergestellt\s+in|prodotto\s+in|fabricado\s+en|hecho\s+en|gemaakt\s+in)\s+"
    r"([a-zà-ÿ.' ]{2,28})", re.IGNORECASE)


def paese_incoerente(o, listing_info=None):
    """(paese letto, brand, forza) se sull'etichetta c'e' un paese di produzione lontano per un brand della tabella
    PRODUZIONE_BRAND, altrimenti None. Cerca "Made in ..." nei testi delle etichette, nella composizione e nel campo
    paese_produzione_letto. Pura."""
    li = listing_info or {}
    contesto = " ".join(str(x or "") for x in (li.get("brand"), li.get("title"), o.get("brand_letto_etichetta"))).lower()
    marca = next((m for m in PRODUZIONE_BRAND if m in contesto), None)
    if not marca:
        return None
    testi = [str(e.get("testo_verbatim") or "") for e in (o.get("etichette") or []) if isinstance(e, dict)]
    testi += [str(o.get("composizione_da_etichetta") or "")]
    candidati = [m.group(1) for t in testi for m in _RE_MADE_IN.finditer(t)]
    if o.get("paese_produzione_letto"):
        candidati.append(str(o["paese_produzione_letto"]))
    for c in candidati:
        parole = re.findall(r"[a-zà-ÿ]+", c.lower().replace(".", "").replace("é", "e"))
        coppie = {" ".join(parole[i:i + 2]) for i in range(len(parole))}
        if any(p in PAESI_LONTANI for p in parole) or any(p in PAESI_LONTANI for p in coppie):
            return c.strip().rstrip(".").title(), marca.title(), PRODUZIONE_BRAND[marca]
    return None


def applica_paese_al_verdetto(v, o, listing_info=None):
    """Brand di livello "medio" con paese lontano: il verdetto legit non puo' restare "probabilmente autentico". Modifica v
    in place e ritorna il motivo (o None)."""
    inc = paese_incoerente(o or {}, listing_info)
    if not inc or inc[2] != "medio" or v.get("legit_verdetto") != "probabilmente_autentico":
        return None
    motivo = f"Made in {inc[0]} insolito per {inc[1]}: servono altre foto prima di fidarsi."
    v["legit_verdetto"] = "sospetto_servono_altre_foto"
    v["legit_motivo_specifico"] = motivo + " " + str(v.get("legit_motivo_specifico") or "")
    return motivo


_ETICHETTE_PROVA = {"main_label", "wash_care_tag", "etichetta_composizione", "codice_prodotto", "ologramma_autenticita"}


def riga_controllo_occhio(o, item_id):
    """Riga di log `OCCHIO |` con cio' che l'Occhio ha letto (marchio, rapporto col brand, paese, etichette con leggibilita' e testo):
    senza, un verdetto discutibile non si puo' ricostruire (caso Missoni 9/10). Pura."""
    o = o or {}
    et = "; ".join(f"{e.get('tipo')}:{e.get('leggibilita')}:'{str(e.get('testo_verbatim') or '')[:40]}'"
                   for e in (o.get("etichette") or []) if isinstance(e, dict)) or "-"
    return (f"OCCHIO | item={item_id} | brand_letto='{str(o.get('brand_letto_etichetta') or '-')[:40]}' | "
            f"relazione={o.get('relazione_brand') or '-'} | paese={o.get('paese_produzione_letto') or '-'} | etichette={et}")


# brand per cui l'etichetta INTERNA (lavaggio, composizione, codice) e' l'unica prova: senza, niente COMPRA (10/10, Prada Sport)
BRAND_ETICHETTA_OBBLIGATORIA = ("prada", "miu miu", "max mara", "rick owens", "missoni")
_ETICHETTE_INTERNE = _ETICHETTE_PROVA - {"main_label"}


def applica_prove_al_verdetto(v, o, brand=None):
    """Segna in v se l'Occhio ha visto almeno un'etichetta NITIDA (marchio, wash tag, composizione, codice, ologramma).
    Senza, un "sospetto" non puo' diventare COMPRA anche con margine alto (caso Loewe 8/10: una foto da lontano, etichetta
    parziale, 14 EUR): `calcola_verdetto` lo manda a CHIEDI ALTRE FOTO. Per i brand di BRAND_ETICHETTA_OBBLIGATORIA serve
    un'etichetta INTERNA nitida (`_etichetta_interna_richiesta`): il solo marchio esterno non basta. Modifica v in place."""
    etichette = [e for e in ((o or {}).get("etichette") or []) if isinstance(e, dict) and e.get("leggibilita") == "nitida"]
    v["_etichetta_nitida"] = any(e.get("tipo") in _ETICHETTE_PROVA for e in etichette)
    nome = (brand or "").lower()
    if any(b in nome for b in BRAND_ETICHETTA_OBBLIGATORIA):
        v["_etichetta_interna_richiesta"] = not any(e.get("tipo") in _ETICHETTE_INTERNE for e in etichette)


def calcola_scarto_occhio(o, solo_cover_photo=False, listing_info=None):
    """Ritorna (scarta: bool, motivo: str|None) dai soli campi osservativi.

    solo_cover_photo: se le foto dell'annuncio non sono state scaricate e
    l'analisi si basa sulla sola cover di Telegram, "nessuna etichetta" e'
    quasi certamente un falso negativo dello scraping, non del capo: in quel
    caso non si scarta (stessa eccezione gia' presente oggi nel codice).

    I confronti passano da _norm() anche se valida_payload_occhio ha gia'
    normalizzato: questa funzione decide se spendere o no le ricerche di
    mercato, e un confronto fallito per una maiuscola di troppo significa
    lasciar passare un capo distrutto o un brand estraneo. Costa nulla,
    e regge anche se un domani viene chiamata su un dict non validato.
    """
    def _norm(valore):
        return valore.strip().lower() if isinstance(valore, str) else valore

    if _norm(o.get("relazione_brand")) == "brand_estraneo":
        return True, (
            "[BRAND NON CORRISPONDENTE] L'etichetta mostra un marchio diverso e non "
            f"correlato ({o.get('brand_letto_etichetta') or 'non leggibile'}) -- cervello "
            "non consultato, il capo non ha valore nel segmento monitorato."
        )

    # Regola richiesta dall'utente il 2026-09-21 (caso reale: "Blazer oversize
    # in lana tessuto Loro Piana" valutato COMPRA usando comp di Loro Piana
    # mainline, quando "Loro Piana" nell'etichetta era solo il fornitore del
    # tessuto -- il capo era di un sarto/maker ignoto). Il nome del fornitore
    # di tessuto non e' il brand del capo, quindi non ha senso cercare comp
    # sul brand del tessuto: si scarta a prescindere, stesso principio dello
    # skip "brand estraneo" sopra ma per un errore di lettura diverso (non un
    # marchio sbagliato, ma la categoria di etichetta sbagliata).
    if _norm(o.get("relazione_brand")) == "tessuto_non_brand":
        return True, (
            "[TESSUTO NON E' IL BRAND] L'etichetta letta e' del fornitore del tessuto "
            f"({o.get('brand_letto_etichetta') or 'non specificato'}), non del produttore "
            "del capo -- cervello non consultato, i comp del brand del tessuto non sono "
            "comp validi per un capo di un maker diverso e ignoto."
        )

    # Skip specifico per le sottolinee Max Mara non-mainline (richiesto
    # dall'utente il 2026-09-21). A differenza delle altre sottolinee/collab
    # (MM6, See by Chloe...), che restano sempre "sottolinea_stessa_maison" e
    # vanno al Cervello normalmente, per Max Mara la tabella LINEE E ERE del
    # Cervello dichiara gia' da tempo che Weekend/Studio/Sportmax/Marella/
    # Pennyblack/Max&Co valgono "solo se iconici/materiali pregiati" -- una
    # regola che pero' il Cervello, senza comp reali sotto mano, tende a
    # ignorare di default (stesso bias di sovrastima gia' osservato su Loro
    # Piana maglieria). Si sposta quindi la decisione a monte: si scarta
    # SEMPRE la sottolinea, a meno che l'Occhio non abbia scritto una
    # giustificazione concreta in sottolinea_max_mara_eccezione (modello
    # iconico o materiale pregiato dichiarato in etichetta). Il contesto
    # brand (li) va controllato esplicitamente: "nome_sottolinea" da solo
    # (es. "Weekend") e' una parola troppo generica per fidarsi senza sapere
    # che il capo e' comunque un Max Mara.
    li_contesto = listing_info or {}
    brand_dichiarato_ctx = _norm(li_contesto.get("brand")) or ""
    titolo_e_desc_ctx = f"{_norm(li_contesto.get('title')) or ''} {_norm(li_contesto.get('description')) or ''}"
    nome_sottolinea_norm = _norm(o.get("nome_sottolinea")) or ""
    e_contesto_max_mara = (
        "max mara" in brand_dichiarato_ctx
        or "max mara" in nome_sottolinea_norm
        or "max mara" in titolo_e_desc_ctx
    )
    MAX_MARA_SOTTOLINEE_NON_MAINLINE = (
        "weekend", "studio", "sportmax", "marella", "pennyblack",
        "max&co", "max & co", "max e co",
    )
    if (
        _norm(o.get("relazione_brand")) == "sottolinea_stessa_maison"
        and e_contesto_max_mara
        and any(s in nome_sottolinea_norm for s in MAX_MARA_SOTTOLINEE_NON_MAINLINE)
        and not o.get("sottolinea_max_mara_eccezione")
    ):
        return True, (
            f"[MAX MARA SOTTOLINEA SENZA VALORE] Sottolinea non-mainline "
            f"({o.get('nome_sottolinea') or 'non specificata'}) senza modello iconico ne' "
            "materiale pregiato dichiarato -- cervello non consultato, sotto questa soglia "
            "Weekend/Studio/Sportmax/Marella/Pennyblack/Max&Co valgono strutturalmente "
            "troppo poco per giustificare la ricerca comp."
        )

    # Il falso conclamato richiede anche la controprova anti-bias: senza,
    # e' esattamente il caso Dries Van Noten (autentico a 5,95 EUR scartato
    # come falso con dettagli costruiti a posteriori).
    if (_norm(o.get("verdetto_legit")) == "probabilmente_falso"
            and _norm(o.get("confidenza_legit")) == "alta"
            and o.get("controprova_prezzo_eseguita") is True):
        return True, f"[FALSO CONCLAMATO] {o.get('motivo_sintetico') or 'rilevato dall analisi visiva.'}"

    # Paese di produzione incoerente col brand (8/10): scarto indipendente dal giudizio del modello, che davanti a
    # un'etichetta dall'aspetto perfetto puo' dichiarare "autentico" ignorando il "Made in".
    incoerente = paese_incoerente(o, listing_info)
    if incoerente and incoerente[2] == "forte":
        return True, (
            f"[FALSO CONCLAMATO] Made in {incoerente[0]} su {incoerente[1]}: produzione incoerente col brand "
            "(abbigliamento prodotto in Italia), anche con etichetta dall'aspetto corretto."
        )

    # 'capi_diversi_tra_le_foto' RIMOSSO dallo scarto automatico (richiesto
    # dall'utente il 2026-09-21, dopo ripetuti falsi positivi su annunci
    # genuini -- caso reale "pull à motif vintage": 4 foto vere in f800,
    # nessun avatar/estraneo nel lotto (il bug di scraping del 2026-09-20/21
    # era gia' risolto per questo annuncio), eppure l'Occhio ha comunque
    # giudicato le foto "capi diversi" e l'annuncio e' stato scartato PRIMA
    # di arrivare al Cervello. A differenza degli altri segnali di questo
    # elenco (screenshot di un altro annuncio, watermark, foto di uno
    # schermo, foto stock...), che sono giudizi quasi binari e affidabili,
    # "capi diversi tra le foto" richiede un confronto visivo fine tra piu'
    # immagini che flash-lite sbaglia troppo spesso per giustificare uno
    # scarto SENZA revisione -- il costo di un falso positivo (un affare
    # vero mai notificato, silenziosamente) e' piu' alto del costo di
    # consultare comunque il Cervello su un eventuale falso annuncio vero.
    # Il segnale resta comunque nello schema e finisce nel testo dell'Occhio
    # (vedi render_occhio_da_json piu' sotto, riga "⚠️ Segnali di rischio
    # sull'annuncio"), quindi il Cervello lo VEDE e puo' comunque pesarlo
    # nel proprio ragionamento -- non e' stato ignorato, solo declassato da
    # scarto automatico a indizio.
    # Stessa scelta per 'foto_di_uno_schermo' (richiesto dall'utente il 2026-10-04): non scarta piu', resta
    # nel testo dell'Occhio come indizio per il Cervello. Gli altri segnali (screenshot di un altro annuncio,
    # watermark di un altro sito, descrizione incoerente) scartano come prima.
    # Anche 'foto_stock_non_del_capo' non scarta piu' (richiesto dall'utente il 2026-10-04: i modelli di riserva,
    # Mistral in testa, lo segnalano a torto su foto vere): resta come indizio per il Cervello.
    segnali_non_scartano = ("capi_diversi_tra_le_foto", "foto_di_uno_schermo", "foto_stock_non_del_capo")
    segnali_annuncio_affidabili = [
        s for s in (o.get("segnali_rischio_annuncio") or [])
        if _norm(s) not in segnali_non_scartano
    ]
    if segnali_annuncio_affidabili:
        return True, (
            "[ANNUNCIO FRAUDOLENTO] Segnali sulle immagini: "
            + ", ".join(str(s) for s in segnali_annuncio_affidabili)
        )

    difetti = o.get("difetti") or []
    if sum(1 for d in difetti
           if d.get("strutturale") and _norm(d.get("gravita")) == "grave") >= 1:
        return True, "[CONDIZIONE DISTRUTTA] Danno strutturale grave rilevato dall'analisi visiva."

    etichette = o.get("etichette") or []

    # Regola severa specifica Miu Miu magliette/t-shirt (richiesta
    # dall'utente il 2026-09-20): categoria a rischio fake molto alto e
    # margini spesso risicati, quindi qui il bar per procedere e' piu' alto
    # del generico "una qualunque etichetta leggibile" sotto -- serve
    # SPECIFICAMENTE la main_label (l'etichetta interna, di solito cucita
    # nel collo) leggibile almeno parzialmente. Se manca o e' illeggibile,
    # skip anche se ci sono altre etichette (taglia, composizione, wash
    # tag...) leggibili: per questa categoria quelle da sole non bastano a
    # verificare l'autenticita'. Stessa eccezione "solo cover photo" delle
    # altre regole di skip: senza le foto reali dell'annuncio non si puo'
    # dire con certezza che l'etichetta interna manchi davvero.
    li = listing_info or {}
    brand_dichiarato = _norm(li.get("brand")) or ""
    titolo_e_desc = f"{_norm(li.get('title')) or ''} {_norm(li.get('description')) or ''}"
    e_miu_miu = "miu miu" in brand_dichiarato or "miu miu" in titolo_e_desc
    MAGLIETTA_KEYWORDS = (
        "maglietta", "magliette", "t-shirt", "tshirt", "t shirt", "tee",
        "canotta", "canottiera", "top",
    )
    e_maglietta = any(kw in titolo_e_desc for kw in MAGLIETTA_KEYWORDS)
    if e_miu_miu and e_maglietta and not solo_cover_photo:
        main_label = next((e for e in etichette if _norm(e.get("tipo")) == "main_label"), None)
        main_label_leggibile = bool(
            main_label and _norm(main_label.get("leggibilita")) in ("nitida", "parziale")
        )
        if not main_label_leggibile:
            return True, (
                "[NESSUNA ETICHETTA INTERNA - MIU MIU T-SHIRT] Regola severa di categoria: "
                "sulle magliette Miu Miu serve la main label (etichetta interna) leggibile "
                "per procedere -- rischio fake troppo alto in questa categoria senza, "
                "cervello non consultato anche se altre etichette sono visibili."
            )

    # Regola severa Prada/Miu Miu sulle BORSE (richiesta dall'utente il
    # 2026-09-28: "hanno sempre bisogno del wash tag giusto"). Stesso
    # principio della regola Miu Miu t-shirt qui sopra, estesa ai due brand
    # dello stesso gruppo (Prada possiede Miu Miu, stessi standard di
    # etichettatura) sulla categoria a rischio fake piu' alto e piu' valore
    # medio: una borsa. Il logo esterno (triangolo in metallo, nastro
    # logato) da solo NON basta -- serve il cartellino interno (main_label
    # o wash_care_tag, di solito cucito nella fodera o vicino a una tasca
    # interna, con dicitura "Made in Italy" e codice di controllo) leggibile
    # almeno parzialmente. Senza, si scarta anche se le altre etichette
    # sembrano coerenti -- e' proprio la discrepanza "logo esterno ok,
    # cartellino interno mai fotografato/illeggibile" il pattern piu' comune
    # delle borse contraffatte di questi due brand. Stessa eccezione
    # "solo cover photo" delle altre regole di skip.
    e_prada_o_miumiu = (
        "prada" in brand_dichiarato or "prada" in titolo_e_desc
        or e_miu_miu
    )
    # Solo sul TITOLO e a parola intera: la descrizione cita spesso "dust bag"
    # o "borsa di tela" come accessorio incluso (scarpe, portafogli...), e un
    # match a sottostringa trattava quei capi come borse da scartare.
    BORSA_KEYWORDS = ("borsa", "borsetta", "tracolla", "pochette", "clutch", "bag", "handbag")
    titolo_ctx = re.sub(r"\b(dust\s*bag|dustbag|shopping\s*bag)\b", " ", _norm(li.get("title")) or "")
    e_borsa = any(re.search(r"\b" + re.escape(kw) + r"\b", titolo_ctx) for kw in BORSA_KEYWORDS)
    if e_prada_o_miumiu and e_borsa and not solo_cover_photo:
        # any() su TUTTE le etichette interne: basta che una sola sia leggibile.
        cartellino_leggibile = any(
            _norm(e.get("tipo")) in ("main_label", "wash_care_tag")
            and _norm(e.get("leggibilita")) in ("nitida", "parziale")
            for e in etichette
        )
        if not cartellino_leggibile:
            return True, (
                "[NESSUNA ETICHETTA INTERNA - PRADA/MIU MIU BORSA] Regola severa di categoria: "
                "su una borsa Prada o Miu Miu il logo esterno non basta, serve il cartellino "
                "interno (main label o wash tag, di solito in fodera) leggibile per procedere "
                "-- rischio fake troppo alto in questa categoria senza, cervello non consultato "
                "anche se il logo esterno sembra coerente."
            )

    nessuna_etichetta = not etichette or all(
        _norm(e.get("leggibilita")) == "illeggibile" for e in etichette
    )
    if nessuna_etichetta and not solo_cover_photo:
        return True, (
            "[NESSUNA ETICHETTA VISIBILE] Nessuna etichetta leggibile per verificare "
            "l'autenticita' -- servono piu' foto (main label + wash tag) prima di procedere."
        )

    return False, None


ETICHETTA_VERDETTO_LEGIT = {
    "probabilmente_autentico": "Probabilmente autentico",
    "sospetto_servono_altre_foto": "Sospetto, servono altre foto",
    "probabilmente_falso": "Probabilmente falso",
    "non_verificabile": "Non verificabile",
}


def valida_payload_occhio(occhio):
    """Normalizza il JSON dell'Occhio e ne mette in sicurezza i valori.

    Come valida_payload_cervello: lo schema garantisce la FORMA, non la
    SENSATEZZA. Un enum fuori lista diventa il default piu' prudente, e i
    problemi non bloccano l'elaborazione ma restano visibili.

    Ritorna (dict_normalizzato, elenco_problemi).
    """
    problemi = []
    o = dict(occhio or {})

    def _enum(campo, ammessi, default):
        valore = o.get(campo)
        valore = valore.strip().lower() if isinstance(valore, str) else None
        if valore in ammessi:
            o[campo] = valore
            return
        if o.get(campo) is not None:
            problemi.append(f"{campo}='{o.get(campo)}' non riconosciuto, uso '{default}'")
        o[campo] = default

    _enum("qualita_evidenza",
          {"sufficiente_per_verdetto", "parziale_servono_altre_foto", "insufficiente"},
          "parziale_servono_altre_foto")
    _enum("relazione_brand",
          {"corrisponde", "sottolinea_stessa_maison", "brand_estraneo", "tessuto_non_brand", "non_leggibile"},
          "non_leggibile")
    _enum("coerenza_materiale", {"coerente", "incoerente", "non_valutabile"}, "non_valutabile")
    _enum("livello_fattura",
          {"alta_sartoriale", "buona_industriale", "media", "scadente", "non_valutabile"},
          "non_valutabile")
    _enum("condizione_osservata",
          {"come_nuovo", "ottime", "buone", "usato_evidente", "danneggiato"}, "buone")
    _enum("verdetto_legit",
          {"probabilmente_autentico", "sospetto_servono_altre_foto",
           "probabilmente_falso", "non_verificabile"},
          "non_verificabile")
    _enum("confidenza_legit", {"alta", "media", "bassa"}, "bassa")
    _enum("profilo_venditore",
          {"privato_genuino", "reseller_esperto", "non_determinabile"}, "non_determinabile")

    for campo in ("etichette", "difetti", "riscontri_autenticita", "indicatori_costruzione",
                  "evidenze_datazione", "foto_mancanti_richieste", "segnali_rischio_annuncio"):
        if not isinstance(o.get(campo), list):
            o[campo] = []

    # Scarta le voci malformate invece di farle esplodere a valle.
    o["etichette"] = [
        e for e in o["etichette"]
        if isinstance(e, dict) and (e.get("testo_verbatim") or "").strip()
    ]
    o["difetti"] = [d for d in o["difetti"] if isinstance(d, dict) and d.get("tipo")]
    o["riscontri_autenticita"] = [
        r for r in o["riscontri_autenticita"]
        if isinstance(r, dict) and (r.get("osservazione") or "").strip()
    ]

    # OCCHIO_RESPONSE_SCHEMA_GEMINI (lo schema realmente spedito a Gemini)
    # non ha piu' maxItems su questi tre array: il limite ora si applica
    # qui, non piu' lato API. Vedi il commento sopra OCCHIO_RESPONSE_SCHEMA.
    o["etichette"] = o["etichette"][:8]
    o["difetti"] = o["difetti"][:8]
    o["riscontri_autenticita"] = o["riscontri_autenticita"][:8]

    # Normalizzazione degli enum ANNIDATI. Lo schema li dichiara minuscoli ma
    # il modello a volte capitalizza ("Grave" invece di "grave"), e su questi
    # campi non c'e' un default prudente che salvi: un confronto fallito in
    # calcola_scarto_occhio significa un difetto strutturale grave NON
    # riconosciuto, quindi un annuncio distrutto che prosegue come se fosse
    # integro. Si normalizza qui, una volta, invece di ripetere .lower() a
    # ogni confronto sparso nel codice.
    ENUM_ANNIDATI = {
        "etichette": ("tipo", "leggibilita"),
        "difetti": ("tipo", "gravita", "fonte"),
        "riscontri_autenticita": ("elemento", "esito", "peso"),
    }
    for nome_array, campi in ENUM_ANNIDATI.items():
        for voce in o[nome_array]:
            for campo in campi:
                if isinstance(voce.get(campo), str):
                    voce[campo] = voce[campo].strip().lower()
            if nome_array == "difetti":
                voce["strutturale"] = bool(voce.get("strutturale"))

    o["segnali_rischio_annuncio"] = [
        s.strip().lower() for s in o["segnali_rischio_annuncio"] if isinstance(s, str) and s.strip()
    ]

    o["controprova_prezzo_eseguita"] = bool(o.get("controprova_prezzo_eseguita"))

    # Un "probabilmente falso" senza nemmeno un riscontro incoerente e' il
    # sintomo esatto del bias prezzo-basso: la conclusione non discende da
    # nessuna osservazione messa per iscritto. Non si sovrascrive il
    # verdetto (potrebbe essere corretto), ma si toglie la confidenza alta,
    # che e' cio' che fa scattare lo scarto automatico.
    if o["verdetto_legit"] == "probabilmente_falso":
        incoerenti = [r for r in o["riscontri_autenticita"] if r.get("esito") == "incoerente"]
        if not incoerenti:
            problemi.append(
                "verdetto 'probabilmente falso' senza nessun riscontro incoerente: "
                "confidenza declassata, verificare a mano prima di scartare"
            )
            o["confidenza_legit"] = "bassa"

    for campo in ("motivo_sintetico", "sintesi_visiva", "evidenza_profilo",
                  "categoria_capo_osservata"):
        if not isinstance(o.get(campo), str):
            o[campo] = ""
        o[campo] = o[campo].strip()

    # Nullable per costruzione (vedi descrizione nello schema): un valore
    # assente o vuoto significa "nessuna eccezione", non "stringa vuota" --
    # calcola_scarto_occhio tratta i due casi allo stesso modo, ma tenerlo
    # None invece di "" evita ambiguita' a chi legge il payload validato.
    if not isinstance(o.get("sottolinea_max_mara_eccezione"), str) or not o["sottolinea_max_mara_eccezione"].strip():
        o["sottolinea_max_mara_eccezione"] = None
    else:
        o["sottolinea_max_mara_eccezione"] = o["sottolinea_max_mara_eccezione"].strip()

    # dettaglio_distintivo_ricerca (aggiunto il 2026-09-25): stessa
    # normalizzazione nullable-per-costruzione di sottolinea_max_mara_eccezione
    # sopra -- usato per la query Resellbot/eBay/Poshmark, vedi
    # _cerca_ebay_sold_via_resellbot.
    if not isinstance(o.get("dettaglio_distintivo_ricerca"), str) or not o["dettaglio_distintivo_ricerca"].strip():
        o["dettaglio_distintivo_ricerca"] = None
    else:
        o["dettaglio_distintivo_ricerca"] = o["dettaglio_distintivo_ricerca"].strip()

    return o, problemi


def render_occhio_da_json(occhio, problemi=None):
    """Converte il JSON dell'Occhio nel formato testuale che il resto della
    pipeline gia' consuma.

    E' il punto che tiene piccola la modifica: build_skip_report continua a
    cercare "**Analisi visiva**", "🏷️ Legit:" e "📨 **Messaggio da inviare:**"
    con le stesse regex di sempre, e il prompt del Cervello riceve un blocco
    di testo come prima -- solo piu' ricco e senza numeri inventati.

    Nessuna cifra economica compare qui: in modalita' JSON l'Occhio non
    produce piu' margine/ROI/decisione, quindi non c'e' nulla da estrarre
    con estrai_margine_preliminare (lo skip su margine preliminare non si
    applica a questo ramo, per costruzione).
    """
    o = occhio or {}
    righe = ["**Analisi visiva**", o.get("sintesi_visiva") or "(nessuna sintesi fornita)"]

    etichette = o.get("etichette") or []
    if etichette:
        righe.append("")
        righe.append("Etichette lette:")
        for e in etichette:
            nota = f" [{e['osservazioni_tecniche']}]" if e.get("osservazioni_tecniche") else ""
            righe.append(
                f"- {e.get('tipo', 'altro')}: \"{e.get('testo_verbatim', '')}\" "
                f"({e.get('leggibilita', 'n/d')}){nota}"
            )
    else:
        righe += ["", "Etichette lette: nessuna leggibile nelle foto."]

    if o.get("composizione_da_etichetta"):
        righe.append(f"Composizione da etichetta: {o['composizione_da_etichetta']}")
    if o.get("materiale_osservato_dalle_foto"):
        righe.append(f"Materiale osservato: {o['materiale_osservato_dalle_foto']} "
                     f"(coerenza con l'etichetta: {o.get('coerenza_materiale', 'non_valutabile')})")
    if o.get("taglia_etichetta"):
        righe.append(f"Taglia da etichetta: {o['taglia_etichetta']}")
    if o.get("paese_produzione_letto"):
        righe.append(f"Paese di produzione da etichetta: {o['paese_produzione_letto']}")
    if o.get("linea_o_era"):
        evidenze = "; ".join(o.get("evidenze_datazione") or []) or "nessuna evidenza dichiarata"
        righe.append(f"Linea/era: {o['linea_o_era']} (evidenze: {evidenze})")
    if o.get("modello_riconosciuto"):
        righe.append(f"Modello riconosciuto: {o['modello_riconosciuto']}")
    if o.get("indicatori_costruzione"):
        righe.append(f"Fattura ({o.get('livello_fattura', 'n/d')}): "
                     + "; ".join(o["indicatori_costruzione"]))
    if o.get("hardware_dettaglio"):
        righe.append(f"Hardware: {o['hardware_dettaglio']}")

    difetti = o.get("difetti") or []
    if difetti:
        righe.append("")
        righe.append(f"Condizione osservata: {o.get('condizione_osservata', 'n/d')}. Difetti:")
        for d in difetti:
            strutturale = ", STRUTTURALE" if d.get("strutturale") else ""
            righe.append(
                f"- {d.get('tipo')} ({d.get('gravita', 'n/d')}{strutturale}) "
                f"in {d.get('posizione', 'posizione non indicata')} "
                f"[{d.get('fonte', 'n/d')}]"
            )
    else:
        righe.append(f"Condizione osservata: {o.get('condizione_osservata', 'n/d')}, nessun difetto rilevato.")

    riscontri = o.get("riscontri_autenticita") or []
    if riscontri:
        righe.append("")
        righe.append("Riscontri di autenticita':")
        for r in riscontri:
            righe.append(
                f"- {r.get('elemento')}: {r.get('osservazione')} "
                f"-> {r.get('esito')} (peso {r.get('peso')})"
            )

    if o.get("segnali_rischio_annuncio"):
        righe.append("")
        righe.append("⚠️ Segnali di rischio sull'annuncio: "
                     + ", ".join(o["segnali_rischio_annuncio"]))

    legit = ETICHETTA_VERDETTO_LEGIT.get(o.get("verdetto_legit"), o.get("verdetto_legit") or "n/d")
    righe += [
        "",
        "## Verdetto",
        f"🏷️ Legit: {legit} — {o.get('motivo_sintetico') or 'nessun motivo fornito'}",
        f"🕐 Confidenza: {(o.get('confidenza_legit') or 'bassa').capitalize()} · "
        f"Evidenza fotografica: {o.get('qualita_evidenza', 'n/d')} · "
        f"Venditore: {o.get('profilo_venditore', 'n/d')}",
    ]
    if o.get("evidenza_profilo"):
        righe.append(f"👤 {o['evidenza_profilo']}")

    foto_mancanti = o.get("foto_mancanti_richieste") or []
    if foto_mancanti:
        righe += [
            "",
            "---",
            "📨 **Messaggio da inviare:**",
            f'"Buongiorno, potrebbe cortesemente aggiungere qualche foto? {"; ".join(foto_mancanti)}. Grazie mille."',
        ]

    if problemi:
        righe.append("")
        for p in problemi:
            righe.append(f"⚠️ _Dato anomalo dall'analisi visiva: {p}_")

    return "\n".join(righe)
