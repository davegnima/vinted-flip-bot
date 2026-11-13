"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re
import html


from bot.testo import _RE_ALT_PRODOTTO_VINTED, _RE_PRODOTTO_VINTED_CON_ID, _RE_TITOLO_PRODOTTO_VINTED, _normalizza_titolo_per_link


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


def campione_pagina_vinted(html_content, lunghezza=900):
    """Campione del markup di una pagina catalogo Vinted per capire perche' il parser non trova articoli (25/10).
    Conta i marcatori tipici e riporta un tratto attorno al primo link di annuncio. Pura: solo per i log."""
    testo = html_content or ""
    primo = testo.find("/items/")
    if primo < 0:
        primo = testo.find("alt=")
    tratto = testo[max(0, primo - 200):max(0, primo - 200) + lunghezza] if primo >= 0 else testo[:lunghezza]
    marcatori = {m: testo.count(m) for m in ('alt="', "/items/", "data-testid", "catalog-item", "item-box", "__NEXT_DATA__")}
    return {"len": len(testo), "marcatori": marcatori, "tratto": " ".join(tratto.split())}


def campione_scheda_vinted(html_content, lunghezza=1800):
    """Tratto di HTML attorno alla prima scheda prodotto di una pagina catalogo (data-testid 'product-item-id-'), con
    le immagini e gli attributi della scheda. Serve per scrivere il parser delle foto dei comparabili sul markup vero
    (31/10: il campione precedente mostrava solo l'intestazione della pagina). Pura: solo per i log."""
    testo = html_content or ""
    primo = testo.find("product-item-id-")
    if primo < 0:
        return None
    return " ".join(testo[max(0, primo - 600):max(0, primo - 600) + lunghezza].split())


def _articoli_vinted(html_content):
    """Lista di (item_id, titolo, prezzo) di una pagina catalogo Vinted. Legge il title= del link overlay (markup dal
    25/10/2026); se non trova nulla ripiega sull'alt= dell'immagine (markup precedente, con la taglia). id None sul ramo alt=."""
    testo = html_content or ""
    trovati = [(m.group(1), m.group(2), m.group(3)) for m in _RE_TITOLO_PRODOTTO_VINTED.finditer(testo)]
    if not trovati:
        trovati = [(None, m.group(1), m.group(2)) for m in _RE_ALT_PRODOTTO_VINTED.finditer(testo)]
    return trovati


def _estrai_articoli_da_alt_vinted(html_content, max_articoli=15):
    """Estrae righe 'titolo — prezzo' dagli attributi alt= delle immagini
    prodotto nell'HTML grezzo di una pagina catalogo Vinted (vedi
    _RE_ALT_PRODOTTO_VINTED per il pattern esatto). Stesso formato di
    output di _estrai_articoli_vinted ('- titolo — €prezzo', una riga per
    articolo) cosi' il resto della pipeline (filtro autoreferenziale,
    categoria, sottolinea brand) funziona invariato su entrambe le fonti."""
    righe, visti = [], set()
    for _id, titolo_grezzo, prezzo_grezzo in _articoli_vinted(html_content):
        titolo = html.unescape(titolo_grezzo).strip()
        prezzo = prezzo_grezzo.replace(",", ".")
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


def _articoli_vinted_con_id(html_content):
    """Come _articoli_vinted, ma solo gli articoli con id (link cliccabile). Ripiega sul markup con data-testid."""
    trovati = [(m.group(1), m.group(2), m.group(3)) for m in _RE_TITOLO_PRODOTTO_VINTED.finditer(html_content or "")]
    if not trovati:
        trovati = [(m.group(1), m.group(2), m.group(3)) for m in _RE_PRODOTTO_VINTED_CON_ID.finditer(html_content or "")]
    return trovati


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
    for item_id, titolo_grezzo, prezzo_grezzo in _articoli_vinted_con_id(html_content):
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


_RE_IMG_VINTED = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_RE_IMG_ID_VINTED = re.compile(r'data-testid="product-item-id-(\d+)--image--img"')
_RE_IMG_SRC_VINTED = re.compile(r'\bsrc="(https://images\d*\.vinted\.net/[^"]+)"')


def _estrai_miniature_vinted(html_content):
    """{id annuncio: url miniatura} dai tag <img> della scheda catalogo (data-testid
    'product-item-id-<ID>--image--img'). Zero richieste: stesso HTML gia' scaricato. Pura."""
    miniature = {}
    for tag in _RE_IMG_VINTED.findall(html_content or ""):
        m_id, m_src = _RE_IMG_ID_VINTED.search(tag), _RE_IMG_SRC_VINTED.search(tag)
        if m_id and m_src:
            miniature.setdefault(m_id.group(1), html.unescape(m_src.group(1)))
    return miniature
