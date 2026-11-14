/* Vestiaire Collective: salva i risultati di ricerca in un file JSON, dal TUO browser (computer, non telefono).
 *
 * Come funziona: la pagina di Vestiaire, quando cerchi, chiama la propria API di ricerca. Questo script si mette in
 * ascolto, copia quella chiamata e la rilancia cambiando SOLO la pagina (offset, a passi di 48), con una pausa tra
 * una richiesta e l'altra. Non invia niente da nessuna parte: alla fine scarica un file sul tuo computer.
 * Non legge ne' stampa cookie o header. Si ferma al primo errore e non insiste.
 *
 * Uso (Chrome sul computer):
 *   1. Apri https://it.vestiairecollective.com e fai una ricerca (es. brand e categoria con i filtri del sito).
 *   2. Premi F12, scheda "Console", incolla TUTTO questo file e premi Invio.
 *   3. Nella pagina, passa alla pagina 2 dei risultati (o cambia un filtro): lo script scrive "Catturata".
 *   4. In console scrivi:  await vc.prova()      -> stampa un riepilogo (non scarica niente)
 *      poi:               await vc.scarica(10)   -> scarica fino a 10 pagine (480 articoli) in un file .json
 * Limiti: massimo 40 pagine per lancio, pausa di 2,5 secondi. Vestiaire non mostra oltre circa 1.200 risultati per ricerca.
 */
(function () {
  const ENDPOINT = "search.vestiairecollective.com/v1/product/search";
  const PAUSA_MS = 2500, PASSO = 48, MAX_PAGINE = 40;
  const dormi = (ms) => new Promise((r) => setTimeout(r, ms));
  const vc = (window.vc = { cattura: null, righe: [] });

  // --- ascolto delle chiamate fetch e XHR della pagina ---
  const fetchOriginale = window.fetch.bind(window);
  window.fetch = function (input, init) {
    try {
      const url = typeof input === "string" ? input : input && input.url;
      if (!vc.cattura && url && url.includes(ENDPOINT) && init && init.body) {
        vc.cattura = { url, init: { method: init.method || "POST", headers: init.headers, body: init.body } };
        console.log("Catturata la ricerca (fetch). Ora scrivi: await vc.prova()");
      }
    } catch (e) { /* non deve mai rompere la pagina */ }
    return fetchOriginale(input, init);
  };
  const aprire = XMLHttpRequest.prototype.open, inviare = XMLHttpRequest.prototype.send;
  const impostaHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (m, u) { this._vc = { url: String(u), headers: {} }; return aprire.apply(this, arguments); };
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) { if (this._vc) this._vc.headers[k] = v; return impostaHeader.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function (body) {
    try {
      if (!vc.cattura && this._vc && this._vc.url.includes(ENDPOINT) && body) {
        vc.cattura = { url: this._vc.url, init: { method: "POST", headers: this._vc.headers, body } };
        console.log("Catturata la ricerca (XHR). Ora scrivi: await vc.prova()");
      }
    } catch (e) { /* idem */ }
    return inviare.apply(this, arguments);
  };

  async function pagina(offset) {
    if (!vc.cattura) throw new Error("Nessuna ricerca catturata: nella pagina vai alla pagina 2 dei risultati e riprova.");
    const corpo = JSON.parse(vc.cattura.init.body);
    corpo.pagination = Object.assign({}, corpo.pagination, { offset });
    const r = await fetchOriginale(vc.cattura.url, Object.assign({}, vc.cattura.init, { body: JSON.stringify(corpo) }));
    if (!r.ok) throw new Error("HTTP " + r.status + " alla pagina con offset " + offset + ": mi fermo.");
    return r.json();
  }

  function riga(a) {  // solo campi del prodotto, nessun dato personale del venditore
    const p = a.price || {};
    return {
      id: a.id, brand: a.brand && a.brand.name, nome: a.name, modello: a.model && a.model.name,
      prezzo_centesimi: p.cents, valuta: p.currency, sold: a.sold, in_stock: a.stock,
      condizione: a.condition && (a.condition.name || a.condition), paese: a.country, creato: a.createdAt,
      link: a.link, descrizione: (a.description || "").slice(0, 300),
    };
  }

  vc.prova = async function () {
    const d = await pagina(0);
    const items = d.items || [];
    const sold = items.filter((a) => a.sold === true).length;
    console.log("Articoli nella pagina:", items.length, "| con sold=true:", sold);
    console.log("Pagine totali dichiarate:", d.paginationStats && d.paginationStats.totalPages);
    console.log("Campi del primo articolo:", items[0] ? Object.keys(items[0]).join(", ") : "(nessun articolo)");
    console.table(items.slice(0, 5).map(riga));
    await dormi(PAUSA_MS);
    const d2 = await pagina(PASSO);
    const i2 = d2.items || [];
    console.log("Pagina 2: articoli", i2.length, "| sold=true:", i2.filter((a) => a.sold === true).length);
    console.log("Copia qui sopra queste righe (non contengono cookie ne' header) e mandale a Claude.");
  };

  vc.scarica = async function (nPagine) {
    const n = Math.min(Math.max(parseInt(nPagine || 5, 10), 1), MAX_PAGINE);
    vc.righe = [];
    for (let i = 0; i < n; i++) {
      const d = await pagina(i * PASSO);
      const items = d.items || [];
      if (!items.length) break;
      vc.righe.push(...items.map(riga));
      console.log("Pagina " + (i + 1) + "/" + n + ": totale articoli " + vc.righe.length);
      if (d.paginationStats && i + 1 >= d.paginationStats.totalPages) break;
      await dormi(PAUSA_MS);
    }
    const blob = new Blob([JSON.stringify(vc.righe)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "vestiaire_" + new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-") + ".json";
    document.body.appendChild(a); a.click(); a.remove();
    console.log("Scaricato " + vc.righe.length + " articoli. Per un'altra ricerca: cambia i filtri nella pagina, vai a pagina 2, poi vc.cattura=null e rifai.");
  };

  console.log("Pronto. Ora, nella pagina, vai alla pagina 2 dei risultati: lo script copia la ricerca.");
})();
