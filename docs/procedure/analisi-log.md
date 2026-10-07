# Analisi dei log

**Scopo**: rispondere con numeri a una domanda sul bot ("come sta andando?", "c'e' valore?", modello in uso, errori, tempi, costo) senza riempire la conversazione.

**Input**: domanda, periodo (default: dall'ultimo cambio rilevante o ultime 24 h), moda o radar. Progetto `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`, worker `7f856e1e-dad7-4798-90de-ac6ca77e5756`; parole esatte dei log in `docs/log.md`.

**Passi**
1. Controllo puntuale: `filter` stretto, `startDate` vicino, `limit` 20-40. Annuncio singolo: l'id tra virgolette. Dopo un deploy: solo righe dopo `"Vinted Oracle avviato"`.
2. Analisi su ore: filtro largo (es. `"| ESITO |" OR "RICONTROLLO LAMPO"`), finestre di 3-6 h, `limit` 500 (finisce in file solo oltre ~80.000 caratteri). Controllare primo e ultimo timestamp: se il limite taglia, scaricare altre finestre. Moda: seguire `docs/recap.md`.
3. Radar: `"RADAR | item"` (promossi), `"esito=RADAR_L1" AND "stato=venduto"` (vendite), `"RADAR SCARTO"` (scarti). Con python: promossi per modulo, brand, catalogo, prezzo mediano; venduti ed entro 15 min per modulo; venduti rapidi con prezzo >= 25 EUR.
4. Elaborare i file con `python3 -I`, mai incollare righe a mano; per un conteggio esatto rifare la richiesta.
5. Banda: `consumi.md`. Se volume o banda sono fuori misura, correggere subito e dirlo.
6. Traffico basso: dirlo e aspettare, non rileggere in loop.

**Formato**: una frase di sintesi; finestra e filtro dichiarati; tabella o 3-6 righe di numeri; esempi concreti; problemi e cosa e' gia' stato fatto; prossimi passi (max 3). Campione piccolo: dirlo.

**Esempi reali (7/10)**
- "La chiave a pagamento e' attiva?": filtro `"Riserva a pagamento" OR "PAGAMENTO"`, `limit` 5 -> `Riserva a pagamento ATTIVA`, 16 richieste fino alle 15:10 UTC.
- Radar 12:54-16:18 UTC: 957 promossi su ~1250; ~20 GB/giorno di proxy -> corretto subito (prezzo minimo, ricontrolli 3 invece di 6). Valore: LEGO Star Wars/Technic con numero di set (Imperial Star Destroyer 75 EUR gia' venduto alla prima lettura); Alessi e minifigure vendono ma a 5-20 EUR.

**Controllo finale**
- [ ] Periodo coperto per intero (o detto cosa manca)?
- [ ] Numeri da script su file, non letti a occhio?
- [ ] Nessuna credenziale riportata (le righe `proxy_used=` dei tracker vecchi ne stampavano)?
- [ ] Stime dichiarate come stime?
