"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re


from bot.costanti import BRAND_BLOCKLIST, VENDITORI_BLOCKLIST
from bot.verdetto import _a_float
# ---- fine import ----
# Miu Miu top/haut/debardeur economici (richiesto dall'utente il 2026-09-30):
# nei log sono tutti capi a prezzo basso con rischio fake altissimo e nessun
# margine reale, quindi si scartano a monte, prima di Occhio e Cervello,
# come gli occhiali. Il tetto di prezzo e' configurabile da Railway con
# MIUMIU_TOP_PREZZO_MAX (default 20 euro; 0 = scarta a qualunque prezzo).
# Solo titolo (non descrizione) per non catturare "top condition" ecc.
try:
    MIUMIU_TOP_PREZZO_MAX = float(os.environ.get("MIUMIU_TOP_PREZZO_MAX", "20").replace(",", "."))
except ValueError:
    MIUMIU_TOP_PREZZO_MAX = 20.0
_RE_MIUMIU = re.compile(r"\bmiu\s*-?\s*miu\b")
_RE_TOP_LEGGERO = re.compile(
    r"\b(tops?|hauts?|d[eé]bardeurs?|tank|tanks|canotta|canottiera|camisole|"
    r"tirantes|al[cç]as|tr[aä]gertop|stricktop|crop|bustier|cami)\b"
)


def _miumiu_top_economico(listing_info):
    titolo = (listing_info.get("title") or "").lower()
    brand = (listing_info.get("brand") or "").lower()
    if not (_RE_MIUMIU.search(titolo) or _RE_MIUMIU.search(brand)):
        return False
    if not _RE_TOP_LEGGERO.search(titolo):
        return False
    if MIUMIU_TOP_PREZZO_MAX <= 0:
        return True
    prezzo = _a_float(listing_info.get("price"), None)
    # prezzo ignoto: si scarta comunque (nei log erano tutti capi da pochi euro)
    return prezzo is None or prezzo <= MIUMIU_TOP_PREZZO_MAX


def check_skip_pre_gemini(listing_info):
    """Filtro veloce basato sul testo, eseguito dopo lo scraping ma PRIMA di API/foto."""
    titolo = (listing_info.get("title") or "").lower()
    descrizione = (listing_info.get("description") or "").lower()
    brand = (listing_info.get("brand") or "").lower()
    seller = (listing_info.get("seller_login") or "").lower()

    testo_completo = f"{titolo} {descrizione}"

    if _miumiu_top_economico(listing_info):
        return True, "[CATEGORIA GENERICA NON FLIPPABILE] Miu Miu top/haut/debardeur a prezzo basso (rischio fake, nessun margine)"

    # 1. Blocklist venditori
    if seller and seller in VENDITORI_BLOCKLIST:
        return True, f"[VENDITORE IN BLOCKLIST] L'utente '{seller}' e' nella blocklist."

    # 1b. Blocklist brand -- controllo sia sul campo brand strutturato sia sul
    # titolo, perche' non tutti gli annunci hanno il campo brand valorizzato
    # correttamente (es. "brand: altro" con il nome vero solo nel titolo).
    for brand_escluso in BRAND_BLOCKLIST:
        if re.search(r'\b' + re.escape(brand_escluso) + r'\b', brand) or \
           re.search(r'\b' + re.escape(brand_escluso) + r'\b', titolo):
            return True, f"[BRAND IN BLOCKLIST] '{brand_escluso}' e' un brand escluso a prescindere."

    # 2. Categorie mai flippabili (lista minima -- volutamente corta, quelle
    # "teoriche" aggiunte in precedenza non si verificano mai in pratica)
    unflippable = [
        "calzini", "calze", "collant", "portachiavi", "profumi", "eau de parfum",
        "eau de toilette", "deodoranti", "cover per telefono", "ciondoli", "guinzagli",
        # calzini/calze/collant multilingua -- lo stesso bug di copertura
        # linguistica gia' visto altrove: l'italiano da solo lascia passare
        # titoli in altre lingue, sprecando foto+token fino all'occhio.
        "socken", "strumpfhose", "strümpfe",
        "socks", "tights", "stockings", "pantyhose",
        "chaussettes", "collants",
        # NOTA: il francese "bas" (calze) e' stato RIMOSSO da questa lista.
        # Era la causa di uno scarto silenzioso di annunci validi (un maglione
        # Loro Piana, uno short Engineered Garments, una t-shirt Our Legacy),
        # perche' "bas" e' anche una parola francese comunissima nelle
        # descrizioni ("en bas", "bassin", "basique") e il match a sottostringa
        # la trovava ovunque. Le calze francesi restano coperte da
        # "chaussettes" e "collants", che non hanno lo stesso problema.
        "calcetines", "medias",
        "meias",
        # occhiali/occhialeria (vista o sole), montature, lenti, astucci -- basso
        # ROI ricorrente e mercato saturo, escluso a monte su richiesta esplicita
        "occhiali", "montatura", "montature", "lenti da vista", "occhiale da sole",
        "occhiale da vista", "astuccio occhiali",
        "glasses", "eyewear", "sunglasses", "spectacles", "eyeglass frames",
        "brille", "brillengestell", "sonnenbrille",
        "lunettes", "monture de lunettes",
        "gafas", "monturas de gafas", "lentes de sol",
        "óculos", "armação de óculos",
        # Collab mass-market note per brand monitorati -- diluiscono il
        # valore, capi economici e molto diffusi rispetto al mainline.
        # "uniqlo" e "h&m" da soli sono termini rari in un annuncio di
        # moda di lusso, rischio di falso positivo basso.
        "uniqlo",
        "missoni for target", "missoni x target",
    ]
    # Match a PAROLA INTERA (\b), non a sottostringa. Prima questa lista usava
    # un semplice "kw in testo", a differenza dei filtri danni/non-originalita'
    # sotto che gia' usavano \b: e' lo stesso bug di collisione per sottostringa
    # gia' visto con "shirt"/"t-shirt", e scartava silenziosamente annunci buoni.
    for kw in unflippable:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[CATEGORIA GENERICA NON FLIPPABILE] Rilevata keyword: {kw}"

    # 2a-bis. Collab con H&M, forma "h&m" separata dal resto perche' su Vinted
    # (e nello scraping) l'ampersand sparisce spesso dal titolo, lasciando
    # solo "Hm" -- caso reale osservato in produzione: "Marni for Hm trench
    # jacket" e' passato indenne per anni perche' il filtro cercava solo la
    # stringa letterale "h&m" con l'apostrofo. "hm" da solo e' troppo rischioso
    # (collide con l'interiezione "hm"/"hmm" in descrizioni scritte a mano),
    # quindi si controllano solo i pattern di collab espliciti "for hm"/"x hm"/
    # "h & m" (con spazi), oltre alla forma originale con l'ampersand.
    HM_COLLAB_PATTERN = re.compile(r'\b(h\s*&\s*m|for\s+hm|x\s+hm)\b')
    if HM_COLLAB_PATTERN.search(testo_completo):
        return True, "[CATEGORIA GENERICA NON FLIPPABILE] Rilevata keyword: collab H&M"

    # 2b. Danno grave dichiarato esplicitamente dal venditore, multilingua
    # (IT/EN/DE/FR/ES/PT -- stessa logica delle categorie: il tracker Vinted
    # intercetta annunci in tutta Europa). Usa \b per evitare falsi positivi
    # su sottostringhe (es. "roto" dentro un'altra parola).
    DANNO_GRAVE_KEYWORDS = [
        # IT
        "rotto", "rotta", "strappato", "strappata", "bucato", "bucata",
        "danneggiato", "danneggiata", "da riparare", "per ricambio", "per pezzi",
        "rovinato", "rovinata", "da buttare", "irreparabile",
        # EN
        "broken", "torn", "ripped", "damaged", "for repair", "for parts",
        "beyond repair", "unusable", "ruined",
        # DE
        "kaputt", "zerrissen", "beschädigt", "defekt", "unbrauchbar", "irreparabel",
        # FR
        "cassé", "cassée", "déchiré", "déchirée", "endommagé", "endommagée",
        "abîmé", "abîmée", "à réparer", "pour pièces", "irréparable", "troué", "trouée",
        # ES
        "roto", "rota", "rasgado", "rasgada", "dañado", "dañada",
        "para reparar", "para piezas", "irreparable",
        # PT
        "quebrado", "quebrada", "rasgado", "danificado", "danificada",
        "para reparo", "irreparável",
    ]
    for kw in DANNO_GRAVE_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[DANNO GRAVE DICHIARATO NEL TESTO] Rilevata keyword: '{kw}' -- non flippabile per regola su danni strutturali."

    # 2c. Non originalita' dichiarata dal venditore stesso, multilingua
    NON_ORIGINALE_KEYWORDS = [
        # IT
        "non originale", "non è originale", "non e' originale", "ispirato a",
        "replica", "imitazione", "copia non originale",
        # "riproduzione" (caso reale segnalato dall'utente il 2026-09-21:
        # "Blazer elegante miu miu (riproduzione)" -- il venditore dichiara
        # ESPLICITAMENTE che e' una riproduzione/copia, ma il termine mancava
        # da questa lista, quindi l'annuncio non veniva scartato qui e
        # arrivava intatto all'Occhio, che ha ignorato la dichiarazione del
        # venditore ("eccesso di cautela") e giudicato il capo autentico sulla
        # sola analisi visiva -- COMPRA su un pezzo che il venditore stesso
        # dice essere una riproduzione. Questo filtro e' deterministico e gira
        # PRIMA di interpellare Gemini, quindi e' la difesa piu' solida:
        # un'istruzione nel prompt puo' essere reinterpretata dal modello
        # (come e' successo qui), un match di keyword no.
        "riproduzione", "riprodotto", "riprodotta",
        # EN
        "not authentic", "not original", "inspired by", "knockoff",
        "reproduction",
        # DE
        "nicht original", "inspiriert von", "nachahmung", "fälschung",
        "reproduktion",
        # FR
        "non authentique", "pas authentique", "inspiré de", "inspirée de",
        "réplique", "contrefaçon", "reproduction",
        # ES
        "no original", "no es original", "inspirado en", "imitación",
        "reproducción",
        # PT
        "não original", "inspirado em", "imitação", "reprodução",
    ]
    for kw in NON_ORIGINALE_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', testo_completo):
            return True, f"[NON ORIGINALE DICHIARATO] Rilevata keyword: '{kw}' -- venditore dichiara che non e' un pezzo originale."

    # 2d. Titoli con stringa di ricerca residua "gilet -blanc"
    if "gilet -blanc" in titolo:
        return True, "[TITOLO CON STRINGA DI RICERCA RESIDUA] Rilevato 'gilet -blanc' nel titolo."

    # 3. Regole specifiche per brand
    if "stella mccartney" in brand and "adidas" in testo_completo:
        return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Stella McCartney collab Adidas (basso valore)."

    # Richiesto dall'utente il 2026-10-01: le t-shirt Jacquemus vanno scartate sempre
    # (basso margine/ROI per questa categoria su questo brand) -- il resto di Jacquemus
    # (vestiti, maglieria, capispalla) continua a essere valutato normalmente.
    if "jacquemus" in brand or "jacquemus" in titolo:
        # Solo sul titolo e a parola intera: in descrizione "da abbinare a una
        # t-shirt" o il francese "jamais portee" (senza accento, contiene "tee")
        # scartavano per errore vestiti e altri capi.
        TSHIRT_KW = ("maglietta", "magliette", "t-shirt", "tshirt", "t shirt", "tee", "tees")
        if any(re.search(r"\b" + re.escape(kw) + r"\b", titolo) for kw in TSHIRT_KW):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Jacquemus t-shirt esclusa su richiesta esplicita (basso margine)."

    # Loro Piana giacche/blazer sartoriali (richiesto dall'utente il 2026-10-03, dati 2026-10-02:
    # 31 annunci Loro Piana su 53 scartati dopo aver gia' chiamato l'Occhio, quasi tutti giacche
    # su misura il cui cartellino e' del fornitore del tessuto, non di Loro Piana). Si applica solo
    # dopo lo scraping (serve la descrizione per non perdere "cashmere"/"storm system") e solo se
    # nulla nel testo segnala un capo Loro Piana vero (linee iconiche, cashmere, camoscio, ecc.).
    if ("loro piana" in brand or "loro piana" in titolo) and "description" in listing_info:
        GIACCA_KW = ("blazer", "blazers", "giacca", "giacche", "veste", "jas", "jacke", "sakko", "jacket", "veston")
        LP_VERO_KW = ("storm", "roadster", "windmate", "rain system", "cashmere", "cachemire", "kaschmir",
                      "vicuna", "vigogna", "baby cashmere", "traveller", "suede", "camoscio", "pelle", "leather",
                      "gilet", "piumino", "bomber", "etichetta loro piana", "label loro piana")
        if (any(re.search(r"\b" + re.escape(kw) + r"\b", titolo) for kw in GIACCA_KW)
                and not any(kw in testo_completo for kw in LP_VERO_KW)):
            return True, ("[TESSUTO NON E' IL BRAND] Loro Piana giacca/blazer senza segnali di capo Loro Piana vero "
                          "(spesso tessuto Loro Piana su giacca sartoriale di altro marchio): scartata prima dell'Occhio.")

    if "yves saint laurent" in brand or "ysl" in brand or "saint laurent" in brand:
        camicie_kw = ["camicia", "camicie", "camicetta", "shirt", "chemise", "blusa", "camisa"]
        if any(kw in testo_completo for kw in camicie_kw):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] YSL camicie/bluse sature e scarso ROI."
        borse_moderne = ["saint laurent paris", "loulou", "sac de jour", "kate", "niki"]
        if any(kw in testo_completo for kw in borse_moderne):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] YSL borse moderne ad altissimo rischio fake."

    if "alexander mcqueen" in brand or "mcqueen" in brand:
        if re.search(r"\bmc_?q\b", testo_completo):
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Alexander McQueen diffusion linea McQ."

    if "chloé" in brand or "chloe" in brand:
        if "see by chloé" in testo_completo or "see by chloe" in testo_completo:
            return True, "[LINEA/VARIANTE ESCLUSA PER BRAND] Chloé diffusion linea See by Chloé."

    # "Loro Piana" citato come TESSUTO, non come produttore del capo (richiesto
    # dall'utente il 2026-09-21, caso reale: "Blazer oversize in lana tessuto
    # Loro Piana" valutato COMPRA sui comp di Loro Piana mainline, quando
    # l'unica etichetta reale era quella del fornitore di stoffa e il
    # produttore vero del capo era un sarto/maker ignoto). E' una pratica
    # sartoriale comune: il tessuto pregiato viene citato per marketing, il
    # capo NON e' fatto da Loro Piana. Skip a monte, prima ancora delle foto:
    # basta che una parola "tessuto"/"fabric" (in tutte le lingue Vinted
    # osservate finora) compaia insieme a "loro piana" nel testo, a
    # prescindere da cosa dice il campo brand strutturato -- e' un segnale
    # sufficientemente specifico da non aver bisogno di conferma visiva.
    # Nota: questo NON copre il caso in cui il testo non lo dichiara ma le
    # FOTO mostrano solo l'etichetta del tessuto -- quel caso e' coperto piu'
    # a valle da relazione_brand == "tessuto_non_brand" nell'Occhio.
    if "loro piana" in testo_completo:
        TESSUTO_KEYWORDS = (
            "tessuto",  # IT
            "fabric", "cloth",  # EN
            "stoff", "gewebe",  # DE
            "tissu", "étoffe", "etoffe",  # FR
            "tejido", "tela",  # ES
            "tecido", "pano",  # PT
        )
        if any(re.search(r'\b' + re.escape(kw) + r'\b', testo_completo) for kw in TESSUTO_KEYWORDS):
            return True, (
                "[TESSUTO NON E' IL BRAND] 'Loro Piana' citato insieme a una parola di "
                "tessuto/stoffa nel titolo o nella descrizione -- quasi certamente il nome "
                "del fornitore del tessuto, non il produttore del capo, scartato senza "
                "consultare foto/cervello."
            )

    return False, None
