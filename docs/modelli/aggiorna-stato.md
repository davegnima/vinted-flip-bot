# Modello: chiudere una tappa in STATO.md

**Scopo.** Far trovare alla prossima sessione (o dopo una compattazione) cosa e' cambiato e cosa resta da controllare.

**Dati necessari.** Cosa e' cambiato (una riga), data, numero della PR, cosa va verificato nei log e dove (filtro esatto), cosa resta all'utente.

**Passi**
1. Aggiungere una riga a "Fatto e in produzione" di `STATO.md` (data, cosa, PR); la cronologia vecchia va in `docs/storico.md`.
2. Se serve un controllo futuro, una riga in "Da controllare" con il filtro dei log.
3. Se resta qualcosa all'utente (chiavi, impostazioni), una riga in "Aperti per l'utente"; se e' stato risolto, toglierla.
4. Se cambia una regola o una soglia: aggiornare `docs/pipeline.md` (e `CLAUDE.md` solo se e' una regola generale).
5. Includere l'aggiornamento nella stessa PR della modifica.

**Output.** Righe brevi, con data e numero PR, senza ripetere il codice.

**Controllo finale**
- Ogni riga ha data e riferimento (PR o filtro log)?
- `CLAUDE.md` resta sotto le 60 righe?
- Nessun segreto?

**Esempio reale.** 7/10, PR #92: riga "chiave Google a pagamento rigenerata, riserva a pagamento attiva (16 richieste fino alle 15:10 UTC), nel recap contare le richieste `PAGAMENTO`".
