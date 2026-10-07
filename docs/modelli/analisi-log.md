# Modello: leggere i log Railway

**Scopo.** Rispondere a una domanda sul comportamento del bot (modello in uso, errori, tempi, costo) senza riempire la conversazione.

**Dati necessari.** Progetto `cd06f689-76ef-4b17-aee8-0c04dc03a4d9`, ambiente `6f828acc-20fc-4858-a48b-3f63f57a5a03`, servizio worker `7f856e1e-dad7-4798-90de-ac6ca77e5756`; la finestra di tempo; le parole esatte del log (`docs/log.md`).

**Passi**
1. Controllo puntuale: `filter` stretto, `startDate` vicino, `limit` 20-40.
2. Analisi su ore: filtro largo (per esempio `"| ESITO |" OR "RICONTROLLO LAMPO"`), finestre di 3-6 h, `limit` 500; il risultato finisce in un file solo oltre circa 80.000 caratteri.
3. Elaborare il file con `python3 -I`, mai incollare righe a mano; per un conteggio esatto rifare la richiesta.
4. Cercare un annuncio: l'id tra virgolette. Dopo un deploy: solo righe successive a `"Vinted Oracle avviato"`.
5. Traffico basso: dirlo e aspettare, non rileggere in loop.

**Output.** Risposta in 3-6 righe: numero trovato, finestra di tempo, esempio di una riga, conclusione. Se il campione e' piccolo, dirlo.

**Controllo finale**
- La finestra e il filtro sono dichiarati nella risposta?
- I numeri vengono da uno script, non da righe lette a occhio?
- Nessuna credenziale o URL con password riportata (le righe `proxy_used=` del tracker ne stampano)?

**Esempio reale.** 7/10: "la chiave a pagamento e' attiva?" con filtro `"Riserva a pagamento" OR "PAGAMENTO"` e `limit` 5: avvio con `Riserva a pagamento ATTIVA` e 16 richieste fino alle 15:10 UTC.
