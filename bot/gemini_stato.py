"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import os
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


from bot.config import GEMINI_API_KEY
from bot.logger import log
from bot import db
# ---- fine import ----
# RILEVAMENTO BLACKOUT GEMINI (richiesto dall'utente il 2026-09-22, log reale:
# ~12 minuti di 503 "high demand" hanno fatto costare a Occhio/Cervello 1-6
# minuti a chiamata invece dei pochi secondi normali). La rotazione di key sui
# 5xx introdotta il 2026-09-21 aiuta quando il 503 e' specifico di UNA key,
# ma se il blackout e' del MODELLO per chiunque, ogni chiamata continua a
# bruciare fino a max_retries (4) tentativi x fino a 4 key prima di arrendersi
# -- decine di secondi reali per tentativo (e' la latenza di Gemini prima di
# restituire il 503, non un timeout nostro), moltiplicati per ogni round del
# Cervello. Stessa idea del raffreddamento gia' usato per Serper qui sopra,
# ma parametri diversi: un blackout Gemini osservato e' uno spike di minuti,
# non ore, quindi il raffreddamento e' molto piu' corto e si riprova a piena
# potenza molto prima.
_gemini_5xx_consecutivi = [0]
_gemini_timestamp_ultimo_5xx = [0.0]
SOGLIA_5XX_GEMINI_PER_BLACKOUT = 3      # chiamate Gemini (Occhio o Cervello) di fila
                                         # finite in errore dopo aver esaurito tutti i
                                         # tentativi/key, prima di considerarlo un blackout
RAFFREDDAMENTO_GEMINI_SECONDI = 300     # 5 minuti: passato questo tempo dall'ultimo
                                         # fallimento si torna a provare a piena potenza
MAX_RETRIES_GEMINI_IN_BLACKOUT = 2      # tentativi per chiamata durante un blackout rilevato,


def _gemini_in_blackout():
    """True se le ultime chiamate Gemini sono finite in errore abbastanza di
    fila e abbastanza di recente da trattarlo come un blackout in corso
    (stessa logica di in_raffreddamento gia' usata per Serper piu' sotto)."""
    if _gemini_5xx_consecutivi[0] < SOGLIA_5XX_GEMINI_PER_BLACKOUT:
        return False
    return (time.time() - _gemini_timestamp_ultimo_5xx[0]) < RAFFREDDAMENTO_GEMINI_SECONDI


def _gemini_registra_esito(successo):
    """Aggiorna il contatore di blackout dopo ogni chiamata Gemini completata
    (con successo o con tutti i tentativi/key esauriti). Chiamata da
    chiama_gemini e da _chiama_gemini_raw dentro chiama_gemini_cervello_forzato
    -- stesso stato condiviso, perche' un blackout del modello colpisce
    Occhio e Cervello allo stesso modo."""
    if successo:
        if _gemini_5xx_consecutivi[0] >= SOGLIA_5XX_GEMINI_PER_BLACKOUT:
            log.info("Gemini: uscito dal blackout 5xx (una chiamata e' andata a buon fine).")
        _gemini_5xx_consecutivi[0] = 0
    else:
        _gemini_5xx_consecutivi[0] += 1
        _gemini_timestamp_ultimo_5xx[0] = time.time()
        if _gemini_5xx_consecutivi[0] == SOGLIA_5XX_GEMINI_PER_BLACKOUT:
            log.warning(
                "Gemini: rilevato blackout (%d chiamate di fila con tutti i tentativi "
                "esauriti) -- retry ridotti a %d per le prossime chiamate, per %ds.",
                _gemini_5xx_consecutivi[0], MAX_RETRIES_GEMINI_IN_BLACKOUT, RAFFREDDAMENTO_GEMINI_SECONDI,
            )


# FALLBACK DI MODELLO SU SOVRACCARICO (aggiunto il 2026-09-24, log reale:
# dalle ~16:00 ora italiana quasi il 100% delle chiamate a
# gemini-3.5-flash-lite torna 503 "This model is currently experiencing high
# demand", su TUTTE le key -- 0 successi su ~150 chiamate tra le 16 e le 18).
# E' un sovraccarico del MODELLO lato Google, non delle nostre key: ruotare
# key non serve (ogni tentativo brucia comunque 10-45s di latenza prima del
# 503) e il rilevamento blackout qui sopra riduce solo i tentativi, non
# recupera l'annuncio. Un modello diverso ha capacita' (e quota free
# giornaliera) separata, quindi e' l'unica leva che fa davvero passare le
# chiamate durante uno spike. Quando il modello principale risponde
# "high demand", si passa SUBITO al modello di riserva per
# RAFFREDDAMENTO_MODELLO_SOVRACCARICO_SECONDI, poi si riprova il principale.
#
# GEMINI_MODEL_FALLBACK: env var, lista di modelli di riserva separati da
# virgola, provati IN ORDINE dopo il principale. Default
# "gemini-3.1-flash-lite,gemini-2.5-flash-lite". Stringa vuota = fallback
# disattivato, comportamento di prima.
#
# AGGIORNATO il 2026-09-24 sera (log dopo il primo deploy del fallback): il
# 503 "high demand" colpiva ANCHE gemini-3.1-flash-lite, quindi una sola
# riserva non basta -- ora e' una catena. Ogni modello che risponde
# "high demand" viene escluso per RAFFREDDAMENTO_MODELLO_SOVRACCARICO_SECONDI
# e si passa subito al successivo; un modello che risponde 404 (nome non piu'
# servito da Google) viene escluso per RAFFREDDAMENTO_MODELLO_INESISTENTE_SECONDI
# invece di sprecarci un tentativo a ogni chiamata. Solo quando TUTTI i
# modelli della catena sono esclusi si torna alla rotazione key + backoff di
# prima sul principale.
#
# AGGIORNATO il 2026-09-26 (log 24-25/09, ~24 item persi): gemini-2.5-flash-lite
# tolto dal default. Non e' un 503 transitorio ne' un problema di quota: e'
# un 404 "not found" costante (confermato anche dalla pagina modelli di
# Google -- l'accesso ai modelli 2.5 e' limitato ai soli progetti che li
# hanno gia' usati attivamente in passato, e il nostro non l'ha mai fatto,
# quindi per noi resta bloccato in modo permanente). Aggravato da un bug
# separato (vedi _gemini_gestisci_modello_non_disponibile piu' sotto): la
# marcatura di esclusione non scattava mai quando il 404 capitava
# sull'ultimo tentativo disponibile -- il caso comune durante un blackout,
# quando i tentativi scendono a MAX_RETRIES_GEMINI_IN_BLACKOUT. Risultato:
# 67 errori 404 su questo modello nei log, 0 marcature di esclusione
# registrate, e diversi item persi invece che semplicemente instradati sul
# prossimo modello della catena.
GEMINI_MODELLI_RISERVA = [
    m.strip() for m in os.environ.get(
        "GEMINI_MODEL_FALLBACK", "gemini-3.1-flash-lite").split(",")
    if m.strip()
]
GEMINI_MODEL_FALLBACK = GEMINI_MODELLI_RISERVA[0] if GEMINI_MODELLI_RISERVA else ""
# CASCATA DI QUOTE (richiesta dall'utente il 2026-10-03): ogni modello Gemini ha la sua quota giornaliera per key.
# Con GEMINI_CASCATA="gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite" (dal migliore al piu' leggero)
# Occhio e Cervello partono dal primo modello e, quando la quota giornaliera finisce su TUTTE le key, scalano al
# successivo senza attese. Vuota = comportamento di prima (modello principale + GEMINI_MODEL_FALLBACK).
GEMINI_CASCATA = [m.strip() for m in os.environ.get("GEMINI_CASCATA", "").split(",") if m.strip()]
# Cascata per FASE (richiesta dall'utente il 2026-10-03): l'Occhio gira su ogni annuncio e conta la velocita',
# il Cervello decide il prezzo e merita i modelli migliori (quota gratuita di pochi richieste al giorno).
# GEMINI_CASCATA_OCCHIO / GEMINI_CASCATA_CERVELLO; se una manca vale la GEMINI_CASCATA generica.
GEMINI_CASCATA_OCCHIO = [m.strip() for m in os.environ.get("GEMINI_CASCATA_OCCHIO", "").split(",") if m.strip()]
GEMINI_CASCATA_CERVELLO = [m.strip() for m in os.environ.get("GEMINI_CASCATA_CERVELLO", "").split(",") if m.strip()]
# Fascia "alta" (prezzo richiesto >= GEMINI_SOGLIA_PREZZO_ALTO): GEMINI_CASCATA_OCCHIO_ALTO / _CERVELLO_ALTO; se
# mancano valgono quelle base della fase.
GEMINI_CASCATA_OCCHIO_ALTO = [m.strip() for m in os.environ.get("GEMINI_CASCATA_OCCHIO_ALTO", "").split(",") if m.strip()]
GEMINI_CASCATA_CERVELLO_ALTO = [m.strip() for m in os.environ.get("GEMINI_CASCATA_CERVELLO_ALTO", "").split(",") if m.strip()]


def cascata_per(ruolo=None):
    """Catena di modelli (dal migliore al piu' leggero) per la fase `ruolo` ("occhio" | "cervello"), [] = nessuna."""
    if ruolo in ("occhio_alto", "cervello_alto"):
        alta = GEMINI_CASCATA_OCCHIO_ALTO if ruolo == "occhio_alto" else GEMINI_CASCATA_CERVELLO_ALTO
        if alta:
            return alta
        ruolo = ruolo.replace("_alto", "")
    specifica = {"occhio": GEMINI_CASCATA_OCCHIO, "cervello": GEMINI_CASCATA_CERVELLO}.get(ruolo) or []
    return specifica or GEMINI_CASCATA


def tutti_i_modelli_cascata():
    return {*GEMINI_CASCATA, *GEMINI_CASCATA_OCCHIO, *GEMINI_CASCATA_CERVELLO,
            *GEMINI_CASCATA_OCCHIO_ALTO, *GEMINI_CASCATA_CERVELLO_ALTO}
RAFFREDDAMENTO_MODELLO_SOVRACCARICO_SECONDI = 15 * 60
RAFFREDDAMENTO_MODELLO_INESISTENTE_SECONDI = 24 * 3600
_gemini_modello_escluso_fino = {}


def _gemini_e_sovraccarico_modello(status_code, corpo_testo):
    """True se la risposta e' il 503 di sovraccarico del modello ("high
    demand" / UNAVAILABLE), non un errore generico o di una singola key."""
    if status_code != 503 or not corpo_testo:
        return False
    t = corpo_testo.lower()
    return "high demand" in t or "overloaded" in t or "unavailable" in t


def _gemini_e_modello_inesistente(status_code, corpo_testo):
    """True se il modello richiesto non esiste (piu') per questa API."""
    if status_code != 404:
        return False
    t = (corpo_testo or "").lower()
    return "not found" in t or "not supported" in t or "is not found" in t or not t


def _gemini_modello_da_url(api_url):
    m = re.search(r"/models/([^:/]+):", api_url)
    return m.group(1) if m else None


def _gemini_modello_escluso(modello):
    scadenza = _gemini_modello_escluso_fino.get(modello)
    if scadenza is None:
        return False
    if time.time() >= scadenza:
        del _gemini_modello_escluso_fino[modello]
        return False
    return True


def _gemini_segna_modello_non_disponibile(modello, secondi, motivo):
    if not _gemini_modello_escluso(modello):
        log.warning("Gemini: modello %s %s -- escluso per %d minuti, passo al successivo della catena.",
                    modello, motivo, secondi // 60)
    _gemini_modello_escluso_fino[modello] = time.time() + secondi
    db.salva_modello_escluso(modello, _gemini_modello_escluso_fino[modello])


def _gemini_url_effettivo(api_url, ruolo=None):
    """URL del primo modello disponibile della catena principale ->
    GEMINI_MODELLI_RISERVA. Se sono tutti esclusi si torna al principale
    (e da li' valgono rotazione key e backoff come prima). Sostituisce solo il
    nome del modello nel path, quindi vale per Occhio e Cervello."""
    cascata = cascata_per(ruolo)
    if cascata:
        for modello in cascata:
            if not _gemini_modello_escluso(modello) and not _gemini_modello_senza_quota(modello):
                return re.sub(r"/models/[^:/]+:", f"/models/{modello}:", api_url)
        return re.sub(r"/models/[^:/]+:", f"/models/{cascata[-1]}:", api_url)
    principale = _gemini_modello_da_url(api_url)
    if not principale or not GEMINI_MODELLI_RISERVA:
        return api_url
    catena = [principale] + [m for m in GEMINI_MODELLI_RISERVA if m != principale]
    for modello in catena:
        if not _gemini_modello_escluso(modello):
            if modello == principale:
                return api_url
            return re.sub(r"/models/[^:/]+:", f"/models/{modello}:", api_url)
    return api_url


def _gemini_gestisci_modello_non_disponibile(api_url, url_usato, status_code, corpo_testo, ruolo=None):
    """Chiamata dopo una risposta non-2xx. Se l'errore dice che il MODELLO
    (non la key) non e' disponibile, lo esclude e ritorna True quando esiste
    un altro modello della catena su cui ritentare subito."""
    if not GEMINI_MODELLI_RISERVA:
        return False
    modello = _gemini_modello_da_url(url_usato)
    if _gemini_e_sovraccarico_modello(status_code, corpo_testo):
        _gemini_segna_modello_non_disponibile(
            modello, RAFFREDDAMENTO_MODELLO_SOVRACCARICO_SECONDI, "in sovraccarico (503 high demand)")
    elif _gemini_e_modello_inesistente(status_code, corpo_testo):
        _gemini_segna_modello_non_disponibile(
            modello, RAFFREDDAMENTO_MODELLO_INESISTENTE_SECONDI, "non disponibile (404)")
    else:
        return False
    return _gemini_url_effettivo(api_url, ruolo) != url_usato


# ---------------------------------------------------------------------------
# GEMINI API KEYS (opzionale) -- rotazione su quota esaurita, stesso
# principio della rotazione proxy qui sotto. Aggiunta il 2026-09-20 su
# richiesta esplicita dell'utente dopo un caso reale in produzione: il piano
# gratuito ("generate_content_free_tier_requests, limit: 500") si e' esaurito
# nel giro di poche ore di traffico normale, con Occhio e Cervello entrambi
# falliti su piu' annunci nonostante il backoff (i 429 di quota esaurita non
# sono un rate-limit al minuto che si risolve da solo in pochi secondi: nei
# log Google chiedeva "retry in 30-60s", molto piu' del backoff massimo di
# ~14s su 4 tentativi, e nel frattempo il bot continuava a generarne altri).
#
# Formato variabile d'ambiente GEMINI_API_KEYS: chiavi separate da virgola
# (una per account Google/progetto AI Studio, cosi' ognuna ha la sua quota
# free indipendente), es. "AIzaSy...primo,AIzaSy...secondo". Se non
# impostata, si usa solo GEMINI_API_KEY (comportamento originale, nessun
# rischio di rottura). La rotazione e' "sticky": si resta sulla key corrente
# finche' funziona (niente round-robin ad ogni chiamata, sprecherebbe quota
# su piu' key per nulla), e si avanza alla prossima SOLO quando una chiamata
# incassa un 429 di quota esaurita -- vedi chiama_gemini e
# chiama_gemini_cervello_forzato.
_GEMINI_API_KEYS_RAW = os.environ.get("GEMINI_API_KEYS", "").strip()
GEMINI_API_KEYS = (
    [k.strip() for k in _GEMINI_API_KEYS_RAW.split(",") if k.strip()]
    if _GEMINI_API_KEYS_RAW else [GEMINI_API_KEY]
)
_gemini_key_index = [0]

if len(GEMINI_API_KEYS) > 1:
    log.info("Gemini: %d API key attive, rotazione automatica su quota esaurita (429).", len(GEMINI_API_KEYS))
else:
    log.info("Gemini: 1 sola API key (GEMINI_API_KEYS non impostata) -- nessuna rotazione disponibile.")


def _gemini_key_attuale(modello=None):
    """Key Gemini da usare nella prossima chiamata. Se la key su cui la
    rotazione sticky si trova al momento e' in cooldown per quota
    giornaliera esaurita (vedi _gemini_key_in_quota_esaurita) e ce n'e'
    un'altra disponibile, avanza subito senza aspettare un fallimento --
    evita di sprecare il primo tentativo di ogni chiamata su una key gia'
    nota per fallire sempre (caso reale del 2026-09-22, vedi commento
    esteso su _gemini_key_quota_esaurita_fino)."""
    if len(GEMINI_API_KEYS) > 1:
        indice_iniziale = _gemini_key_index[0]
        for _ in range(len(GEMINI_API_KEYS)):
            if not _gemini_key_in_quota_esaurita(GEMINI_API_KEYS[_gemini_key_index[0] % len(GEMINI_API_KEYS)], modello):
                break
            _gemini_key_index[0] = (_gemini_key_index[0] + 1) % len(GEMINI_API_KEYS)
            if _gemini_key_index[0] == indice_iniziale:
                # Giro completo, tutte in cooldown -- si usa comunque questa,
                # meglio tentare che restituire un errore senza nemmeno provare.
                break
    return GEMINI_API_KEYS[_gemini_key_index[0] % len(GEMINI_API_KEYS)]


def _gemini_prossima_key(modello=None):
    """Passa alla key successiva -- chiamata dopo un 429 (quota esaurita) o,
    da FIX 2026-09-21, anche dopo un 500/502/503/504 (vedi commento esteso
    in chiama_gemini). Ritorna True se si e' davvero cambiata key (ce
    n'erano altre disponibili oltre a quella corrente), False se c'e' una
    sola key o si e' gia' fatto il giro completo -- in quel caso ha senso
    solo il backoff, non un altro switch immediato.

    Salta le key gia' segnalate come a quota giornaliera esaurita (vedi
    _gemini_segna_key_quota_esaurita) quando ce ne sono altre disponibili,
    cosi' la rotazione "sticky" non ci si pianta sopra di nuovo al giro
    successivo -- vedi caso reale del 2026-09-22 sotto."""
    if len(GEMINI_API_KEYS) <= 1:
        return False
    indice_prima = _gemini_key_index[0]
    for _ in range(len(GEMINI_API_KEYS)):
        _gemini_key_index[0] = (_gemini_key_index[0] + 1) % len(GEMINI_API_KEYS)
        if _gemini_key_index[0] == indice_prima:
            # Giro completo: tutte le altre key sono in cooldown di quota,
            # non c'e' scelta migliore -- si resta su questa.
            break
        if not _gemini_key_in_quota_esaurita(GEMINI_API_KEYS[_gemini_key_index[0]], modello):
            break
    log.warning(
        "Gemini: key #%d in errore (429/5xx), passo alla key #%d.",
        indice_prima + 1, _gemini_key_index[0] + 1,
    )
    return _gemini_key_index[0] != indice_prima


# Cooldown per key con quota giornaliera esaurita (429 RESOURCE_EXHAUSTED sul
# piano free, es. "generate_content_free_tier_requests, limit: 500") --
# aggiunto il 2026-09-22, caso reale: durante un blackout 503 di ~45 minuti
# (vedi _gemini_in_blackout piu' sopra) la key #3 tra le 4 configurate
# risultava SEMPRE in errore 429 di quota esaurita, letteralmente su ogni
# singola chiamata dell'intera finestra osservata nei log -- non un
# rate-limit che si risolve da solo (il messaggio di Google suggeriva
# "retry in" pochi secondi, ma e' una quota GIORNALIERA: il vero reset e'
# su scala di ore, non secondi). La rotazione "sticky" esistente passava
# comunque, prima o poi, di nuovo su quella key ad ogni giro, sprecando un
# tentativo garantito-fallimentare -- particolarmente costoso durante un
# blackout 503 concorrente, dove i tentativi disponibili sono gia' ridotti
# a MAX_RETRIES_GEMINI_IN_BLACKOUT (2): un tentativo su una key morta
# dimezza le vere chance di successo su una key diversa. Con questo
# cooldown, una volta rilevata una key a quota esaurita, la si esclude
# dalla rotazione per alcune ore invece di ritentarla ad ogni giro.
_gemini_key_quota_esaurita_fino = {}
RAFFREDDAMENTO_QUOTA_ESAURITA_GEMINI_SECONDI = 6 * 3600  # 6 ore, stima prudente verso il basso rispetto al reset giornaliero reale


def _gemini_e_errore_quota_giornaliera(status_code, corpo_testo):
    """True se la risposta 429 e' una vera quota GIORNALIERA esaurita
    (RESOURCE_EXHAUSTED sul piano free), non un generico rate-limit al
    minuto -- distinzione fatta sul corpo della risposta Google, non solo
    sullo status code, perche' un 429 puo' in teoria capitare anche per
    altri motivi transitori."""
    if status_code != 429 or not corpo_testo:
        return False
    testo_lower = corpo_testo.lower()
    return "resource_exhausted" in testo_lower or "free_tier" in testo_lower or "exceeded your current quota" in testo_lower


def _gemini_secondi_retry(corpo_testo):
    """Secondi di attesa suggeriti da Google in un 429 (campo retryDelay "37046s" o testo "retry in 46.8s" /
    "retry in 10h17m26s"). None se assenti. Distingue il limite al minuto (decine di secondi) da quello
    giornaliero (ore): il 2026-10-03 gemini-3.5-flash (5 richieste/minuto) veniva escluso per 6 ore."""
    if not corpo_testo:
        return None
    m = re.search(r'"retryDelay"\s*:\s*"([\d.]+)s"', corpo_testo)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", corpo_testo)
    if m and any(m.groups()):
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)
    return None


SOGLIA_QUOTA_GIORNALIERA_SECONDI = 3600


def prossimo_reset_quota_gemini(adesso=None):
    """Timestamp del prossimo reset della quota giornaliera free di Gemini: mezzanotte di Pacific (07:00 UTC con l'ora
    legale, 08:00 UTC con quella solare)."""
    adesso = adesso if adesso is not None else time.time()
    pacifico = ZoneInfo("America/Los_Angeles")
    ora = datetime.fromtimestamp(adesso, pacifico)
    mezzanotte = (ora + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return mezzanotte.timestamp()


def cooldown_quota_affidabile(fino, adesso=None):
    """Un cooldown di quota si ripristina da DB solo se e' breve (limite al minuto) o finisce al reset di Pacific.
    Quelli lunghi di altro tipo (da "retry in 23h" di Google) li ha scritti la regola vecchia: il reset vero era gia' passato."""
    adesso = adesso if adesso is not None else time.time()
    if fino - adesso <= SOGLIA_QUOTA_GIORNALIERA_SECONDI:
        return True
    return abs(fino - (prossimo_reset_quota_gemini(adesso) + 60)) <= 5


def _gemini_segna_key_quota_esaurita(key, modello=None, secondi=None):
    """Marca `key` come a quota giornaliera esaurita per
    RAFFREDDAMENTO_QUOTA_ESAURITA_GEMINI_SECONDI: la rotazione la salta
    finche' il cooldown non scade (vedi _gemini_prossima_key /
    _gemini_key_in_quota_esaurita)."""
    gia_segnalata = _gemini_key_in_quota_esaurita(key, modello)
    durata = RAFFREDDAMENTO_QUOTA_ESAURITA_GEMINI_SECONDI
    if secondi is not None:
        durata = min(max(secondi + 2, 5), 24 * 3600)   # attesa indicata da Google (minuto o giorno), non 6h fisse
    if durata >= SOGLIA_QUOTA_GIORNALIERA_SECONDI:
        # quota del giorno: il "retry in 23h" di Google e' una stima sballata, il reset vero e' a mezzanotte Pacific.
        # 4/10: 3.5-flash restava escluso fino alle 23:59 UTC anche se la quota era tornata alle 07:00 UTC (0/500 usate).
        durata = min(durata, max(prossimo_reset_quota_gemini() - time.time(), 60) + 60)
    _gemini_key_quota_esaurita_fino[(key, modello or "")] = time.time() + durata
    db.salva_quota_gemini(key, modello, _gemini_key_quota_esaurita_fino[(key, modello or "")])
    if not gia_segnalata:
        log.warning(
            "Gemini: key in errore 429 di quota esaurita per il modello %s -- esclusa dalla rotazione per %s.",
            modello or "(qualsiasi)", f"{durata / 60:.0f} minuti" if durata >= 120 else f"{durata:.0f} secondi",
        )


def _gemini_modello_senza_quota(modello):
    """True se la quota giornaliera di `modello` e' esaurita su TUTTE le key: la cascata passa al successivo."""
    return bool(GEMINI_API_KEYS) and all(_gemini_key_in_quota_esaurita(k, modello) for k in GEMINI_API_KEYS)


def gemini_cascata_esaurita(ruolo=None):
    """True se TUTTI i modelli della cascata di `ruolo` hanno la quota finita su tutte le key: Gemini non puo'
    rispondere e si passa ai modelli di riserva (vedi riserva_llm)."""
    modelli = cascata_per(ruolo)
    # un modello escluso (404, sovraccarico) o senza quota su tutte le key non e' piu' utilizzabile: 4/10 la cascata
    # restava "non esaurita" per un modello escluso e il bot continuava a chiamare Gemini ricevendo 429
    return bool(modelli) and all(_gemini_modello_escluso(m) or _gemini_modello_senza_quota(m) for m in modelli)


def _gemini_key_in_quota_esaurita(key, modello=None):
    """True se `key` e' attualmente in cooldown per quota giornaliera
    esaurita (vedi _gemini_segna_key_quota_esaurita) o e' stata segnata non valida per ogni modello
    (vedi _gemini_segna_key_non_valida: voce con modello "")."""
    for chiave in ((key, modello or ""), (key, "")):
        scadenza = _gemini_key_quota_esaurita_fino.get(chiave)
        if scadenza is None:
            continue
        if time.time() >= scadenza:
            del _gemini_key_quota_esaurita_fino[chiave]
            continue
        return True
    return False


# Key non valida (5/10: una chiave Google cancellata dava 401 "bound service account is deleted or disabled" e il bot
# ritentava sempre quella, perche' ruotava solo su 429/5xx): si esclude per ogni modello e si passa alla successiva.
RAFFREDDAMENTO_KEY_NON_VALIDA_SECONDI = 6 * 3600


def _gemini_e_errore_key_non_valida(status_code, corpo_testo):
    """True per 401/403 che dicono che la KEY (non il modello o la quota) e' rifiutata. Pura."""
    if status_code not in (401, 403):
        return False
    t = (corpo_testo or "").lower()
    return any(m in t for m in ("unauthenticated", "api key", "api_key", "service account", "permission_denied",
                                "permission denied"))


def _gemini_segna_key_non_valida(key):
    """Esclude `key` per ogni modello per RAFFREDDAMENTO_KEY_NON_VALIDA_SECONDI e logga quante key valide restano."""
    gia = _gemini_key_in_quota_esaurita(key, None)
    _gemini_key_quota_esaurita_fino[(key, "")] = time.time() + RAFFREDDAMENTO_KEY_NON_VALIDA_SECONDI
    db.salva_quota_gemini(key, "", _gemini_key_quota_esaurita_fino[(key, "")])
    if gia:
        return
    n = GEMINI_API_KEYS.index(key) + 1 if key in GEMINI_API_KEYS else 0
    valide = sum(1 for k in GEMINI_API_KEYS if not _gemini_key_in_quota_esaurita(k, None))
    log.warning("Gemini: key #%d NON VALIDA (401/403, cancellata o disabilitata) -- esclusa per %d ore. "
                "Key valide rimaste: %d su %d.%s", n, RAFFREDDAMENTO_KEY_NON_VALIDA_SECONDI // 3600, valide,
                len(GEMINI_API_KEYS), "" if valide else " NESSUNA: aggiornare GEMINI_API_KEYS su Railway.")


def ripristina_stato_gemini():
    """All'avvio: ricarica dal DB i cooldown di quota e le esclusioni di modello ancora validi, cosi' un riavvio
    (ogni deploy) non fa rispendere chiamate per riscoprire le quote finite. Ritorna (n_quote, n_modelli)."""
    quote, esclusi = db.carica_stato_gemini(GEMINI_API_KEYS)
    quote = {k: f for k, f in quote.items() if cooldown_quota_affidabile(f)}
    _gemini_key_quota_esaurita_fino.update(quote)
    _gemini_modello_escluso_fino.update(esclusi)
    return len(quote), len(esclusi)
