"""Lettura dei comandi, liste (ag/tg, confronto) e calendario scolastico."""

from datetime import date, timedelta

import pytest

from argus import comandi
from argus.calendario import giorno_di_scuola, leggi_patrono
from argus.comandi import (CmdAiuto, CmdDormo, CmdErrore, CmdLavoro, CmdLista, CmdPausa, CmdRegistra,
                           CmdStato, durata_minuti)
from argus.liste import LISTE_PARTENZA, Liste, leggi_voce, programma_in, sito_in
from argus.tempo import ora_roma


# --- durate e ps ----------------------------------------------------------------------------------

@pytest.mark.parametrize("testo,minuti", [
    ("10", 10), ("10 min", 10), ("10m", 10), ("1h", 60), ("1h30", 90), ("90 min", 90),
    ("1 h", 60), ("1h 30", 90), ("2h05", 125), ("5 minuti", 5), ("1 ora", 60),
])
def test_durate_valide(testo, minuti):
    assert durata_minuti(testo) == minuti


@pytest.mark.parametrize("testo", ["0", "dieci", "1h60", "", "-5", "10 secondi", "1.5h"])
def test_durate_non_valide(testo):
    assert durata_minuti(testo) is None


@pytest.mark.parametrize("testo,motivo,minuti", [
    ("ps m: bagno & t: 10", "bagno", 10),
    ("PS M: Bagno & T: 10 MIN", "Bagno", 10),
    ("ps m:merenda&t:1h30", "merenda", 90),
    ("ps   m:  vado a prendere l'acqua   &   t:  5m ", "vado a prendere l'acqua", 5),
])
def test_pausa_valida(testo, motivo, minuti):
    assert comandi.analizza(testo) == CmdPausa(motivo=motivo, minuti=minuti)


@pytest.mark.parametrize("testo", [
    "ps", "ps bagno", "ps m: bagno", "ps t: 10", "ps m: & t: 10", "ps m: bagno & t: dieci",
    "ps m: bagno t: 10", "ps t: 10 & m: bagno", "ps m: bagno & t: 0",
])
def test_pausa_sbagliata_da_l_esempio(testo):
    c = comandi.analizza(testo)
    assert isinstance(c, CmdErrore)
    assert c.risposta == "Non ho capito. Scrivi così: ps m: bagno & t: 10"


def test_lv_dm_st_aiuto():
    assert comandi.analizza("lv30") == CmdLavoro(30)
    assert comandi.analizza("LV 30") == CmdLavoro(30)
    assert comandi.analizza("lv0") == CmdLavoro(0)
    assert isinstance(comandi.analizza("lv 4"), CmdErrore)
    assert isinstance(comandi.analizza("lv 241"), CmdErrore)
    assert isinstance(comandi.analizza("lv"), CmdErrore)
    assert isinstance(comandi.analizza("lvx"), CmdErrore)
    assert comandi.analizza("dm45") == CmdDormo(45)
    assert comandi.analizza("Dm 45") == CmdDormo(45)
    assert isinstance(comandi.analizza("dm"), CmdErrore)
    assert comandi.analizza("st") == CmdStato()
    assert comandi.analizza(" ST ") == CmdStato()
    assert comandi.analizza("aiuto") == CmdAiuto()
    assert comandi.analizza("Aiuto") == CmdAiuto()


def test_lb_qd_vs_tf():
    assert comandi.analizza("lb storia") == CmdRegistra("lb", "registra", "storia")
    assert comandi.analizza("LB Storia moderna") == CmdRegistra("lb", "registra", "Storia moderna")
    assert comandi.analizza("lb") == CmdRegistra("lb", "elenco")
    assert comandi.analizza("lb via storia") == CmdRegistra("lb", "togli", "storia")
    assert comandi.analizza("qd matematica") == CmdRegistra("qd", "registra", "matematica")
    assert comandi.analizza("qd via matematica") == CmdRegistra("qd", "togli", "matematica")
    assert isinstance(comandi.analizza("lb via"), CmdErrore)
    assert isinstance(comandi.analizza("lb " + "x" * 41), CmdErrore)
    assert comandi.analizza("vs") == CmdRegistra("vs", "registra")
    assert comandi.analizza("tf") == CmdRegistra("tf", "registra")
    assert isinstance(comandi.analizza("vs ciao"), CmdErrore)


def test_ag_tg():
    assert comandi.analizza("ag studio onenote.exe") == CmdLista("ag", "studio", "onenote.exe")
    assert comandi.analizza("TG Lavoro GitHub.com") == CmdLista("tg", "lavoro", "github.com")
    assert isinstance(comandi.analizza("ag svago youtube.com"), CmdErrore)
    assert isinstance(comandi.analizza("ag studio"), CmdErrore)


def test_testo_sconosciuto():
    c = comandi.analizza("ciao")
    assert c == CmdErrore("Non ho capito. Scrivi aiuto per vedere i comandi.")
    assert isinstance(comandi.analizza(""), CmdErrore)


# --- liste ----------------------------------------------------------------------------------------

def test_confronto_programmi():
    assert programma_in("SOFFICE.EXE", ["soffice.exe"])
    assert not programma_in("soffice", ["soffice.exe"])
    assert programma_in("Lectio.exe", ["lectio"])
    assert programma_in("wisper ufficio 1.1.exe", ["wisper ufficio"])
    assert programma_in("MinecraftLauncher.exe", ["minecraft"])
    assert not programma_in("notepad++.exe", ["notepad.exe"])
    assert programma_in("argus.agente.exe", LISTE_PARTENZA["sempre"]["programmi"])


def test_confronto_siti():
    assert sito_in("it.wikipedia.org", ["wikipedia.org"])
    assert sito_in("wikipedia.org", ["wikipedia.org"])
    assert not sito_in("notwikipedia.org", ["wikipedia.org"])
    assert sito_in("192.168.0.20", ["192.168."])
    assert sito_in("localhost:8770", ["localhost"])
    assert sito_in("127.0.0.1:5000", ["127.0.0.1"])
    assert not sito_in("192.169.1.1", ["192.168."])
    assert sito_in("WWW.YouTube.com", ["youtube.com"])
    assert not sito_in("", ["youtube.com"])


def test_leggi_voce():
    assert leggi_voce("OneNote.exe") == ("programmi", "onenote.exe")
    assert leggi_voce("https://www.github.com/esempio") == ("siti", "github.com")
    assert leggi_voce("docs.rs") == ("siti", "docs.rs")
    assert leggi_voce("wisper ufficio") == ("programmi", "wisper ufficio")
    assert leggi_voce("!!!") is None


def test_ag_vale_dopo_4_giorni_tg_subito():
    t0 = ora_roma(2026, 11, 9, 15, 20)
    liste = Liste()
    v0 = liste.versione(t0)
    ok, risposta, mod = liste.aggiungi("studio", "onenote.exe", t0)
    assert ok and mod is not None
    assert risposta == "onenote.exe sarà nella lista studio dal 13/11 alle 15:20."
    assert "onenote.exe" not in liste.attive(t0 + timedelta(days=3, hours=23))["studio"]["programmi"]
    assert liste.versione(t0 + timedelta(days=3)) == v0
    assert "onenote.exe" in liste.attive(t0 + timedelta(days=4))["studio"]["programmi"]
    assert liste.versione(t0 + timedelta(days=4)) == v0 + 1
    # togliere vale subito
    t1 = t0 + timedelta(days=5)
    ok, risposta, _ = liste.togli("studio", "onenote.exe", t1)
    assert risposta == "onenote.exe tolto dalla lista studio."
    assert "onenote.exe" not in liste.attive(t1)["studio"]["programmi"]
    assert liste.versione(t1) == v0 + 2


def test_tg_di_una_voce_di_partenza_e_annulla_aggiunta_in_attesa():
    t0 = ora_roma(2026, 11, 9, 15, 0)
    liste = Liste()
    liste.togli("lavoro", "github.com", t0)
    assert "github.com" not in liste.attive(t0)["lavoro"]["siti"]
    liste.aggiungi("studio", "docs.rs", t0)
    ok, risposta, mod = liste.togli("studio", "docs.rs", t0 + timedelta(hours=1))
    assert mod is None and "tolto" in risposta
    assert "docs.rs" not in liste.attive(t0 + timedelta(days=10))["studio"]["siti"]


def test_mai_non_si_aggiunge():
    t0 = ora_roma(2026, 11, 9, 15, 0)
    liste = Liste()
    ok, risposta, mod = liste.aggiungi("studio", "steam.exe", t0)
    assert mod is None and risposta == "steam.exe è nella lista Mai: non si può aggiungere."
    ok, risposta, mod = liste.aggiungi("studio", "www.instagram.com", t0)
    assert mod is None
    ok, risposta, mod = liste.aggiungi("lavoro", "minecraftlauncher2.exe", t0)
    assert mod is None


def test_doppia_aggiunta_e_gia_presente():
    t0 = ora_roma(2026, 11, 9, 15, 0)
    liste = Liste()
    _, r, _ = liste.aggiungi("studio", "wikipedia.org", t0)
    assert r == "wikipedia.org è già nella lista studio."
    liste.aggiungi("studio", "docs.rs", t0)
    _, r, m = liste.aggiungi("studio", "docs.rs", t0 + timedelta(hours=1))
    assert m is None and "già in arrivo" in r


def test_liste_per_pc_forma_del_contratto():
    liste = Liste().per_pc(ora_roma(2026, 11, 9, 15, 0))
    assert set(liste) >= {"versione", "sempre", "studio", "lavoro", "da_giudicare", "mai", "browser"}
    assert liste["da_giudicare"] == ["youtube.com", "claude.ai", "chatgpt.com", "gemini.google.com",
                                     "grok.com", "copilot.microsoft.com"]
    assert liste["browser"] == ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]
    assert set(liste["sempre"]) == {"programmi", "siti"}


def test_modifiche_si_salvano():
    from argus.liste import Modifica
    t0 = ora_roma(2026, 11, 9, 15, 0)
    liste = Liste()
    _, _, m = liste.aggiungi("lavoro", "docs.rs", t0)
    copia = Liste([Modifica.da_dict(m.a_dict())])
    assert copia.versione(t0 + timedelta(days=4)) == liste.versione(t0 + timedelta(days=4))


# --- calendario -----------------------------------------------------------------------------------

@pytest.mark.parametrize("giorno,scuola", [
    (date(2026, 9, 9), False), (date(2026, 9, 10), True), (date(2026, 9, 12), False),
    (date(2026, 10, 30), False), (date(2026, 11, 2), False), (date(2026, 11, 3), True),
    (date(2026, 12, 7), False), (date(2026, 12, 9), True), (date(2026, 12, 23), True),
    (date(2026, 12, 24), False), (date(2027, 1, 6), False), (date(2027, 1, 7), True),
    (date(2027, 2, 8), False), (date(2027, 2, 15), True), (date(2027, 3, 26), False),
    (date(2027, 3, 31), True), (date(2027, 4, 29), False), (date(2027, 4, 30), False),
    (date(2027, 5, 31), False), (date(2027, 6, 3), True), (date(2027, 6, 8), True),
    (date(2027, 6, 9), False), (date(2027, 9, 13), False), (date(2026, 11, 15), False),
])
def test_calendario_veneto(giorno, scuola):
    assert giorno_di_scuola(giorno) is scuola


def test_sabato_e_patrono():
    assert giorno_di_scuola(date(2026, 11, 14), sabato_scuola=True)
    assert not giorno_di_scuola(date(2026, 11, 14))
    assert not giorno_di_scuola(date(2026, 11, 11), patrono="11/11")
    assert leggi_patrono("25/04") == (4, 25)
    assert leggi_patrono("2026-11-11") == (11, 11)
    assert leggi_patrono("11-11") == (11, 11)
    with pytest.raises(ValueError):
        leggi_patrono("San Martino")
