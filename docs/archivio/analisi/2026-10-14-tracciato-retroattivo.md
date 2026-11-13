# Recap 8-13/10 con il verdetto recuperato (14/10)

Dati: 3765 righe TRACCIATO dell'8-13/10 (log salvati nei recap). 92 righe di annunci venduti non avevano l'esito del bot
(venduti in 15-60 s, prima della fine del Cervello). Recuperato dai log `ESITO |` e `PREAVVISO |` per numero annuncio:
85 su 92. Gli altri 7 non hanno mai avuto un verdetto: analisi interrotta da un riavvio del worker (deploy) a meta' strada.

## Prima / dopo (venduti entro 15 min = "veloci", 665 annunci)

| | prima | dopo |
|---|---|---|
| veloci senza esito | 88 (13%) | 3 (0%) |
| COMPRA tra i veloci | 103 (15%) | 137 (20%) |
| CHIEDI FOTO tra i veloci | 76 (11%) | 91 (13%) |
| TRATTA tra i veloci | 70 (10%) | 84 (12%) |
| NON COMPRARE tra i veloci | 100 (15%) | 115 (17%) |
| COMPRA venduti entro 15 min | 33% | 40% |
| COMPRA venduti entro 1 h | 52% | 57% |
| semaforo 🟢 tra i veloci | 265 | 321 |

## Semaforo e velocita' (dati completi)

| semaforo | annunci | venduti entro 15 min | entro 60 s | COMPRA venduti entro 15 min |
|---|---|---|---|---|
| 🟢 | 846 | 36% | 13% | 51% (136) |
| 🟡 | 833 | 18% | 5% | 32% (115) |
| 🔴 | 1849 | 8% | 2% | 15% (88) |

Venduti entro 60 s: 190. Con preavviso 114 (60%); senza: 36 🔴, 24 🟡, 14 🟢.

## Per fascia di prezzo

| prezzo | annunci | entro 15 min | entro 60 s | COMPRA entro 15 min |
|---|---|---|---|---|
| <=10 | 281 | 43% | 14% | 59% (44) |
| 10-20 | 563 | 28% | 9% | 37% (106) |
| 20-35 | 1022 | 15% | 5% | 26% (113) |
| 35-50 | 779 | 13% | 3% | 31% (42) |
| >50 | 1120 | 8% | 2% | 37% (35) |

## Brand: COMPRA venduti entro 15 min

Alti: Vivienne Westwood 90% (10), Loro Piana 87% (15), Prada 49% (45), Miu Miu 50% (6), Courreges 47% (17).
Bassi: Marni 11% (19), Loewe 14% (22), Dries 12% (8), Rick Owens 0% (3), Undercover 0% (3), Fendi 0% (7).
Brand tolti il 13/10 (Acne, Fendi, Zegna, Toteme): venduti entro 15 min 5%, 6%, 6%, 2%: la scelta regge.

Limite: "venduto in fretta" non vuol dire "margine >= 50 EUR" (il margine reale non si misura); campioni per brand piccoli.
