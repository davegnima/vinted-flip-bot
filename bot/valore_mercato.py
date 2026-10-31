"""Radar v2 (non moda): rivendita verosimile ricavata dagli annunci simili in vendita adesso, con tetto dal prezzo del nuovo.

Funzioni pure, senza rete: il worker scarica la pagina catalogo (comps._cerca_vinted_testo_diretto) e passa
qui il testo nel formato '- titolo — €prezzo'. Proposta: docs/proposta-radar-v2-2026-10-23.md.

  1. parse_comp          righe '- titolo — €prezzo' -> [(titolo, prezzo)]
  2. solo_usato          toglie i comparabili nuovi (cartellino, sigillato...): gonfiano il prezzo
  3. stima_mercato       prezzi richiesti -> 25° percentile senza valori anomali, con affidabilita'
  4. tetto_dal_nuovo     l'usato non vale mai quanto il nuovo: tetto = quota del nuovo
  5. valuta              margine e ROI con le stesse regole del radar (radar_matrice.margine_roi, trattativa inclusa)
"""
import re
import statistics

from bot.config import SPEDIZIONE_STIMATA_EUR
from bot.radar_matrice import RADAR_MARGINE_MIN, RADAR_ROI_MIN, margine_roi
# ---- fine import ----

# Quota massima del prezzo del nuovo per un usato (da calibrare per categoria con i dati dell'ombra).
QUOTA_NUOVO_USATO = 0.60
# Comparabili minimi per dare una stima.
MIN_COMPARABILI = 4
_RE_RIGA = re.compile(r"^\s*-\s*(.+?)\s+[—-]\s+€\s*([\d.,]+)\s*$")
_RE_NUOVO = re.compile(r"\b(nuov[oai]|sigillat[oai]|cartellino|mai usat[oai]|mai aperto|new|neuf|neu|bnwt|nwt)\b", re.I)
# Parti, ricambi e accessori: un annuncio che le cita non e' l'oggetto intero e non va confrontato con gli interi.
_RE_PEZZO = re.compile(
    r"\b(quadrant[ei]|cinturin[oi]|maglia|maglie|bracciale ricambio|mouvement|movimento|lunetta|corona|vetro ricambio|ricambi?|"
    r"pezz[oi] di ricambio|per ricambi|per pezzi|guasto|rotto|difettos[oa]|scatola vuota|box vuot[oa]|solo scatola|libretto|manuale|"
    r"istruzioni|custodia|cover|cavo|caricabatterie|filtro|spazzola|testina|ugello|batteria|sacchett[oi]|"
    r"non funzionante|non funziona|bloccat[oa]|icloud|da riparare|per componenti|"
    # 31/10: accessori visti come falsi verdi (borsa 3DS, filtri ND DJI, supporti Sonos, ventilatore Xbox, cartucce, Verpackung)
    r"borsa|borse|tasche|aufbewahrungstasche|etui|housse|sleeve|filtri|filters?|supporto|supporti|supports?|halterung|"
    r"action mount|ventilador|ventilatore|lüfter|cartucc[ae]|cartridges?|pokeball|verpackung|keine konsole|ohne konsole|"
    r"empty box|box only|"
    # 31/10 (secondo giro): scocche, campane, cinturini QuickFit e batterie sciolte viste con 0-1 comparabili
    r"scocc[ae]|coque|campana de aspiraci[oó]n|quickfit|bracelet (?:silicone|de rechange|[àa] d[ée]gagement)|"
    r"ne s'?allume (?:plus|pas)|ne d[ée]marre (?:plus|pas)|hors service|d[ée]fectueu[xs]e?|kaputt|defekt|no funciona|averiad[oa]|"
    r"battery grip|impugnatura|bg-?e\d+|"
    # 31/10 (terzo giro): accessori in piu' lingue e parti di passeggino visti come verdi/gialli sospetti
    r"watchst[äa]nder|ladestation|"
    r"soporte|chasis|ch[aâ]ssis|vestidura|regenhoes|regenhoezen|"
    r"batteries (?:enduro|pour|de rechange)|recambio|repuesto|ersatzteile?|pi[èe]ces? d[ée]tach[ée]es?)\b", re.I)
# Titolo che inizia con la scatola ("Scatola Xbox series X"): e' l'imballo, non la console.
_RE_SCATOLA_INIZIO = re.compile(
    r"^\s*(?:la )?(scatola|box|boite|boîte|karton|emballage|caja|accessori|accessoires?|accesorios|acess[oó]rios|"
    r"[\w-]*zubeh[öo]r|accessor(?:y|ies))\b", re.I)
# 31/10: parole generiche in IT/FR/ES/DE/EN che sporcano la ricerca dei comparabili (stato, taglia, colore, venditore)
_PAROLE_GENERICHE = {"gebraucht", "neuwertig", "defekt", "très", "tres", "bon", "bonne", "état", "etat", "occasion", "bueno", "buen",
                     "estado", "usado", "usada", "perfecto", "perfekt", "guter", "gutem", "zustand", "used", "good", "condition",
                     "excellent", "like", "great", "bellissimo", "bellissima", "splendido", "pari", "quasi", "ottimo", "ottima",
                     "spedizione", "tracciata", "gratis", "garanzia", "funzionante", "funzionanti", "completo", "completa",
                     "nero", "nera", "bianco", "bianca", "noir", "blanc", "negro", "schwarz", "weiss", "weiß", "black", "white",
                     "rosso", "blu", "grigio", "rouge", "bleu", "gris", "verde", "grau", "rot", "blau", "grün"}
_PAROLE_VUOTE = {"vendo", "vendesi", "usato", "usata", "ottime", "ottimo", "buone", "condizioni", "perfette", "perfetto",
                 "come", "nuovo", "nuova", "originale", "con", "per", "di", "il", "la", "in", "e", "a", "da", "del", "della"}


def parse_comp(testo):
    """[(titolo, prezzo_eur)] dalle righe '- titolo — €prezzo'; ignora le righe non nel formato."""
    out = []
    for riga in (testo or "").splitlines():
        m = _RE_RIGA.match(riga)
        if not m:
            continue
        try:
            out.append((m.group(1), float(m.group(2).replace(",", "."))))
        except ValueError:
            continue
    return out


def solo_usato(comps):
    """Toglie i comparabili che dichiarano di essere nuovi: il loro prezzo non e' una rivendita da usato."""
    return [(t, p) for t, p in comps if not _RE_NUOVO.search(t)]


def e_un_pezzo(titolo):
    """Prima parola di ricambio/accessorio nel titolo, None se sembra l'oggetto intero. Pura."""
    m = _RE_PEZZO.search(titolo or "") or _RE_SCATOLA_INIZIO.search(titolo or "")
    return m.group(0).lower().strip() if m else None


def _parole(testo):
    return {w for w in re.findall(r"[\w]+", (testo or "").lower()) if len(w) > 2 and w not in _PAROLE_VUOTE}


def comparabili_simili(comps, query, brand=None, soglia=0.6):
    """Tiene i comparabili interi (niente pezzi) i cui titoli contengono almeno `soglia` delle parole della ricerca (marca esclusa).

    Il motore di Vinted e' largo: cercando 'omega quadrante seamaster' restituisce orologi interi. Senza questo filtro
    il quadrante a 35 EUR sembrerebbe un affare rispetto a orologi da 700 EUR."""
    chiave = _parole(query) - _parole(brand)
    out = []
    for t, p in comps:
        if e_un_pezzo(t):
            continue
        if chiave and len(chiave & _parole(t)) / len(chiave) < soglia:
            continue
        out.append((t, p))
    return out


_RE_SIGLA_MODELLO = re.compile(r"^(?=[a-z0-9]*[a-z])(?=[a-z0-9]*\d)[a-z0-9]{2,}$")
_RE_SPECIFICA = re.compile(r"^\d+(mp|gb|tb|mb|mm|cm|ml|cl|kg|gr|w|v|hz|k|g|l|x|inch|pollici)$")


def _e_sigla_modello(w):
    """'s1900', 'ps5', 'v15', 'a7iii' si' (sono il modello); '2mp', '64gb', '24cm' no (sono specifiche). Pura."""
    return bool(_RE_SIGLA_MODELLO.match(w)) and not _RE_SPECIFICA.match(w)


def query_comp(titolo, brand=None, max_parole=4):
    """Testo di ricerca: marca + prime parole significative del titolo (niente 'usato', 'ottime condizioni'...).

    Se il titolo ha una sigla di modello (es. 'S1900'), la ricerca parte dalla parola prima della sigla (la serie, 'finepix'):
    'Fotocamera compatta digitale Fujifilm FinePix S1900' dava 'fujifilm fotocamera compatta digitale' e il modello restava
    fuori (31/10)."""
    parole = [w for w in re.findall(r"[\w'’]+", (titolo or "").lower()) if w not in _PAROLE_VUOTE and w not in _PAROLE_GENERICHE]
    b = brand.lower().split() if brand else []
    if b:
        parole = [w for w in parole if w not in b]
    for i, w in enumerate(parole):
        if _e_sigla_modello(w):
            if i > 0 and not parole[i - 1].isdigit():
                parole = parole[i - 1:]
            else:
                parole = parole[i:]
            parole = [x for x in parole if not x.isdigit() and not _RE_SPECIFICA.match(x)]  # '12.2MP' lascia '12' e '2mp': rumore
            break
    return " ".join((b + parole)[:max_parole])


def stima_mercato(prezzi, min_n=MIN_COMPARABILI):
    """Stima dai prezzi richiesti di annunci simili. None se i comparabili sono troppo pochi.

    rivendita = 25° percentile dopo aver tolto i valori fuori scala (sotto 0,3x o sopra 3x la mediana).
    La trattativa non e' qui: la applica margine_roi (SCONTO_TIPICO_TRATTATIVA_VENDITA).
    affidabilita': alta con >= 10 comparabili e fascia stretta (p75/p25 <= 1,6), media con >= 6, bassa altrimenti.
    """
    v = sorted(p for p in prezzi if p and p > 0)
    if len(v) < min_n:
        return None
    med = statistics.median(v)
    v = [p for p in v if 0.3 * med <= p <= 3 * med]
    if len(v) < min_n:
        return None
    q = statistics.quantiles(v, n=4, method="inclusive")
    p25, mediana, p75 = q[0], q[1], q[2]
    stretta = p25 > 0 and p75 / p25 <= 1.6
    aff = "alta" if len(v) >= 10 and stretta else "media" if len(v) >= 6 else "bassa"
    return {"n": len(v), "minimo": v[0], "p25": round(p25, 2), "mediana": round(mediana, 2), "p75": round(p75, 2),
            "massimo": v[-1], "rivendita": round(p25, 2), "affidabilita": aff}


def tetto_dal_nuovo(rivendita, prezzo_nuovo, quota=QUOTA_NUOVO_USATO):
    """L'usato non vale quanto il nuovo: la rivendita non supera quota x prezzo del nuovo (se noto)."""
    if not prezzo_nuovo or prezzo_nuovo <= 0:
        return rivendita
    return min(rivendita, round(prezzo_nuovo * quota, 2))


def semaforo(v):
    """Verde: affare con almeno 6 comparabili (candidato ad avviso). Giallo: affare con 2-5 comparabili (solo osservazione, non suona). Rosso: il resto."""
    if not v.get("ok"):
        return "rosso"
    n = v.get("n") or 0
    if n >= 6:
        return "verde"
    return "giallo" if n >= 2 else "rosso"


def valuta(prezzo, stima, prezzo_nuovo=None, spedizione_eur=SPEDIZIONE_STIMATA_EUR, rischio_falsi=1, rischio_guasti=1):
    """Verdetto economico di un annuncio da `prezzo` EUR. Pura.

    Ritorna dict con rivendita, margine, roi, ok (margine >= RADAR_MARGINE_MIN e ROI >= RADAR_ROI_MIN) e motivo.
    Senza stima (pochi comparabili) ok e' sempre False con motivo 'pochi_comparabili'.
    """
    if not stima:
        return {"ok": False, "motivo": "pochi_comparabili", "rivendita": None, "margine": None, "roi": None, "semaforo": "rosso"}
    riv = tetto_dal_nuovo(stima["rivendita"], prezzo_nuovo)
    marg, roi = margine_roi(prezzo, riv, spedizione_eur, rischio_falsi, rischio_guasti)
    ok = marg >= RADAR_MARGINE_MIN and roi >= RADAR_ROI_MIN
    motivo = "ok" if ok else ("margine_basso" if marg < RADAR_MARGINE_MIN else "roi_basso")
    v = {"ok": ok, "motivo": motivo, "rivendita": riv, "margine": marg, "roi": roi,
         "limitato_dal_nuovo": riv < stima["rivendita"], "affidabilita": stima["affidabilita"], "n": stima["n"]}
    v["semaforo"] = semaforo(v)
    return v
