# Come leggere i log senza sprecare token

Spostato da `CLAUDE.md` il 7/10. Regole 1-2 e 5-6 restano riassunte in `CLAUDE.md`.

I log sono enormi. Regole:
1. Filtrare SEMPRE con `filter` e finestre di tempo strette (`startDate`), `limit` basso (20-40) per controlli puntuali.
2. Per analisi su ore: `limit` 500 e il risultato finisce in un file; elaborarlo con `python3`/`jq`, non leggerlo a mano.
   - Il risultato viene salvato in un file SOLO se supera circa 80.000 caratteri; altrimenti arriva inline nella conversazione (costoso e impossibile da elaborare con uno script). Per averlo sempre in file, allargare il filtro: per esempio `"| ESITO |" OR "classe=AFFARE" OR "classe=MEDIO AFFARE" OR "classe=NORMALE" OR "classe=NON AFFARE"` su finestre di 3-6 ore (una finestra notturna con poche righe resta comunque piccola: in quel caso aggiungere anche `"PANEL |"` oppure accorpare notte e sera in una finestra piu' larga).
   - Mai incollare a mano nello script righe lette in conversazione: se serve un conteggio esatto, rifare la richiesta con il filtro allargato.
3. Cercare per id annuncio: `filter` con l'id tra virgolette.
4. Filtri utili (parole esatte nei log):
   - esiti per annuncio: `"| ESITO |"`; saltati senza messaggio: `"SKIP non inviato"`
   - errori: `Traceback`, `"Markdown fallita"`, `"FALLITA"`
   - modelli: `"GEMINI_USO"`, `"RISERVA |"`, `"PANEL |"`, `"PANEL HTTP"`
   - vendite rapide: `"RICONTROLLO LAMPO"`; preavviso push (una riga per annuncio, con semaforo, regola e caratteristiche: categoria, condizione, materiale, taglia, lingua, n. foto, venditore, ora): `"PREAVVISO |"`; tempi del preavviso (pubblicazione -> telegram -> preavviso, secondi di invio): `"PREAVVISO_INVIATO |"`; le righe `RICONTROLLO LAMPO` e `PREAVVISO` portano i `preferiti` letti dalla pagina; `PREAVVISO` ha anche `fonte_cat` (titolo, descrizione, catalogo o nessuna); le righe `ESITO` portano `item=` per incrociarle con `PREAVVISO` e `RICONTROLLO LAMPO`
   - banda proxy: `"RIEPILOGO BANDA"`
   - radar fase 0: `"RADAR |"` (visitati), `"RADAR SCARTO |"` (scartati al livello 1), `"MESSAGGIO RADAR"`; i ricontrolli radar hanno `esito=RADAR_L1_*` nelle righe `RICONTROLLO LAMPO` (da tenere fuori dal recap moda)
5. Dopo un deploy controllare solo righe successive all'avvio (`"Vinted Oracle avviato"` riporta la versione).
6. Se non arrivano annunci analizzati (traffico basso, es. sabato sera) dirlo e aspettare, non rileggere in loop.
