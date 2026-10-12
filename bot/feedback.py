"""Feedback dell'utente su autenticita' e prezzo di rivendita atteso (12/10).

Due canali: (1) un messaggio "Controllo autenticita'" con bottoni (Originale / Falso / Non so, poi il prezzo di rivendita
atteso) proposto ogni volta che c'e' un rischio falso su un annuncio economicamente interessante; (2) la risposta a testo a
qualunque scheda o verdetto del bot ("f", "o", "o 90", "90"). Ogni input finisce nel DB (eventi `feedback`) e in una riga di
log `FEEDBACK |` con il contesto dell'annuncio: sono le etichette VERE con cui tarare Occhio, Cervello e semaforo."""
import os
import re
import time
import asyncio
import traceback

from bot.config import TELEGRAM_OWNER_CHAT_ID
from bot.logger import log
from bot import db
from bot.testo import _escapa_markdown_legacy as esc
from bot.telegram_api import (telegram_send_con_tastiera, telegram_edit_con_tastiera, telegram_get_updates,
                              telegram_answer_callback, telegram_edit_tastiera, telegram_send_richiesta_prezzo, righe_feedback)

FEEDBACK_ATTIVO = os.environ.get("FEEDBACK_ATTIVO", "1").strip() != "0"
FEEDBACK_MAX_GIORNO = int(float(os.environ.get("FEEDBACK_MAX_GIORNO", "60")))   # controlli proposti al giorno
GIUDIZI = {"f": "falso", "o": "originale", "n": "non_so"}
PREZZI_RAPIDI = (30, 40, 50, 60, 80, 100, 120, 150, 200)
_RE_NUMERO = re.compile(r"^\d{1,5}(?:[.,]\d{1,2})?$")
_PAROLE = {
    "f": "f", "falso": "f", "fake": "f", "falsa": "f",
    "o": "o", "orig": "o", "originale": "o", "legit": "o", "autentico": "o",
    "?": "n", "nonso": "n",
}
_proposti = {"giorno": "", "n": 0, "item": set()}


def parse_risposta(testo):
    """Interpreta una risposta a testo: ("falso"|"originale"|"non_so"|None, prezzo|None), oppure None se non e' un feedback.
    Esempi: "f" -> falso; "o 90" -> originale a 90 EUR; "90" -> solo prezzo; "falso 40 eur" -> falso (prezzo ignorato). Pura."""
    t = (testo or "").strip().lower().replace("€", " ").replace("euro", " ").replace("eur", " ")
    parti = [p for p in re.split(r"[\s;]+", t) if p]
    if not parti or len(parti) > 3:
        return None
    giudizio, prezzo = None, None
    for p in parti:
        if p in _PAROLE and giudizio is None:
            giudizio = GIUDIZI[_PAROLE[p]]
        elif _RE_NUMERO.match(p) and prezzo is None:
            prezzo = float(p.replace(",", "."))
        else:
            return None
    if giudizio is None and prezzo is None:
        return None
    return giudizio, (None if giudizio == "falso" else prezzo)


def rischio_falso_da_verdetto(legit_verdetto, decisione, semaforo):
    """True se vale la pena chiedere il tuo parere sul falso: il Cervello non e' convinto dell'autenticita' ma l'annuncio e'
    economicamente interessante (COMPRA/TRATTA/CHIEDI FOTO oppure semaforo verde/giallo). Pura."""
    if legit_verdetto not in ("sospetto_servono_altre_foto", "probabilmente_falso"):
        return False
    return decisione in ("COMPRA", "TRATTA", "CHIEDI ALTRE FOTO") or semaforo in ("🟢", "🟡")


def rischio_falso_da_scarto(motivo_skip, semaforo):
    """True se un annuncio scartato dall'Occhio per falso/frode/brand diverso e' economicamente interessante (semaforo verde/giallo):
    sono i falsi negativi piu' costosi. Pura."""
    m = str(motivo_skip or "")
    return semaforo in ("🟢", "🟡") and m.startswith(("[FALSO CONCLAMATO", "[ANNUNCIO FRAUDOLENTO", "[BRAND NON CORRISPONDENTE"))


def _ammesso(item_id):
    oggi = time.strftime("%Y-%m-%d", time.gmtime())
    if _proposti["giorno"] != oggi:
        _proposti.update({"giorno": oggi, "n": 0, "item": set()})
    if item_id in _proposti["item"] or _proposti["n"] >= FEEDBACK_MAX_GIORNO:
        return False
    _proposti["item"].add(item_id)
    _proposti["n"] += 1
    return True


def tastiera_giudizio(item_id):
    return [[{"text": "✅ Originale", "callback_data": f"fb|{item_id}|o"},
             {"text": "❌ Falso", "callback_data": f"fb|{item_id}|f"},
             {"text": "❓ Non so", "callback_data": f"fb|{item_id}|n"}]]


def tastiera_prezzo(item_id, fv=None):
    prezzi = list(PREZZI_RAPIDI)
    if fv:
        prezzi = sorted(set(prezzi + [int(round(fv / 5.0) * 5)]))[:10]
    righe, riga = [], []
    for p in prezzi:
        riga.append({"text": f"{p} €", "callback_data": f"fp|{item_id}|{p}"})
        if len(riga) == 3:
            righe.append(riga)
            riga = []
    if riga:
        righe.append(riga)
    righe.append([{"text": "Salta il prezzo", "callback_data": f"fp|{item_id}|0"}])
    return righe


def testo_controllo(ctx, url, motivo):
    """Testo Markdown del messaggio di controllo autenticita'. Pura."""
    righe = [f"🔎 *Controllo autenticità* · 🏷️ {esc(str(ctx.get('brand') or 'n/d'))}"]
    if ctx.get("titolo"):
        righe.append(esc(str(ctx["titolo"])))
    pezzi = []
    if ctx.get("prezzo") is not None:
        pezzi.append(f"💶 {ctx['prezzo']:.0f} €")
    if ctx.get("sem"):
        pezzi.append(str(ctx["sem"]))
    if ctx.get("fv"):
        pezzi.append(f"fair value ~{ctx['fv']} €")
    if pezzi:
        righe.append(esc(" · ".join(pezzi)))
    if motivo:
        righe.append("❗ " + esc(str(motivo)[:220]))
    if url:
        righe.append(f"[vedi su Vinted]({url})")
    righe.append("Cosa dici tu? (puoi anche rispondere con «f», «o» o «o 90»)")
    return "\n".join(righe)


def _base_testo(testo):
    """Il testo del messaggio di controllo senza la domanda finale e senza le righe di esito aggiunte dai passi precedenti."""
    return re.split(r"\n(?:Cosa dici|✅|❓|❌)", testo or "")[0]


def contesto_annuncio(listing_info, esito=None, target=None, legit=None):
    """Dati dell'annuncio da riportare nel messaggio e nel log del feedback. Pura."""
    from bot.verdetto import _a_float
    fv = (listing_info or {}).get("fair_value") or {}
    return {"brand": (listing_info or {}).get("brand"), "titolo": ((listing_info or {}).get("title") or "")[:80],
            "prezzo": _a_float((listing_info or {}).get("price"), None), "sem": fv.get("semaforo"), "fv": fv.get("fv"),
            "esito": esito, "target": target, "legit": legit}


def registra_feedback(item_id, giudizio, prezzo, fonte, ctx=None):
    """Salva il parere (DB + riga di log). Se c'e' un prezzo atteso lo registra anche come stima umana del fair value."""
    ctx = ctx or {}
    log.info("FEEDBACK | item=%s | giudizio=%s | prezzo_atteso=%s | fonte=%s | brand='%s' | prezzo=%s | esito=%s | sem=%s | fv=%s | target=%s | legit=%s | motivo=%s",
             item_id, giudizio or "-", prezzo if prezzo is not None else "-", fonte, ctx.get("brand") or "n/d", ctx.get("prezzo"),
             ctx.get("esito"), ctx.get("sem"), ctx.get("fv"), ctx.get("target"), ctx.get("legit"),
             str(ctx.get("motivo") or "-").replace("|", "/")[:80])
    try:
        db.scrivi_evento("feedback", str(item_id), ctx.get("brand"), {"giudizio": giudizio, "prezzo_atteso": prezzo, "fonte": fonte, **{
            k: ctx.get(k) for k in ("prezzo", "esito", "sem", "fv", "target", "legit", "motivo", "titolo")}})
    except Exception:
        log.warning("Feedback non salvato nel DB:\n%s", traceback.format_exc())
    if prezzo:
        try:
            from bot.fair_value import fv_registra_umana
            fv_registra_umana(item_id, prezzo)
        except Exception:
            log.warning("Stima umana non registrata:\n%s", traceback.format_exc())


def registra_verdetto(item_id, valutazione, ctx=None):
    """Salva il parere dell'utente sul verdetto del Cervello ("giusto"|"sbagliato"): DB + riga `FEEDBACK VERDETTO`."""
    ctx = ctx or {}
    log.info("FEEDBACK VERDETTO | item=%s | verdetto=%s | brand='%s' | prezzo=%s | esito=%s | sem=%s | fv=%s | target=%s | legit=%s",
             item_id, valutazione, ctx.get("brand") or "n/d", ctx.get("prezzo"), ctx.get("esito"), ctx.get("sem"),
             ctx.get("fv"), ctx.get("target"), ctx.get("legit"))
    try:
        db.scrivi_evento("feedback", str(item_id), ctx.get("brand"), {"giudizio": None, "prezzo_atteso": None, "fonte": "verdetto",
                         "verdetto_utente": valutazione, **{k: ctx.get(k) for k in ("prezzo", "esito", "sem", "fv", "target", "legit", "motivo", "titolo")}})
    except Exception:
        log.warning("Parere sul verdetto non salvato nel DB:\n%s", traceback.format_exc())


def registra_nota(item_id, nota, ctx=None):
    """Salva il commento libero dell'utente su un annuncio (DB + riga di log `FEEDBACK NOTA`), da rileggere nel recap."""
    ctx = ctx or {}
    nota = " ".join((nota or "").split())[:500]
    if not nota:
        return
    log.info("FEEDBACK NOTA | item=%s | brand='%s' | prezzo=%s | esito=%s | sem=%s | fv=%s | legit=%s | nota=%s",
             item_id, ctx.get("brand") or "n/d", ctx.get("prezzo"), ctx.get("esito"), ctx.get("sem"), ctx.get("fv"),
             ctx.get("legit"), nota)
    try:
        db.scrivi_evento("feedback", str(item_id), ctx.get("brand"), {"giudizio": None, "prezzo_atteso": None, "fonte": "nota", "nota": nota, **{
            k: ctx.get(k) for k in ("prezzo", "esito", "sem", "fv", "target", "legit", "motivo", "titolo")}})
    except Exception:
        log.warning("Nota non salvata nel DB:\n%s", traceback.format_exc())


async def proponi_controllo(item_id, url, ctx, motivo, reply_to=None):
    """Manda nella chat principale (senza suono) il messaggio con i bottoni, una volta per annuncio e nei limiti giornalieri.
    Non solleva mai. Ritorna True se e' partito."""
    if not FEEDBACK_ATTIVO or not item_id or not _ammesso(str(item_id)):
        return False
    try:
        ctx = {**ctx, "motivo": motivo}
        mid = await telegram_send_con_tastiera(TELEGRAM_OWNER_CHAT_ID, testo_controllo(ctx, url, motivo),
                                               tastiera_giudizio(item_id), reply_to=reply_to, disable_notification=True)
        log.info("FEEDBACK PROPOSTO | item=%s | brand='%s' | motivo=%s | inviato=%s", item_id, ctx.get("brand") or "n/d",
                 str(motivo or "")[:60].replace("|", "/"), bool(mid))
        _contesti[str(item_id)] = ctx
        return bool(mid)
    except Exception:
        log.warning("Controllo autenticita' non proposto:\n%s", traceback.format_exc())
        return False


_contesti = {}   # item_id -> contesto del controllo proposto (per il log del parere)


def _righe_base(msg):
    """Le righe della tastiera del messaggio senza quelle del feedback (restano 'Apri su Vinted' ecc.). Pura."""
    righe = ((msg.get("reply_markup") or {}).get("inline_keyboard") or [])
    return [r for r in righe if not any(str(b.get("callback_data", "")).startswith(("sb|", "sp|", "sn|", "sv|")) for b in r)]


def _url_da_righe(righe):
    for r in righe:
        for b in r:
            if b.get("url") and "/items/" in b["url"]:
                return b["url"]
    return None


def _ctx_item(item_id):
    ctx = dict(_contesti.get(item_id) or {})
    try:
        from bot.tracciamento import _tracc_ctx
        for k, v in (_tracc_ctx.get(item_id) or {}).items():
            ctx.setdefault({"_titolo": "titolo", "_prezzo": "prezzo", "brand_n": "brand"}.get(k, k), v)
    except Exception:
        pass
    return ctx


def tastiera_prezzi_scheda(item_id, fv=None):
    """Prezzi rapidi da mostrare sulla scheda dopo Originale/Non so (come tastiera_prezzo, con 'altro prezzo' a risposta aperta). Pura."""
    righe = [[{"text": b["text"], "callback_data": b["callback_data"].replace("fp|", "sp|", 1)} for b in r]
             for r in tastiera_prezzo(item_id, fv)[:-1]]
    righe.append([{"text": "✍️ Altro prezzo", "callback_data": f"sp|{item_id}|ask"},
                  {"text": "Salta", "callback_data": f"sp|{item_id}|0"}])
    return righe


async def _gestisci_callback_scheda(cq, dati):
    """Bottoni di feedback sotto la scheda/verdetto di un annuncio (sb = giudizio, sp = prezzo)."""
    tipo, item_id, valore = dati
    msg = cq.get("message") or {}
    chat, mid = (msg.get("chat") or {}).get("id"), msg.get("message_id")
    base = _righe_base(msg)
    url = _url_da_righe(base)
    ctx = _ctx_item(item_id)
    stato = lambda t: [[{"text": t, "callback_data": f"sn|{item_id}|x"}, {"text": "↩️ Cambia", "callback_data": f"sb|{item_id}|r"}],
                    [{"text": "📝 Aggiungi nota", "callback_data": f"sp|{item_id}|nota"}]]
    if tipo == "sv":
        valutazione = "giusto" if valore == "g" else "sbagliato"
        registra_verdetto(item_id, valutazione, ctx)
        await telegram_edit_tastiera(chat, mid, base + stato(f"🧠 Verdetto {valutazione}"))
        await telegram_answer_callback(cq.get("id"), f"Registrato: verdetto {valutazione}")
        return
    if tipo == "sb":
        if valore == "r":
            _contesti.setdefault(item_id, {}).pop("_giudizio", None)
            await telegram_edit_tastiera(chat, mid, base + righe_feedback(url or f"/items/{item_id}"))
            await telegram_answer_callback(cq.get("id"))
        elif valore == "f":
            registra_feedback(item_id, "falso", None, "bottone", ctx)
            await telegram_edit_tastiera(chat, mid, base + stato("❌ Registrato: falso"))
            await telegram_answer_callback(cq.get("id"), "Registrato: falso")
        else:
            giudizio = GIUDIZI.get(valore, "originale")
            _contesti.setdefault(item_id, {})["_giudizio"] = giudizio
            await telegram_edit_tastiera(chat, mid, base + tastiera_prezzi_scheda(item_id, ctx.get("fv")))
            await telegram_answer_callback(cq.get("id"), "A che prezzo lo rivenderesti?")
        return
    if valore == "nota":
        await telegram_send_richiesta_prezzo(
            chat, f"📝 Scrivi la tua nota su questo annuncio (es. perche' e' falso, cosa non torna).\n{url or ''}".strip(),
            reply_to=mid, segnaposto="La tua nota")
        await telegram_answer_callback(cq.get("id"), "Scrivi la nota")
        return
    if valore == "ask":
        await telegram_send_richiesta_prezzo(
            chat, f"💶 A che prezzo lo rivenderesti? Scrivi solo il numero (es. 90).\n{url or ''}".strip(), reply_to=mid)
        await telegram_answer_callback(cq.get("id"), "Scrivi il prezzo")
        return
    prezzo = float(valore) or None
    giudizio = (_contesti.get(item_id) or {}).get("_giudizio") or "originale"
    registra_feedback(item_id, giudizio, prezzo, "bottone", ctx)
    await telegram_edit_tastiera(chat, mid, base + stato(f"✅ {giudizio}" + (f" · {prezzo:.0f} €" if prezzo else "")))
    await telegram_answer_callback(cq.get("id"), "Registrato")


async def gestisci_callback(cq):
    """Elabora la pressione di un bottone (dict `callback_query` di Telegram). Non solleva mai."""
    try:
        dati = (cq.get("data") or "").split("|")
        msg = cq.get("message") or {}
        chat, mid = (msg.get("chat") or {}).get("id"), msg.get("message_id")
        if len(dati) == 3 and dati[0] in ("sb", "sp", "sv"):
            await _gestisci_callback_scheda(cq, dati)
            return
        if len(dati) != 3 or dati[0] not in ("fb", "fp"):
            await telegram_answer_callback(cq.get("id"))
            return
        tipo, item_id, valore = dati
        ctx = _contesti.get(item_id, {})
        base = _base_testo(msg.get("text") or "")
        if tipo == "fb":
            giudizio = GIUDIZI.get(valore)
            if giudizio == "falso":
                registra_feedback(item_id, "falso", None, "bottone", ctx)
                await telegram_edit_con_tastiera(chat, mid, f"{base}\n❌ Registrato: falso", [])
                await telegram_answer_callback(cq.get("id"), "Registrato: falso")
            else:
                _contesti.setdefault(item_id, {})["_giudizio"] = giudizio
                await telegram_edit_con_tastiera(chat, mid, f"{base}\n{'✅ Originale' if giudizio == 'originale' else '❓ Non so'} · a che prezzo lo rivenderesti?",
                                                 tastiera_prezzo(item_id, ctx.get("fv")))
                await telegram_answer_callback(cq.get("id"))
        else:
            prezzo = float(valore) or None
            giudizio = (_contesti.get(item_id) or {}).get("_giudizio") or "originale"
            registra_feedback(item_id, giudizio, prezzo, "bottone", ctx)
            await telegram_edit_con_tastiera(chat, mid, f"{base}\n✅ Registrato: {giudizio}" + (f" · atteso {prezzo:.0f} €" if prezzo else ""), [])
            await telegram_answer_callback(cq.get("id"), "Registrato")
    except Exception:
        log.warning("Pressione bottone non elaborata:\n%s", traceback.format_exc())


async def ciclo_callback():
    """Legge le pressioni dei bottoni (long polling su getUpdates). Si ferma da solo se un altro processo legge gli stessi aggiornamenti."""
    if not FEEDBACK_ATTIVO:
        return
    offset = None
    while True:
        aggiornamenti, esito = await telegram_get_updates(offset)
        if esito == "conflitto":
            log.warning("FEEDBACK | getUpdates in conflitto con un altro lettore: pausa di 5 minuti")
            await asyncio.sleep(300)
            continue
        if esito == "errore":
            await asyncio.sleep(10)
            continue
        for u in aggiornamenti:
            offset = (u.get("update_id") or 0) + 1
            if u.get("callback_query"):
                await gestisci_callback(u["callback_query"])
