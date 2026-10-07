# Ciclo di una modifica

**Scopo**: portare una modifica dal codice alla produzione verificata, senza chiedere ok (regola del 7/10).

**Input**: cosa cambiare e perche' (dato o richiesta dell'utente).

**Passi**
1. `git fetch origin main` e branch `claude/...` ripartito da `origin/main` (main cambia spesso: rileggere i file toccati).
2. Modifica minima, stile del codice vicino, commenti in italiano; nuova variabile = valore di default sensato + riga in `.env.example`.
3. Test: `python3 -m pytest -q` e `python3 -m pyflakes main_telethon.py bot` (venv se mancano le dipendenze). Un test nuovo per ogni regola nuova.
4. Aggiornare `docs/` o `CLAUDE.md` se cambia un meccanismo; `STATO.md` a tappa chiusa.
5. Commit con perche' e numeri, push, PR (descrizione: problema, modifiche, test).
6. CI verde -> squash merge. Rossa per colpa della PR -> sistemare. Rossa anche su main -> unire e dirlo.
7. `controllo-deploy.md`.

**Formato**: cosa e' cambiato (1-3 righe), link alla PR come owner/repo#N, verifica in produzione.

**Esempio reale**: davegnima/vinted-flip-bot#88 (radar: prezzo minimo e ricontrolli ridotti) - test 143 ok, CI verde, unita, deploy verificato.

**Controllo finale**
- [ ] Branch ripartito da main aggiornato?
- [ ] Test e pyflakes puliti?
- [ ] CI verificata prima del merge?
- [ ] Produzione verificata dopo il deploy?
