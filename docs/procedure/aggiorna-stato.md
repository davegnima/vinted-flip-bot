# Modello: chiudere una tappa in STATO.md

**Scopo.** Far trovare alla prossima sessione (o dopo una compattazione) lo stato vero in poche righe. `STATO.md` + `CLAUDE.md` devono restare sotto 5.000 token (circa 20.000 byte in tutto).

**Dati necessari.** Cosa e' cambiato (una riga), data, numero della PR, cosa va verificato nei log e dove (filtro esatto), cosa resta all'utente.

**Passi**
1. Cronologia: aggiungere UNA voce (data, cosa, PR, numeri misurati) in fondo al file del tema in `docs/storico/` (`moda.md`, `radar.md`, `tracker.md`, `infrastruttura.md`). Mai in `STATO.md`.
2. `STATO.md`, sezione "Stato corrente": correggere la riga che non e' piu' vera (sostituire, non aggiungere).
3. Se serve un controllo futuro: una riga in "Controlli da fare" con il filtro dei log. Togliere i controlli gia' fatti.
4. Se resta qualcosa all'utente o un lavoro a meta': una riga in "Punti aperti"; se e' risolto, toglierla.
5. Se cambia una regola o una soglia: aggiornare `docs/pipeline.md` (e `CLAUDE.md` solo se e' una regola generale).
6. Includere l'aggiornamento nella stessa PR della modifica.

**Controllo finale**
- `wc -c CLAUDE.md STATO.md`: somma sotto 20.000 byte? `STATO.md` sotto le 60 righe?
- Ogni voce dello storico ha data e riferimento (PR o filtro log)?
- Nessun segreto?

**Esempio reale.** 13/11: la voce lunga "tolte `V2 ghd` e `V2 audio e hifi`, recap dal CSV..." va in `docs/storico/radar.md`; in `STATO.md` cambia solo la riga "Ricerche attive: circa 17".
