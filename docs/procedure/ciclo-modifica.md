# Ciclo di una modifica (dal codice al merge e alla verifica)

**Scopo**: portare una modifica in produzione verificata, senza chiedere ok (Railway fa il deploy da `main` a ogni merge, ~1,5 min).

**Input**: cosa cambiare e perche' (dato o richiesta dell'utente), file toccati.

**Passi**
1. `git fetch origin main` e `git checkout -B claude/<branch> origin/main` (main cambia spesso, anche per altre sessioni: rileggere i file toccati).
2. Modifica minima, stile del codice vicino, commenti in italiano; variabile nuova = default sensato + nome in `.env.example` + riga in `docs/pipeline.md`.
3. Test: `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot` (0 nomi non definiti; venv se mancano le dipendenze). Un test per ogni regola nuova.
4. Rileggere il proprio diff cercando cosa farebbe rifiutare la CI; nessun segreto.
5. `STATO.md` nella stessa PR se la tappa cambia lo stato (`aggiorna-stato.md`).
6. Commit con perche' e numeri e le righe di attribuzione; `git push --force-with-lease -u origin <branch>`; PR verso `main` (problema, modifiche, test).
7. CI (workflow `CI`, job `test`, ~25 s): leggere `conclusion` sull'ultimo commit. Rossa per colpa della PR -> sistemare; rossa anche su main -> unire e dirlo. Conflitto (`dirty`): unire `origin/main`, risolvere, ripetere 3-7.
8. Squash merge, poi `controllo-deploy.md` se tocca il runtime.

**Formato**: una frase: PR come owner/repo#N, esito CI, cosa cambia in produzione, verifica fatta, cosa resta all'utente.

**Esempi reali**: davegnima/vinted-flip-bot#88 (radar: prezzo minimo e ricontrolli ridotti) - test ok, CI verde, unita, banda verificata. davegnima/vinted-flip-bot#90 (riordino documenti): conflitto con main dopo #89 e #91, risolto con merge di `origin/main`, CI verde, squash.

**Controllo finale**
- [ ] Branch ripartito da main aggiornato e senza conflitti?
- [ ] Test, pyflakes e CI verdi sull'ultimo commit?
- [ ] Nessun segreto nel diff?
- [ ] Produzione verificata dopo il deploy?
