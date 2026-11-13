"""Verifica con Jev degli avvisi dei brand nuovi della moda (richiesta dell'utente, 02/11).

I brand in FAIR_VALUE_BRAND_NUOVI hanno un fair value stimato da me, non misurato. Qui, prima di avvisare, si fa come nel radar:
  1. comparabili cercati su Vinted (brand_ids[] + categoria dell'annuncio + parole del titolo);
  2. Jev giudica ogni titolo (stesso modello / simile / altro) e la rivendita si ricalcola sui comparabili veri;
  3. Jev guarda la prima foto e dice se l'articolo sembra originale del brand (indizio dalla sola foto, non una certificazione).
Esito: 'conferma' (margine >= 50 EUR e ROI >= 100% sui comparabili, foto non sospetta), 'scarta' (i comparabili non reggono il margine
oppure la foto sembra falsa/altra marca), 'non_verificato' (comparabili non trovati o Jev spento: l'avviso parte con l'avvertenza).
Spenta con MODA_JEV=0 (default 1, letta una volta sola in bot/config.py); MODA_JEV_TUTTI=1 la estende a tutti gli avvisi (non solo ai brand nuovi). Costo: poche chiamate Jev solo per i pochi avvisi dei brand nuovi; tetto MODA_JEV_MAX_GIORNO.
"""
import os
import re
import time
import asyncio
import traceback
from urllib.parse import quote

from bot.comps import _cerca_vinted_testo_diretto, _miniature_comp
from bot.config import MODA_JEV, SPEDIZIONE_STIMATA_EUR
from bot.costanti import VINTED_BRAND_IDS
from bot.foto import download_image_bytes, optimize_image_bytes
from bot.comps_filtri import BRAND_SOTTOLINEE_DA_ESCLUDERE
from bot.fair_value import FAIR_VALUE_APPRESO, FAIR_VALUE_BRAND_NUOVI, FAIR_VALUE_SOTTOLINEE, _jsonl_append
from bot.jev import CONF_AUTENTICITA_MIN, MAX_FOTO_AUTENTICITA, DOMANDA_FOTO_COMP_MODA, JEV_FOTO_COMPS, MAX_FOTO_COMPS, confronta_foto_comparabili, giudica_autenticita
from bot.logger import log
from bot.vinted_api import condizione_comp
from bot.vinted_search import aggiusta_prezzo_comp, stati_comps
from bot.velocita import riga_velocita
from bot.moda_gemini import controlla as controlla_gemini, e_non_moda, e_replica, riga_consiglio, riga_condizioni, riga_stima_gemini, serve_controllo, sconto_difetti
from bot.testo import RigaMd, _normalizza_titolo_per_link, link_markdown
from bot.valore_mercato import comparabili_simili, parse_comp, query_comp, solo_usato, stima_mercato, valuta
# ---- fine import ----

MODA_JEV_MAX_GIORNO = int(os.environ.get("MODA_JEV_MAX_GIORNO", "600") or 600)
# 02/11 (richiesta dell'utente): la verifica vale per TUTTI gli avvisi della moda, non solo per i brand nuovi. 0 = solo brand nuovi.
MODA_JEV_TUTTI = os.environ.get("MODA_JEV_TUTTI", "0").strip() in ("1", "true", "si")
# 02/11 (richiesta dell'utente): l'avviso parte SUBITO (come prima della verifica) e lo stesso messaggio viene aggiornato con l'esito
# Jev (comparabili, foto) o con "scartato dalla verifica". 0 = avviso trattenuto fino alla verifica.
MODA_JEV_SUBITO = os.environ.get("MODA_JEV_SUBITO", "1").strip() not in ("0", "false", "no", "")
MIN_COMPARABILI = 3
# 5/11 (utente): Jev scarta sul margine solo sotto i 40 EUR (prima 50, soglia del radar); il ROI minimo resta quello di sempre.
try:
    MODA_JEV_MARGINE_MIN = float(os.environ.get("MODA_JEV_MARGINE_MIN", "40"))
except ValueError:
    MODA_JEV_MARGINE_MIN = 40.0
# 6/11 (utente): limite alla dispersione. Sui comparabili del testo (dopo aver tolto i fuori scala, come fa stima_mercato) il rapporto
# p75/p25 dei prezzi sopra questa soglia dice che non c'e' un prezzo di mercato: niente CONFERMATO, resta la stima rapida. Soglia SCELTA,
# non misurata (la fascia "stretta" di stima_mercato e' 1,6); si regola con MODA_JEV_DISPERSIONE_MAX, 0 = spento.
try:
    MODA_JEV_DISPERSIONE_MAX = float(os.environ.get("MODA_JEV_DISPERSIONE_MAX", "2.5") or 0)
except ValueError:
    MODA_JEV_DISPERSIONE_MAX = 2.5
# 02/11: la foto dei comparabili conta solo se Jev li trova MOLTO simili (stesso modello, confidenza >= soglia): allora il loro prezzo
# diventa la rivendita; altrimenti resta la ricerca testuale come prima (Jev non scarta piu' i comparabili: era troppo stringente).
CONF_FOTO_MOLTO_SIMILE = 0.6
_conteggio = {"giorno": None, "n": 0}


def tratteni_per_verifica(fv, regola):
    """True se l'avviso va trattenuto fino alla verifica Jev: con MODA_JEV_TUTTI ogni avviso (regola diversa da 'no'); altrimenti solo
    la regola brand_nuovo sui brand nuovi. Pura."""
    if not MODA_JEV or not regola or regola == "no":
        return False
    return bool(MODA_JEV_TUTTI or regola == "da_verificare" or (regola == "brand_nuovo" and (fv or {}).get("brand") in FAIR_VALUE_BRAND_NUOVI))


def id_brand(brand):
    """Id Vinted del brand dalla tabella della moda, o None. Pura."""
    return VINTED_BRAND_IDS.get((brand or "").strip().lower())


# 8/11 (utente): ordine della ricerca dei comparabili. Oggi 'newest_first' (ultimi pubblicati); da provare 'relevance' (piu' simili al testo)
# e 'price_low_to_high'. MODA_COMPS_PROVA: ordini alternativi cercati IN OMBRA (solo nelle ricerche in ombra, non cambiano nessun esito) e
# confrontati nel log `COMPS ORDINE`, per scegliere con i dati.
MODA_COMPS_ORDINE = os.environ.get("MODA_COMPS_ORDINE", "newest_first").strip() or "newest_first"
MODA_COMPS_PROVA = [o.strip() for o in os.environ.get("MODA_COMPS_PROVA", "").split(",") if o.strip()]


def url_comparabili(brand, testo=None, catalogo=None, ordine=None, condizione=None, stato=None):
    """Ricerca dei simili: brand_ids[] + categoria foglia dell'annuncio + parole del titolo (se ci sono). None senza id brand. Pura."""
    bid = id_brand(brand)
    if not bid and not brand:
        return None
    # senza id (brand storici fuori dalla tabella) il brand entra come parola di ricerca
    t = f"&search_text={quote(testo if bid else ((brand or '') + ' ' + (testo or '')).strip())}" if (testo or not bid) else ""
    c = f"&catalog[]={catalogo}" if catalogo else ""
    b = f"brand_ids[]={bid}" if bid else "currency=EUR"
    return f"https://www.vinted.it/catalog?{b}{c}{t}&order={ordine or MODA_COMPS_ORDINE}{f'&status_ids[]={stato}' if stato else stati_comps(condizione)}"


MODA_JEV_OMBRA = os.environ.get("MODA_JEV_OMBRA", "1").strip() not in ("0", "false", "no", "")
try:
    MODA_JEV_OMBRA_MAX_ORA = int(os.environ.get("MODA_JEV_OMBRA_MAX_ORA", "20") or 20)
except ValueError:
    MODA_JEV_OMBRA_MAX_ORA = 20
try:
    MODA_JEV_OMBRA_CAMPIONI_MIN = int(os.environ.get("MODA_JEV_OMBRA_CAMPIONI_MIN", "5") or 5)
except ValueError:
    MODA_JEV_OMBRA_CAMPIONI_MIN = 5
LEGIT_APPRESO_FILE = os.environ.get("LEGIT_APPRESO_FILE", "/data/legit_appreso.jsonl")
_ombra_chiamate = []   # istanti dell'ultima ora: tetto MODA_JEV_OMBRA_MAX_ORA (ogni ricerca costa banda proxy)


def semaforo_da_verificare(fv):
    """True se il semaforo di quel brand e categoria non e' ancora verificato dai dati: confidenza bassa o a priori, oppure meno di
    MODA_JEV_OMBRA_CAMPIONI_MIN campioni appresi (comparabili Jev, Gemini, tuoi). 8/11 (utente): i rossi vanno cercati solo finche'
    serve a portare il semaforo a una confidenza verificata, poi la ricerca si ferma. Pura."""
    if not fv or not fv.get("brand"):
        return False
    if fv.get("conf") in ("bassa", "stima"):
        return True
    if not fv.get("categoria"):
        return False
    return (FAIR_VALUE_APPRESO.get(f"{fv['brand']}|{fv['categoria']}") or {}).get("n", 0) < MODA_JEV_OMBRA_CAMPIONI_MIN


def serve_ombra(fv, adesso=None):
    """True se un annuncio che il semaforo scarta vale una ricerca di comparabili 'in ombra': semaforo ancora da verificare
    (vedi semaforo_da_verificare) e sotto il tetto orario. Registra la chiamata. Pura a parte il contatore."""
    if not MODA_JEV_OMBRA or not semaforo_da_verificare(fv):
        return False
    adesso = adesso if adesso is not None else time.time()
    while _ombra_chiamate and adesso - _ombra_chiamate[0] > 3600:
        _ombra_chiamate.pop(0)
    if len(_ombra_chiamate) >= MODA_JEV_OMBRA_MAX_ORA:
        return False
    _ombra_chiamate.append(adesso)
    return True


def registra_legit(listing_info, brand, gemini, linea=None):
    """Archivia cosa Gemini ha letto sull'etichetta e il suo giudizio (/data/legit_appreso.jsonl), per confrontare in futuro le etichette
    nuove con quelle gia' viste. Per ora SOLO registrazione: il giudizio di Gemini non e' una certificazione, non decide nulla. Mai eccezioni."""
    try:
        if gemini:
            _jsonl_append(LEGIT_APPRESO_FILE, {"item": listing_info.get("item_id"), "brand": brand, "linea": linea, "autenticita": gemini.get("autenticita"),
                                               "conf": gemini.get("confidenza"), "etichetta": gemini.get("etichetta_letta"), "linea_etichetta": gemini.get("linea_etichetta"),
                                               "made_in": gemini.get("made_in"), "indizi": gemini.get("indizi"), "motivo": gemini.get("motivo")}, "legit_appreso")
    except Exception:
        pass


def linea_dal_testo(testo, brand, descrizione=None):
    """Nome della sottolinea del brand scritta nel titolo o nella descrizione ('weekend max mara' da 'Cappotto Weekend MaxMara'), o None.
    Nella descrizione la parola sola non basta ('l'ho usato nel weekend'): il nome del brand deve stare a meno di 25 caratteri. Pura."""
    b = (brand or "").strip().lower()
    regole = FAIR_VALUE_SOTTOLINEE.get(b, {})
    t = (testo or "").lower()
    for nome, pattern in regole.items():
        if re.search(pattern, t):
            return nome
    d = (descrizione or "").lower()
    compatto = b.replace(" ", r"\s*")
    for nome, pattern in regole.items():
        for m in re.finditer(pattern, d):
            vicino = d[max(0, m.start() - 25):m.end() + 25]
            if re.search(compatto, vicino) or re.search(re.escape(nome), vicino):
                return nome
    return None


def linea_da_etichetta(etichetta, brand):
    """(nota, linea) dalla linea che Gemini ha letto sull'etichetta: nota=False se non l'ha letta; ('principale', 'mainline', 'brand') -> (True, None);
    un nome di sottolinea riconosciuto -> (True, nome). Pura."""
    e = (etichetta or "").strip().lower()
    if not e or e in ("non_leggibile", "non leggibile", "n/d", "-"):
        return False, None
    if e in ("principale", "mainline", "main", "brand", "linea principale"):
        return True, None
    for nome, pattern in FAIR_VALUE_SOTTOLINEE.get((brand or "").strip().lower(), {}).items():
        if re.search(pattern, e) or nome in e:
            return True, nome
    return False, None


def filtra_per_linea(comps, brand, linea):
    """6/11 (utente): Weekend Max Mara non e' Max Mara. Con una sottolinea dichiarata tiene solo i comparabili che la nominano; senza,
    toglie quelli che nominano una sottolinea nota del brand (fascia di prezzo diversa). Un comparabile che non nomina la linea resta tra
    quelli della linea principale: dal solo titolo non si puo' sapere. Pura."""
    b = (brand or "").strip().lower()
    pattern_tutti = list(FAIR_VALUE_SOTTOLINEE.get(b, {}).values())
    parole = BRAND_SOTTOLINEE_DA_ESCLUDERE.get(b, [])
    if linea:
        pat = FAIR_VALUE_SOTTOLINEE[b][linea]
        return [(t, p) for t, p in comps if re.search(pat, t.lower())]
    return [(t, p) for t, p in comps if not any(re.search(x, t.lower()) for x in pattern_tutti) and not any(w in t.lower() for w in parole)]


def comparabili_con_link(coppie, mappe, n=MAX_FOTO_COMPS):
    """[(titolo, prezzo, url)] dei `n` comparabili piu' vicini alla mediana dei prezzi che hanno un link noto. `mappe` = dizionari
    {(titolo normalizzato, prezzo 2f): url} delle ricerche. Pura."""
    if not coppie:
        return []
    prezzi = sorted(p for _, p in coppie)
    mediana = prezzi[len(prezzi) // 2]
    out, visti = [], set()
    for t, p in sorted(coppie, key=lambda c: abs(c[1] - mediana)):
        url = next((m[k] for m in mappe if m for k in [(_normalizza_titolo_per_link(t), f"{p:.2f}")] if k in m), None)
        if url and url not in visti:
            visti.add(url)
            out.append((t, p, url))
        if len(out) >= n:
            break
    return out


async def _miniature_dei_comparabili(link_comps):
    """[(comparabile, byte)] delle miniature (ridotte a 512 px) dei comparabili con link noto e foto scaricabile: l'allineamento resta,
    cosi' il confronto di Jev si riferisce al comparabile giusto. Lista vuota se mancano."""
    con_foto = []
    for c in link_comps:
        m = re.search(r"/items/(\d+)", c[2])
        u = _miniature_comp.get(m.group(1)) if m else None
        if u:
            con_foto.append((c, u))
    con_foto = con_foto[:MAX_FOTO_COMPS]
    scaricate = await asyncio.gather(*(download_image_bytes(u) for _c, u in con_foto), return_exceptions=True)
    out = []
    for (c, _u), b in zip(con_foto, scaricate):
        if isinstance(b, bytes) and b:
            out.append((c, await asyncio.to_thread(optimize_image_bytes, b, 512)))
    return out


def prezzi_pesati_da_foto(coppie, confronti, conf_min=CONF_FOTO_MOLTO_SIMILE):
    """(prezzi, comparabili): prezzi dei comparabili che Jev giudica dalla foto, con pesi 10/11 (utente): stesso_modello vale il doppio di
    simile, diverso (o non chiaro, o confidenza bassa) 0. Il peso 2 e' il prezzo ripetuto due volte, cosi' stima_mercato lo conta il doppio.
    Se nessun comparabile e' 'stesso_modello' ritorna ([], []): resta la stima testuale. Pura."""
    if not coppie or not confronti:
        return [], []
    prezzi, comp, stesso = [], [], False
    for (c, _b), (sc, cf) in zip(coppie, confronti):
        if (cf or 0) < conf_min or sc not in ("stesso_modello", "simile"):
            continue
        peso = 2 if sc == "stesso_modello" else 1
        stesso = stesso or sc == "stesso_modello"
        prezzi += [c[1]] * peso
        comp.append(c)
    return (prezzi, comp) if stesso else ([], [])


SIGLE_FOTO = {"stesso_modello": "SM", "simile": "S", "diverso": "D"}


def sigle_foto_comps(coppie, confronti, conf_min=CONF_FOTO_MOLTO_SIMILE):
    """Lista (titolo, prezzo, url, sigla) dei comparabili guardati da Jev, in ordine SM, S, D, ? (10/11, utente: 'SM, S, D vicino ai comps').
    SM stesso modello, S simile, D diverso, ? non chiaro o confidenza bassa. Pura."""
    ordine = {"SM": 0, "S": 1, "D": 2, "?": 3}
    out = []
    for (c, _b), (sc, cf) in zip(coppie or [], confronti or []):
        sigla = SIGLE_FOTO.get(sc, "?") if (cf or 0) >= conf_min else "?"
        out.append((c[0], c[1], c[2], sigla))
    return sorted(out, key=lambda x: ordine[x[3]])


def riassunto_sigle(elenco):
    """'2 SM · 1 S · 1 D' dai comparabili con sigla (vuoto se non ce ne sono). Pura."""
    conta = {}
    for *_r, sg in elenco or []:
        conta[sg] = conta.get(sg, 0) + 1
    return " · ".join(f"{conta[k]} {k}" for k in ("SM", "S", "D", "?") if conta.get(k))


def _entro_il_tetto():
    oggi = time.strftime("%Y-%m-%d")
    if _conteggio["giorno"] != oggi:
        _conteggio.update(giorno=oggi, n=0)
    if _conteggio["n"] >= MODA_JEV_MAX_GIORNO:
        return False
    _conteggio["n"] += 1
    return True


def comparabili_non_simili(foto_comps):
    """True se Jev, guardando le foto, non trova NESSUN comparabile simile all'annuncio (almeno uno 'diverso', nessun 'simile'/'stesso_modello'):
    la rivendita dai prezzi dei comparabili non e' un riferimento valido (6/11, utente: sacca Miu Miu a 5 EUR contro comparabili da 3 a 600 EUR).
    Pura."""
    if not foto_comps:
        return False
    scelte = [sc for sc, _cf in foto_comps]
    return "diverso" in scelte and not any(sc in ("simile", "stesso_modello") for sc in scelte)


def correggi_per_difetti(v, prezzo, gemini):
    """(v_nuovo, sconto_pct): abbassa la rivendita dei comparabili (in genere in buone condizioni) dei difetti letti da Gemini nelle foto e
    rifa' margine, ROI ed esito con le stesse soglie di valuta(). Lo sconto e' una stima di Gemini, con tetto per gravita' (moda_gemini).
    Senza difetti, senza rivendita o senza Gemini ritorna (v, 0). Non cambia v. Pura."""
    pct = sconto_difetti(gemini)
    if not v or not pct or v.get("rivendita") is None:
        return v, 0.0
    stima = {"rivendita": v["rivendita"] * (1 - pct / 100), "affidabilita": v.get("affidabilita"), "n": v.get("n"),
             "richiesto_mediano": v.get("richiesto_mediano"), "vendita_rapida": v.get("vendita_rapida"), "calibrazione": v.get("calibrazione")}
    nuovo = valuta(prezzo, stima, spedizione_eur=SPEDIZIONE_STIMATA_EUR, margine_min=MODA_JEV_MARGINE_MIN)
    nuovo["rivendita_prima_difetti"] = v["rivendita"]
    return nuovo, pct


def rivendita_mista(fv, riv_comps, n_comps, gemini, riv_rilevanza=None):
    """(rivendita, parti): media pesata di stime indipendenti (7/11, utente: 'prezzo di rivendita bilanciato tra semaforo, comparabili e
    Gemini, con i loro valori tra parentesi'). 8/11 (utente): pesi RELATIVI al semaforo, che vale w = 0,3 con confidenza alta / 0,2 media /
    0,1 bassa: comparabili per rilevanza w, comparabili per data (newest_first) 0,8 x w, Gemini w (uguale al semaforo, solo se la sua
    confidenza e' almeno 0,4). Rapporti scelti dall'utente (10/11: prima rilevanza 2,5 x e newest_first 1,8 x; ora Gemini e rilevanza
    contano uguale, newest_first un po' meno), non misurati. `parti` = {'semaforo','comparabili','rilevanza','gemini'} con i soli
    valori presenti. (None, {}) se non c'e' nessuna stima. Pura."""
    parti, pesi = {}, {}
    w = {"alta": 0.3, "media": 0.2}.get((fv or {}).get("conf"), 0.1)
    if fv and fv.get("fv"):
        parti["semaforo"] = float(fv["fv"])
        pesi["semaforo"] = w
    if riv_comps:
        parti["comparabili"] = float(riv_comps)
        pesi["comparabili"] = 0.8 * w
    if riv_rilevanza:
        parti["rilevanza"] = float(riv_rilevanza)
        pesi["rilevanza"] = w
    rg, cg = (gemini or {}).get("rivendita_gemini_eur"), (gemini or {}).get("rivendita_confidenza")
    if rg and cg is not None and cg >= 0.4:
        parti["gemini"] = float(rg)
        pesi["gemini"] = w
    if not parti:
        return None, {}
    tot = sum(pesi.values())
    return round(sum(parti[k] * pesi[k] for k in parti) / tot, 2), {k: round(v, 2) for k, v in parti.items()}


CONF_GEMINI_PREVALE = 0.85   # Gemini "coerente" con almeno questa confidenza...
CONF_JEV_REPLICA_DEBOLE = 0.75   # ...corregge una "replica probabile" di Jev se questa e' sotto questa confidenza


def gemini_prevale(autenticita, gemini):
    """True se Gemini (tutte le foto, etichette lette) dice "coerente" con confidenza alta e Jev (una sola lettura per foto) dice "replica probabile"
    con confidenza non alta: prevale Gemini (7/11, utente: caso Jean Paul Gaultier, Jev 51% replica contro Gemini 95% coerente). Una replica di Jev
    sicura, o "altra marca", non si corregge. Pura."""
    return bool(autenticita and autenticita[0] == "replica_probabile" and (autenticita[1] or 0) < CONF_JEV_REPLICA_DEBOLE
                and gemini and gemini.get("autenticita") == "probabile" and (gemini.get("confidenza") or 0) >= CONF_GEMINI_PREVALE)


def decidi(valutazione, autenticita, gemini=None, foto_comps=None, dispersione=None):
    """(esito, motivo) dalle due verifiche. `valutazione` = dict di valuta() o None se i comparabili mancano; `autenticita` =
    (scelta, confidenza) o None; `gemini` = dict del controllo Gemini su tutte le foto o None. Il falso scarta sempre; senza comparabili
    l'avviso parte non verificato. Pura."""
    if e_replica(gemini):
        return "scarta", "gemini:replica"
    if e_non_moda(gemini):   # 9/11: Gemini vede che non e' moda (es. un profumo con il nome di un brand): niente avviso
        return "scarta", "gemini:non_moda"
    if autenticita and autenticita[0] in ("replica_probabile", "altra_marca") and (autenticita[1] or 0) >= CONF_AUTENTICITA_MIN \
            and not gemini_prevale(autenticita, gemini):
        return "scarta", "foto:" + autenticita[0]
    if valutazione is None:
        return "non_verificato", "comparabili_non_trovati"
    if not valutazione.get("ok"):
        return "scarta", "comparabili:" + str(valutazione.get("motivo"))
    if comparabili_non_simili(foto_comps):
        return "non_verificato", "comparabili_non_simili"
    if MODA_JEV_DISPERSIONE_MAX and dispersione and dispersione > MODA_JEV_DISPERSIONE_MAX:
        return "non_verificato", "prezzi_dispersi"
    return "conferma", "ok"


def riga_esito_scheda(ris):
    """Riga (testo semplice) per la scheda della chat principale dopo la verifica: perche' l'avviso e' partito o no. Pura."""
    a = ris.get("autenticita")
    if ris.get("esito") == "scarta":
        if ris.get("motivo") == "gemini:non_moda":
            return f"🚫 Gemini: non avvisato, non è moda ({((ris.get('gemini') or {}).get('confidenza') or 0):.0%})"
        if ris.get("motivo") == "gemini:replica":
            return f"🚫 Gemini: non avvisato, indizi di replica nelle foto ({((ris.get('gemini') or {}).get('confidenza') or 0):.0%})"
        if str(ris.get("motivo", "")).startswith("foto:") and a:
            return f"🚫 Jev: non avvisato, la foto sembra {a[0].replace('_', ' ')} ({(a[1] or 0):.0%})"
        if ris.get("rivendita") is not None:
            return (f"🚫 Jev: non avvisato, rivendita sui {ris['n']} comparabili ~{ris['rivendita']:.0f} € "
                    f"(margine ~{ris['margine']:.0f} €, ROI {ris['roi']:.0f}%)")
        return "🚫 Jev: non avvisato (" + str(ris.get("motivo")) + ")"
    if ris.get("esito") == "conferma":
        return f"✅ Jev: confermato, rivendita ~{ris['rivendita']:.0f} € (margine ~{ris['margine']:.0f} €), avviso mandato"
    if ris.get("motivo") == "prezzi_dispersi":
        return "⚠️ Jev: i prezzi dei comparabili sono troppo diversi tra loro, rivendita non affidabile, avviso mandato non verificato"
    if ris.get("motivo") == "comparabili_non_simili":
        return "⚠️ Jev: i comparabili non assomigliano alla foto, rivendita non affidabile, avviso mandato non verificato"
    if ris.get("motivo") == "tetto_giornaliero":
        return "⚠️ Jev: tetto giornaliero di verifiche raggiunto, avviso mandato non verificato"
    return "⚠️ Jev: comparabili non trovati, avviso mandato non verificato"


def _dati_jev_piatti(ris):
    """Campi piatti del risultato di Jev per la riga TRACCIATO (solo valori presenti). Pura, mai eccezioni."""
    try:
        a = ris.get("autenticita")
        g = ris.get("gemini") or {}
        d = {"jev_esito": ris.get("esito"), "jev_motivo": str(ris.get("motivo") or "")[:40], "jev_n": ris.get("n"),
             "jev_riv": ris.get("rivendita"), "jev_marg": ris.get("margine"), "jev_roi": ris.get("roi"),
             "jev_disp": round(ris["dispersione"], 2) if ris.get("dispersione") else None,
             "jev_foto": a[0] if a else None, "jev_foto_conf": a[1] if a else None,
             "jev_gem": g.get("autenticita"), "jev_gem_conf": g.get("confidenza"), "jev_tipo": g.get("tipo_oggetto"), "jev_legit": _stato_originalita(ris)[0]}
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items() if v not in (None, "")}
    except Exception:
        return {}


def _stato_originalita(ris):
    """('replica'|'dubbio'|'non_chiaro'|'ok'|'nessuno', parti): sintesi dei controlli di autenticita' (Jev sulle foto, risposte del legit check di Jev,
    Gemini su tutte le foto) per il messaggio. Il caso peggiore vince; una replica probabile con confidenza bassa conta comunque (6/11, utente:
    non declassare, ma far vedere subito se e' originale). Pura."""
    a = ris.get("autenticita")
    g = ris.get("gemini")
    parti, stato = [], "nessuno"

    def peggio(nuovo_stato):
        ordine = ["nessuno", "ok", "non_chiaro", "dubbio", "replica"]
        return nuovo_stato if ordine.index(nuovo_stato) > ordine.index(stato) else stato
    if a and a[0] and gemini_prevale(a, g):
        parti.append(f"Jev foto: replica probabile ({(a[1] or 0):.0%}), ma Gemini sulle etichette dice coerente: prevale Gemini")
        stato = "ok"
        a = None
    if a and a[0]:
        etichette = {"originale_plausibile": "sembra originale", "non_chiaro": "non si capisce", "replica_probabile": "replica probabile", "altra_marca": "altra marca"}
        parti.append(f"Jev foto: {etichette.get(a[0], a[0])}" + (f" ({a[1]:.0%})" if a[1] is not None else ""))
        stato = peggio({"originale_plausibile": "ok", "non_chiaro": "non_chiaro"}.get(a[0], "replica"))
        for nome, r in (getattr(a, "dettagli", None) or {}).items():
            if r and r[0] in ("incoerente", "sospetta"):
                parti.append(f"{nome.replace('_', ' ')} {r[0].upper()}")
                stato = peggio("dubbio")
    if g and g.get("autenticita"):
        etichette = {"probabile": "coerente", "dubbia": "dubbio", "replica": "replica", "altra_marca": "altro marchio", "non_verificabile": "non verificabile"}
        parti.append(f"Gemini foto: {etichette.get(g['autenticita'], g['autenticita'])}" + (f" ({g['confidenza']:.0%})" if g.get("confidenza") is not None else ""))
        stato = peggio({"probabile": "ok", "non_verificabile": "non_chiaro", "dubbia": "dubbio"}.get(g["autenticita"], "replica"))
    return stato, parti


def _da_chiedere(ris):
    """Cosa chiedere al venditore per sciogliere i dubbi: la richiesta di Gemini (ha visto le foto) oppure, se non c'e', quella ricavata dalle
    risposte di Jev (etichetta di lavaggio con il made in se non si vede). Stringa vuota se non serve. Pura."""
    g = ris.get("gemini") or {}
    if g.get("da_chiedere"):
        return g["da_chiedere"]
    det = getattr(ris.get("autenticita"), "dettagli", None) or {}
    if (det.get("made_in") or (None,))[0] == "non_visibile":
        return "foto dell'etichetta di lavaggio con il made in"
    return ""


def riga_azione(ris, stato):
    """'👉 ...' cosa fare quando l'originalita' non e' sicura (7/11, utente: 'non capisco se devo comprare, se fake, cosa devo chiedere'). Per
    'ok' nessuna riga: il verdetto dice gia' che si puo' comprare. Pura."""
    if stato == "replica":
        return "👉 Non comprare: indizi di replica nelle foto"
    if stato in ("dubbio", "non_chiaro", "nessuno"):
        chiedi = _da_chiedere(ris)
        return "👉 Prezzo buono ma originalità non verificata: " + (f"prima chiedi {chiedi}" if chiedi else "chiedi al venditore foto di etichette interne e cuciture")
    return None


def azione_codice(ris):
    """Azione del verdetto per la riga TRACCIATO (8/11): 'compra' (originalita' ok), 'chiedi' (dubbia: prima chiedere foto/dettagli),
    'non_comprare' (replica) o 'scartato' (Jev scarta). Pura."""
    if ris.get("esito") == "scarta":
        return "scartato"
    stato, _ = _stato_originalita(ris)
    return {"ok": "compra", "replica": "non_comprare"}.get(stato, "chiedi")


def riga_originalita(ris):
    """Riga in evidenza subito sotto il verdetto: l'annuncio sembra originale o no, con chi lo dice (6/11, utente: 'piu' visibilita' immediata di se
    e' originale o no', senza declassare l'avviso). None se scartato (il verdetto spiega gia' il perche') o se il legit check e' stato saltato. Pura."""
    if ris.get("esito") == "scarta" or ris.get("legit_saltato"):
        return None
    stato, parti = _stato_originalita(ris)
    testa = "🔐 Originalità: " + {"replica": "🚨 FAKE probabile", "dubbio": "⚠️ DA CONTROLLARE", "non_chiaro": "⚠️ DA CONTROLLARE (non chiara)",
                                  "ok": "✅ LEGIT (sembra originale)", "nessuno": "❔ NON VERIFICATA"}[stato]
    azione = riga_azione(ris, stato)
    return testa + (" · " + " · ".join(parti) if parti else "") + (("\n" + azione) if azione else "")


def parti_rivendita_testo(parti):
    """' (semaforo 82 · comparabili 270 · Gemini 250)': i valori da cui nasce la rivendita mista, solo quelli presenti. Vuota con un solo valore. Pura."""
    if not parti or len(parti) < 2:
        return ""
    nomi = {"semaforo": "semaforo", "comparabili": "recenti", "rilevanza": "rilevanti", "gemini": "Gemini"}
    return " (" + " · ".join(f"{nomi[k]} {parti[k]:.0f}" for k in nomi if k in parti) + ")"


def riga_verdetto(ris):
    """Prima riga del messaggio: esito e numero che l'ha deciso, senza parole di contorno (8/11, utente: 'zero parole senza valore aggiunto').
    Formati: '✅ CONFERMATO · rivendita ~X € (parti) · margine ~X € · ROI X%', '🚫 SCARTATO · rivendita ~X € (parti) · margine X € < 40 €',
    '🚫 SCARTATO · replica (Gemini 80%)', '⚠️ NON VERIFICATO · nessun comparabile'. Pura."""
    mot = str(ris.get("motivo", ""))
    if ris.get("esito") == "scarta":
        if mot.startswith("comparabili:") and ris.get("rivendita") is not None:
            if mot.endswith("roi_basso"):
                dove = f"ROI {ris['roi']:.0f}% < 100%"
            else:
                dove = f"margine ~{ris['margine']:.0f} € < {MODA_JEV_MARGINE_MIN:g} €"
            dif = f" · difetti −{ris['sconto_difetti']:.0f}%" if ris.get("sconto_difetti") else ""
            # 8/11: la rivendita e' quella mista (semaforo, comparabili per data e per rilevanza, Gemini): si mostrano i valori da cui nasce
            return f"🚫 SCARTATO · rivendita ~{ris['rivendita']:.0f} €{parti_rivendita_testo(ris.get('parti_rivendita'))}{dif} · {dove}"
        a = ris.get("autenticita")
        if mot == "gemini:non_moda":
            return f"🚫 SCARTATO · non è moda (Gemini {((ris.get('gemini') or {}).get('confidenza') or 0):.0%})"
        if mot == "gemini:replica":
            return f"🚫 SCARTATO · replica (Gemini {((ris.get('gemini') or {}).get('confidenza') or 0):.0%})"
        if mot.startswith("foto:") and a:
            return f"🚫 SCARTATO · foto: {a[0].replace('_', ' ')} ({(a[1] or 0):.0%})"
        return "🚫 SCARTATO · " + (mot or "motivo n/d")
    if ris.get("esito") == "conferma":
        # 8/11 (utente: stile 'linguaggio degli aerei'): esito, rivendita mista con i valori, margine e ROI su una riga; l'originalita' ha la sua riga
        tag = f" · difetti −{ris['sconto_difetti']:.0f}%" if ris.get("sconto_difetti") else ""
        return (f"✅ CONFERMATO · rivendita ~{ris['rivendita']:.0f} €{parti_rivendita_testo(ris.get('parti_rivendita'))} · "
                f"margine ~{ris['margine']:.0f} € · ROI {ris['roi']:.0f}%{tag}")
    if mot == "comparabili_non_simili" and ris.get("rivendita") is not None:
        return f"⚠️ NON VERIFICATO · {ris['n']} comparabili non simili alla foto"
    if mot == "prezzi_dispersi" and ris.get("rivendita") is not None:
        return f"⚠️ NON VERIFICATO · prezzi dispersi (quartile alto {ris['dispersione']:.1f}× il basso)"
    parti, mix = ris.get("parti_rivendita") or {}, ris.get("rivendita_testata")
    if mix and parti and not any(k in parti for k in ("comparabili", "rilevanza")):
        # 10/11 (utente): senza comparabili l'avviso parte lo stesso; riga corta, le fonti stanno tra parentesi
        return f"⚠️ NON VERIFICATO · senza comparabili · rivendita ~{mix:.0f} €{parti_rivendita_testo(parti)}"
    return "⚠️ NON VERIFICATO · nessun comparabile"


def righe_messaggio(ris, brand=None):
    """Righe (testo semplice) dei passi di verifica, a blocchi (7/11, utente: 'strutturato male'; la didascalia Telegram taglia a 1024 caratteri):
    🔎 Comparabili con numeri e fiducia, subito sotto i LINK; 🔍 condizioni e 📉 difetti; ⚡ rotazione del brand. L'originalita' (con Jev e Gemini)
    e' gia' sotto il verdetto (riga_originalita) e la rivendita mista con i tre valori e' nell'intestazione, quindi niente righe sparse per
    Jev, Gemini e semaforo. Pura."""
    righe = []
    consiglio = riga_consiglio(ris.get("gemini"))   # 9/11 (utente): Gemini come consigliere di flip, una riga
    if consiglio:
        righe.append(consiglio)
    n = ris.get("n") or 0
    sigle = ris.get("link_comps_foto")
    comps = ris.get("rivendita_comps") if ris.get("rivendita_comps") is not None else ris.get("rivendita")
    if comps is None and not ris.get("rivendita_ril"):
        righe.append("🔎 Comparabili: nessuno")
    if comps is not None:
        riga = f"📅 Più recenti: {n}"
        pc = ris.get("prezzi_comps")
        if pc:
            riga += f" · {pc[0]:g}–{pc[1]:g} €" if pc[0] != pc[1] else f" · {pc[0]:g} €"
        riga += f" · ~{comps:.0f} €"
        riga += f" · foto: {riassunto_sigle(sigle)}" if sigle else ""
        righe.append(riga)
        link = ris.get("link_comps") or []
        if sigle:   # 10/11 (utente): vicino a ogni comparabile SM stesso modello, S simile, D diverso (giudizio di Jev sulle miniature)
            righe += [RigaMd(f"• {sg} · {link_markdown(t, u)} · {p:g} €") for t, p, u, sg in sigle[:3]]
        elif link:   # comparabili identificati, con il link all'annuncio (richiesta dell'utente, 02/11): subito sotto i numeri
            righe += [RigaMd(f"• {link_markdown(t, u)} · {p:g} €") for t, p, u in link[:3]]
        else:
            righe += [f"• {p:g} € {t[:40]}" for t, p in (ris.get("esempi") or [])[:3]]
    if ris.get("rivendita_ril"):
        # 8/11 (utente: 'aggiungili'): anche i comparabili ordinati per rilevanza, con fascia, rivendita e link
        riga = f"🎯 Più rilevanti: {ris.get('n_ril') or 0}"
        pr = ris.get("prezzi_comps_ril")
        if pr:
            riga += f" · {pr[0]:g}–{pr[1]:g} €" if pr[0] != pr[1] else f" · {pr[0]:g} €"
        righe.append(riga + f" · ~{ris['rivendita_ril']:.0f} €")
        visti = {c[2] for c in (sigle or ris.get("link_comps") or [])[:3]}
        link_ril = [c for c in (ris.get("link_comps_ril") or []) if c[2] not in visti]
        if link_ril:
            righe += [RigaMd(f"• {link_markdown(t, u)} · {p:g} €") for t, p, u in link_ril[:2]]
        elif not ris.get("link_comps_ril"):
            righe += [f"• {p:g} € {t[:40]}" for t, p in (ris.get("esempi_ril") or [])[:3]]
    if ris.get("legit_saltato"):
        righe.append("⏭ Legit check saltato: scartato sui prezzi")
    else:
        cond = riga_condizioni(ris.get("gemini"))
        if cond:
            righe.append(cond)
        if ris.get("sconto_difetti") and ris.get("rivendita_prima_difetti"):
            righe.append(f"📉 Difetti −{ris['sconto_difetti']:.0f}% · comparabili ~{ris['rivendita_prima_difetti']:.0f} → ~{(ris.get('rivendita_comps') or ris['rivendita']):.0f} €")
        avviso = (riga_stima_gemini(ris.get("gemini"), comps) or "").partition("\n")[2]
        if avviso:
            righe.append(avviso)
    if brand is not None:
        righe.append(riga_velocita(brand).replace("⚡ Velocità brand:", "⚡ Rotazione brand:").replace("⚡ Velocità:", "⚡ Rotazione brand:"))
    return righe


def _riga_stima(st):
    """'n=..|p25=..|med=..|p75=..|disp=..' dai comparabili, o 'n=0'. Pura."""
    if not st:
        return "n=0"
    return f"n={st['n']}|p25={st['p25']:.0f}|med={st['mediana']:.0f}|p75={st['p75']:.0f}|disp={st['p75'] / st['p25']:.2f}" if st.get("p25") else f"n={st['n']}"


async def _prova_ordini(listing_info, brand, prezzo, stima_base, cerca, linea):
    """Ricerca in ombra con ordini alternativi e riga di confronto nel log. Non cambia nessun esito. Mai eccezioni."""
    for ordine in MODA_COMPS_PROVA:
        try:
            _u, _l, st, _v = await cerca(linea, ordine)
            log.info("COMPS ORDINE | item=%s | brand=%s | cat=%s | prezzo=%s | base[%s]=%s | prova[%s]=%s | fv_stima=%s",
                     listing_info.get("item_id") or "-", brand, (listing_info.get("fair_value") or {}).get("categoria"), prezzo,
                     MODA_COMPS_ORDINE, _riga_stima(stima_base), ordine, _riga_stima(st), (listing_info.get("fair_value") or {}).get("fv"))
        except Exception:
            log.info("COMPS ORDINE | prova %s non riuscita", ordine)


async def verifica(listing_info, foto, tutte_le_foto=None, solo_comparabili=False):
    """Dict {esito, motivo, n, rivendita, margine, roi, link, autenticita}. Mai eccezioni: in caso di errore 'non_verificato'."""
    fv = listing_info.get("fair_value") or {}
    brand = fv.get("brand")
    ris = {"esito": "non_verificato", "motivo": "errore", "n": 0, "rivendita": None, "margine": None, "roi": None, "esempi": [], "autenticita": None, "foto_comps": None, "gemini": None, "link_comps": [], "da_foto": False}
    try:
        titolo = listing_info.get("title") or ""
        prezzo = float(listing_info.get("price") or 0)
        catalogo = listing_info.get("catalog_id")
        # le verifiche in ombra (solo_comparabili) hanno il loro tetto orario e non consumano quello giornaliero (12/11, utente)
        if not solo_comparabili and not _entro_il_tetto():
            ris["motivo"] = "tetto_giornaliero"
            return ris
        # i comparabili cercano brand + categoria + prime parole del titolo; se sono pochi, solo brand + categoria.
        # La linea (es. Weekend per Max Mara) si legge da titolo e descrizione; se le foto dicono altro si rifa' la ricerca (vedi sotto).
        linea = linea_dal_testo(f"{titolo} {brand or ''}", brand, listing_info.get("description"))

        async def cerca(linea, ordine=None):
            testo = " ".join(query_comp(titolo, brand).split()[len((brand or "").split()):][:3])
            if linea:
                # la linea (es. "weekend") entra nella ricerca anche se non e' nelle prime parole del titolo
                parola = linea.replace((brand or "").strip().lower(), "").strip() or linea
                if parola not in testo.lower():
                    testo = f"{parola} {testo}".strip()
            usate, mappe = [], []
            for t in ([testo, None] if testo else [None]):
                # 11/11 (utente): UNA richiesta con le condizioni concatenate (nuovo senza cartellino, ottime, buone + quella dell'annuncio);
                # la condizione di ogni comparabile si legge dalla risposta e il prezzo si corregge di poco nella stima (vedi sotto)
                url = url_comparabili(brand, t, catalogo, ordine, listing_info.get("condition"))
                if not url:
                    break
                risposta, ok, _mappa = await _cerca_vinted_testo_diretto(url)
                mappe.append(_mappa)
                if not ok:
                    continue
                comps = [c for c in solo_usato(parse_comp(risposta)) if not (c[0] == titolo and abs(c[1] - prezzo) < 0.01)]
                if not comps:
                    continue
                comps = filtra_per_linea(comps, brand, linea)
                if t:
                    comps = comparabili_simili(comps, t, brand)
                usate = comps
                if len(comps) >= MIN_COMPARABILI:
                    break
            # prezzi portati alla condizione dell'annuncio (comparabile peggiore: sale; migliore: scende), solo per la stima; condizione ignota = invariato
            st = stima_mercato([aggiusta_prezzo_comp(p, condizione_comp(_t, p), listing_info.get("condition")) for _t, p in usate], min_n=MIN_COMPARABILI)
            return usate, comparabili_con_link(usate, mappe), st, (valuta(prezzo, st, spedizione_eur=SPEDIZIONE_STIMATA_EUR, margine_min=MODA_JEV_MARGINE_MIN) if st else None)

        if linea:
            ris["linea"] = linea
        comps_pool, link_comps, stima, v = await cerca(linea)
        prezzi = [p for _t, p in comps_pool]
        if solo_comparabili:
            # Jev 'in ombra' (annunci che il semaforo scarta): niente foto ne' Gemini, serve solo la rivendita dei comparabili per imparare
            ris["ombra"] = True
            if v:
                ris.update(n=v.get("n") or len(prezzi), rivendita=v.get("rivendita"), margine=v.get("margine"), roi=v.get("roi"), motivo="ombra",
                           ok_comps=bool(v.get("ok")))   # ok_comps: i comparabili da soli darebbero margine e ROI sufficienti
                if stima and stima.get("p25"):
                    ris["dispersione"] = stima["p75"] / stima["p25"]
            log.info("MODA JEV OMBRA | item=%s | brand=%s | prezzo=%s | n=%s | rivendita=%s | dispersione=%s | fv_stima=%s | linea=%s | categoria=%s | campioni=%s | conf=%s",
                     listing_info.get("item_id") or "-", brand, prezzo, ris["n"], ris["rivendita"], ris.get("dispersione"), fv.get("fv"), ris.get("linea"),
                     fv.get("categoria"), (FAIR_VALUE_APPRESO.get(f"{brand}|{fv.get('categoria')}") or {}).get("n", 0), fv.get("conf"))
            if MODA_COMPS_PROVA:
                await _prova_ordini(listing_info, brand, prezzo, stima, cerca, linea)
            return ris
        foto_jpeg = None
        if foto:
            # Vinted serve anche webp: Jev accetta solo png/jpeg, quindi si converte in jpeg (prima la foto non partiva: foto=-)
            foto_jpeg = await asyncio.to_thread(optimize_image_bytes, foto, 768)
        if JEV_FOTO_COMPS and foto_jpeg and link_comps:
            # foto dell'annuncio contro le miniature dei comparabili piu' vicini alla mediana: se Jev li trova MOLTO simili il loro prezzo
            # diventa la rivendita (anche con pochi comparabili testuali); se no si torna alla stima testuale, senza foto
            coppie = await _miniature_dei_comparabili(link_comps)
            if coppie:
                ris["foto_comps"] = await asyncio.to_thread(confronta_foto_comparabili, titolo, foto_jpeg, [b for _c, b in coppie], DOMANDA_FOTO_COMP_MODA)
                ris["link_comps_foto"] = sigle_foto_comps(coppie, ris["foto_comps"])
                prezzi_v, vicini = prezzi_pesati_da_foto(coppie, ris["foto_comps"])
                if vicini:
                    stima_v = stima_mercato(prezzi_v, min_n=1)
                    if stima_v:
                        v = {**valuta(prezzo, stima_v, spedizione_eur=SPEDIZIONE_STIMATA_EUR, margine_min=MODA_JEV_MARGINE_MIN), "n": len(vicini)}
                        link_comps = vicini
                        ris["da_foto"] = True
                        log.info("MODA JEV FOTO | brand=%s | stesso_o_simili=%s/%s | rivendita=%s | titolo=%s", brand, len(vicini), len(coppie), v.get("rivendita"), titolo[:60])
        if v is not None and not v.get("ok"):
            # 5/11 (utente): se i comparabili scartano gia' l'annuncio il legit check (Jev e Gemini, token e quota) non serve
            ris["legit_saltato"] = True
        elif foto_jpeg:
            # 5/11 (utente): Jev guarda TUTTE le foto (fino a JEV_AUTENTICITA_FOTO), non solo la prima: etichette, wash tag, made in, hardware
            altre = [f for f in (tutte_le_foto or [])[1:MAX_FOTO_AUTENTICITA] if f]
            tutte_jpeg = [foto_jpeg] + [await asyncio.to_thread(optimize_image_bytes, f, 768) for f in altre]
            ris["autenticita"] = await asyncio.to_thread(giudica_autenticita, titolo, brand, tutte_jpeg)
        if not ris.get("legit_saltato") and serve_controllo(ris["autenticita"], prezzo, (v or {}).get("rivendita")):
            # Jev non e' sicuro dell'originalita' (o il prezzo e' troppo basso): Gemini gratuito guarda tutte le foto
            ris["gemini"] = await controlla_gemini(titolo, brand, prezzo, listing_info.get("description"), tutte_le_foto or ([foto] if foto else []),
                                                   item_id=listing_info.get("item_id"), comps=comps_pool)
        registra_legit(listing_info, brand, ris["gemini"], linea)
        if ris["gemini"]:
            nota, linea_foto = linea_da_etichetta(ris["gemini"].get("linea_etichetta"), brand)
            if nota and linea_foto != linea:
                # l'etichetta in foto dice un'altra linea (es. titolo "Max Mara", etichetta "Weekend"): stima rifatta sulla linea vera
                log.info("MODA JEV LINEA | item=%s | brand=%s | titolo/descrizione=%s | etichetta=%s", listing_info.get("item_id") or "-", brand, linea or "principale", linea_foto or "principale")
                linea = linea_foto
                ris["linea"], ris["linea_da_foto"] = linea, True
                comps_pool, link_comps, stima, v = await cerca(linea)
                prezzi = [p for _t, p in comps_pool]
                ris["da_foto"], ris["foto_comps"], ris["link_comps_foto"] = False, None, None
        # 8/11 (utente): stessa ricerca ordinata per rilevanza, entra nella rivendita mista con peso 2,5 x semaforo (newest_first 1,8 x); 10/11 (utente): rilevanza 1 x, newest_first 0,8 x, Gemini 1 x
        riv_ril = None
        try:
            _u, _l, st_ril, v_ril = await cerca(linea, "relevance")
            riv_ril = (v_ril or {}).get("rivendita") if st_ril else None
            if riv_ril:
                ris["rivendita_ril"], ris["n_ril"] = riv_ril, (v_ril or {}).get("n") or st_ril.get("n")
                ris["link_comps_ril"], ris["esempi_ril"] = _l, list(_u[:3])
                ris["prezzi_comps_ril"] = (st_ril["minimo"], st_ril["massimo"])
                ris["dispersione_ril"] = st_ril["p75"] / st_ril["p25"] if st_ril.get("p25") else None
            log.info("COMPS ORDINE | item=%s | brand=%s | cat=%s | prezzo=%s | base[%s]=%s | rilevanza=%s | fv_stima=%s", listing_info.get("item_id") or "-", brand,
                     fv.get("categoria"), prezzo, MODA_COMPS_ORDINE, _riga_stima(stima), _riga_stima(st_ril), fv.get("fv"))
        except Exception:
            log.info("Moda Jev: ricerca per rilevanza non riuscita")
        v, sconto = correggi_per_difetti(v, prezzo, ris["gemini"])
        if sconto:
            ris["sconto_difetti"], ris["rivendita_prima_difetti"] = sconto, v.get("rivendita_prima_difetti")
            if riv_ril:
                riv_ril = riv_ril * (1 - sconto / 100)
            log.info("MODA JEV DIFETTI | item=%s | brand=%s | gravita=%s | sconto=%.0f%% | rivendita %.0f -> %.0f | margine=%s | difetti=%s",
                     listing_info.get("item_id") or "-", brand, ris["gemini"].get("gravita_difetti"), sconto, v["rivendita_prima_difetti"], v["rivendita"],
                     v.get("margine"), ris["gemini"].get("difetti"))
        # rivendita mista (7/11): semaforo, comparabili (gia' scontati dei difetti) e Gemini; margine, ROI ed esito si calcolano su questa
        riv_comps = v.get("rivendita") if v else None
        mix, parti = rivendita_mista(fv, riv_comps, (v or {}).get("n") or len(prezzi), ris["gemini"], riv_ril)
        ris["rivendita_comps"], ris["parti_rivendita"] = riv_comps, parti
        if v and mix and len(parti) > 1:
            stima_mix = {k: v.get(k) for k in ("affidabilita", "n", "richiesto_mediano", "vendita_rapida", "calibrazione")}
            stima_mix["rivendita"] = mix
            v = valuta(prezzo, stima_mix, spedizione_eur=SPEDIZIONE_STIMATA_EUR, margine_min=MODA_JEV_MARGINE_MIN)
        ris["rivendita_testata"] = (v or {}).get("rivendita") if v else mix   # senza comparabili: solo per l'intestazione, l'esito resta non verificato
        ris["esito"], ris["motivo"] = decidi(v, ris["autenticita"], ris["gemini"], ris["foto_comps"],
                                         None if ris["da_foto"] or not stima or not stima.get("p25") else stima["p75"] / stima["p25"])
        if v:
            ris.update(n=v.get("n") or len(prezzi), rivendita=v.get("rivendita"), margine=v.get("margine"), roi=v.get("roi"),
                       esempi=list(comps_pool[:3]), link_comps=link_comps)
            # la fascia mostrata e' quella usata davvero (fuori scala gia' tolti da stima_mercato), non il minimo e massimo grezzi
            pz = sorted(c[1] for c in link_comps) if ris.get("da_foto") else ([stima["minimo"], stima["massimo"]] if stima else sorted(prezzi))
            if pz:
                ris["prezzi_comps"] = (pz[0], pz[-1])
            if stima and stima.get("p25") and not ris.get("da_foto"):
                ris["dispersione"] = stima["p75"] / stima["p25"]
        _item = listing_info.get("item_id") or (re.search(r"/items/(\d+)", str(listing_info.get("url") or "")) or [None, "-"])[1]
        listing_info["jev_dati"] = _dati_jev_piatti(ris)   # 9/11: tutto Jev nella riga TRACCIATO (un annuncio = una riga, join per item)
        log.info("MODA JEV | item=%s | brand=%s | prezzo=%s | esito=%s | motivo=%s | n=%s | rivendita=%s | margine=%s | fv_stima=%s | foto=%s | appreso=%s",
                 _item, brand, prezzo, ris["esito"], ris["motivo"], ris["n"], ris["rivendita"], ris["margine"],
                 fv.get("fv"), ris["autenticita"] or "-",
                 (FAIR_VALUE_APPRESO.get(f"{ris.get('linea') or brand}|{fv.get('categoria')}") or {}).get("fv", "-"))
    except Exception:
        log.warning("Moda Jev: verifica non riuscita:\n%s", traceback.format_exc())
    return ris
