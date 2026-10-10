"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import asyncio
import time
import os
import re
import difflib
import traceback


from bot.config import (BRAND_ESCLUSI_ALERT_CHIEDI_FOTO, MAX_ANALISI_PARALLELE, SOGLIA_MARGINE_ALERT_CHIEDI_FOTO,
                        SOGLIA_MARGINE_ALERT_CHIEDI_FOTO_BRAND_ESCLUSI, TELEGRAM_ALERT_CHAT_ID, TELEGRAM_OWNER_CHAT_ID)
from bot.verdetto import EMOJI_DECISIONE, ETICHETTA_CONFIDENZA, ETICHETTA_RISCHIO, _a_float, _estrai_item_id_da_url
from bot.testo import _escapa_markdown_legacy
from bot.fair_value import _riga_fair_value_testo, _riga_fair_value_unica
from bot.logger import log
from bot.telegram_api import telegram_edit_caption, telegram_edit_message, telegram_send_media_group, telegram_send_message, telegram_send_photo, telegram_send_photo_con_bottone, telegram_send_with_buttons
# ---- fine import ----
# GALLERIA ANTICIPATA (richiesto dall'utente il 2026-09-28): la galleria
# completa arriva nella chat principale APPENA le foto sono scaricate, prima
# di Occhio e Cervello, invece di restare ferma in memoria per tutta
# l'analisi Gemini. Quando il verdetto e' pronto arriva SOLO il testo, come
# risposta al messaggio della galleria. A questo punto l'annuncio ha gia'
# superato FILTRO PRE-SCRAPE e FILTRO PRE-GEMINI, quindi nessuna galleria
# "inutile" per annunci scartati gratis. La galleria parte sempre SILENZIOSA:
# la decisione non e' ancora nota, e il push resta legato al solo verdetto
# COMPRA come prima. Il canale alert resta invariato (foto + testo insieme a
# fine analisi): li' l'invio dipende proprio dal verdetto.
# GALLERIA_ANTICIPATA=0 per tornare al comportamento precedente.
GALLERIA_ANTICIPATA = os.environ.get("GALLERIA_ANTICIPATA", "1").strip() != "0"

# PAUSA ANALISI GEMINI (richiesto dall'utente il 2026-09-28, durante un
# sovraccarico 503 prolungato di Gemini): ANALISI_GEMINI=0 su Railway ->
# arriva SOLO la galleria (album + scheda), nessuna chiamata a
# Gemini/Serper, nessun verdetto. Restano attivi scrape, foto e i filtri
# gratuiti (pre-scrape, pre-Gemini), quindi le gallerie restano solo per
# annunci pertinenti. Il canale alert in pausa non riceve nulla: dipende dal
# verdetto. Cambiare la variabile su Railway riavvia il servizio, quindi il
# valore letto all'avvio basta.
ANALISI_GEMINI_ATTIVA = os.environ.get("ANALISI_GEMINI", "1").strip() != "0"


STATO_ANALISI_COMPLETATA = "✅ Analisi completata, risposta qui sotto"
STATO_ANALISI_COMPLETATA_UNIFICATA = "✅ Analisi completata"
STATO_ANALISI_INTERROTTA = "⚠️ Analisi interrotta per un errore"


def _stato_analisi_testo(n_foto):
    return (f"⏳ Analisi in corso… · {n_foto} foto" if ANALISI_GEMINI_ATTIVA
            else f"⏸️ Analisi AI in pausa · {n_foto} foto")


def _didascalia_galleria_anticipata(listing_info, url, n_foto):
    """Didascalia CORTA dell'album (solo testo semplice, niente Markdown).
    Il contenuto vero sta nella scheda che segue (_scheda_annuncio_testo):
    la notifica push di un album mostra solo "N foto", quindi prezzo e brand
    devono stare nel messaggio di testo mandato per ultimo."""
    return f"📸 {listing_info.get('title') or 'Annuncio'} · {n_foto} foto"[:1024]


def _eta_annuncio_testo(age_days):
    if age_days is None:
        return None
    minuti = max(0, int(age_days * 24 * 60))
    if minuti < 60:
        return f"online da {max(1, minuti)} min"
    if minuti < 24 * 60:
        return f"online da {minuti // 60} h"
    return f"online da {minuti // (24 * 60)} g"


LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA = 600


def _righe_dettagli_annuncio(listing_info):
    """Riga ✨ condizione · 🧵 materiale · 🎨 colore · 📏 taglia (o None)."""
    esc = _escapa_markdown_legacy
    dettagli = []
    for emoji, chiave in (("📏", "size"), ("✨", "condition"), ("🧵", "material_raw"), ("🎨", "color_raw")):
        valore = (listing_info.get(chiave) or "").strip() if isinstance(listing_info.get(chiave), str) else None
        if valore:
            dettagli.append(f"{emoji} {esc(valore)}")
    return " · ".join(dettagli) or None


def _riga_caricato_annuncio(listing_info):
    """🕒 online da N min / 'Caricato' relativo della pagina (solo il primo pezzo: il campo grezzo contiene
    anche descrizione e hashtag, vedi bug del 2026-10-03)."""
    eta = _eta_annuncio_testo(listing_info.get("age_days"))
    if eta:
        return f"🕒 {eta}"
    if listing_info.get("uploaded_text"):
        relativo = str(listing_info["uploaded_text"]).split(",")[0].strip()
        if relativo:
            return f"🕒 Caricato: {_escapa_markdown_legacy(relativo)}"
    return None


def _riga_venditore_annuncio(listing_info):
    esc = _escapa_markdown_legacy
    venditore = []
    if listing_info.get("seller_login"):
        venditore.append(esc(str(listing_info["seller_login"])))
    rep = listing_info.get("seller_feedback_reputation")
    n_rec = listing_info.get("seller_feedback_count")
    if n_rec is not None:
        venditore.append(f"⭐ {rep:.1f} ({n_rec})".replace(".", ",") if rep is not None else f"{n_rec} recensioni")
    if listing_info.get("seller_items_count") is not None:
        venditore.append(f"{listing_info['seller_items_count']} articoli")
    if listing_info.get("seller_country"):
        venditore.append(esc(str(listing_info["seller_country"])))
    return ("👤 " + " · ".join(venditore)) if venditore else None


def _descrizione_utile(listing_info):
    """Descrizione compattata e accorciata, oppure None se non aggiunge nulla al titolo (molti venditori
    ripetono il titolo nella descrizione: la riga sarebbe un doppione)."""
    descrizione = " ".join((listing_info.get("description") or "").split())
    if not descrizione:
        return None
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()
    d, t = norm(descrizione), norm(listing_info.get("title"))
    if t:
        parole_t, parole_d = t.split(), d.split()
        # doppione: tutte le parole del titolo ci sono anche nella descrizione (anche con un refuso) e la
        # descrizione ha al massimo 4 parole in piu'
        tutte = all(any(w == x or difflib.SequenceMatcher(None, w, x).ratio() >= 0.8 for x in parole_d)
                    for w in parole_t)
        if d in t or (tutte and len(parole_d) <= len(parole_t) + 4):
            return None
    if len(descrizione) > LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA:
        descrizione = descrizione[:LUNGHEZZA_MAX_DESCRIZIONE_SCHEDA].rstrip() + "…"
    return descrizione


def _scheda_annuncio_testo(listing_info, url, n_foto):
    """Scheda dell'annuncio per il messaggio di testo che segue la galleria
    (richiesto dall'utente il 2026-09-29). PREZZO E BRAND SEMPRE IN PRIMA
    RIGA: e' il messaggio piu' recente della chat, quindi quello che compare
    nell'anteprima della notifica, e l'utente vuole vedere prima quelli e
    non "N foto". Solo dati gia' letti dal tracker e dalla pagina annuncio
    (nessuna richiesta in piu' a Vinted); testo libero sempre passato da
    _escapa_markdown_legacy perche' il messaggio va con parse_mode=Markdown."""
    esc = _escapa_markdown_legacy
    righe = []
    testa = _testa_prezzo_brand(listing_info)
    if testa:
        # Preavviso: il fulmine e il margine rapido stanno nella prima riga, quella dell'anteprima della notifica.
        fv = listing_info.get("fair_value") or {}
        marca = ""
        if listing_info.get("preavviso"):
            marca = "⚡ " + (f"{fv['semaforo']} ~+{fv['margine']:.0f} € · " if fv.get("margine") is not None and fv.get("semaforo") else "")
        righe.append(marca + "*" + testa + "*")
    righe.append(esc(listing_info.get("title") or "Annuncio"))
    righe.append("")
    riga_fv = _riga_fair_value_testo(listing_info.get("fair_value"))
    for riga in (_righe_dettagli_annuncio(listing_info), esc(riga_fv) if riga_fv else None,
                 _riga_caricato_annuncio(listing_info), _riga_venditore_annuncio(listing_info)):
        if riga:
            righe.append(riga)
    descrizione = _descrizione_utile(listing_info)
    if descrizione:
        righe += ["", f"📝 {esc(descrizione)}"]
    righe += ["", _stato_analisi_testo(n_foto)]
    return "\n".join(righe)


def _testa_prezzo_brand(listing_info):
    """'💶 35,00 € · 🏷️ Brand' (o None): la riga piu' vista del messaggio."""
    prezzo = _a_float(listing_info.get("price"), None)
    brand = (listing_info.get("brand") or "").strip()
    testa = []
    if prezzo is not None:
        testa.append(f"💶 {prezzo:.2f} €".replace(".", ","))
    if brand and brand != "?":
        testa.append(f"🏷️ {_escapa_markdown_legacy(brand)}")
    return " · ".join(testa) or None


RIGA_PREAVVISO_IN_ATTESA = "_preavviso del semaforo: la valutazione completa arriva dopo_"


def testo_preavviso(listing_info, url=None, riga_finale=RIGA_PREAVVISO_IN_ATTESA, riga_tempi=None, compatto=False):
    """Messaggio breve del PREAVVISO (gruppo COMPRA): prima riga = fulmine, semaforo, margine rapido, prezzo e brand
    (e' quello che compare nell'anteprima della notifica), poi titolo, dettagli, fair value rapido, link e riga finale
    (sostituita a fine analisi). Pura."""
    esc = _escapa_markdown_legacy
    fv = listing_info.get("fair_value") or {}
    testa = _testa_prezzo_brand(listing_info) or ""
    marca = "⚡ " + (f"{fv['semaforo']} ~+{fv['margine']:.0f} € · " if fv.get("margine") is not None and fv.get("semaforo") else "")
    righe = [marca + "*" + testa + "*", esc(listing_info.get("title") or "Annuncio")]
    if compatto:
        # preavviso rimasto senza verdetto: l'esito (scartato/interrotto) in cima, poi solo testata e titolo con il semaforo
        # (richiesta del 10/10: il messaggio riporta il verdetto finale, non lo concatena al preavviso)
        esito, _, resto = (riga_finale or "").partition("\n")
        link = [f"[vedi su Vinted]({url})"] if url else []   # l'album non ha il bottone: il link resta sempre nel testo
        return "\n".join([esito] + righe + link + ([resto] if resto else []))
    for riga in (_righe_dettagli_annuncio(listing_info), esc(_riga_fair_value_testo(fv) or "")):
        if riga:
            righe.append(riga)
    if url:
        righe.append(f"[vedi su Vinted]({url})")
    if riga_tempi:
        righe.append(esc(riga_tempi))
    righe += ["", riga_finale]
    return "\n".join(righe)


def link_messaggio_chat_principale(msg_id):
    """Link al messaggio della chat principale (album o scheda), se la chat e' un supergruppo (id -100...):
    https://t.me/c/<id senza -100>/<messaggio>. In una chat privata Telegram non permette link: None. Pura."""
    chat = str(TELEGRAM_OWNER_CHAT_ID)
    if not msg_id or not chat.startswith("-100"):
        return None
    return f"https://t.me/c/{chat[4:]}/{msg_id}"


def riga_scarto_preavviso(motivo, msg_id=None, interrotta=False):
    """Riga finale del preavviso rimasto senza verdetto: motivo dello scarto (max 220 caratteri) e link al messaggio
    originale nella chat principale, dove ci sono scheda e foto. Pura."""
    if interrotta:
        testa = "⚠️ analisi interrotta per un errore"
    else:
        testa = "🚫 scartato prima del verdetto"
        if motivo:
            testa += ": " + _escapa_markdown_legacy(_compatta_testo(motivo, 220))
    link = link_messaggio_chat_principale(msg_id)
    return testa + (f"\n[messaggio originale nell'altra chat]({link})" if link else "")


def didascalia_verdetto(testo, limite=1024):
    """Riduce il messaggio del verdetto alla didascalia di una foto (max 1024): tiene i paragrafi interi dall'alto
    finche' ci stanno; se il primo e' gia' troppo lungo lo tronca all'ultima riga intera. Pura."""
    testo = (testo or "").strip()
    if len(testo) <= limite:
        return testo
    out = ""
    for par in testo.split("\n\n"):
        candidato = (out + "\n\n" + par) if out else par
        if len(candidato) > limite:
            break
        out = candidato
    if out:
        return out
    righe, acc = testo.split("\n"), ""
    for r in righe:
        if len(acc) + len(r) + 2 > limite:
            break
        acc += (r + "\n")
    return acc.rstrip() + "…" if acc else testo[:limite - 1] + "…"


def _preavviso_inviato(listing_info, id_msg, tipo, riga_tempi, secondi, t_inizio):
    """Dict del preavviso inviato + riga di log con i tempi (secondi): pubblicazione -> telegram -> preavviso, piu' i
    secondi spesi nell'invio. L'ora di consegna al telefono non e' osservabile: si misura fino alla risposta di Telegram."""
    sec = secondi or {}
    invio = time.time() - t_inizio
    totale = (sec["totale"] + invio) if sec.get("totale") is not None else None
    log.info("PREAVVISO_INVIATO | item=%s | tipo=%s | pub_telegram=%s | telegram_preavviso=%s | invio=%.1f | pub_preavviso=%s",
             _estrai_item_id_da_url(listing_info.get("url")) if listing_info.get("url") else "n/d", tipo,
             None if sec.get("pub_telegram") is None else round(sec["pub_telegram"], 1),
             None if sec.get("telegram_notifica") is None else round(sec["telegram_notifica"], 1), invio,
             None if totale is None else round(totale, 1))
    return {"msg_id": id_msg, "tipo": tipo, "base": listing_info, "riga_tempi": riga_tempi}



def chiedi_foto_da_notificare(brand, margine):
    """True se un CHIEDI ALTRE FOTO merita l'alert nel gruppo: margine sopra SOGLIA_MARGINE_ALERT_CHIEDI_FOTO; per i brand
    in BRAND_ESCLUSI_ALERT_CHIEDI_FOTO solo dal margine SOGLIA_MARGINE_ALERT_CHIEDI_FOTO_BRAND_ESCLUSI (50 EUR). Pura."""
    if margine is None or margine <= SOGLIA_MARGINE_ALERT_CHIEDI_FOTO:
        return False
    nome = (brand or "").strip().lower()
    if any(b in nome for b in BRAND_ESCLUSI_ALERT_CHIEDI_FOTO):
        return margine >= SOGLIA_MARGINE_ALERT_CHIEDI_FOTO_BRAND_ESCLUSI
    return True

async def invia_preavviso(listing_info, url, photo_bytes_list=None, riga_tempi=None, secondi=None):
    """Manda il PREAVVISO nel gruppo COMPRA (con suono se listing_info["preavviso_suono"]): ALBUM con tutte le foto (una sola foto: foto con bottone),
    didascalia = testo_preavviso. Senza foto: solo testo con bottone. A fine analisi lo stesso messaggio viene
    AGGIORNATO col verdetto (vedi aggiorna_preavviso): un solo messaggio per annuncio nel gruppo.
    Ritorna {"msg_id", "tipo": album|foto|testo, "base"} oppure None. Non solleva mai."""
    if not TELEGRAM_ALERT_CHAT_ID or not url:
        return None
    testo = testo_preavviso(listing_info, url, riga_tempi=riga_tempi)
    foto = list(photo_bytes_list or [])
    t_inizio = time.time()
    silenzioso = not listing_info.get("preavviso_suono", True)   # suono solo per i migliori (PREAVVISO_SUONO_RAPPORTO_MIN)
    try:
        if len(foto) > 1:
            id_msg = await telegram_send_media_group(
                TELEGRAM_ALERT_CHAT_ID, foto, caption=testo, disable_notification=silenzioso, parse_mode="Markdown")
            if id_msg is not None:
                return _preavviso_inviato(listing_info, id_msg, "album", riga_tempi, secondi, t_inizio)
        elif len(foto) == 1:
            id_msg = await telegram_send_photo_con_bottone(
                TELEGRAM_ALERT_CHAT_ID, foto[0], testo, url, disable_notification=silenzioso)
            if id_msg is not None:
                return _preavviso_inviato(listing_info, id_msg, "foto", riga_tempi, secondi, t_inizio)
        id_msg = await telegram_send_with_buttons(
            TELEGRAM_ALERT_CHAT_ID, testo, url, None, disable_notification=silenzioso)
        if id_msg is not None:
            return _preavviso_inviato(listing_info, id_msg, "testo", riga_tempi, secondi, t_inizio)
    except Exception:
        log.warning("Preavviso non inviato:\n%s", traceback.format_exc())
    return None


async def aggiorna_preavviso(stato, url, testo_verdetto=None, riga_finale=None):
    """Sostituisce il contenuto del messaggio di preavviso: con il verdetto (didascalia ridotta se e' una foto) o,
    senza verdetto, con la scheda del preavviso e una riga finale ("scartato", "interrotta"). Una sola volta per
    annuncio. Ritorna True se il messaggio e' stato aggiornato."""
    if not stato or stato.get("preavviso_aggiornato"):
        return False
    task = stato.get("task_preavviso")
    if task is None:
        return False
    try:
        info = await asyncio.wait_for(task, 15)
    except Exception:
        return False
    if not info:
        return False
    try:
        if testo_verdetto is not None:
            testo = testo_verdetto
        else:
            testo = testo_preavviso(info["base"], url, riga_finale=riga_finale or RIGA_PREAVVISO_IN_ATTESA,
                                    riga_tempi=info.get("riga_tempi"), compatto=bool(riga_finale))
        if info["tipo"] == "testo":
            ok = await telegram_edit_message(TELEGRAM_ALERT_CHAT_ID, info["msg_id"], testo, url)
        else:
            ok = await telegram_edit_caption(
                TELEGRAM_ALERT_CHAT_ID, info["msg_id"], didascalia_verdetto(testo),
                url if info["tipo"] == "foto" else None)
        if ok:
            stato["preavviso_aggiornato"] = True
        return ok
    except Exception:
        log.warning("Preavviso non aggiornato:\n%s", traceback.format_exc())
        return False


async def _invia_galleria_anticipata(listing_info, url, photo_bytes_list, stato=None):
    """Manda nella chat principale l'ALBUM con tutte le foto e SUBITO DOPO la
    scheda di testo (prezzo, brand, dettagli, descrizione, bottone "Apri su
    Vinted"). Ordine voluto: la scheda e' l'ultimo messaggio, quindi e' lei
    l'anteprima della notifica. Silenzioso (la decisione non e' ancora nota e il push resta
    legato al verdetto COMPRA), tranne la scheda quando scatta il PREAVVISO (vedi valuta_preavviso).

    Ritorna il message_id dell'album, a cui agganciare il verdetto. None se
    disattivata o se l'album non e' partito: in quel caso
    _invia_risultato_telegram rimanda le foto a fine analisi come prima,
    cosi' un problema qui non fa mai perdere le foto."""
    # In pausa la galleria e' l'unico messaggio: parte anche con
    # GALLERIA_ANTICIPATA=0.
    if not photo_bytes_list or not (GALLERIA_ANTICIPATA or not ANALISI_GEMINI_ATTIVA):
        return None
    n_foto = len(photo_bytes_list)
    id_album = None
    try:
        didascalia = _didascalia_galleria_anticipata(listing_info, url, n_foto)
        if n_foto > 1:
            id_album = await telegram_send_media_group(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list, caption=didascalia, disable_notification=True,
            )
        else:
            id_album = await telegram_send_photo(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=didascalia, disable_notification=True,
            )
    except Exception:
        log.warning("Galleria anticipata non inviata, le foto partiranno col verdetto:\n%s", traceback.format_exc())
    # La scheda parte comunque, anche se l'album e' fallito: in pausa e'
    # l'unica informazione che arriva.
    try:
        scheda = _scheda_annuncio_testo(listing_info, url, n_foto)
        if url:
            id_scheda = await telegram_send_with_buttons(
                TELEGRAM_OWNER_CHAT_ID, scheda, url, None, disable_notification=not (listing_info.get("preavviso") and not listing_info.get("preavviso_gruppo")), reply_to=id_album,
            )
            if stato is not None and id_scheda:
                # Serve a modificare la riga di stato a fine analisi.
                stato["msg_id_scheda"] = id_scheda
                stato["testo_scheda"] = scheda
                stato["url_scheda"] = url
                stato["stato_testo_iniziale"] = _stato_analisi_testo(n_foto)
        else:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID, scheda, disable_notification=not (listing_info.get("preavviso") and not listing_info.get("preavviso_gruppo")), reply_to=id_album,
            )
    except Exception:
        log.warning("Scheda annuncio non inviata:\n%s", traceback.format_exc())
    return id_album


async def _invia_risultato_telegram(listing_info, url, photo_bytes_list, header, output_finale,
                                    decisione, e_compra, scenario_usato, urgenza="Bassa",
                                    margine=None, msg_id_galleria=None, stato=None, testo_unificato=None):
    item_id = _estrai_item_id_da_url(url)
    # L'urgenza ora arriva calcolata da calcola_verdetto invece di essere
    # dedotta dal testo del verdetto (_e_urgenza_alta cercava parole come
    # "alta"/"subito"/"forte" dentro la stringa di decisione, e bastava una
    # variante di wording del modello per sbagliare bersaglio).
    e_compra_urgente = e_compra and urgenza == "Alta" and decisione == "COMPRA"

    # Notifica push solo su COMPRA (richiesto dall'utente il 2026-09-20): il
    # messaggio arriva SEMPRE nella chat (nessun filtro sui contenuti, resta
    # tutto consultabile), ma per TRATTA/CHIEDI ALTRE FOTO/NON COMPRA/SKIP
    # Telegram lo consegna senza suono/vibrazione/badge push -- stesso
    # meccanismo di "muta le notifiche" che Telegram offre gia' di suo,
    # applicato messaggio per messaggio invece che sull'intera chat.
    silenzioso = decisione != "COMPRA"

    # Galleria gia' arrivata in anticipo (vedi GALLERIA_ANTICIPATA): qui solo
    # il testo, in risposta a quel messaggio. Altrimenti foto + testo come prima.
    if msg_id_galleria is None:
        if len(photo_bytes_list) > 1:
            await telegram_send_media_group(
                TELEGRAM_OWNER_CHAT_ID,
                photo_bytes_list,
                caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto",
                disable_notification=silenzioso,
            )
        elif len(photo_bytes_list) == 1:
            await telegram_send_photo(
                TELEGRAM_OWNER_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"),
                disable_notification=silenzioso,
            )

    # Richiesto dall'utente il 2026-10-03: un solo messaggio per annuncio. Se non e' un COMPRA (il push
    # arriva solo con un messaggio NUOVO: una modifica non notifica) l'analisi viene scritta nella scheda
    # "Analisi in corso", la cui riga di stato diventa "Analisi completata". Se non entra in un messaggio
    # o la modifica fallisce, si ricade sul messaggio separato di prima.
    unificato = False
    if (stato and decisione != "COMPRA" and ANALISI_GEMINI_ATTIVA and stato.get("msg_id_scheda")
            and stato.get("url_scheda")):
        try:
            vecchio = stato.get("stato_testo_iniziale")
            testo_scheda = stato.get("testo_scheda") or ""
            if vecchio and vecchio in testo_scheda:
                testo_unico = testo_unificato or (
                    testo_scheda.replace(vecchio, STATO_ANALISI_COMPLETATA_UNIFICATA)
                    + "\n\n" + "—" * 20 + "\n" + header + output_finale)
                if len(testo_unico) <= 3900:
                    unificato = await telegram_edit_message(
                        TELEGRAM_OWNER_CHAT_ID, stato["msg_id_scheda"], testo_unico, stato["url_scheda"])
                    if unificato:
                        stato["scheda_unificata"] = True
        except Exception:
            log.warning("Analisi non unificata alla scheda, invio separato:\n%s", traceback.format_exc())

    # Il messaggio separato (COMPRA, che deve restare nuovo per il push) usa lo STESSO testo completo degli altri
    # esiti (titolo, dettagli, caricato, margine, venditore, descrizione), richiesto dall'utente il 2026-10-03:
    # prima era la versione ridotta header + output. Se non entra in un messaggio si ricade su quella.
    testo_messaggio = testo_unificato if (testo_unificato and len(testo_unificato) <= 3900) else header + output_finale

    if not unificato and url:
        await telegram_send_with_buttons(
            TELEGRAM_OWNER_CHAT_ID, testo_messaggio, url, item_id if e_compra_urgente else None,
            disable_notification=silenzioso, reply_to=msg_id_galleria,
        )
    elif not unificato:
        await telegram_send_message(TELEGRAM_OWNER_CHAT_ID, testo_messaggio,
                                    disable_notification=silenzioso, reply_to=msg_id_galleria)

    # Ristretto a decisione == "COMPRA" il 2026-09-20, secondo giro (questo
    # alert e' un sendMessage separato che NON passa per silenzioso/
    # disable_notification sopra, quindi finche' il trigger restava
    # "e_compra" (COMPRA O TRATTA O CHIEDI ALTRE FOTO) continuava a suonare a
    # piena voce anche su deal ancora incerti -- probabile causa reale delle
    # notifiche push ricevute su stati diversi da COMPRA, a prescindere dal
    # disable_notification sul messaggio principale, che comunque su Telegram
    # silenzia solo il SUONO, non fa sparire del tutto banner/vibrazione).
    # Richiesto dall'utente il 2026-09-20, terzo giro: niente piu' testo ad
    # hoc ("AZIONE RICHIESTA" riassunto) -- nel gruppo alert deve arrivare
    # LO STESSO messaggio completo (foto + header + output_finale, con gli
    # stessi bottoni) che va nella chat principale, non un duplicato
    # semplificato. E' letteralmente un secondo invio dello stesso
    # contenuto verso una chat diversa, sempre a volume pieno (mai
    # silenzioso: e' l'unico posto dove vuole davvero il push).
    #
    # Riallargato a CHIEDI ALTRE FOTO il 2026-09-21 (caso reale: pull Ann
    # Demeulemeester margine=67.55 EUR ROI=799%, scartato dall'alert solo
    # perche' mancava il wash tag nelle foto -- "un CHIEDI ALTRE FOTO con
    # cotale margine vale la pena essere visto"). Non un blanket come nel
    # 2026-09-20 (quello ha causato il giro di restrizione): solo quando il
    # margine supera (">" stretto) SOGLIA_MARGINE_ALERT_CHIEDI_FOTO, e MAI
    # per i brand in BRAND_ESCLUSI_ALERT_CHIEDI_FOTO -- stessa richiesta,
    # stesso messaggio: su questi brand l'autenticita' ancora "sospetta"
    # pesa piu' del margine, meglio aspettare le foto aggiuntive prima del
    # push.
    e_chiedi_foto_di_valore = decisione == "CHIEDI ALTRE FOTO" and chiedi_foto_da_notificare(listing_info.get("brand"), margine)
    # Preavviso gia' nel gruppo (album con tutte le foto): lo si AGGIORNA col verdetto invece di mandare altri
    # messaggi (richiesto dall'utente il 2026-10-04). Vale per ogni esito; se la modifica non riesce, per i soli
    # esiti da notificare si ricade sul testo in risposta all'album.
    if TELEGRAM_ALERT_CHAT_ID and stato and stato.get("task_preavviso") is not None:
        if await aggiorna_preavviso(stato, url, testo_verdetto=testo_messaggio):
            return
        if stato.get("preavviso_aggiornato"):
            return
        if decisione == "COMPRA" or e_chiedi_foto_di_valore:
            try:
                info = await asyncio.wait_for(stato["task_preavviso"], 15)
            except Exception:
                info = None
            if info:
                if url:
                    await telegram_send_with_buttons(
                        TELEGRAM_ALERT_CHAT_ID, testo_messaggio, url,
                        item_id if (e_compra_urgente and item_id) else None, reply_to=info["msg_id"])
                else:
                    await telegram_send_message(TELEGRAM_ALERT_CHAT_ID, testo_messaggio, reply_to=info["msg_id"])
                return
    if TELEGRAM_ALERT_CHAT_ID and (decisione == "COMPRA" or e_chiedi_foto_di_valore):
        if len(photo_bytes_list) > 1:
            await telegram_send_media_group(
                TELEGRAM_ALERT_CHAT_ID,
                photo_bytes_list,
                caption=f"📸 {listing_info.get('title')} · {len(photo_bytes_list)} foto",
            )
        elif len(photo_bytes_list) == 1:
            await telegram_send_photo(
                TELEGRAM_ALERT_CHAT_ID, photo_bytes_list[0], caption=listing_info.get("title"),
            )

        if url:
            await telegram_send_with_buttons(
                TELEGRAM_ALERT_CHAT_ID, testo_messaggio, url,
                item_id if (e_compra_urgente and item_id) else None,
            )
        else:
            await telegram_send_message(TELEGRAM_ALERT_CHAT_ID, testo_messaggio)


class _PermessoAnalisi:
    """Posto nel tetto di analisi Gemini parallele, preso a meta' pipeline
    (dopo la galleria) e rilasciato sempre da process_listing, anche su
    return anticipato o eccezione."""

    def __init__(self, semaforo):
        self._semaforo = semaforo
        self._preso = False

    async def acquisisci(self, url=None):
        if self._preso:
            return
        if self._semaforo.locked():
            log.info("Analisi Gemini in coda (%d gia' in corso, max %d), scrape e foto gia' fatti: %s",
                     MAX_ANALISI_PARALLELE, MAX_ANALISI_PARALLELE, url)
        await self._semaforo.acquire()
        self._preso = True

    def rilascia(self):
        if self._preso:
            self._preso = False
            self._semaforo.release()


async def _aggiorna_stato_scheda(stato, nuovo_stato):
    """A fine analisi sostituisce nella scheda la riga "⏳ Analisi in corso"
    (modificando il messaggio, niente messaggio nuovo). Mai bloccante: se la
    modifica fallisce la scheda resta com'era."""
    if not stato or not ANALISI_GEMINI_ATTIVA or not stato.get("msg_id_scheda"):
        return
    if stato.get("scheda_unificata"):
        return  # la scheda contiene gia' lo stato finale e l'analisi: non riscriverla
    if stato.get("stato_finale_override") and nuovo_stato == STATO_ANALISI_COMPLETATA:
        nuovo_stato = stato["stato_finale_override"]
    try:
        vecchio = stato.get("stato_testo_iniziale")
        testo = stato.get("testo_scheda") or ""
        if not vecchio or vecchio not in testo:
            return
        await telegram_edit_message(
            TELEGRAM_OWNER_CHAT_ID, stato["msg_id_scheda"],
            testo.replace(vecchio, nuovo_stato), stato.get("url_scheda"),
        )
    except Exception:
        log.warning("Aggiornamento riga di stato della scheda non riuscito:\n%s", traceback.format_exc())


def _compatta_testo(testo, max_len=900):
    testo = " ".join((testo or "").split())
    return testo if len(testo) <= max_len else testo[:max_len].rsplit(" ", 1)[0] + "…"


def _blocco_azioni(output_finale):
    """Il blocco '💬 Azioni (tocca per copiare)' di render_messaggio_verdetto (testo da incollare al venditore),
    oppure None. E' fatto di righe consecutive fino alla prima riga vuota."""
    righe = output_finale.split("\n")
    for i, riga in enumerate(righe):
        if riga.startswith("💬"):
            blocco = []
            for r in righe[i:]:
                if not r.strip() or r.startswith("---"):
                    break
                blocco.append(r)
            return "\n".join(blocco)
    return None


def _blocco_comp(output_finale):
    """Elenco dei comp (righe '• €prezzo · titolo con link _[fonte]_') dal render completo, con intestazione breve."""
    righe = [r for r in output_finale.split("\n") if r.startswith("• €")]
    return ("📊 Comp:\n" + "\n".join(righe)) if righe else None


def _deal_score_coerente(v, decisione):
    """Il deal_score e' un'opinione del modello, la decisione la calcola Python da margine e ROI: se divergono
    (es. 8/10 su un NON COMPRARE) il punteggio mostrato viene riportato dentro la fascia della decisione."""
    score = v.get("deal_score")
    if not isinstance(score, (int, float)):
        return None
    if decisione == "NON COMPRARE":
        return min(int(score), 4)
    if decisione == "COMPRA":
        return max(int(score), 7)
    return int(score)


def dati_deboli(verdetto, stima_instabile=False):
    """True per COMPRA/TRATTA appoggiati a dati fragili: stima instabile tra i campioni o un solo comp (richiesto
    dall'utente il 2026-10-04). Solo un'icona nel messaggio: la decisione non cambia. Pura."""
    if (verdetto or {}).get("decisione") not in ("COMPRA", "TRATTA"):
        return False
    return bool(stima_instabile) or len((verdetto or {}).get("comp_usati") or []) <= 1


def componi_messaggio_compatto(listing_info, v, verdetto, output_finale, url=None, riga_fv="", footer="", deboli=False):
    """Messaggio breve per tutte le decisioni (richiesto dall'utente il 2026-10-03): verdetto + link, prezzo
    d'acquisto (spese incluse) -> atteso, brand e nome, giorni; poi la sola analisi dell'analista e i dati
    ridotti a emoji + valore. Il testo da copiare al venditore (TRATTA / CHIEDI ALTRE FOTO) e gli avvisi
    ⚠️ vengono dal render completo."""
    esc = _escapa_markdown_legacy
    dec = verdetto["decisione"]
    emoji = EMOJI_DECISIONE.get(dec, "🔵")
    link = f" · [vedi su Vinted]({url})" if url else ""
    urgente = " 🔥" if verdetto.get("urgenza") == "Alta" and dec == "COMPRA" else ""
    righe = [f"{emoji} *{dec}*{urgente}{link}"]
    if verdetto.get("margine") is None:
        righe.append("💶 prezzo non rilevato: calcolo non disponibile")
    else:
        righe.append(f"💶 {verdetto['acquisto_pieno']:.0f} € → 🎯 {verdetto['vendita_attesa']:.0f} € · "
                     f"*+{verdetto['margine']:.0f} €* · ROI {verdetto['roi']:.0f}%")
        if dec == "TRATTA":
            righe.append(f"🤝 offri {verdetto['tratta_prezzo_prodotto']:.0f} € → *+{verdetto['tratta_margine']:.0f} €* "
                         f"· ROI {verdetto['tratta_roi']:.0f}%")
    brand = (listing_info.get("brand") or "").strip()
    titolo = esc(listing_info.get("title") or "Annuncio")
    riga_nome = (f"🏷️ {esc(brand)} · " if brand and brand != "?" else "🏷️ ") + titolo
    giorni = v.get("giorni_stimati_vendita")
    if giorni:
        riga_nome += f" · ⏱ ~{giorni} gg"
    righe.append(riga_nome)
    righe.append("")
    righe.append("🧠 " + esc(_compatta_testo(v.get("note_analista"))))
    legit = {"probabilmente_autentico": "✅", "sospetto_servono_altre_foto": "❓",
             "probabilmente_falso": "❌"}.get(v.get("legit_verdetto"), "❔")
    righe.append(f"{legit} {esc(_compatta_testo(v.get('legit_motivo_specifico'), 160))}")
    righe.append(f"🛡️ fake {ETICHETTA_RISCHIO.get(v.get('rischio_fake'), '?')} · conf "
                 f"{ETICHETTA_CONFIDENZA.get(v.get('confidenza'), '?')} · 🎯 {_deal_score_coerente(v, dec)}/10"
                 + (" · ⚠️ dati deboli" if deboli else ""))
    dettagli = _righe_dettagli_annuncio(listing_info)
    if dettagli:
        righe.append(dettagli)
    righe.append(" · ".join(x.strip() for x in (
        _riga_venditore_annuncio(listing_info), _riga_caricato_annuncio(listing_info)) if x))
    if riga_fv:
        righe.append(riga_fv)
    comp = _blocco_comp(output_finale)
    if comp:
        righe += ["", comp]
    azioni = _blocco_azioni(output_finale)
    if azioni:
        righe += ["", azioni]
    avvisi = [r for r in output_finale.split("\n") if r.startswith("⚠️")]
    if avvisi:
        righe += [""] + avvisi
    if footer:
        righe += ["", footer]
    return "\n".join(r for r in righe if r is not None)


def componi_testi_verdetto(listing_info, verdetto_calcolato, output_finale, info_foto="", campioni_target=None,
                           stima_instabile=False, url=None, v=None, footer_compatto=""):
    """Dal testo di render_messaggio_verdetto (prima riga = decisione, seconda = margine, poi il resto) costruisce:
    - header: intestazione del messaggio STANDALONE (COMPRA, che deve restare un messaggio nuovo per il push);
    - resto: il corpo senza le prime due righe;
    - unificato: il messaggio unico che sostituisce la scheda "Analisi in corso" (tutti gli altri esiti):
      verdetto + prezzo + brand in prima riga, poi ogni dato UNA volta sola (richiesto dall'utente il 2026-10-03).
    Pura, testabile."""
    righe_output = output_finale.split("\n", 2)
    riga_verdetto = righe_output[0]
    riga_margine = righe_output[1] if len(righe_output) > 1 else ""
    resto_output = righe_output[2] if len(righe_output) > 2 else ""

    brand_escapato = _escapa_markdown_legacy(listing_info.get("brand"))
    # Link "vedi su Vinted" subito dopo la decisione (richiesto dall'utente il 2026-10-03).
    link = f" · [vedi su Vinted]({url})" if url else ""
    riga_verdetto = riga_verdetto + link
    riga_verdetto_con_brand = riga_verdetto + (f" · {brand_escapato}" if brand_escapato else "")
    riga_fv = _riga_fair_value_unica(listing_info.get("fair_value"), verdetto_calcolato, campioni_target, stima_instabile)

    header = (
        riga_verdetto_con_brand + "\n"
        + (riga_margine + "\n" if riga_margine else "")
        + (riga_fv + "\n" if riga_fv else "")
        + f"🆕 *{_escapa_markdown_legacy(listing_info.get('title'))}*"
        + info_foto
        + f"\n{'—' * 20}\n"
    )

    testa = _testa_prezzo_brand(listing_info)
    deal, _, resto = resto_output.partition("\n\n")
    if v is not None and verdetto_calcolato:
        compatto = componi_messaggio_compatto(listing_info, v, verdetto_calcolato, output_finale, url=url,
                                              riga_fv=riga_fv, footer=footer_compatto,
                                              deboli=dati_deboli(verdetto_calcolato, stima_instabile))
        return header, resto_output, compatto
    sep = "—" * 20
    blocchi = [
        riga_verdetto,
        testa,
        sep,
        riga_margine or None,
        deal or None,
        riga_fv or None,
        sep,
        f"🆕 *{_escapa_markdown_legacy(listing_info.get('title') or 'Annuncio')}*",
        _righe_dettagli_annuncio(listing_info),
        _riga_caricato_annuncio(listing_info),
        info_foto.strip() or None,
        _riga_venditore_annuncio(listing_info),
    ]
    descrizione = _descrizione_utile(listing_info)
    if descrizione:
        blocchi.append(f"📝 {_escapa_markdown_legacy(descrizione)}")
    unificato = "\n".join(b for b in blocchi if b is not None) + "\n\n" + resto
    if url:
        unificato += f"\n\n🔗 [Apri su Vinted]({url})"
    return header, resto_output, unificato


# RICHIESTA ETICHETTA INTERNA per Prada, Miu Miu (richiesta dell'utente l'8/10) e Max Mara, Rick Owens, Missoni (9/10; Fendi no):
# l'etichetta interna e' l'unico modo per verificare l'autenticita' di questi brand. Se l'Occhio non la vede lo scarto era silenzioso (nessun messaggio, solo
# il log); ora, se la stima rapida e' promettente (semaforo 🟢/🟡 dopo la correzione dalla velocita'), arriva un messaggio
# "chiedi l'etichetta" con il testo da incollare al venditore, nella sua lingua. Non si compra mai senza etichetta.
from bot.occhio import BRAND_ETICHETTA_OBBLIGATORIA  # noqa: E402
# sempre in italiano (richiesta dell'utente l'8/10): cortese e dritto al punto
RICHIESTA_ETICHETTA_VENDITORE = (
    "Buongiorno, potrebbe cortesemente inviarmi una foto dell'etichetta interna (marca e composizione) "
    "e di quella con il codice? Grazie mille."
)


def richiede_etichetta(listing_info, motivo_skip):
    """True se lo scarto e' per etichetta mancante, il brand e' in BRAND_ETICHETTA_OBBLIGATORIA e la stima rapida e' promettente. Pura."""
    if not str(motivo_skip or "").startswith("[NESSUNA ETICHETTA"):
        return False
    nome = f"{listing_info.get('brand') or ''} {listing_info.get('title') or ''}".lower()
    if not any(b in nome for b in BRAND_ETICHETTA_OBBLIGATORIA):
        return False
    return (listing_info.get("fair_value") or {}).get("semaforo") in ("🟢", "🟡")


def testo_richiesta_etichetta(listing_info, url):
    """Messaggio Telegram (Markdown) con il testo da incollare al venditore. Pura."""
    esc = _escapa_markdown_legacy
    fv = listing_info.get("fair_value") or {}
    prezzo = _a_float(listing_info.get("price"), None)
    righe = [f"🔎 *CHIEDI L'ETICHETTA INTERNA*{f' · [vedi su Vinted]({url})' if url else ''}",
             f"🏷️ {esc((listing_info.get('brand') or '').strip())} · {esc(listing_info.get('title') or 'Annuncio')}"]
    if prezzo is not None and fv.get("fv"):
        righe.append(f"💶 {prezzo:.0f} € → stima rapida ~{fv['fv']:.0f} € · {fv.get('semaforo', '')}")
    righe += ["❗ Senza etichetta interna leggibile non si compra: rischio fake troppo alto.",
              "", "📝 Da incollare al venditore:", f"`{RICHIESTA_ETICHETTA_VENDITORE}`"]
    return "\n".join(righe)


async def invia_richiesta_etichetta(listing_info, url, reply_to=None):
    """Manda la richiesta nella chat principale (silenziosa) e, se il margine rapido supera la soglia dell'alert CHIEDI FOTO,
    anche nel gruppo con suono. Ritorna True se almeno un messaggio e' partito."""
    testo = testo_richiesta_etichetta(listing_info, url)
    inviato = False
    try:
        await telegram_send_with_buttons(TELEGRAM_OWNER_CHAT_ID, testo, url, None, disable_notification=True, reply_to=reply_to)
        inviato = True
    except Exception:
        log.warning("Richiesta etichetta non inviata in chat:\n%s", traceback.format_exc())
    margine_rapido = (listing_info.get("fair_value") or {}).get("margine")
    if TELEGRAM_ALERT_CHAT_ID and chiedi_foto_da_notificare(listing_info.get("brand"), margine_rapido):
        try:
            await telegram_send_with_buttons(TELEGRAM_ALERT_CHAT_ID, testo, url, None)
            inviato = True
        except Exception:
            log.warning("Richiesta etichetta non inviata nel gruppo:\n%s", traceback.format_exc())
    return inviato

