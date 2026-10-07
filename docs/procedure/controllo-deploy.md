# Controllo dopo un deploy

**Scopo**: dopo un merge su `main` (worker o tracker) o un riavvio, essere sicuri che moda e radar ricevano e lavorino.

**Input**: quale servizio e' ripartito e a che ora (UTC).

**Passi**
1. Deploy finito: Railway `list-deployments` (stato SUCCESS) del servizio.
2. Worker: log da poco prima del deploy con `"Vinted Oracle avviato" OR "MESSAGGIO TRACKER" OR "MESSAGGIO RADAR" OR Traceback`; la versione deve essere il commit unito.
3. Tracker (`vinted-notifications`, `vinted-radar`): GET `/control/status` deve dare `"telegram":true`. Se false: POST `/control/telegram/start` (Auto Start e' acceso dal 7/10, ma va verificato).
4. Moda: almeno un `MESSAGGIO TRACKER` dopo l'avvio. Radar: almeno un `MESSAGGIO RADAR` (arriva dal gruppo "Radar grezzo", `RADAR_GROUP_ID`).
5. Se il deploy toccava Gemini o la riserva: almeno una riga `GEMINI_USO` o `RISERVA |` senza errori 400.

**Formato**: una riga per servizio: ok / problema e cosa ho fatto.

**Esempio reale (7/10 13:01)**: dopo il merge del tracker entrambi i processi Telegram risultavano fermi (`telegram:false`): riavviati con `/control/telegram/start`, attivato Auto Start; moda di nuovo in arrivo alle 13:02.

**Controllo finale**
- [ ] Versione nel log = commit unito?
- [ ] Moda e radar ricevono messaggi dopo l'avvio?
- [ ] Nessun Traceback nuovo?
