# Ricerche dei tracker

**Scopo**: aggiungere, cambiare o togliere ricerche nei due tracker senza rumore e senza perdere annunci.

**Input**: cosa cercare (brand/modello/categoria), tracker (moda `vinted-notifications` o radar `vinted-radar`), eventuale prezzo.

**Passi**
1. Leggere le ricerche attuali: GET `/queries` del tracker (id in `/update_query/<id>`).
2. Costruire l'URL `https://www.vinted.it/catalog?...` (Claude costruisce l'URL, non lo visita): `search_text`, `catalog[]` (id letti dai log `RADAR |` `catalogo=`), `brand_ids[]` se il brand esiste su Vinted (LEGO 89162, Persol 12775, Artemide 1078857, Coach 6721), `price_to`, `currency=EUR`, `order=newest_first`.
3. Prezzi: `price_to` circa meta' della rivendita veloce (ROI >= 100%); niente `price_from` (8/10, richiesta dell'utente): un modello che vale messo a 5 EUR per sbaglio e' l'affare; nel radar sotto `RADAR_PREZZO_MIN` (10 EUR) passa solo un modello noto della matrice con buy max.
4. POST `/update_query/<id>` (campi `query`, `query_name`; radar con nome "R ...") o `/add_query`.
5. Verifica dopo un giro (15-60 s): log del tracker `"for query N:"` con id recenti (~10.28 miliardi a ottobre 2026). Id vecchi = filtro sbagliato (es. brand Nintendo nei videogiochi): togliere quel filtro.
6. Aggiornare `STATO.md` con le ricerche.

**Formato**: tabella ricerca / filtri / prezzi; cosa e' stato tolto e perche'; esito della verifica.

**Esempio reale (7/10 16:25)**: LEGO con catalogo 1767 + brand 89162, 25-80 EUR; lampade con cataloghi 3836, 3862, 3839; tolti Alessi, Audeze, "lampada vintage"; le ricerche Nintendo con brand davano solo annunci di anni fa -> tolto il brand, tenuto il catalogo 3026.

**Controllo finale**
- [ ] Ogni ricerca restituisce annunci recenti?
- [ ] Prezzi coerenti con margine 50 EUR e ROI 100%?
- [ ] La moda non e' stata toccata (se il lavoro era sul radar)?
