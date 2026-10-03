"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


# ---- fine import ----
# Pattern che estrae titolo+prezzo dall'attributo alt="..." di ogni <img>
# prodotto nella griglia catalogo Vinted -- confermato il 2026-09-20 via
# view-source reale fornito dall'utente:
# alt="Manteau Jean Paul Gaultier, Brand: Jean Paul Gaultier, Condizioni:
# Ottime, Taglia: M / IT 42 / EU 38, 140.00 €, 147.70 €"
# Il primo prezzo (140.00) e' l'ask "nudo", il secondo (147.70) include le
# fee Vinted -- prendiamo il primo per coerenza con le altre fonti comp, che
# lavorano tutte in ASK senza fee. Molto piu' robusto di un parser
# HTML->markdown generico: il dato e' gia' strutturato da Vinted stesso nel
# markup, non va indovinato dalla disposizione visiva del testo.
_RE_ALT_PRODOTTO_VINTED = re.compile(
    r'alt="([^"]+?),\s*Brand:.*?,\s*Condizioni:.*?,\s*Taglia:[^,"]*,\s*([\d]+(?:[.,]\d+)?)\s*€',
    re.IGNORECASE,
)


# Pattern gemello di _RE_ALT_PRODOTTO_VINTED che cattura ANCHE l'ID
# dell'articolo (Punto 3 concordato il 2026-09-25: link cliccabili nei
# comp, rimappati in Python al rendering finale usando titolo+prezzo come
# chiave, MAI passati al Cervello -- vedi la discussione su allucinazioni
# di link e troncamento Markdown di Telegram). Confermato sul frammento
# HTML reale fornito dall'utente lo stesso giorno: ogni box prodotto ha un
# div contenitore con data-testid="product-item-id-NNNN" (l'ID nudo, senza
# suffisso) che precede sempre l'alt= della sua stessa immagine -- i due
# suffissi "--image" e "--overlay-link" sugli altri elementi dello stesso
# box hanno un "--" subito dopo le cifre, quindi non superano il gruppo
# (\d+)" (cifre seguite direttamente da virgolette) e non vengono presi.
#
# Non serve leggere l'href dell'<a>: lo stesso frammento fornito dall'utente
# arrivava con l'href gia' rovinato in sintassi Markdown da uno strumento di
# copia (ulteriore controprova che fidarsi del testo dell'href e' fragile),
# mentre https://www.vinted.it/items/{id} da solo e' un URL valido -- Vinted
# fa redirect alla pagina completa con lo slug anche senza di esso.
_RE_PRODOTTO_VINTED_CON_ID = re.compile(
    r'data-testid="product-item-id-(\d+)".*?'
    r'alt="([^"]+?),\s*Brand:.*?,\s*Condizioni:.*?,\s*Taglia:[^,"]*,\s*([\d]+(?:[.,]\d+)?)\s*€',
    re.IGNORECASE | re.DOTALL,
)


def _etichetta_piattaforma_da_url(url):
    """Determina eBay/Poshmark/Vinted dal DOMINIO dell'URL del comp, invece
    di fidarsi dell'etichetta di fonte generica ('eBay/Poshmark', 'ricerca
    on-demand') -- aggiunto il 2026-09-25 su richiesta dell'utente: il pool
    interno gia' sapeva distinguere eBay da Poshmark riga per riga (tag
    '[ebay]'/'[poshmark]', vedi _query_resellbot_raw), ma quell'informazione
    si perdeva non appena il Cervello ricopiava il comp nel suo JSON (il
    campo fonte e' un enum a grana piu' larga, 'ebay_poshmark'). Il dominio
    dell'URL e' un dato oggettivo, deciso in Python, mai dal modello -- stesso
    principio delle altre reti di sicurezza deterministiche in questo file.
    Ritorna None se il dominio non e' uno di quelli riconosciuti (lascia
    l'etichetta generica invariata)."""
    if not url:
        return None
    u = url.lower()
    if "poshmark." in u:
        return "Poshmark"
    if "ebay." in u:
        return "eBay"
    if "vinted." in u:
        return "Vinted"
    return None


def _normalizza_titolo_per_link(titolo):
    """Normalizzazione MINIMA (minuscolo, spazi compattati) per il lookup
    titolo->URL comp. Deliberatamente diversa da _normalizza_titolo_per_dedup,
    che droppa l'ultima parola del titolo -- pensata per confrontare il
    titolo dell'annuncio contro un comp con la taglia in coda, non per
    riconoscere due copie dello stesso identico titolo comp (qui perdere
    l'ultima parola creerebbe falsi mancati match)."""
    if not titolo:
        return ""
    return re.sub(r"\s+", " ", titolo.strip().lower())


def _escapa_markdown_legacy(testo):
    """Sfugge i caratteri speciali della sintassi Markdown legacy di Telegram
    (_, *, `, [) in un testo che finira' dentro un messaggio con
    parse_mode=Markdown. Serve per qualunque testo NON scritto a mano da noi
    -- tipicamente estratto via regex dall'output grezzo del modello --
    perche' puo' contenere sequenze come nomi di campo JSON ('main_label',
    'font_etichetta') o valori enum ('parziale_servono_altre_foto') che
    Telegram interpreta come marcatori di formattazione. Un numero dispari
    di underscore nell'INTERO messaggio fa fallire il parsing di tutto il
    messaggio, non solo del pezzo incriminato (bug reale in produzione il
    2026-09-20, caso 'Polo Loro Piana': il testo grezzo dell'Occhio dentro
    build_skip_report conteneva 'main_label', 'font_etichetta' e
    'parziale_servono_altre_foto', 5 underscore in totale, numero dispari ->
    HTTP 400 'can't find end of the entity'. Stesso identico meccanismo gia'
    visto e risolto per l'URL della ricerca visuale in
    render_messaggio_verdetto, qui pero' il testo e' prosa libera, quindi la
    soluzione e' sfuggire i caratteri invece di un link Markdown o backtick."""
    if not testo:
        return testo
    return re.sub(r"([_*`\[])", r"\\\1", testo)


def _normalizza_titolo_per_dedup(title):
    if not title:
        return ""
    t = title.strip()
    t_senza_virgolette = re.sub(r"['\"][^'\"]*['\"]\s*$", "", t).strip()
    if t_senza_virgolette != t:
        base = t_senza_virgolette
    else:
        parole = t.split()
        base = " ".join(parole[:-1]) if len(parole) > 1 else t
    return re.sub(r"\s+", " ", base).strip().lower()
