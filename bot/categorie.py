"""Modulo estratto da main_telethon.py (spostamento meccanico)."""
import re


from bot.costanti import CATEGORIA_KEYWORDS, MATERIALI_PREGIATI_PRIORITA, MATERIALI_TRADUZIONI
# ---- fine import ----
def scegli_materiale_per_ricerca(material_value_raw):
    if not material_value_raw:
        return None
    testo_lower = material_value_raw.lower()
    materiali_annuncio = [m.strip() for m in testo_lower.split(",")]

    for materiale_prioritario in MATERIALI_PREGIATI_PRIORITA:
        if any(materiale_prioritario in elemento for elemento in materiali_annuncio):
            return materiale_prioritario

    for termine_straniero, termine_it in MATERIALI_TRADUZIONI.items():
        if re.search(r'\b' + re.escape(termine_straniero) + r'\b', testo_lower):
            return termine_it

    return None


def estrai_categoria_da_titolo(titolo, descrizione=None):
    """Trova la categoria del capo cercando tutte le keyword multilingua nel
    titolo (e, se fornita, nella descrizione), e sceglie quella con il match
    PIU' LUNGO/specifico -- non la prima trovata nell'ordine del dizionario.
    Necessario perche' altrimenti keyword generiche possono "vincere" per
    errore su keyword piu' specifiche che le contengono come sottostringa:
    es. "shirt" (categoria camicia) e' una sottostringa di "t-shirt"
    (categoria t-shirt), quindi con un semplice "primo match" un titolo come
    "T shirt uomo" veniva categorizzato come camicia invece che t-shirt,
    portando a comp di camicie eleganti al posto di magliette basic -- due
    fasce di prezzo completamente diverse.

    La descrizione e' stata aggiunta il 2026-09-19 dopo un caso reale (The
    Row "Ophelia", maglione da oltre 800 EUR di listino) in cui il titolo
    dell'annuncio era solo il nome del modello, senza nessuna parola che
    indicasse il tipo di capo -- la categoria restava "non rilevata" e
    Vestiaire/eBay venivano saltati del tutto, anche se la descrizione
    conteneva "sweater"/"maglione" e l'occhio/cervello lo scoprivano comunque
    in ricerca on-demand, troppo tardi per alimentare la rete di sicurezza
    sui comp.

    Estendere il match alla descrizione (testo libero, molto piu' lungo del
    titolo) ha reso subito evidente in test un bug gia' latente ma raro sul
    solo titolo: alcune keyword corte in CATEGORIA_KEYWORDS sono sottostringhe
    di parole italiane comunissime -- "cap" (cappello) dentro "capo",
    "top" (canotta) dentro "soprattutto", "rock" (gonna) dentro "barocco",
    ecc. Un semplice `in` le faceva scattare per errore su descrizioni
    discorsive. Risolto usando confini di parola (\\b) invece di sottostringa
    libera, mantenendo intatta la logica "match piu' lungo vince" (che
    resta necessaria per casi come "t-shirt" vs "shirt", dove entrambe le
    keyword rispettano il confine di parola).

    IMPORTANTE (bug trovato in test il 2026-09-19, stesso giorno
    dell'estensione alla descrizione): concatenare titolo e descrizione in
    un unico testo prima di cercare il match piu' lungo dava PRIORITA'
    ALLA LUNGHEZZA DELLA KEYWORD invece che alla fonte. Caso reale: annuncio
    "Gilet Max Mara elegante", descrizione "da abbinare con una camicia
    bianca sotto" -- "camicia" (7 char, ma e' solo un capo da ABBINAMENTO
    citato nella descrizione) batteva "gilet" (5 char, ma e' il capo
    IN VENDITA, dichiarato nel titolo dal venditore). Il titolo e' un
    segnale molto piu' affidabile di cosa sia il capo della descrizione
    (che spesso menziona altri capi solo come contesto di stile). Per
    questo ora si cerca PRIMA solo nel titolo, e si usa la descrizione
    SOLO come fallback quando il titolo non da' nessun match -- niente
    piu' concatenazione con pari peso tra le due fonti."""
    migliore_dal_titolo = _cerca_categoria_in_testo(titolo)
    if migliore_dal_titolo:
        return migliore_dal_titolo
    return _cerca_categoria_in_testo(descrizione)


def _cerca_categoria_in_testo(testo):
    """Cerca la categoria con match piu' lungo/specifico in UN SOLO testo
    (vedi estrai_categoria_da_titolo per il perche' titolo e descrizione
    non vengono piu' concatenati)."""
    if not testo:
        return None
    testo_lower = testo.lower()
    migliore_categoria = None
    migliore_lunghezza = 0
    for categoria_it, parole_chiave in CATEGORIA_KEYWORDS.items():
        for parola in parole_chiave:
            if len(parola) <= migliore_lunghezza:
                continue
            if re.search(r'\b' + re.escape(parola) + r'\b', testo_lower):
                migliore_categoria = categoria_it
                migliore_lunghezza = len(parola)
    return migliore_categoria
