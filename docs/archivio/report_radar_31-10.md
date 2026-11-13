# Report radar non moda, 31/10 (dati dai log, solo letture)

## Risultato in una frase
Il radar e' pulito e leggero in banda (circa 1,7 GB/giorno, minimo stimato), ma ancora non dimostra di trovare affari: su 1.702 verdetti solo 62 verdi e 86 gialli, nessuna conferma di vendita veloce e nessun invio alla chat "Annunci cervello" ancora osservato.

## Copertura e affidabilita'
- Finestra: 12:58-20:28 UTC del 31/10 (circa 7,5 h, V2 acceso alle 12:16). Non sono le 24 h previste. Campione grande per i conteggi dei semafori, piccolo per ogni singola ricerca.
- Banda: finestra 23,7 h, ma 19 riavvii azzerano il contatore, quindi 1,7 GB/giorno e' una stima MINIMA (altri campioni di oggi: 3,1-6 GB/giorno). Tenere il tetto di 8 GB/giorno come riferimento.
- TRACCIATO_RADAR, RADAR PRIVATO/FOTO ed errori Telegram: nessuna riga trovata. Non significa che non ci siano stati, ma che non sono nel set letto.

## Numeri
- Semafori: rosso 1.554 (91%), giallo 86 (5%), verde 62 (4%).
- Motivi dei rossi: margine_basso 1.012, pochi_comparabili 453, sopra_riferimento 72, roi_basso 17.
- Jev (1.631 giudizi): affare_vero 678, non_affare 673, falso_o_ricambio 280.
- Disaccordo semaforo/Jev: 26 gialli su 86 (30%) e 12 verdi su 62 (19%) avrebbero un declassamento. E' disaccordo tra due modelli, non un falso confermato.
- Traffico: catalogo_comp 50% (434 KB a richiesta), pagina_annuncio 41% (267 KB).

## Ricerche
- Rendono (verdi/gialli sul totale): Console 31/234, V2 dji 14/34, V2 gopro 8/55, V2 3ds 6/14, V2 switch 6/76, V2 dyson 7/53, V2 dewalt 5/24.
- Rumorose, zero gialli e verdi: V2 games workshop (99 rossi), V2 posate in set (35), V2 alessi (34), V2 rosenthal (18), V2 iittala (17), V2 fujifilm (20), V2 leica (12), V2 kitchenaid (10), V2 thermomix (10).
- Quasi inutili: Fotocamere pellicola (111 rossi, 2 gialli), V2 sony cuffie (48 rossi, 1 verde), V2 smeg (47/1), V2 le creuset (44/1), V2 makita (33/1).
- Dove Jev contraddice di piu': Console (8 falso_o_ricambio su 31), V2 dji (6 su 14), V2 switch (5 su 6), V2 bugaboo (3 su 6).

## Cosa cambiare per completare il piano (per impatto)
1. **Conferma dell'invio in chat.** Aspettare il primo giallo/verde dopo il deploy della PR 239 e verificare `RADAR PRIVATO`. Controllo gia' programmato (21:10 UTC).
2. **Potare le ricerche a zero resa** (games workshop, posate in set, alessi, rosenthal, iittala, fujifilm, leica, kitchenaid, thermomix): meno traffico e meno rumore. Tenerle solo se si trova una categoria piu' stretta. Sicurezza: media, campione di 7,5 h.
3. **Stringere le quasi inutili** (Fotocamere pellicola, sony cuffie, smeg, le creuset, makita) con `catalog[]` solo se visto nei log; altrimenti pausa.
4. **Misurare gli affari veri.** Oggi `TRACCIATO_RADAR` non compare: verificare che il tracciamento dei gialli e verdi del radar sia attivo, altrimenti la % di affare (obiettivo 3) resta non misurabile.
5. **Log del catalogo nella riga V2.** Le righe V2 non stampano `catalog[]`: senza questo non si ricavano gli id per Smeg, Venini, Festool, KitchenAid. Aggiungere `catalogo=` alla riga (modifica piccola, a costo zero di rete).
6. **Regola Jev (dopo 24 h di ombra).** Applicare solo il declassamento (mai alzare un rosso) di verdi e gialli con non_affare o falso_o_ricambio; valutare prima i venduti veloci. Ricerche con piu' disaccordo: Console, dji, switch, bugaboo.
7. **Filtri anti-falsi.** Scatola/Verpackung/"keine Konsole" in `e_un_pezzo`; falsi gialli noti (Pin's TF1, Verslife non Dyson, Garmin cinturini con id 3032 da non usare).
8. **Pavimento deterministico e filtro appreso.** Rivendita p25 < prezzo + 50 gia' rosso al prefiltro; il filtro appreso conta anche rivendita bassa (1.012 rossi per margine_basso sono quasi tutti scartabili prima di scaricare i comparabili: risparmio di banda).
9. **Documenti.** `CLAUDE.md` regole 6 e 10, `STATO.md`, `docs/procedure/ricerche-tracker.md`.

## Limiti
- Nessun numero qui stima vendite o margini reali: sono verdetti del bot, non esiti di vendita.
- Le righe 12:16-12:58 non sono nei conteggi.
