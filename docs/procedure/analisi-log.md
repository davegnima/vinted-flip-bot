# Analisi dei log

**Scopo**: rispondere a "come sta andando? c'e' valore?" con numeri, per moda o radar.

**Input**: periodo (default: dall'ultimo cambio rilevante o ultime 24 h), moda o radar. Se manca, chiedere solo il periodo.

**Passi**
1. Regole di lettura: `docs/log.md` (filtri larghi, `limit` 500, file + python). Per la moda seguire `docs/recap.md`.
2. Radar: scaricare `"RADAR | item"` a finestre finche' copre tutto il periodo (controllare primo e ultimo timestamp); vendite con `"esito=RADAR_L1" AND "stato=venduto"`; scarti con `"RADAR SCARTO"`.
3. Con python: promossi per modulo, brand, catalogo, prezzo mediano; venduti ed entro 15 min per modulo; venduti rapidi con prezzo >= 25 EUR (titolo, prezzo, secondi).
4. Banda: ultima riga `RIEPILOGO BANDA` (MB dall'avvio / ore) -> GB al giorno.
5. Se il volume o la banda sono fuori misura, correggere subito (ricerche o codice) e dirlo.

**Formato**: una frase di sintesi; tabella per modulo (promossi, venduti, entro 15 min); 3-6 esempi concreti di venduti rapidi; problemi trovati e cosa e' gia' stato fatto; prossimi passi (max 3).

**Esempio reale (7/10, radar 12:54-16:18 UTC)**: 957 promossi su ~1250 (il livello 1 scartava solo i fuori categoria); ~20 GB/giorno di proxy -> corretto subito (prezzo minimo, ricontrolli 3 invece di 6). Valore: LEGO Star Wars/Technic con numero di set (Imperial Star Destroyer 75 EUR gia' venduto alla prima lettura, 7259 a 35 EUR in 15 s); Alessi e minifigure vendono ma a 5-20 EUR; audio, libri, Contax quasi senza annunci.

**Controllo finale**
- [ ] Il periodo e' coperto per intero (o e' detto che manca un pezzo)?
- [ ] I numeri vengono da script su file, non da righe copiate a mano?
- [ ] C'e' la banda in GB/giorno?
- [ ] Stime dichiarate come stime?
