"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


from bot.config import SERPER_API_KEY
from bot.verdetto import _estrai_prezzi_da_pool_ricerca
from bot.testo import _normalizza_titolo_per_link
from bot.logger import log
from bot import http_clients as hc
# ---- fine import ----
def valuta_qualita_comp(comps_text):
    """Stima se i comp pre-raccolti da Serper sono sufficienti a dare un
    verdetto senza bisogno di forzare una ricerca aggiuntiva. Euristica
    semplice: conta quanti prezzi reali compaiono nel blocco, e verifica
    che la categoria non sia stata saltata per mancata rilevazione.

    Soglia abbassata da 5 a 3 (controllo costi, Pareto): i comp pre-raccolti
    sono gia' inclusi nel costo Serper esistente, mentre ogni ricerca extra
    che il Cervello decide di forzare quando questa funzione ritorna False
    e' un giro di chiamata Gemini aggiuntivo (il costo piu' caro e variabile
    del bot, vedi MAX_ROUNDS_FUNZIONE). 3 prezzi reali gia' anticipano quasi
    sempre un range utilizzabile, senza dover pagare per scoprirlo."""
    if not comps_text:
        return False
    if "Categoria non rilevata" in comps_text:
        return False
    n_prezzi = len(re.findall(r"€\s*\d", comps_text)) + len(re.findall(r"EUR\s*[\d.,]+", comps_text))
    return n_prezzi >= 3


# Snippet-placeholder che Google/Serper restituisce quando non riesce a
# generare un estratto reale (pagina JS-rendered, bloccata, o senza testo
# indicizzabile) -- puro rumore, occupa spazio nel contesto del cervello
# senza portare ne' un prezzo ne' informazione utile.
SNIPPET_PLACEHOLDER_INUTILI = [
    "nessuna informazione disponibile per questa pagina",
]

# Simboli di valuta non-EUR il cui prezzo non e' direttamente comparabile
# senza conversione (mercati regionali: baht thailandese, yen, rupia, won,
# ecc.) -- un risultato che ha SOLO questi simboli di prezzo (nessun
# €/EUR/$/USD/£/GBP nello snippet) va scartato perche' il cervello non ha
# modo di convertirlo in modo affidabile e rischia di trattarlo come comp
# diretto.
SIMBOLI_VALUTA_NON_COMPARABILI = ["฿", "¥", "₹", "₩", "₫", "₱"]
SIMBOLI_VALUTA_COMPARABILI = ["€", "eur", "$", "usd", "£", "gbp"]


def _riga_serper_e_rumore(titolo, snippet):
    """True se la riga (titolo+snippet) di un risultato Google/Serper va
    scartata perche' non porta informazione utile al cervello -- vedi
    SNIPPET_PLACEHOLDER_INUTILI e SIMBOLI_VALUTA_NON_COMPARABILI sopra per
    il dettaglio dei due casi coperti, individuati da un caso reale
    (ricerca on-demand 'GU x Undercover Cargo' che restituiva pagine eBay
    senza snippet e annunci in thailandese con prezzi in baht)."""
    testo_completo = f"{titolo} {snippet}".strip()
    if not testo_completo:
        return True
    # .rstrip(".") perche' Google a volte restituisce il placeholder con un
    # punto finale ("...pagina.") e a volte senza -- confermato empiricamente
    # nel caso reale che ha originato questo filtro (vedi log 'gu × undercover').
    snippet_lower = snippet.strip().lower().rstrip(".")
    if snippet_lower in SNIPPET_PLACEHOLDER_INUTILI:
        return True
    ha_valuta_non_comparabile = any(simbolo in testo_completo for simbolo in SIMBOLI_VALUTA_NON_COMPARABILI)
    ha_valuta_comparabile = any(simbolo in testo_completo.lower() for simbolo in SIMBOLI_VALUTA_COMPARABILI)
    if ha_valuta_non_comparabile and not ha_valuta_comparabile:
        return True
    return False


async def cerca_serper_mirata(query):
    """Ricerca aggiuntiva mirata, richiamabile dal cervello quando i comp
    pre-raccolti sono insufficienti o fuori tema.

    Ritorna (testo, mappa_url) dal 2026-09-25 (Punto 3 esteso alla ricerca
    on-demand, richiesto dall'utente): mappa_url e' costruita da r['link']
    (il campo con l'URL della pagina, gia' restituito da Serper ma prima
    scartato qui) SOLO per le righe dove riusciamo anche a isolare un
    prezzo dal titolo+snippet con lo stesso regex €/EUR usato per il pool
    (_estrai_prezzi_da_pool_ricerca) -- a differenza di Vinted/Resellbot, qui
    non c'e' un prezzo strutturato garantito riga per riga (e' testo libero
    di uno snippet Google), quindi il match e' best-effort: se il prezzo non
    si isola in modo univoco, quella riga resta senza link piuttosto che
    rischiare di agganciarne uno sbagliato. L'URL non viene MAI passato al
    Cervello (resta fuori dal testo restituito) -- stesso principio delle
    altre fonti, il link si riattacca in Python al rendering finale."""
    if not SERPER_API_KEY:
        return "Ricerca non eseguita (SERPER_API_KEY non impostata).", {}
    payload = [{"q": query, "gl": "it", "hl": "it", "num": 10}]
    try:
        resp = await hc._client_generico.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json=payload, timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception as e:
        return f"Ricerca fallita: {e}", {}
    lines = []
    mappa_url = {}
    scartate = 0
    for batch in results:
        for r in batch.get("organic", [])[:8]:
            titolo = r.get("title", "")
            snippet = (r.get("snippet", "") or "")[:150]
            if _riga_serper_e_rumore(titolo, snippet):
                scartate += 1
                continue
            lines.append(f"- {titolo}: {snippet}")
            link = (r.get("link") or "").strip()
            if link:
                prezzi_riga = _estrai_prezzi_da_pool_ricerca(f"{titolo} {snippet}")
                # Solo se il prezzo e' univoco su questa riga: due prezzi
                # diversi nello stesso snippet (es. prezzo originale +
                # scontato) renderebbero la chiave ambigua, meglio nessun
                # link che uno sbagliato.
                if len(prezzi_riga) == 1:
                    prezzo = next(iter(prezzi_riga))
                    chiave = (_normalizza_titolo_per_link(titolo), f"{prezzo:.2f}")
                    mappa_url.setdefault(chiave, link)
    if scartate:
        log.info("cerca_serper_mirata: scartate %d righe di rumore (snippet vuoto/placeholder o valuta non comparabile) per query '%s'.", scartate, query)
    testo = "\n".join(lines) if lines else "Nessun risultato trovato per questa query."
    return testo, mappa_url
