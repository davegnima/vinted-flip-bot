"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
import html


from bot.costanti import CATEGORIA_KEYWORDS
from bot.testo import _RE_ALT_PRODOTTO_VINTED, _RE_PRODOTTO_VINTED_CON_ID, _normalizza_titolo_per_dedup, _normalizza_titolo_per_link
from bot.logger import log
# ---- fine import ----
# Falsi positivi idiomatici: "dress" in "dress shirt"/"dress pants" e' un
# aggettivo (capo elegante), non indica un abito. Senza questa esclusione,
# il filtro categoria "abito" li fa passare per errore.
ESCLUSIONI_FALSI_POSITIVI_CATEGORIA = {
    "abito": ["dress shirt", "dress pants", "dress code", "dress shoes"],
}

# Rumore generico da scartare sempre, indipendentemente dalla categoria:
# taglie bambino (non comparabili a un capo adulto), collab diffusion
# economiche (es. "for Target"), e frasi che indicano che il brand e' citato
# solo come RIFERIMENTO/ispirazione, non come brand reale del prodotto.
RUMORE_GENERICO_COMP = [
    # taglie/target bambino
    "girls age", "boys age", "kids size", "toddler", "baby size",
    "girl's", "girls'", "girls ", " girls", "boy's", "boys'", "boys ", " boys",
    "kids ", " kids", "kids logo", "kids cotton",
    "years old", "age 4", "age 6", "age 8", "age 10", "age 12",
    # collab diffusion economiche
    "for target", "x target", "for h&m", "x h&m",
    # brand citato solo come riferimento/ispirazione, non prodotto reale
    "similar to", "similar graphic", "similar style to", "inspired by",
    "reference to", "in the style of", "style of", "style inspired",
    "homage to", "tribute to",
]

# Per ogni brand monitorato, le sue sottolinee/collaborazioni da escludere
# SEMPRE dai comp quando si valuta la linea principale -- condividono il
# nome brand nei titoli ma appartengono a fasce di prezzo completamente
# diverse (es. Y-3 e' streetwear di massa via Adidas, non Yohji Yamamoto
# mainline; See by Chloe' e' diffusion, non Chloe' mainline).
BRAND_SOTTOLINEE_DA_ESCLUDERE = {
    "chloé": ["see by chloé", "see by chloe"],
    "chloe": ["see by chloé", "see by chloe"],
    "yohji yamamoto": ["y-3", "y3 ", " y3", "y-3 adidas", "adidas y-3"],
    "alexander mcqueen": ["mcq alexander mcqueen", " mcq "],
    "maison margiela": ["mm6"],
    "margiela": ["mm6"],
    "missoni": ["missoni sport", "missoni home", "missoni mare", "missoni kids", "missoni junior"],
    "stella mccartney": ["adidas by stella mccartney", "stella mccartney for adidas", "adidas x stella mccartney", "pour adidas"],
    "raf simons": ["fred perry x raf simons", "raf simons x fred perry", "calvin klein x raf simons"],
    # Aggiunti: stessa logica, brand delle watch che hanno sottolinee/collab
    # a fascia di prezzo molto piu' bassa e che contaminano i comp.
    "helmut lang": ["helmut lang jeans"],
    "issey miyake": ["me issey miyake", "haat", "bao bao"],
    "max mara": ["weekend max mara", "max mara weekend", "max mara studio", "sportmax", "marella", "pennyblack", "max&co", "max & co"],
    "jean paul gaultier": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "jpg": ["jpg jean's", "jean's paul gaultier", "gaultier2", "junior gaultier"],
    "arc'teryx": ["arc'teryx lt", "arcteryx kids"],
    "moschino": ["love moschino", "moschino jeans", "boutique moschino"],
    "armani": ["emporio armani", "armani exchange", "armani jeans", "a|x"],
    "versace": ["versace jeans", "versus versace", "versace collection"],
    "vivienne westwood": ["vivienne westwood anglomania kids"],
}


def _filtra_comp_per_brand_sottolinee(testo_comp, brand):
    """Esclude dai comp le righe che appartengono a una sottolinea/collab
    nota del brand (vedi BRAND_SOTTOLINEE_DA_ESCLUDERE), che altrimenti
    contamina la stima con prezzi di una fascia di mercato completamente
    diversa pur condividendo il nome brand nel titolo."""
    if not testo_comp or not brand:
        return testo_comp

    sottolinee = BRAND_SOTTOLINEE_DA_ESCLUDERE.get(brand.strip().lower(), [])
    if not sottolinee:
        return testo_comp

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            if any(sub in riga_lower for sub in sottolinee):
                scartate += 1
                continue
        righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_brand_sottolinee: scartate %d righe di sottolinea/collab per brand '%s'.", scartate, brand)

    return "\n".join(righe_filtrate)


# Valori di linea_o_era che NON sono un'etichetta letterale spendibile come
# testo di ricerca (una descrizione di epoca/generica, non qualcosa che
# compare scritto su un'etichetta o in un titolo Vinted) -- esclusi
# dall'arricchimento della ricerca comp sotto per non aggiungere rumore.
LINEA_O_ERA_NON_UTILI_PER_RICERCA = {"mainline", "non determinabile", "non_determinabile"}


def _e_linea_o_era_utile_per_ricerca(linea_o_era):
    """True se linea_o_era e' un'etichetta letterale spendibile in una query
    di ricerca (es. "JEAN'S PAUL GAULTIER", "JPG.JEAN'S", "Veilance", "Linea
    10"), False se e' una descrizione di era/epoca generica (es. "Era Lang
    1986-2005") o un valore segnaposto ("mainline", "non determinabile") che
    aggiungerebbe solo rumore invece di aiutare la ricerca."""
    if not linea_o_era or not isinstance(linea_o_era, str):
        return False
    testo = linea_o_era.strip()
    if not testo or testo.lower() in LINEA_O_ERA_NON_UTILI_PER_RICERCA:
        return False
    # Una descrizione di era contiene quasi sempre un anno a 4 cifre
    # ("1986-2005", "post-2006", "pre-2012"): utile per il Cervello come
    # informazione (resta in linea_o_era_rilevata), ma inutile come testo di
    # ricerca letterale -- nessuna etichetta reale scrive "post-2006" su un
    # capo, quindi cercarlo alla lettera non trova nulla.
    if re.search(r"\b(19|20)\d{2}\b", testo):
        return False
    return True


def _arricchisci_brand_per_ricerca(brand_annuncio, occhio_json):
    """Brand/etichetta da usare per la ricerca comp (Serper), arricchito con
    la sottolinea o la linea/etichetta specifica lette dall'Occhio quando
    presenti e utili come testo di ricerca. Richiesto dall'utente il
    2026-09-22 ("assicurati che quando la linea e' M Missoni o Jean's Paul
    Gaultier il modello usi quella linea per trovare comp -- cosi' per tutte
    le sottolinee"): generalizza due casi gia' osservati in produzione,
    entrambi con lo stesso sintomo (comp della linea sbagliata, spesso piu'
    cari, trattati come validi perche' la ricerca usava solo il brand madre).

    1. Sottolinee con un nome diverso dal brand principale (Weekend Max
       Mara, M Missoni, MM6...): gia' coperte da nome_sottolinea quando
       relazione_brand == "sottolinea_stessa_maison" (fix del 2026-09-20).
    2. Linee/etichette dello STESSO brand nominale ma con un testo di
       etichetta specifico da cercare alla lettera per non mischiare fasce
       di prezzo diverse (caso reale JPG: "JEAN'S PAUL GAULTIER" con
       apostrofo vs "JPG.JEAN'S" sono due diffusion diverse, ma "Jean Paul
       Gaultier" da solo non fa questa distinzione nella ricerca comp):
       coperte da linea_o_era, indipendentemente da relazione_brand, filtrato
       da _e_linea_o_era_utile_per_ricerca per escludere descrizioni di era
       generiche.

    Il campo brand del listing riflette quasi sempre solo il brand madre
    scelto dal venditore, mai la sottolinea/linea specifica -- senza questo
    arricchimento quel testo e' l'unico usato per la ricerca comp.
    """
    if not occhio_json:
        return brand_annuncio

    brand_annuncio_norm = (brand_annuncio or "").strip().lower()
    etichette_da_aggiungere = []

    if occhio_json.get("relazione_brand") == "sottolinea_stessa_maison":
        nome_sottolinea = str(occhio_json.get("nome_sottolinea") or "").strip()
        if nome_sottolinea and nome_sottolinea.lower() not in brand_annuncio_norm:
            etichette_da_aggiungere.append(nome_sottolinea)

    linea_o_era = str(occhio_json.get("linea_o_era") or "").strip()
    if (
        _e_linea_o_era_utile_per_ricerca(linea_o_era)
        and linea_o_era.lower() not in brand_annuncio_norm
        and linea_o_era.lower() not in (e.lower() for e in etichette_da_aggiungere)
    ):
        etichette_da_aggiungere.append(linea_o_era)

    if not etichette_da_aggiungere:
        return brand_annuncio

    brand_arricchito = " ".join(etichette_da_aggiungere + [brand_annuncio or ""]).strip()
    log.info(
        "process_listing: brand arricchito per la ricerca comp: '%s' -> '%s' "
        "(sottolinea/linea letta dall'Occhio sull'etichetta).",
        brand_annuncio, brand_arricchito,
    )
    return brand_arricchito


def _filtra_comp_per_categoria(testo_comp, categoria):
    """Filtra le righe comp che non contengono nessuna keyword della
    categoria rilevata (in nessuna lingua tra quelle coperte da
    CATEGORIA_KEYWORDS), scartando anche falsi positivi idiomatici e
    rumore generico (taglie bambino, collab diffusion economiche).
    Necessario perche' eBay/Vestiaire a volte restituiscono risultati
    "correlati al brand" fuori categoria nonostante la query includa la
    categoria -- il motore di ricerca della fonte non la rispetta
    rigidamente, quindi il filtro va fatto sui risultati."""
    if not testo_comp or not categoria:
        return testo_comp

    keywords = CATEGORIA_KEYWORDS.get(categoria, [])
    if not keywords:
        return testo_comp

    esclusioni = ESCLUSIONI_FALSI_POSITIVI_CATEGORIA.get(categoria, [])

    righe_filtrate = []
    scartate = 0
    for riga in testo_comp.split("\n"):
        if riga.strip().startswith("-"):
            riga_lower = riga.lower()
            e_rumore = any(kw in riga_lower for kw in RUMORE_GENERICO_COMP)
            e_falso_positivo = any(kw in riga_lower for kw in esclusioni)
            match_categoria = any(kw in riga_lower for kw in keywords)
            if match_categoria and not e_rumore and not e_falso_positivo:
                righe_filtrate.append(riga)
            else:
                scartate += 1
        else:
            righe_filtrate.append(riga)

    if scartate:
        log.info("_filtra_comp_per_categoria: scartate %d righe fuori categoria/rumore '%s'.", scartate, categoria)

    return "\n".join(righe_filtrate)


def _rimuovi_comp_autoreferenziale(testo_comp_vinted, titolo_annuncio):
    """Filtra dai comp Vinted l'annuncio stesso in valutazione, che spesso
    compare tra i risultati di ricerca (stesso titolo) senza essere un dato
    di mercato indipendente -- rischia di essere scambiato per un comp
    reale invece che per l'oggetto stesso."""
    if not testo_comp_vinted or not titolo_annuncio:
        return testo_comp_vinted

    titolo_norm = _normalizza_titolo_per_dedup(html.unescape(titolo_annuncio))
    righe_filtrate = []
    for riga in testo_comp_vinted.split("\n"):
        m = re.match(r"-\s*(.+?)\s*—\s*€", riga)
        if m and _normalizza_titolo_per_dedup(html.unescape(m.group(1))) == titolo_norm:
            continue
        righe_filtrate.append(riga)
    return "\n".join(righe_filtrate)


def _estrai_articoli_da_alt_vinted(html_content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dagli attributi alt= delle immagini
    prodotto nell'HTML grezzo di una pagina catalogo Vinted (vedi
    _RE_ALT_PRODOTTO_VINTED per il pattern esatto). Stesso formato di
    output di _estrai_articoli_vinted ('- titolo — €prezzo', una riga per
    articolo) cosi' il resto della pipeline (filtro autoreferenziale,
    categoria, sottolinea brand) funziona invariato su entrambe le fonti."""
    righe, visti = [], set()
    for m in _RE_ALT_PRODOTTO_VINTED.finditer(html_content or ""):
        titolo = html.unescape(m.group(1)).strip()
        prezzo = m.group(2).replace(",", ".")
        if not titolo or len(titolo) < 3:
            continue
        chiave = (titolo[:60].lower(), prezzo)
        if chiave in visti:
            continue
        visti.add(chiave)
        righe.append(f"- {titolo} — €{prezzo}")
        if len(righe) >= max_articoli:
            break
    if not righe:
        return "  Nessun articolo trovato (pattern alt= senza match -- possibile cambio di markup Vinted, da rivedere)."
    return "\n".join(righe)


def _estrai_mappa_url_comp_vinted(html_content):
    """Costruisce {(titolo_normalizzato, prezzo_2f): url} dallo stesso HTML
    grezzo passato a _estrai_articoli_da_alt_vinted (vedi
    _RE_PRODOTTO_VINTED_CON_ID), cosi' il rendering finale del messaggio puo'
    riattaccare un link cliccabile al comp che il Cervello ha ricopiato nel
    suo JSON -- un semplice dict.get() su titolo+prezzo, senza fuzzy
    matching che rischierebbe di agganciare il comp sbagliato. Il prezzo e'
    la chiave nello stesso formato ".2f" prodotto da calcola_verdetto sui
    comp validati (vedi comp['prezzo_eur'] = round(prezzo, 2))."""
    mappa = {}
    for m in _RE_PRODOTTO_VINTED_CON_ID.finditer(html_content or ""):
        item_id, titolo_grezzo, prezzo_grezzo = m.group(1), m.group(2), m.group(3)
        titolo = html.unescape(titolo_grezzo).strip()
        if not titolo or len(titolo) < 3:
            continue
        try:
            prezzo_norm = f"{float(prezzo_grezzo.replace(',', '.')):.2f}"
        except ValueError:
            continue
        chiave = (_normalizza_titolo_per_link(titolo), prezzo_norm)
        mappa.setdefault(chiave, f"https://www.vinted.it/items/{item_id}")
    return mappa
