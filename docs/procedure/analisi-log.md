# Analisi dei log

**Scopo**: rispondere con numeri a una domanda sul bot ("come sta andando?", "c'e' valore?", modello in uso, errori, tempi, costo) senza riempire la conversazione.

**Input**: domanda, periodo (default: dall'ultimo cambio rilevante o ultime 24 h), moda o radar. Progetto `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`, worker `7f856e1e-dad7-4798-90de-ac6ca77e5756`; parole esatte dei log in `docs/log.md`.

**Passi**
1. Controllo puntuale: `filter` stretto, `startDate` vicino, `limit` 20-40. Annuncio singolo: l'id tra virgolette. Dopo un deploy: solo righe dopo `"Vinted Oracle avviato"`.
2. Analisi su ore: filtro largo (es. `"| ESITO |" OR "RICONTROLLO LAMPO"`), finestre di 3-6 h, `limit` 500 (finisce in file solo oltre ~80.000 caratteri). Controllare primo e ultimo timestamp: se il limite taglia, scaricare altre finestre. Moda: seguire `docs/recap.md`.
3. Radar, ARCHIVIO PERMANENTE (6/11, richiesta dell'utente: niente richieste inline ai log): ogni serie chiusa del radar e' salvata nel DB sul volume `/data` come evento `tracciato_radar` (stessi campi della riga `TRACCIATO_RADAR`, piu' `storia`). Lettura: `db.leggi_eventi("tracciato_radar", dal_ts)`; funzioni in `bot/archivio_radar.py`; comando Telegram dell'utente `/esporta_radar [giorni]` invia il CSV di tutti i casi e scrive nei log una riga `RIEPILOGO RICERCHE` per ricerca (annunci, validi, venduti entro 1 h, gialli/verdi). Le analisi per ricerca partono da qui; i log restano per i controlli puntuali. Prima del 6/11 sera gli esiti sono solo nei log.
   Radar (log): `"RADAR | item"` (promossi), `"esito=RADAR_L1" AND "stato=venduto"` (vendite), `"RADAR SCARTO"` (scarti). Con python: promossi per modulo, brand, catalogo, prezzo mediano; venduti ed entro 15 min per modulo; venduti rapidi con prezzo >= 25 EUR.
4. Elaborare i file con `python3 -I`, mai incollare righe a mano; per un conteggio esatto rifare la richiesta.
5. Banda: `consumi.md`. Se volume o banda sono fuori misura, correggere subito e dirlo.
6. Traffico basso: dirlo e aspettare, non rileggere in loop.

**Velocita' di vendita (7/11, richiesta dell'utente: tutti i dati, pochi token)**: la tabella `bot/dati/velocita.json` NON si aggiorna piu' dai log. Il worker legge l'archivio `tracciato` del DB (volume /data), la aggiorna da solo ogni 23 h (`ciclo_velocita`, decadimento 0,97) e salva su `/data/velocita.json` (ha la precedenza su quella del repo; `VELOCITA_APPRESA_FILE`). Riga di controllo nei log: `VELOCITA AGGIORNATA`; comando Telegram dell'utente `/velocita` per aggiornare subito. `tools/aggiorna_velocita.py` resta per i log vecchi.

**Dati strutturati (9/11)**: dopo `carica`, la tabella `annunci` ha UNA riga per annuncio e ogni campo di `TRACCIATO` e' una colonna (esito, semaforo, prezzo, Jev `jev_*`, `legit_jev`, vendita `stato`/`venduto_s`...). Una domanda nuova = `sql "SELECT ... FROM annunci ..."`, mai righe di log a mano. Se manca un dato, va aggiunto alla riga `TRACCIATO` (`_contesto_tracciato`), non cercato in altre righe.

**Strumento fisso (6/11): `tools/log_dati.py`**. I log si leggono UNA volta in un database locale e il recap esce con un comando, senza righe di log nella conversazione: (1) get-logs con filtro largo (`"TRACCIATO" OR "MODA JEV" OR "GEMINI_USO" OR "Gemini TIMEOUT"`), `limit` 500, finestre di 4-6 h: oltre ~80.000 caratteri Railway salva il file e nella conversazione compare solo il percorso; (2) `python3 tools/log_dati.py carica FILE...` (doppioni ignorati); (3) `python3 tools/log_dati.py riepilogo [--dal 2026-11-05T06:00]`: annunci, ciechi, veloci per semaforo e per esito Jev (confronto confermati/scartati), esiti Jev, Gemini per modello (n, p50, p90, ritentati, timeout); (4) domande nuove con `sql "SELECT ..."` sulle tabelle `tracciato`, `gemini_uso`, `gemini_timeout`, `jev`. Se una finestra torna inline (troppo stretta) allargare il filtro o la finestra invece di leggerla.

**Formato**: una frase di sintesi; finestra e filtro dichiarati; tabella o 3-6 righe di numeri; esempi concreti; problemi e cosa e' gia' stato fatto; prossimi passi (max 3). Campione piccolo: dirlo.

**Esempi reali (7/10)**
- Radar 12:54-16:18 UTC: 957 promossi su ~1250; ~20 GB/giorno di proxy -> corretto subito (prezzo minimo, ricontrolli 3 invece di 6). Valore: LEGO Star Wars/Technic con numero di set (Imperial Star Destroyer 75 EUR gia' venduto alla prima lettura); Alessi e minifigure vendono ma a 5-20 EUR.

**Controllo finale**
- [ ] Periodo coperto per intero (o detto cosa manca)?
- [ ] Numeri da script su file, non letti a occhio?
- [ ] Nessuna credenziale riportata (le righe `proxy_used=` dei tracker vecchi ne stampavano)?
- [ ] Stime dichiarate come stime?
