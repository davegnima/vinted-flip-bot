# Modello: da codice pronto a merge in main

**Scopo.** Portare una modifica verificata in produzione (Railway fa il deploy da `main` a ogni merge, circa 1,5 minuti).

**Dati necessari.** Branch `claude/cosa-posso-fare-t99uhl` allineato a `origin/main`; elenco dei file toccati; motivo della modifica in una riga.

**Passi**
1. `git fetch origin main` e riallineare il branch (`git checkout -B <branch> origin/main`, poi applicare la modifica) se `main` e' avanzato.
2. `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot` (devono dare 0 errori di nomi non definiti).
3. Rileggere il proprio diff cercando cosa farebbe rifiutare la CI.
4. Commit con le due righe finali di attribuzione, `git push --force-with-lease -u origin <branch>`.
5. Aprire la PR verso `main` (titolo breve, corpo con cosa cambia e numero dei test).
6. Attendere la CI (workflow `CI`, job `test`, circa 25 s): leggere `conclusion` della run sull'ultimo commit, non solo "in corso".
7. Se mergeable_state e' `dirty`: unire `origin/main` nel branch, risolvere (rigenerando, non a mano, i file generati), ripetere 2-6.
8. Squash merge. Poi controllare nei log solo le righe dopo `"Vinted Oracle avviato"` se la modifica tocca il runtime.

**Output.** Una frase: PR numero, esito della CI, SHA di merge, cosa cambia in produzione e cosa resta a carico dell'utente.

**Controllo finale (tutti si/no)**
- CI `success` sull'ultimo commit della PR?
- Nessun conflitto con `main`?
- Nessuna chiave, password o token nel diff?
- `STATO.md` aggiornato se la tappa cambia lo stato (vedi `aggiorna-stato.md`)?

**Esempio reale.** PR #90 (riordino documenti, 7/10): conflitto con `main` dopo #89 e #91, risolto con merge di `origin/main`, CI verde sul commit `41aa8a6`, squash merge `b9774f9`.
