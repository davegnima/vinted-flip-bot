# Test di Jev (TypeSafe AI) sui titoli degli annunci del radar senza modello (25/10).
# Non fa parte del bot: scrive solo un file con le risposte, da controllare a occhio.
# Uso: JEV_API_KEY=... python3 prova_jev.py annunci.json risposte.json
#   annunci.json: [{"id": "...", "titolo": "...", "prezzo": 40.0, "candidati": ["Nikon FM2", "Leica M3", ...]}]
# La chiave NON va scritta nel file: si legge dalla variabile d'ambiente JEV_API_KEY.
import json, os, sys, urllib.request

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODELLO = "jev-latest"


def chiedi(chiave, annuncio):
    domanda = {
        "type": "choice",
        "instructions": "Scegli il modello dell'oggetto descritto dal titolo, tra i candidati. "
                        "Se il titolo non basta per riconoscerne uno, scegli 'nessuno'.",
        "options": annuncio["candidati"] + ["nessuno"],
    }
    corpo = {"model": MODELLO,
             "state": f"Titolo annuncio Vinted: {annuncio['titolo']}\nPrezzo: {annuncio['prezzo']} EUR",
             "questions": {"modello": domanda}}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def main():
    chiave = os.environ.get("JEV_API_KEY", "").strip()
    if not chiave:
        sys.exit("Manca JEV_API_KEY nell'ambiente.")
    annunci = json.load(open(sys.argv[1]))
    risposte = []
    for a in annunci:
        try:
            esito = chiedi(chiave, a)
        except Exception as e:
            esito = {"errore": str(e)}
        risposte.append({"id": a["id"], "titolo": a["titolo"], "prezzo": a["prezzo"], "risposta": esito})
    json.dump(risposte, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print(f"{len(risposte)} risposte scritte in {sys.argv[2]}")


if __name__ == "__main__":
    main()
