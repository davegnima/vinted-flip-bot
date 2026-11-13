# Dal tracker al motore di arbitraggio (direzione dell'utente, 01/11)

Obiettivo: non trovare "annunci economici", ma **inefficienze di prezzo**: il venditore non ha valorizzato il prodotto e la domanda paga molto di piu'. Il prezzo basso e' solo un sintomo, non il criterio.

## Definizione operativa (misurabile)
Un annuncio e' un'inefficienza se, per la sua identita' di prodotto:
1. **Prezzo atteso** (p25 dei comparabili verificati, costo totale con spedizione) supera il costo di almeno 50 EUR e ROI >= 100%.
2. **Il prezzo richiesto e' fuori distribuzione** (distanza dalla mediana dei comparabili in scarti robusti, non solo "sotto la soglia").
3. **Esiste domanda**: prova osservata (annunci simili venduti entro 1 h / 24 h dal tracciamento), non supposta.
4. **Non e' un difetto travestito**: Jev (stato, completezza, replica, ricambio).
Il punto 3 e' oggi il piu' debole: si misura con `TRACCIATO_RADAR` e `operazioni`, mai inventato (regola 16).

## Tre stadi
| Stadio | Cosa guarda | Stato |
|---|---|---|
| A. Parole chiave e marche | ricerche del tracker + matrice modelli (`radar_matrice`) | fatto (radar v1/v2) |
| B. Categoria, caratteristiche, identita' | `catalog[]` + `product_identity` + comparabili verificati da Jev; la distribuzione di prezzo e' per identita', non per parola | in corso (tappe 1-5, PR 254-262) |
| C. Anomalie automatiche | feed larghi per categoria, raggruppati per identita'; si segnalano i punti fuori distribuzione anche su prodotti mai elencati | da costruire |

## Piano dello stadio C (una PR per passo, CI verde, STATO.md a ogni passo)
1. **Misura offline (solo letture, zero banda in piu')**: `tools/radar_liste/anomalie.py` legge gli eventi `radar_v2` e `TRACCIATO_RADAR` gia' nel DB, raggruppa per identita' (marca, categoria, modello normalizzato) e calcola: distribuzione prezzi, annunci fuori distribuzione, quota venduta entro 1 h. Risponde a: quali prodotti NON in lista avevano gia' prodotto anomalie vere e vendute in fretta? Sono le candidate a diventare ricerche.
2. **Scoperta**: lista di prodotti candidati (identita' con >= N anomalie vendute veloci) proposta come nuove ricerche tracker con `price_to` e `catalog[]`, caricate con `v2_ricerche.py --aggiungi` (regole 1 e 10), una categoria alla volta, `RIEPILOGO BANDA` a ogni lotto (regola 12).
3. **Feed per categoria senza parola chiave** (solo categorie ad alto valore, tetto per categoria): ogni annuncio nuovo e' confrontato con la distribuzione in cache dell'identita' (cache persistente nel DB, TTL 7-14 giorni, solo con >= 6 comparabili verificati); fuori distribuzione + prezzo <= tetto -> candidato. Niente richiesta di catalogo per ogni annuncio (e' la causa dei consumi alti).
4. **Punteggio di anomalia** (z robusto su mediana/MAD) affiancato al margine; Jev solo sui candidati. Soglia tarata sui venduti veloci, non a priori.
5. **Ciclo di apprendimento**: i venduti veloci e le risposte nel gruppo aggiornano le soglie e la lista dei prodotti; i falsi alimentano `RADAR AUDIT`.

## Vincoli
Niente Gemini nel non moda (solo Jev, 20 EUR/mese dal 1/11); banda sotto ~30 GB/giorno (1 TB/mese dal 1/11); io non visito vinted.it (regola 7): i dati arrivano dal bot; nessun numero stimato senza dichiararlo.

## Metriche di successo
Quota di affari veri tra gli avvisi (venduti entro 1 h senza falso), prodotti scoperti fuori lista che diventano ricerche, tempo dal messaggio all'avviso, MB/min.
