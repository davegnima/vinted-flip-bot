"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import asyncio
import time
import re
import difflib
import traceback


from bot.config import (TELEGRAM_ALERT_CHAT_ID, TELEGRAM_OWNER_CHAT_ID)
from bot.parsing import _a_float, _estrai_item_id_da_url
from bot.testo import RigaMd, _escapa_markdown_legacy
from bot.fair_value import _riga_fair_value_testo
from bot.logger import log
from bot.tempi import caricato_attendibile
from bot.telegram_api import telegram_delete_message, telegram_edit_caption, telegram_edit_message, telegram_send_media_group, telegram_send_message, telegram_send_photo, telegram_send_photo_con_bottone, telegram_send_with_buttons
# ---- fine import ----
# GALLERIA ANTICIPATA (richiesto dall'utente il 2026-09-28): la galleria completa arriva nella chat principale APPENA le foto
# sono scaricate, seguita dalla scheda di testo. La galleria parte silenziosa.


def _stato_analisi_testo(n_foto):
    return f"🚦 Solo semaforo, senza AI · {n_foto} foto"


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
    if listing_info.get("uploaded_text") and caricato_attendibile(listing_info["uploaded_text"]):
        relativo = str(listing_info["uploaded_text"]).split(",")[0].strip()
        if relativo:
            return f"🕒 Caricato: {_escapa_markdown_legacy(relativo)}"
    return None


def _riga_venditore_annuncio(listing_info):
    esc = _escapa_markdown_legacy
    venditore = []
    login, sid = listing_info.get("seller_login"), str(listing_info.get("seller_id") or "")
    if login and sid.isdigit():
        # nome cliccabile verso il profilo (14/10, richiesta dell'utente). Nel Markdown legacy il testo del link non si
        # escapa (il backslash comparirebbe): si tolgono solo le parentesi che chiuderebbero il link.
        dominio = re.search(r"https?://(?:www\.)?(vinted\.[a-z.]+)", str(listing_info.get("url") or ""))
        nome = re.sub(r"[\[\]()]", "", str(login)) or "profilo"
        venditore.append(f"[{nome}](https://www.{dominio.group(1) if dominio else 'vinted.it'}/member/{sid})")
    elif login:
        venditore.append(esc(str(login)))
    rep = listing_info.get("seller_feedback_reputation")
    n_rec = listing_info.get("seller_feedback_count")
    if n_rec is not None:
        venditore.append(f"⭐ {rep:.1f} ({n_rec})".replace(".", ",") if rep is not None else f"{n_rec} recensioni")
    if listing_info.get("seller_items_count") is not None:
        venditore.append(f"{listing_info['seller_items_count']} articoli")
    if listing_info.get("seller_country"):
        venditore.append(esc(str(listing_info["seller_country"])))
    return ("👤 " + " · ".join(venditore)) if venditore else None


def riga_query(listing_info):
    """'🔎 Query: <nome>' con il link alla ricerca del tracker che ha trovato l'annuncio (17/10, richiesta
    dell'utente), oppure None. Testo del link senza parentesi quadre/tonde, come per il venditore. Pura."""
    nome, url = listing_info.get("query_name"), listing_info.get("query_url")
    if not nome and not url:
        return None
    nome = re.sub(r"[\[\]()]", "", str(nome or "")).strip() or "ricerca"
    if url:
        return f"🔎 Query: [{nome}]({str(url).replace('(', '%28').replace(')', '%29')})"
    return f"🔎 Query: {_escapa_markdown_legacy(nome)}"


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
                 _riga_caricato_annuncio(listing_info), _riga_venditore_annuncio(listing_info),
                 riga_query(listing_info)):
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


def _riga_titolo(listing_info, url=None):
    """Titolo dell'annuncio; con l'url diventa il link all'annuncio (5/11, utente: il 'vedi su Vinted' in fondo veniva tagliato
    dalla didascalia da 1024 caratteri, il titolo sta in alto e non cade mai). Pura."""
    titolo = _escapa_markdown_legacy(listing_info.get("title") or "Annuncio")
    return f"[{titolo}]({url})" if url else titolo


def testo_preavviso(listing_info, url=None, riga_finale=RIGA_PREAVVISO_IN_ATTESA, riga_tempi=None, compatto=False):
    """Messaggio breve del PREAVVISO (gruppo COMPRA): prima riga = fulmine, semaforo, margine rapido, prezzo e brand
    (e' quello che compare nell'anteprima della notifica), poi titolo, dettagli, fair value rapido, link e riga finale
    (sostituita a fine analisi). Pura."""
    esc = _escapa_markdown_legacy
    fv = listing_info.get("fair_value") or {}
    testa = _testa_prezzo_brand(listing_info) or ""
    marca = "⚡ " + (f"{fv['semaforo']} ~+{fv['margine']:.0f} € · " if fv.get("margine") is not None and fv.get("semaforo") else "")
    verdetto = listing_info.get("riga_verdetto_jev") if listing_info.get("righe_jev") else None
    if listing_info.get("righe_jev"):
        # dopo la verifica Jev: verdetto in chiaro in cima, poi intestazione "🟢 *15 €* ➜ rivendita ~*270 €*" (come il radar) oppure, se scartato,
        # solo prezzo e brand; la stima rapida del semaforo resta come primo passo, spiegata (5/11, utente: 'da dove deriva il ~+90?')
        # 8/11 (utente: 'capisco dopo troppe righe di che oggetto parliamo'; 'organizza come il linguaggio degli aerei'): prima l'identificazione
        # (semaforo, brand, titolo con link, prezzo), poi esito con rivendita mista, originalita' e cosa fare, una riga vuota, poi i dettagli.
        prezzo = _a_float(listing_info.get("price"), None)
        brand = (listing_info.get("brand") or "").strip()
        sem = fv.get("semaforo") or "🟢"
        if str(verdetto or "").startswith("🚫"):
            sem = "🚫"   # 10/11 (utente): se Jev scarta, il bollino del semaforo diventa quello di scartato
        identificazione = (sem + " " + (f"*{esc(brand)}* · " if brand and brand != "?" else "") + _riga_titolo(listing_info, url)
                           + (f" · *{prezzo:g} €*" if prezzo is not None else ""))
        originalita = listing_info.get("riga_originalita_jev")
        # 9/11 (utente): il verdetto di Gemini (💬) e' la seconda riga, subito dopo titolo e prezzo
        consiglio = next((r for r in (listing_info.get("righe_jev") or []) if str(r).startswith("💬")), None)
        righe = [identificazione] + ([esc(consiglio)] if consiglio else []) + ([esc(listing_info["riga_recupero"])] if listing_info.get("riga_recupero") else []) \
            + ([esc(verdetto)] if verdetto else []) + ([esc(originalita)] if originalita else []) + [""]
    else:
        righe = [marca + "*" + testa + "*", _riga_titolo(listing_info, url)]
    if compatto:
        # preavviso rimasto senza verdetto: l'esito (scartato/interrotto) in cima, poi solo testata e titolo con il semaforo
        # (richiesta del 10/10: il messaggio riporta il verdetto finale, non lo concatena al preavviso)
        esito, _, resto = (riga_finale or "").partition("\n")
        link = [f"[vedi su Vinted]({url})"] if url else []   # l'album non ha il bottone: il link resta sempre nel testo
        return "\n".join([esito] + righe + link + ([resto] if resto else []))
    riga_sem = None if listing_info.get("righe_jev") else esc(_riga_fair_value_testo(fv) or "")   # con la verifica il semaforo e' nella rivendita mista
    for riga in (_righe_dettagli_annuncio(listing_info), _riga_venditore_annuncio(listing_info) if listing_info.get("righe_jev") else None, riga_sem):
        if riga:
            righe.append(riga)
    righe_jev = listing_info.get("righe_jev")
    if righe_jev:
        # brand nuovo verificato con comparabili e foto (bot/moda_jev.py): il messaggio nasce gia' con l'esito, niente "in attesa"
        righe += [r if isinstance(r, RigaMd) else esc(r) for r in righe_jev if not (isinstance(r, str) and r.startswith("💬") and not isinstance(r, RigaMd))]
        if riga_finale == RIGA_PREAVVISO_IN_ATTESA:
            riga_finale = ""
    if url and not righe_jev:   # con la verifica il titolo e' gia' il link all'annuncio
        righe.append(f"[vedi su Vinted]({url})")
    if riga_query(listing_info):
        righe.append(riga_query(listing_info))
    if riga_tempi:
        righe.append(esc(riga_tempi))
    righe += ["", riga_finale] if riga_finale else []
    return _entra_nella_didascalia(righe) if righe_jev else "\n".join(righe)


# Righe da togliere per prime, in quest'ordine, se il messaggio supera la didascalia di Telegram (1024 caratteri): mai i link dei comparabili,
# il verdetto, l'originalita' e i difetti (7/11, utente: il link dei comparabili mancava perche' la didascalia era tagliata).
_RIGHE_DA_TOGLIERE = ("ℹ️", "🖼", "⚡", "🔎 Query", "💶", "👁", "🧠", "⏭", "🚦", "💬", "👤")


def _entra_nella_didascalia(righe, limite=1000):
    """Testo del messaggio con al massimo `limite` caratteri: toglie le righe meno utili (vedi _RIGHE_DA_TOGLIERE) finche' ci sta. Pura."""
    righe = list(righe)
    for prefisso in _RIGHE_DA_TOGLIERE:
        # il limite di Telegram conta il testo visibile: l'indirizzo dentro "[titolo](url)" non conta (9/11)
        if len(re.sub(r"\]\([^)]*\)", "]", "\n".join(righe))) <= limite:
            break
        righe = [r for r in righe if not r.startswith(prefisso)]
    return "\n".join(righe)


def link_messaggio_chat_principale(msg_id):
    """Link al messaggio della chat principale (album o scheda), se la chat e' un supergruppo (id -100...):
    https://t.me/c/<id senza -100>/<messaggio>. In una chat privata Telegram non permette link: None. Pura."""
    chat = str(TELEGRAM_OWNER_CHAT_ID)
    if not msg_id or not chat.startswith("-100"):
        return None
    return f"https://t.me/c/{chat[4:]}/{msg_id}"


def riga_scarto_preavviso(motivo, msg_id=None, interrotta=False, riavvio=False):
    """Riga finale del preavviso rimasto senza verdetto: motivo dello scarto (max 220 caratteri) e link al messaggio
    originale nella chat principale, dove ci sono scheda e foto. Pura."""
    if interrotta and riavvio:
        testa = "🔄 analisi interrotta dal riavvio del bot (aggiornamento): l'annuncio resta valido, controllalo a mano"
    elif interrotta:
        testa = "⚠️ analisi interrotta per un errore"
    else:
        testa = "🚫 scartato prima del verdetto"
        if motivo:
            testa += ": " + _escapa_markdown_legacy(_compatta_testo(motivo, 220))
    link = link_messaggio_chat_principale(msg_id)
    return testa + (f"\n[messaggio originale nell'altra chat]({link})" if link else "")


RIGA_SOLO_SEMAFORO = "🚦 Avviso dal solo semaforo (stima rapida, senza AI): autenticita' non verificata"


def testo_avviso_solo_semaforo(listing_info, url=None, msg_id=None):
    """Messaggio dell'avviso dal solo semaforo: testata con semaforo, margine rapido, prezzo e brand, titolo,
    fair value rapido, link e avvertenza che manca la verifica. Pura."""
    esc = _escapa_markdown_legacy
    fv = listing_info.get("fair_value") or {}
    marca = (fv.get("semaforo") or "🟢") + " " + (f"~+{fv['margine']:.0f} € · " if fv.get("margine") is not None else "")
    righe = [marca + "*" + (_testa_prezzo_brand(listing_info) or "") + "*", esc(listing_info.get("title") or "Annuncio"),
             esc(_riga_fair_value_testo(fv) or "")]
    righe = [r for r in righe if r]
    if url:
        righe.append(f"[vedi su Vinted]({url})")
    link = link_messaggio_chat_principale(msg_id)
    righe += ["", RIGA_SOLO_SEMAFORO] + ([f"[messaggio originale nell'altra chat]({link})"] if link else [])
    return "\n".join(righe)


def _testo_visibile(testo):
    """Testo come lo conta Telegram (limite 1024 della didascalia): senza l'indirizzo dentro '[titolo](url)'. Pura."""
    return re.sub(r"\]\([^)]*\)", "]", testo or "")


def didascalia_verdetto(testo, limite=1024):
    """Riduce il messaggio del verdetto alla didascalia di una foto (max 1024, limite di Telegram): se non ci sta accorcia le
    righe piu' lunghe (analisi, dubbi: troncate con "…") e tiene tutte le altre, cosi' restano esito, prezzi, dettagli e fair
    value. Se non basta ancora, toglie le righe dal fondo. Pura."""
    testo = (testo or "").strip()
    if len(testo) > limite:   # la riga della ricerca (link lungo) cade per prima, come prima
        testo = "\n".join(r for r in testo.split("\n") if not r.startswith("🔎 Query:"))
    if len(_testo_visibile(testo)) <= limite:   # Telegram conta il testo visibile: l'indirizzo di "[titolo](url)" non conta (9/11, avviso Sacai senza riga Gemini e senza stime)
        return testo
    # la riga della ricerca (link lungo fino a ~600 caratteri) e' la prima a cadere: accorciata spezzerebbe il link
    righe = [r for r in testo.split("\n") if not r.startswith("🔎 Query:")]
    MIN_RIGA = 140
    for _ in range(len(righe) * 2 + 5):          # numero di giri limitato: la funzione deve sempre finire
        totale = len(_testo_visibile("\n".join(righe)))
        if totale <= limite:
            break
        i = max(range(len(righe)), key=lambda k: len(_testo_visibile(righe[k])))
        if len(righe[i]) <= MIN_RIGA:
            break
        tenuti = max(MIN_RIGA, len(righe[i]) - (totale - limite) - 1)
        accorciata = righe[i][:tenuti].rstrip(" \\") + "…"
        if righe[i][:1] in ("_", "*") and righe[i].endswith(righe[i][:1]) and accorciata.count(righe[i][:1]) % 2:
            accorciata += righe[i][:1]   # riga tutta in corsivo/grassetto: richiude il segno, senno' Telegram rifiuta il Markdown
        if len(accorciata) >= len(righe[i]):     # nessun progresso (riga gia' accorciata al minimo)
            break
        righe[i] = accorciata
    while len(_testo_visibile("\n".join(righe))) > limite and len(righe) > 1:
        righe.pop()
    out = "\n".join(righe).rstrip()
    return out if len(_testo_visibile(out)) <= limite else out[:limite - 1] + "…"


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


async def invia_preavviso(listing_info, url, photo_bytes_list=None, riga_tempi=None, secondi=None):
    """Manda il PREAVVISO nel gruppo COMPRA (con suono se listing_info["preavviso_suono"]): ALBUM con tutte le foto (una sola foto: foto con bottone),
    didascalia = testo_preavviso. Senza foto: solo testo con bottone. A fine analisi lo stesso messaggio viene
    AGGIORNATO col verdetto (vedi aggiorna_preavviso): un solo messaggio per annuncio nel gruppo.
    Ritorna {"msg_id", "tipo": album|foto|testo, "base"} oppure None. Non solleva mai."""
    if not TELEGRAM_ALERT_CHAT_ID or not url:
        return None
    # 7/11: il messaggio "Recuperato" e' definitivo (nessun verdetto da aggiungere dopo): niente riga "in attesa"
    testo = testo_preavviso(listing_info, url, riga_tempi=riga_tempi, **({"riga_finale": ""} if listing_info.get("riga_recupero") else {}))
    foto = list(photo_bytes_list or [])
    t_inizio = time.time()
    silenzioso = not listing_info.get("preavviso_suono", True)   # suono solo per i migliori (PREAVVISO_SUONO_RAPPORTO_MIN)
    # 9/11: la didascalia di foto e album ha il limite di 1024 caratteri; il taglio brutale spezzava il link della ricerca (fino a ~600 car.)
    # e Telegram rifiutava il Markdown (messaggio mostrato con asterischi e parentesi). Si accorcia per righe, come per il verdetto.
    didascalia = didascalia_verdetto(testo) if foto else testo
    try:
        if len(foto) > 1:
            id_msg = await telegram_send_media_group(
                TELEGRAM_ALERT_CHAT_ID, foto, caption=didascalia, disable_notification=silenzioso, parse_mode="Markdown")
            if id_msg is not None:
                return _preavviso_inviato(listing_info, id_msg, "album", riga_tempi, secondi, t_inizio)
        elif len(foto) == 1:
            id_msg = await telegram_send_photo_con_bottone(
                TELEGRAM_ALERT_CHAT_ID, foto[0], didascalia, url, disable_notification=silenzioso)
            if id_msg is not None:
                return _preavviso_inviato(listing_info, id_msg, "foto", riga_tempi, secondi, t_inizio)
        id_msg = await telegram_send_with_buttons(
            TELEGRAM_ALERT_CHAT_ID, testo, url, None, disable_notification=silenzioso)
        if id_msg is not None:
            return _preavviso_inviato(listing_info, id_msg, "testo", riga_tempi, secondi, t_inizio)
    except Exception:
        log.warning("Preavviso non inviato:\n%s", traceback.format_exc())
    return None


async def invia_galleria_dopo_lampo(stato, titolo, photo_bytes_list):
    """Dopo un preavviso lampo (solo copertina): l'ALBUM con tutte le foto, appena scaricate, nel gruppo COMPRA come risposta al
    preavviso e senza suono (il suono e' gia' partito col lampo). Ritorna l'id dell'album (la sua didascalia riceve il verdetto
    finale: e' il messaggio piu' in basso nel feed) oppure None. Non solleva mai."""
    try:
        info = await asyncio.wait_for(stato["task_preavviso"], 15)
        if info and len(photo_bytes_list) > 1:
            return await telegram_send_media_group(
                TELEGRAM_ALERT_CHAT_ID, photo_bytes_list, caption=f"📸 {titolo} · {len(photo_bytes_list)} foto",
                disable_notification=True, reply_to=info["msg_id"])
    except Exception:
        log.warning("Galleria dopo il preavviso lampo non inviata:\n%s", traceback.format_exc())
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
        id_album = None
        if info["tipo"] != "testo" and stato.get("task_album_lampo") is not None:
            try:
                id_album = await asyncio.wait_for(stato["task_album_lampo"], 15)
            except Exception:
                id_album = None
        # 9/11: il testo realmente inviato (prime 3 righe) resta nel log, per confrontarlo con quello che si vede su Telegram
        log.info("PREAVVISO TESTO | item=%s | tipo=%s | car=%d | righe=%r", _estrai_item_id_da_url(url) if url else "n/d", info["tipo"],
                 len(testo), [r[:110] for r in testo.split("\n")[:3]])
        if info["tipo"] == "testo":
            ok = await telegram_edit_message(TELEGRAM_ALERT_CHAT_ID, info["msg_id"], testo, url)
        elif id_album and await telegram_edit_caption(TELEGRAM_ALERT_CHAT_ID, id_album, didascalia_verdetto(testo), None):
            # preavviso lampo + album: il verdetto sta nella didascalia dell'album (il messaggio piu' in basso, 11/10) e il
            # preavviso con la sola copertina si CANCELLA (meno messaggi da guardare); se la cancellazione fallisce resta con
            # la sola testata (esito, prezzi, brand) e il bottone
            ok = await telegram_delete_message(TELEGRAM_ALERT_CHAT_ID, info["msg_id"]) or await telegram_edit_caption(
                TELEGRAM_ALERT_CHAT_ID, info["msg_id"], didascalia_verdetto(testo, 350), url if info["tipo"] == "foto" else None)
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
    if not photo_bytes_list:
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
                TELEGRAM_OWNER_CHAT_ID, scheda, url, None, disable_notification=not (listing_info.get("preavviso") and not listing_info.get("preavviso_gruppo") and not listing_info.get("verifica_jev")), reply_to=id_album,
            )
            if stato is not None and id_scheda:
                # Serve a modificare la riga di stato a fine analisi.
                stato["msg_id_scheda"] = id_scheda
                stato["testo_scheda"] = scheda
                stato["url_scheda"] = url
                stato["stato_testo_iniziale"] = _stato_analisi_testo(n_foto)
        else:
            await telegram_send_message(
                TELEGRAM_OWNER_CHAT_ID, scheda, disable_notification=not (listing_info.get("preavviso") and not listing_info.get("preavviso_gruppo") and not listing_info.get("verifica_jev")), reply_to=id_album,
            )
    except Exception:
        log.warning("Scheda annuncio non inviata:\n%s", traceback.format_exc())
    return id_album


async def aggiorna_scheda_jev(stato, riga):
    """Sostituisce nella scheda della chat principale la riga di stato con l'esito della verifica Jev (modifica, nessuna
    notifica). Mai bloccante."""
    if not stato or not stato.get("msg_id_scheda"):
        return
    try:
        testo = stato.get("testo_scheda") or ""
        vecchio = stato.get("stato_testo_iniziale")
        nuovo = _escapa_markdown_legacy(riga)
        testo = testo.replace(vecchio, nuovo) if vecchio and vecchio in testo else testo + "\n" + nuovo
        await telegram_edit_message(TELEGRAM_OWNER_CHAT_ID, stato["msg_id_scheda"], testo, stato.get("url_scheda"))
    except Exception:
        log.warning("Esito Jev non scritto nella scheda:\n%s", traceback.format_exc())


def _compatta_testo(testo, max_len=900):
    testo = " ".join((testo or "").split())
    return testo if len(testo) <= max_len else testo[:max_len].rsplit(" ", 1)[0] + "…"
