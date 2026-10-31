from bot import radar_appreso as ra
from bot.radar import da_cancellare


def _pulisci():
    ra._oss.clear(); ra._contatori.clear(); ra._segnalate.clear()


def test_servono_tre_osservazioni_solide():
    _pulisci()
    assert ra.registra("wii console", 5.0, 8, None, 1000)
    assert ra.registra("wii console", 8.0, 8, None, 1001)
    assert ra.limite_famiglia("wii console", 1002) is None
    ra.registra("wii console", 6.0, 8, None, 1002)
    assert ra.limite_famiglia("wii console", 1003) == 8.0


def test_osservazioni_deboli_non_contano():
    _pulisci()
    assert not ra.registra("x y", 1.0, 3, None, 1)      # pochi comparabili
    assert not ra.registra("x y", 1.0, 9, 1, 1)         # ricerca allargata
    assert not ra.registra("x y", None, 9, None, 1)     # limite ignoto


def test_scarto_sopra_il_limite_con_campione(monkeypatch):
    _pulisci()
    monkeypatch.setattr(ra, "RADAR_APPRESO", True)
    monkeypatch.setattr(ra, "RADAR_APPRESO_CAMPIONE", 3)
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.da_saltare("wii console", 14, 2000) is None       # entro il margine di sicurezza (10 x 1,25 + 2 = 14,5)
    assert ra.da_saltare("wii console", 30, 2000) == 10.0
    assert ra.da_saltare("wii console", 30, 2000) == 10.0
    assert ra.da_saltare("wii console", 30, 2000) is None       # ogni 3 passa il calcolo completo
    assert ra.da_saltare("altra famiglia", 30, 2000) is None    # famiglia sconosciuta


def test_osservazioni_scadute(monkeypatch):
    _pulisci()
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.limite_famiglia("wii console", 1000 + 8 * 86400) is None


def test_spento_con_variabile(monkeypatch):
    _pulisci()
    monkeypatch.setattr(ra, "RADAR_APPRESO", False)
    for i in range(3):
        ra.registra("wii console", 10.0, 8, None, 1000 + i)
    assert ra.da_saltare("wii console", 99, 2000) is None


def test_famiglia_senza_margine_si_cancella_dal_gruppo():
    assert da_cancellare({"semaforo": "rosso", "motivo": "famiglia_senza_margine"})
