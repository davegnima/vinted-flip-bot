"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


from bot.costanti import VINTED_BRAND_IDS
# ---- fine import ----
URL_REGEX = re.compile(r"https?://(?:www\.)?vinted\.[a-z]+/items/\S+", re.IGNORECASE)
# Tollerante sia al vecchio formato del servizio a pagamento (parole "Price"/
# "Brand" letterali) sia al nuovo formato solo-emoji di Vinted-Notifications
# (💰/🏷️ senza parole) -- prima riconosceva SOLO il vecchio formato, quindi
# passando a un tracker diverso prezzo e brand risultavano sempre vuoti ("?").
PRICE_REGEX = re.compile(
    r"(?:Price\s*:\s*|Prezzo\s*:\s*|💰\s*|💶\s*)([\d]+(?:[.,]\d+)?)\s*(?:EUR|€)?",
    re.IGNORECASE,
)
BRAND_REGEX = re.compile(
    r"(?:Brand\s*:\s*|Marca\s*:\s*|🏷️\s*|🛍️\s*)(.+)",
    re.IGNORECASE,
)


TITOLO_NON_RILEVATO = "Titolo non rilevato"


# Il tracker scrive a volte "Brand: None" (letteralmente) quando Vinted non ha
# il brand: il 2026-10-02 due annunci su 94 ("Loro Piana", "Fendi") sono finiti
# con brand "None" e senza il ramo brand dei controlli. Se il brand manca lo si
# ricava dal titolo, solo con un nome della mappa brand a parola intera.
BRAND_VALORI_VUOTI = {"none", "null", "n/d", "nd", "-", "--", "n/a", "sconosciuto", "unknown"}


def _brand_da_titolo(titolo):
    t = (titolo or "").lower()
    if not t or titolo == TITOLO_NON_RILEVATO:
        return None
    for nome in sorted(VINTED_BRAND_IDS, key=len, reverse=True):
        if re.search(r"(?<!\w)" + re.escape(nome) + r"(?!\w)", t):
            return nome.title()
    return None


def parse_vinted_tracker_message(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    for line in lines:
        line_lower = line.lower()
        # Salta le righe di prezzo/brand in ENTRAMBI i formati (vecchio a
        # parole, nuovo a emoji), cosi' non vengono scambiate per titolo.
        e_riga_prezzo = line_lower.startswith(("price", "prezzo")) or "price" in line_lower or line.startswith(("💰", "💶"))
        e_riga_brand = line_lower.startswith(("brand", "marca")) or line.startswith(("🏷️", "🛍️"))
        if e_riga_prezzo or e_riga_brand:
            continue
        # Rimuove QUALSIASI emoji iniziale (non solo "📌" come prima) -- il
        # bug del titolo con emoji duplicata (es. "🆕 🆕 Titolo") veniva da
        # qui: il vecchio codice toglieva solo "📌 ", quindi con un titolo
        # tracker che iniziava per "🆕 " quell'emoji restava nel testo salvato
        # e l'header del bot ne aggiungeva un'altra sopra.
        cleaned = re.sub(r"^[\U0001F000-\U0001FFFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]+\s*", "", line).strip()
        if cleaned and title is None:
            title = cleaned
            break
    price_match = PRICE_REGEX.search(text)
    brand_match = BRAND_REGEX.search(text)
    brand = brand_match.group(1).strip() if brand_match else None
    if brand and brand.lower() in BRAND_VALORI_VUOTI:
        brand = None
    if not brand:
        brand = _brand_da_titolo(title)
    return {
        "title": title or TITOLO_NON_RILEVATO,
        "price": price_match.group(1) if price_match else None,
        "brand": brand,
    }


def extract_url_from_text(text):
    match = URL_REGEX.search(text or "")
    return match.group(0) if match else None
