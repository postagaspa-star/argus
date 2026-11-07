"""Pausa (ps), lavoro (lv), dormo (dm), stato (st) dentro il motore."""

from argus.motore import Classe, PcMinuto, Regole
from simulatore import (DORME, FERMO, FUORI, LAVORA_PC, MANGIA, SDRAIATO, STUDIA_LIBRO, STUDIA_PC, TABLET,
                        TELEFONO, Sim, hm)


def _pronto(s: Sim) -> None:
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)


# --- ps -----------------------------------------------------------------------------------------

def test_pausa_risposta_e_fine_arrotondata_al_minuto():
    s = Sim()
    _pronto(s)
    r = s.cmd("ps m: bagno & t: 10", "14:00:00")
    assert r.ok and r.risposta == "Pausa fino alle 14:10."
    r = s.cmd("PS M: Bagno & T: 5", "14:00:20")  # sostituisce: i 10 tornano
    assert r.risposta == "Pausa fino alle 14:06."
    assert s.m.giorno.pausa.motivo == "Bagno"


def test_pausa_fuori_vista_neutra_poi_sforo_distrazione_subito():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:20", **STUDIA_LIBRO)
    s.cmd("ps m: bagno & t: 10", "14:20")
    s.tratto("14:20", "14:35", **FUORI)
    s.tratto("14:35", "14:40", **STUDIA_LIBRO)
    assert s.conta(Classe.NEUTRO, "14:20", "14:30") == 10
    assert s.conta(Classe.DISTRAZIONE, "14:30", "14:35") == 5
    assert s.m.giorno.agg_distrazione == 5
    v = [x.testo for x in s.voci if x.motivo == "distrazione"]
    assert v == ["La pausa è finita. Torna a studiare: mancano 40 minuti."]


def test_pausa_finisce_appena_torna_a_studiare_e_restituisce_i_minuti():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: merenda & t: 10", "14:00")
    s.tratto("14:00", "14:04", **MANGIA)
    s.tratto("14:04", "14:10", **STUDIA_LIBRO)
    assert s.m.giorno.pausa is None
    assert s.m.giorno.pausa_usata == 4
    assert s.m.pausa_disponibile(hm("14:10")) == 6


def test_budget_pausa_10_piu_10_ogni_50_minuti():
    s = Sim()
    _pronto(s)  # arrivo 13:30
    r = s.cmd("ps m: bagno & t: 15", "13:40")
    assert r.risposta == "Ti restano 10 minuti di pausa."
    assert s.m.giorno.pausa is None
    assert s.m.pausa_disponibile(hm("14:19")) == 10
    assert s.m.pausa_disponibile(hm("14:20")) == 20
    assert s.m.pausa_disponibile(hm("15:10")) == 30
    s.cmd("ps m: bagno & t: 20", "14:20")
    assert s.m.pausa_disponibile(hm("14:21")) == 0
    r = s.cmd("ps m: acqua & t: 1", "14:21")  # chiude quella in corso (1 minuto usato) e riprova
    assert r.risposta == "Pausa fino alle 14:22."


def test_pausa_sintassi_sbagliata():
    s = Sim()
    _pronto(s)
    from argus import comandi
    c = comandi.analizza("ps bagno 10")
    assert c.risposta == "Non ho capito. Scrivi così: ps m: bagno & t: 10"


def test_pausa_prima_dell_arrivo_non_serve():
    s = Sim()
    r = s.cmd("ps m: bagno & t: 10", "12:00")
    assert r.risposta == "Adesso sei libero: non serve."


def test_pausa_col_telefono_e_neutra_ma_semif_controlla_il_motivo():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: bagno & t: 10", "14:00")
    s.tratto("14:00", "14:10", **TELEFONO)
    assert s.conta(Classe.NEUTRO, "14:00", "14:10") == 10
    domande = s.domande_pausa
    # visto 2 minuti di fila -> prima domanda, poi una ogni 5 minuti
    assert [d.motivo for d in domande] == ["bagno", "bagno"]
    assert domande[0].id == s.m.giorno.pausa.id if s.m.giorno.pausa else True


def test_motivo_della_pausa_falso_imbroglio_30():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: bagno & t: 10", "14:00")
    s.tratto("14:00", "14:03", **TELEFONO)
    id_pausa = s.domande_pausa[0].id
    eff = s.m.esito_pausa(id_pausa, "non_torna", hm("14:03:20"))
    s._registra(eff)
    assert s.m.giorno.agg_imbroglio == 30
    assert s.m.giorno.pausa is None
    assert s.voci[-1].testo == "Quello che fai non torna con il motivo della pausa: altri 30 minuti."
    # un secondo giudizio sulla stessa pausa non aggiunge niente
    s.m.esito_pausa(id_pausa, "non_torna", hm("14:04"))
    assert s.m.giorno.agg_imbroglio == 30


def test_pausa_che_torna_o_non_si_capisce_nessuna_conseguenza():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: merenda & t: 10", "14:00")
    s.tratto("14:00", "14:03", **MANGIA)
    s.m.esito_pausa(s.m.giorno.pausa.id, "torna", hm("14:03"))
    s.m.esito_pausa(s.m.giorno.pausa.id, "non_si_capisce", hm("14:03"))
    assert s.m.giorno.agg_imbroglio == 0


def test_pausa_sforata_ma_tornato_in_vista_senza_distrazione_finisce_lo_sforo():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: acqua & t: 5", "14:00")
    s.tratto("14:00", "14:07", **FUORI)  # 14:05 e 14:06 sforati
    s.tratto("14:07", "14:10", **FERMO)  # visto, in piedi: nel dubbio neutro, sforo finito
    s.tratto("14:10", "14:14", **FUORI)  # 4 minuti fuori: neutri come sempre
    assert s.m.giorno.agg_distrazione == 2
    assert s.m.giorno.pausa_sforata is False


# --- lv -----------------------------------------------------------------------------------------

def test_lavoro_conta_e_cambia_modalita():
    s = Sim()
    _pronto(s)
    r = s.cmd("lv30", "14:00")
    assert r.risposta == "Lavoro fino alle 14:30."
    assert s.m.modalita(hm("14:00:30")) == "lavoro"
    assert s.m.stato_pc(hm("14:01"))["comando_attivo"] == {"tipo": "lv", "fino": "14:30"}
    s.tratto("14:00", "14:30", **LAVORA_PC)
    assert s.m.giorno.lavoro == 30
    assert s.m.modalita(hm("14:30")) == "studio"
    s.tratto("14:30", "14:40", **LAVORA_PC)  # lv finito: il lavoro non conta più
    assert s.m.giorno.lavoro == 30
    s.tratto("14:40", "15:10", **STUDIA_PC)
    assert s.m.giorno.fatta_alle == hm("15:09")


def test_lavoro_senza_lv_non_conta():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", **LAVORA_PC)
    assert s.m.giorno.lavoro == 0


def test_lavoro_fuori_da_lv_non_e_permesso():
    """Fuori da lv il PC copre le cose di lavoro: non sono studio, non fermano il conto del fuori
    vista e non coprono un tablet in mano."""
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:05", **LAVORA_PC)
    assert s.conta(Classe.NEUTRO, "14:00", "14:05") == 5
    assert s.m.giorno.studio == 0 and s.m.giorno.lavoro == 0
    # non visto, PC su una cosa di lavoro: il fuori vista conta (dal sesto minuto distrazione)
    s.tratto("14:05", "14:12", visto=False, pc=PcMinuto("lavoro", True))
    assert s.m.giorno.agg_distrazione == 2
    # tablet in mano mentre il PC è su lavoro fuori da lv: imbroglio
    s.tratto("14:12", "14:13", **{**TABLET, "pc": PcMinuto("lavoro", True)})
    assert s.m.giorno.agg_imbroglio == 30
    # durante lv, invece, il PC su lavoro copre il fuori vista
    s2 = Sim()
    _pronto(s2)
    s2.cmd("lv 60", "14:00")
    s2.tratto("14:00", "14:12", visto=False, pc=PcMinuto("lavoro", True))
    assert s2.m.giorno.agg_distrazione == 0


def test_lv0_chiude_e_limiti():
    s = Sim()
    _pronto(s)
    assert s.cmd("lv 0", "14:00").risposta == "Non c'è un tempo di lavoro aperto."
    assert s.cmd("lv 45", "14:00").risposta == "Lavoro fino alle 14:45."
    assert s.cmd("lv0", "14:10").risposta == "Lavoro chiuso."
    assert s.m.modalita(hm("14:10")) == "studio"
    assert s.cmd("lv4", "14:10").ok is False
    assert s.cmd("lv241", "14:10").ok is False


def test_verifiche_si_coprono_solo_studiando():
    s = Sim(regole=Regole(verifiche=20))
    _pronto(s)
    s.cmd("lv 120", "14:00")
    s.tratto("14:00", "15:20", **LAVORA_PC)  # 80 minuti di lavoro
    assert s.m.totale() == 80
    assert s.m.fatti() == 60
    assert s.m.giorno.fatta_alle is None
    s.tratto("15:20", "15:40", **STUDIA_LIBRO)
    assert s.m.giorno.fatta_alle == hm("15:39")


# --- dm -----------------------------------------------------------------------------------------

def test_dm_valido_neutro_senza_voce_poi_si_alza():
    s = Sim()
    _pronto(s)
    r = s.cmd("dm45", "14:00")
    assert r.risposta == "Dormi pure fino alle 14:45. Fatti vedere sdraiato entro 5 minuti."
    s.tratto("14:00", "14:02", **FERMO)
    s.tratto("14:02", "14:30", **SDRAIATO)
    assert s.m.giorno.dm.stato == "valido"
    s.minuto("14:30", **FERMO)  # in piedi un minuto: il dm finisce
    assert s.m.giorno.dm is None
    s.tratto("14:31", "14:33", **TELEFONO)
    assert s.conta(Classe.NEUTRO, "14:00", "14:31") == 31
    assert s.conta(Classe.DISTRAZIONE, "14:31", "14:33") == 1
    assert s.eventi("dm_valido")


def test_dm_annullato_se_non_lo_vedono_sdraiato_entro_5_minuti():
    s = Sim()
    _pronto(s)
    s.cmd("dm 30", "14:00:30")
    s.tratto("14:00", "14:08", **FERMO)
    assert s.m.giorno.dm is None
    assert s.eventi("dm_annullato")
    assert "Non ti vedo sdraiato: dm annullato." in [v.testo for v in s.voci]


def test_dm_niente_voce_anche_con_distrazione_e_fuori_vista_oltre_5_vale_la_regola():
    s = Sim()
    _pronto(s)
    s.cmd("dm 60", "14:00")
    s.tratto("14:00", "14:05", **DORME)
    s.tratto("14:05", "14:15", **FUORI)
    assert s.conta(Classe.NEUTRO, "14:05", "14:10") == 5
    assert s.conta(Classe.DISTRAZIONE, "14:10", "14:15") == 5
    assert not [v for v in s.voci]


def test_dm_sforato_non_punisce():
    s = Sim()
    _pronto(s)
    s.cmd("dm 20", "14:00")
    s.tratto("14:00", "15:00", **DORME)
    # scaduto alle 14:20 ma dorme ancora: il dm resta (sforato) finché non si alza
    assert s.m.giorno.dm is not None and s.m.giorno.dm.sforato
    assert s.m.giorno.agg_distrazione == 0
    assert s.conta(Classe.NEUTRO, "14:00", "15:00") == 60


def test_dm_fuori_limiti():
    s = Sim()
    _pronto(s)
    assert s.cmd("dm 2", "14:00").ok is False
    assert s.cmd("dm", "14:00").ok is False


# --- st -----------------------------------------------------------------------------------------

def test_st_durante_lo_studio():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:20", **STUDIA_LIBRO)
    s.cmd("lv 30", "14:20")
    r = s.cmd("st", "14:20:30")
    assert r.ok
    assert "Quota: 20 di 60 minuti (mancano 40)." in r.risposta
    assert "Comando attivo: lavoro fino alle 14:50." in r.risposta
    assert "Fine prevista: 15:00." in r.risposta
    assert "Adesso: studio." in r.risposta


def test_st_prima_dell_arrivo_e_di_sabato():
    from datetime import date
    s = Sim()
    assert "non è ancora partita" in s.cmd("st", "12:00").risposta
    s2 = Sim(giorno=date(2026, 11, 14))
    assert s2.cmd("st", "12:00").risposta == "Oggi non è giorno di scuola: sei libero."
