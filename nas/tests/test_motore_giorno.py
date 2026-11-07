"""Arrivo, giorni di scuola, mezzanotte e riporto (regole sezioni 2, 3, 13)."""

from datetime import date, timedelta

from argus.motore import Classe, Mezzanotte, Motore, Regole
from simulatore import FUORI, LUNEDI, MANGIA, STUDIA_LIBRO, Sim, hm

VENERDI = date(2026, 11, 13)
SABATO = date(2026, 11, 14)
MARTEDI = date(2026, 11, 10)


def test_arrivo_dopo_le_11_e_tre_ore_di_assenza():
    s = Sim()
    s.minuto("07:20", visto=True, stanza="camera", dove="in_piedi", posa="in_piedi")
    assert s.m.giorno.arrivo is None
    s.minuto("13:30", **MANGIA)
    assert s.m.giorno.arrivo == hm("13:30")
    assert s.eventi("arrivo")
    assert s.m.modalita(hm("13:31")) == "studio"


def test_niente_arrivo_prima_delle_11():
    s = Sim()
    s.minuto("10:30", **MANGIA)
    assert s.m.giorno.arrivo is None
    # alle 11:10 è visto ma l'ultima volta era 40 minuti fa: non è un arrivo
    s.minuto("11:10", **MANGIA)
    assert s.m.giorno.arrivo is None


def test_malato_a_casa_tutto_il_giorno_niente_quota():
    s = Sim()
    t = hm("08:00")
    while t < hm("23:00"):
        s.minuto(t, visto=True, stanza="camera", dove="letto", posa="sdraiato")
        t += timedelta(minutes=20)
    assert s.m.giorno.arrivo is None
    assert s.m.modalita(hm("16:00")) == "libero"
    assert s.m.stato_pc(hm("16:00"))["messaggio_copertura"] is None


def test_mai_visto_prima_arriva_alla_prima_vista_dopo_le_11():
    s = Sim()
    s.minuto("14:05", **MANGIA)
    assert s.m.giorno.arrivo == hm("14:05")


def test_persona_sdraiata_non_riconosciuta_blocca_l_arrivo():
    # Malato a letto col viso nascosto: "forse visto" vale per il conto delle 3 ore.
    s = Sim()
    s.minuto("10:30", visto=False, forse_visto=True)
    s.minuto("12:00", **MANGIA)
    assert s.m.giorno.arrivo is None


def test_niente_arrivo_di_sabato_ne_nei_festivi():
    s = Sim(giorno=SABATO)
    s.minuto("14:00", **MANGIA)
    assert s.m.giorno.scuola is False
    assert s.m.giorno.arrivo is None
    s2 = Sim(giorno=date(2026, 12, 8))
    s2.minuto("14:00", **MANGIA)
    assert s2.m.giorno.arrivo is None


def test_sabato_di_scuola_se_configurato():
    s = Sim(giorno=SABATO, regole=Regole(sabato_scuola=True))
    s.minuto("13:30", **MANGIA)
    assert s.m.giorno.arrivo is not None


def test_patrono_configurato():
    s = Sim(giorno=LUNEDI, regole=Regole(patrono="09/11"))
    s.minuto("13:30", **MANGIA)
    assert s.m.giorno.scuola is False


def test_mezzanotte_riporto_massimo_30():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:20", **STUDIA_LIBRO)  # 20 di 60
    eff = s.tratto("23:58", "00:02", **FUORI)
    assert any(isinstance(e, Mezzanotte) for e in eff)
    ev = s.eventi("mezzanotte")[-1].dettagli
    assert ev["mancavano"] == 40 and ev["riporto"] == 30 and ev["persi"] == 10
    assert s.m.giorno.data == MARTEDI
    assert s.m.giorno.riporto == 30
    assert s.m.totale() == 90


def test_riporto_piccolo_passa_intero():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:50", **STUDIA_LIBRO)
    s.m.allinea(hm("00:01", MARTEDI))
    assert s.m.giorno.riporto == 10


def test_riporto_salta_il_fine_settimana():
    s = Sim(giorno=VENERDI)
    s.arriva()
    s.tratto("14:00", "14:30", **STUDIA_LIBRO)
    s.m.allinea(hm("10:00", date(2026, 11, 16)))  # lunedì dopo
    assert s.m.giorno.data == date(2026, 11, 16)
    assert s.m.giorno.riporto == 30


def test_senza_arrivo_il_riporto_si_perde():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:20", **STUDIA_LIBRO)
    s.m.allinea(hm("00:00", MARTEDI))
    assert s.m.giorno.riporto == 30
    # martedì malato: visto a letto la mattina e poi tutto il giorno, niente arrivo
    s.minuto(hm("09:00", MARTEDI), visto=True, stanza="camera", dove="letto", posa="sdraiato")
    s.minuto(hm("11:30", MARTEDI), visto=True, stanza="camera", dove="letto", posa="sdraiato")
    assert s.m.giorno.arrivo is None
    s._registra(s.m.allinea(hm("00:00", date(2026, 11, 11))))
    assert s.m.giorno.riporto == 0
    assert s.eventi("riporto_perso")


def test_quota_fatta_niente_riporto_e_minuti_in_piu_non_si_accumulano():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "16:00", **STUDIA_LIBRO)
    assert s.m.giorno.fatta_alle == hm("14:59")
    assert s.m.giorno.studio == 60  # dopo la quota non si conta più
    s.m.allinea(hm("00:00", MARTEDI))
    assert s.m.giorno.riporto == 0


def test_quota_fatta_libera_il_pc_e_ferma_la_visione():
    s = Sim()
    s.arriva()
    assert s.m.analizza_immagini(hm("14:00"))
    s.tratto("14:00", "15:00", **STUDIA_LIBRO)
    assert s.m.modalita(hm("15:01")) == "libero"
    assert s.m.stato_pc(hm("15:01"))["quota_fatta_oggi"] is True
    assert not s.m.analizza_immagini(hm("15:01"))
    assert [v.testo for v in s.voci][-1] == "Fatto per oggi. Sei libero."
    # il giorno di scuola dopo la visione riparte da mezzanotte
    s.m.allinea(hm("00:00", MARTEDI))
    assert s.m.analizza_immagini(hm("00:00", MARTEDI))


def test_inattivo_senza_telecamere_non_conta_niente():
    m = Motore(Regole(), oggi=LUNEDI)
    m.inattivo = True
    s = Sim(motore=m)
    s.minuto("13:30", **MANGIA)
    s.tratto("14:00", "14:10", **STUDIA_LIBRO)
    assert s.m.giorno.arrivo is None
    assert s.m.modalita(hm("14:00")) == "inattivo"
    assert not s.classi


def test_minuto_ripetuto_non_conta_due_volte():
    s = Sim()
    s.arriva()
    s.minuto("14:00", **STUDIA_LIBRO)
    s.minuto("14:00", **STUDIA_LIBRO)
    assert s.m.giorno.studio == 1


def test_esporta_e_importa_a_metà_pomeriggio():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:10", **STUDIA_LIBRO)
    s.cmd("ps m: bagno & t: 10", "14:10")
    s.tratto("14:10", "14:15", **FUORI)
    dati = s.m.esporta()
    m2 = Motore.importa(dati, Regole())
    assert m2.esporta() == dati
    s2 = Sim(motore=m2)
    s2.tratto("14:15", "14:25", **FUORI)
    # pausa fino alle 14:20, poi sforata: 5 minuti di distrazione
    assert m2.giorno.agg_distrazione == 5
    assert s2.classe("14:16") == Classe.NEUTRO


def test_nas_spento_per_giorni_chiude_tutti_i_giorni():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:30", **STUDIA_LIBRO)
    eff = s.m.allinea(hm("12:00", date(2026, 11, 12)))
    assert sum(1 for e in eff if isinstance(e, Mezzanotte)) == 3
    # martedì e mercoledì senza arrivo: il riporto di lunedì si è perso martedì
    assert s.m.giorno.riporto == 0
