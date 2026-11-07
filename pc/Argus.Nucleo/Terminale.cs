namespace Argus.Nucleo;

/// <summary>I testi fissi per lo studente: italiano semplice, senza emoji.</summary>
public static class Testi
{
    /// <summary>La seconda riga della copertura col tasto del terminale (di serie "Ctrl+Alt+T").</summary>
    public static string SecondaRigaCopertura(string tasto) => "Torna a una cosa permessa o apri il terminale: " + tasto;

    /// <summary>
    /// Quando il tasto del terminale è già preso da un altro programma (RegisterHotKey rifiutato) il testo non
    /// deve promettere un tasto che non funziona: il terminale si apre facendo clic sulla copertura.
    /// </summary>
    public const string SecondaRigaCoperturaSenzaTasto = "Torna a una cosa permessa o apri il terminale: fai clic qui.";
    public const string NasNonRisponde = "Il NAS non risponde: riprova tra poco.";
    public const string Benvenuto = "Argus. Scrivi un comando e premi Invio (aiuto per l'elenco). Esc nasconde la finestra.";

    /// <summary>Regole 8: l'elenco dei comandi, una riga ciascuno.</summary>
    public static readonly string Aiuto = string.Join("\n", new[]
    {
        "ps m: <motivo> & t: <durata>   pausa (esempio: ps m: bagno & t: 10)",
        "lv<minuti>                     tempo di lavoro (lv30); lv0 lo chiude",
        "dm<minuti>                     dormo (dm45)",
        "st                             come sto andando oggi",
        "lb <nome>                      registra un libro di scuola (lb: elenco, lb via <nome>: toglie)",
        "qd <nome>                      registra un quaderno (qd: elenco, qd via <nome>: toglie)",
        "vs                             registra il tuo viso (10 scatti)",
        "tf                             registra il tuo telefono (6 scatti)",
        "ag <studio|lavoro> <programma.exe|sito>   aggiunge alla lista (vale dopo 4 giorni)",
        "tg <studio|lavoro> <programma.exe|sito>   toglie dalla lista (vale subito)",
        "aiuto                          questo elenco",
    });
}

/// <summary>
/// I comandi quando il NAS non risponde: il NAS decide tutto, qui si risponde solo per non lasciare lo
/// studente senza niente. "aiuto" dà l'elenco, "st" dice cosa fa il PC adesso, il resto aspetta il NAS.
/// </summary>
public static class ComandiLocali
{
    public static string Rispondi(string testo, ModalitaEffettiva? modalita)
    {
        var t = (testo ?? "").Trim().ToLowerInvariant();
        if (t == "aiuto") return Testi.Aiuto;
        if (t == "st")
        {
            var cosa = modalita?.Modalita switch
            {
                Modalita.Studio => "Intanto il PC è in modalità studio.",
                Modalita.Lavoro => "Intanto il PC è in modalità lavoro.",
                Modalita.Libero => "Intanto il PC è libero.",
                _ => "Intanto Argus è fermo.",
            };
            return "Il NAS non risponde: la quota la sa solo lui. " + cosa;
        }
        return Testi.NasNonRisponde;
    }
}

/// <summary>
/// I campioni (uno al secondo) in attesa di partire con POST /api/pc/attivita: al massimo 30, i più recenti.
/// Se l'invio non riesce tornano in coda (sempre al massimo 30).
/// </summary>
public sealed class CodaCampioni
{
    public const int Massimo = 30;
    private readonly object chiave = new();
    private readonly LinkedList<Campione> coda = new();

    public void Aggiungi(Campione c)
    {
        lock (chiave)
        {
            coda.AddLast(c);
            while (coda.Count > Massimo) coda.RemoveFirst();
        }
    }

    public List<Campione> Preleva()
    {
        lock (chiave)
        {
            var tutti = coda.ToList();
            coda.Clear();
            return tutti;
        }
    }

    /// <summary>Rimette in testa i campioni non partiti (prima dei nuovi), tenendo i 30 più recenti.</summary>
    public void Rimetti(IReadOnlyList<Campione> campioni)
    {
        lock (chiave)
        {
            for (int i = campioni.Count - 1; i >= 0; i--) coda.AddFirst(campioni[i]);
            while (coda.Count > Massimo) coda.RemoveFirst();
        }
    }

    public int Quanti
    {
        get { lock (chiave) return coda.Count; }
    }
}
