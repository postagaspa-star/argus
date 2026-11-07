"""Tutte le frasi che lo studente legge o sente. Italiano semplice, frasi brevi, niente emoji.

Tenerle qui insieme serve a due cose: si correggono in un posto solo, e la voce può
preparare in anticipo (cache su disco) quelle che non cambiano.
"""

# --- Voce (regole sezione 11) -----------------------------------------------------------------
VOCE_DISTRAZIONE = "Torna a studiare: mancano {mancano} minuti."
VOCE_FUORI_VISTA = "Non ti vedo da 5 minuti. Se ti serve una pausa, scrivila nel terminale."
VOCE_PRANZO_FINITO = "Non ti vedo da un'ora: da adesso il tempo conta. Se ti serve una pausa, scrivila nel terminale."
VOCE_IMBROGLIO = "Quello non è un dispositivo di studio: altri 30 minuti."
VOCE_PAUSA_FALSA = "Quello che fai non torna con il motivo della pausa: altri 30 minuti."
VOCE_QUOTA_FATTA = "Fatto per oggi. Sei libero."
VOCE_DM_ANNULLATO = "Non ti vedo sdraiato: dm annullato."
VOCE_PAUSA_FINITA = "La pausa è finita. Torna a studiare: mancano {mancano} minuti."

FRASI_FISSE_VOCE = [
    VOCE_FUORI_VISTA,
    VOCE_PRANZO_FINITO,
    VOCE_IMBROGLIO,
    VOCE_PAUSA_FALSA,
    VOCE_QUOTA_FATTA,
    VOCE_DM_ANNULLATO,
]

# --- Copertura del PC (regole sezione 12) --------------------------------------------------------
COPERTURA = "Adesso è tempo di studio. Mancano {mancano} minuti."
COPERTURA_UN_MINUTO = "Adesso è tempo di studio. Manca 1 minuto."

# --- Risposte ai comandi (regole sezione 8) ------------------------------------------------------
NON_CAPITO = "Non ho capito. Scrivi aiuto per vedere i comandi."
ESEMPIO_PS = "Non ho capito. Scrivi così: ps m: bagno & t: 10"
ESEMPIO_LV = "Non ho capito. Scrivi così: lv 30 (da 5 a 240 minuti, lv0 per chiudere)"
ESEMPIO_DM = "Non ho capito. Scrivi così: dm 45 (da 5 a 600 minuti)"
ESEMPIO_LB = "Non ho capito. Scrivi così: lb storia (oppure lb da solo per l'elenco, lb via storia per toglierlo)"
ESEMPIO_QD = "Non ho capito. Scrivi così: qd matematica (oppure qd da solo per l'elenco, qd via matematica per toglierlo)"
ESEMPIO_AG = "Non ho capito. Scrivi così: ag studio onenote.exe oppure ag lavoro github.com"
ESEMPIO_TG = "Non ho capito. Scrivi così: tg studio onenote.exe oppure tg lavoro github.com"
ESEMPIO_VS = "Non ho capito. Scrivi solo: vs"
ESEMPIO_TF = "Non ho capito. Scrivi solo: tf"
ESEMPIO_ST = "Non ho capito. Scrivi solo: st"

PAUSA_OK = "Pausa fino alle {fino}."
PAUSA_BUDGET = "Ti restano {minuti} minuti di pausa."
PAUSA_BUDGET_UNO = "Ti resta 1 minuto di pausa."
PAUSA_RESTA = ": resta quella fino alle {fino}."
LAVORO_OK = "Lavoro fino alle {fino}."
LAVORO_CHIUSO = "Lavoro chiuso."
LAVORO_NESSUNO = "Non c'è un tempo di lavoro aperto."
DORMO_OK = "Dormi pure fino alle {fino}. Fatti vedere sdraiato entro 5 minuti."
NON_SERVE_LIBERO = "Adesso sei libero: non serve."
NON_SERVE_INATTIVO = "Argus adesso è spento: non serve."

AIUTO = "\n".join([
    "ps m: <motivo> & t: <durata> - pausa (esempio: ps m: bagno & t: 10)",
    "lv <minuti> - tempo di lavoro, da 5 a 240 minuti; lv0 lo chiude",
    "dm <minuti> - dormo (esempio: dm 45)",
    "st - come sto andando oggi",
    "lb <nome> - registra un libro di scuola; lb da solo = elenco; lb via <nome> = toglie",
    "qd <nome> - registra un quaderno; qd da solo = elenco; qd via <nome> = toglie",
    "vs - registra il tuo viso (10 scatti)",
    "tf - registra il tuo telefono (6 scatti)",
    "ag <studio|lavoro> <programma.exe|sito> - aggiunge alla lista, vale dopo 4 giorni",
    "tg <studio|lavoro> <programma.exe|sito> - toglie dalla lista, vale subito",
    "aiuto - questo elenco",
])

# Registrazione di libri, quaderni, viso, telefono
FOTO_CONSIGLIO = {
    "lb": "Copertina e 2-3 pagine aperte.",
    "qd": "Copertina e 2-3 pagine aperte.",
    "vs": "Guarda la webcam e gira un po' la testa.",
    "tf": "Davanti, dietro e di lato.",
}
FOTO_SCATTI = {"lb": 6, "qd": 6, "vs": 10, "tf": 6}
NOMI_TIPO = {"lb": "libri", "qd": "quaderni"}
ELENCO_VUOTO = {"lb": "Nessun libro registrato.", "qd": "Nessun quaderno registrato."}
ELENCO = {"lb": "Libri registrati: {nomi}.", "qd": "Quaderni registrati: {nomi}."}
REGISTRA_PRONTO = {
    "lb": "Fai le foto del libro «{nome}».",
    "qd": "Fai le foto del quaderno «{nome}».",
    "vs": "Fai le foto del tuo viso.",
    "tf": "Fai le foto del tuo telefono.",
}
TOLTO = "«{nome}» tolto."
NON_TROVATO = "«{nome}» non c'è."
FOTO_SALVATE = "«{nome}» salvato ({n} foto)."
FOTO_VISO_SALVATE = "Viso salvato ({n} foto)."
FOTO_TELEFONO_SALVATE = "Telefono salvato ({n} foto)."
FOTO_NESSUN_VISO = "Non ho trovato il viso in nessuna foto. Riprova con più luce, guardando la webcam."
FOTO_OGGETTO_MANCA = {
    "tf": "Non vedo un telefono nelle foto: riprova inquadrandolo bene.",
    "lb": "Non vedo un libro nelle foto: riprova inquadrandolo bene.",
    "qd": "Non vedo un quaderno nelle foto: riprova inquadrandolo bene.",
}
FOTO_POCHE_VALIDE = "Solo {validi} foto su {n} vanno bene: ne servono almeno {minimo}. Riprova."

# Liste (ag / tg)
LISTA_VOCE_NON_VALIDA = "Non ho capito il programma o il sito. Scrivi per esempio onenote.exe oppure github.com"
LISTA_E_MAI = "{voce} è nella lista Mai: non si può aggiungere."
LISTA_GIA_PRESENTE = "{voce} è già nella lista {lista}."
LISTA_GIA_IN_ATTESA = "{voce} è già in arrivo nella lista {lista}: vale dal {quando}."
LISTA_AGGIUNTA = "{voce} sarà nella lista {lista} dal {quando}."
LISTA_TOLTA = "{voce} tolto dalla lista {lista}."
LISTA_NON_PRESENTE = "{voce} non è nella lista {lista}."

# Stato (st)
CLASSI_PAROLE = {
    "studio": "studio",
    "lavoro": "lavoro",
    "neutro": "neutro",
    "distrazione": "distrazione",
    "imbroglio": "imbroglio",
    "sospeso": "in sospeso",
    "nessuna": "niente",
}


def mancano(minuti: int) -> str:
    if minuti == 1:
        return COPERTURA_UN_MINUTO
    return COPERTURA.format(mancano=minuti)


def budget_pausa(minuti: int, resta_fino: str | None = None) -> str:
    """"Ti restano X minuti di pausa." e, se c'è una pausa in corso che resta, fino a quando."""
    testo = PAUSA_BUDGET_UNO if minuti == 1 else PAUSA_BUDGET.format(minuti=minuti)
    if resta_fino:
        testo = testo[:-1] + PAUSA_RESTA.format(fino=resta_fino)
    return testo
