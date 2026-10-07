# Modello: cambiare una variabile del worker

**Scopo.** Modificare il comportamento del bot senza toccare il codice, e verificare che sia partito il deploy giusto.

**Dati necessari.** Nome e valore della variabile (se e' una chiave o un segreto: non scriverla in file, commit o PR, e chiederla all'utente); servizio worker `7f856e1e-dad7-4798-90de-ac6ca77e5756`; elenco dei nomi in `.env.example`.

**Passi**
1. Leggere i nomi con `list-variables` (i valori dei segreti non sono leggibili e non servono).
2. `set-variables` solo per la chiave interessata; non toccare `PROXY_LIST` / `PROXY_ESCLUSI` del worker.
3. Controllare il deploy con `list-deployments` (stato, orario) o con `"Vinted Oracle avviato"` nei log.
4. Verificare l'effetto con una riga di log specifica della funzione (per esempio `Riserva a pagamento ATTIVA`, `RADAR PAUSA |`).
5. Se la variabile e' nuova, aggiungere il nome a `.env.example` e una riga a `docs/pipeline.md`.

**Output.** Variabile cambiata (solo nome e valore non segreto), deploy partito alle hh:mm, riga di log che conferma l'effetto.

**Controllo finale**
- Nessun valore segreto scritto da nessuna parte?
- Deploy riuscito e riga di log vista?
- Variabile documentata in `.env.example`?

**Esempio reale.** 4-6/10: `RISERVA_CERVELLO_MODELLI` e `PANEL_CERVELLO_MODELLI` con i modelli Cerebras, NVIDIA e OpenRouter; poi righe `RISERVA |` con quei modelli nei log.
