# Analisi brand, semaforo, prezzi e radar (dati dell'8/10, 9/10 mattina)

Fonte: righe `TRACCIATO` (645 annunci moda, 578 con esito chiaro, 67 spariti a parte) e `TRACCIATO_RADAR` (1.130, 983 con esito) del worker, 8/10 07:00-22:00 UTC. UN SOLO GIORNO: con n < 30 per brand l'errore e' di +-10 punti o piu'. Veloce = venduto o prenotato entro 15 min.

## Semaforo, Cervello, velocita' (390 annunci con verdetto del Cervello, 56 veloci)
| Regola | Segnalati | Veloci presi | Recall | Precisione |
|---|---|---|---|---|
| solo 🟢 | 45 | 20 | 36% | 44% |
| 🟢 + 🟡 | 164 | 35 | 62% | 21% |
| Cervello COMPRA/TRATTA/CHIEDI | 204 | 44 | 79% | 22% |
| Cervello solo COMPRA | 57 | 15 | 27% | 26% |
| 🟢 E Cervello positivo | 34 | 19 | 34% | 56% |
Semaforo corretto: 🟢 40% veloci (n 80), 🟡 15% (165), 🔴 9% (282); d'origine 31% / 21% / 9%. La tabella di velocita' usata il 8/10 era costruita col 7/10, quindi i numeri sono fuori campione.
Accordo 🟢/Cervello: 54% (poco piu' del caso).

## Prezzo (moda)
| Fascia | n | veloci | venduti 1 h | COMPRA/TRATTA | qualificanti (margine >= 50, ROI >= 100) | di cui veloci / venduti |
|---|---|---|---|---|---|---|
| 0-20 | 70 | 36% | 46% | 17 | 4 | 2 / 2 |
| 20-35 | 159 | 15% | 32% | 57 | 8 | 1 / 5 |
| 35-50 | 112 | 19% | 30% | 40 | 7 | 0 / 4 |
| 50-75 | 135 | 13% | 19% | 46 | 7 | 4 / 5 |
| 75+ | 102 | 7% | 13% | 22 | 3 | 1 / 1 |
Qualificanti totali 29: 17 venduti in 1 h, 8 veloci. Margine stimato dal Cervello: 1.313 EUR sui venduti, 924 sugli invenduti (stime, non incassi).
Ricerche moda (price_to): q1 35 (Missoni, Vivienne Westwood, Jean Paul Gaultier, Marni, Miu Miu), q2 75 (Max Mara e altri), q3 50, q4 120 (Prada, Loro Piana, Cucinelli, Acne, Fendi, Loewe), q5 60. Mappa dedotta dai prezzi massimi osservati per brand.

## Brand (moda, n >= 14)
| Brand | n | veloci | venduti | qualificanti (veloci) | Nota |
|---|---|---|---|---|---|
| Max Mara | 114 | 9% | 17% | 4 (0) | rosso salta il Cervello dal 9/10 |
| Prada | 104 | 25% | 34% | 5 (4) | sopra 50 EUR: 13/75 veloci, 4 qualificanti veloci |
| Loro Piana | 44 | 16% | 32% | 1 (1) | sotto 25 EUR 7/11 veloci; sopra 25 EUR 0/33 |
| Missoni | 37 | 14% | 27% | 0 | resta (regola utente) |
| Cucinelli | 37 | 22% | 35% | 0 | |
| Acne Studios | 36 | 8% | 8% | 2 (2) | 29 su 36 sopra 50 EUR |
| Zegna | 24 | 4% | 4% | 0 | candidato a uscire |
| Courreges | 22 | 9% | 23% | 0 | candidato a uscire |
| Fendi | 20 | 15% | 20% | 1 (0) | 17% spariti |
| Jacquemus | 18 | 11% | 22% | 0 | |
| Jean Paul Gaultier | 17 | 47% | 71% | 0 | veloce ma margini piccoli |
| Miu Miu | 16 | 38% | 38% | 1 (1) | 24% spariti |
| Marni | 14 | 7% | 29% | 2 (0) | |
| Vivienne Westwood | 13 | 46% | 62% | 0 | veloce ma margini piccoli |
Loewe: 17 annunci, 12 spariti (71%); dei 5 rimasti 2 qualificanti, entrambi venduti in 1 h.

## Radar (983 annunci, 56 veloci = 5,7%; venduti in 1 h 9,9%)
| Modulo | n | veloci | spariti |
|---|---|---|---|
| lego | 468 | 6,8% | 44 |
| console_retro | 116 | 8,6% | 9 |
| borse_vintage | 124 | 7,3% | 36 (22%) |
| occhiali | 81 | 4,9% | 2 |
| illuminazione_design | 55 | 0% | 8 |
| fotografia | 40 | 2,5% | 13 |
| audio, collezionismo, ceramiche, golf, argento, bijoux | 99 | 0% | 11 |
Per fascia di prezzo il tasso e' piatto (5-8%); LEGO 30-40 EUR 9,8%, 40-50 EUR 4,5%. Il radar non manda messaggi (fase 0): la vendita in 1 h non misura il valore delle nicchie lente (lampade, audio).

## Notifica
Mediana messaggio -> notifica circa 18 s. Dei 154 venduti, 23 in <= 60 s e 58 in <= 5 min.
