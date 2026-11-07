namespace Argus.Nucleo;

/// <summary>Come è stato riconosciuto un programma (regole 12, "programmi riconosciuti davvero").</summary>
public enum ComeRiconosciuto
{
    /// <summary>Un programma di Argus, dalla sua cartella in Program Files e col suo nome esatto.</summary>
    Argus,

    /// <summary>In Program Files, Program Files (x86) o Windows, in una cartella dove lo studente non può scrivere: vale il nome.</summary>
    CartellaProtetta,

    /// <summary>In una cartella dello studente, con firma Authenticode valida: vale il nome originale scritto nel file.</summary>
    Firma,

    /// <summary>Il percorso completo è tra i <c>percorsi_fidati</c> della configurazione.</summary>
    PercorsoFidato,

    /// <summary>In una cartella dello studente, senza firma valida o senza nome originale: non vale per le liste.</summary>
    NonRiconosciuto,

    /// <summary>Il percorso del programma non si legge: non vale per le liste.</summary>
    SenzaPercorso,
}

/// <summary>
/// Il programma in primo piano (o che suona), riconosciuto.
/// </summary>
/// <param name="NomeFile">Il nome del file com'è (minuscolo), per esempio "soffice.exe".</param>
/// <param name="Nome">Il nome che vale per le liste (minuscolo, con ".exe"), o null se il programma non è riconosciuto.</param>
/// <param name="Come">Come è stato riconosciuto.</param>
/// <param name="NomeOriginale">Il nome originale scritto nella versione del file (minuscolo, con ".exe"), se c'è.</param>
public sealed record Riconoscimento(string NomeFile, string? Nome, ComeRiconosciuto Come, string? NomeOriginale = null)
{
    public const string PrefissoNonRiconosciuto = "non_riconosciuto:";

    public bool Riconosciuto => Nome != null;

    /// <summary>
    /// Il nome da mandare al NAS nei campioni (<c>processo</c>, <c>audio</c>). Un programma non riconosciuto va
    /// come "non_riconosciuto:gioco.exe": così il NAS, che giudica i campioni dal nome, non lo conta come studio.
    /// Se però il nome del file o quello originale sono nella lista "mai", va il nome così com'è (il NAS deve
    /// vederlo).
    /// </summary>
    public string NomePerNas(Liste liste)
    {
        if (Nome != null) return Nome;
        if (NomeFile.Length == 0) return "";
        if (Confronto.ProgrammaInLista(NomeFile, liste.Mai.Programmi)) return NomeFile;
        if (NomeOriginale != null && Confronto.ProgrammaInLista(NomeOriginale, liste.Mai.Programmi)) return NomeOriginale;
        return PrefissoNonRiconosciuto + NomeFile;
    }

    /// <summary>Per le prove e per chi ha già controllato il programma: riconosciuto dal nome (cartella protetta).</summary>
    public static Riconoscimento DalNome(string exe)
    {
        var n = RiconoscitoreProgrammi.NomeExe(exe);
        return new Riconoscimento(n, n, ComeRiconosciuto.CartellaProtetta);
    }
}

/// <summary>Quello che serve sapere di un file su disco. Nell'agente lo fa Windows, nelle prove un finto.</summary>
public interface ISistemaFile
{
    /// <summary>Data di modifica e dimensione, o null se il file non si legge (per la memoria dei controlli).</summary>
    (DateTime Modifica, long Byte)? Impronta(string percorso);

    /// <summary>
    /// Lo studente (l'utente che fa girare l'agente) può cambiare questo file o aggiungere file nella sua cartella?
    /// Nel dubbio sì.
    /// </summary>
    bool Scrivibile(string percorso);

    /// <summary>Firma Authenticode valida, con la radice della catena fidata dal computer (non solo dall'utente).</summary>
    bool FirmaValida(string percorso);

    /// <summary>OriginalFilename della versione del file, o null.</summary>
    string? NomeOriginale(string percorso);
}

/// <summary>
/// Riconosce un programma dal percorso, non solo dal nome (regole 12; revisione B5):
/// <list type="bullet">
/// <item>i programmi di Argus valgono solo dalla loro cartella in Program Files e col nome esatto; un altro
/// programma che si chiama "argus..." non vale mai per le liste;</item>
/// <item>in Program Files, Program Files (x86) e Windows basta il nome, se lo studente non può scrivere in quella
/// cartella (in Windows\Temp, per esempio, può: lì vale come una cartella dello studente);</item>
/// <item>altrove (profilo, Download, Desktop, OneDrive, Temp, AppData, altri dischi...) vale solo con una firma
/// valida e il nome originale scritto nel file, oppure se il percorso completo è tra i percorsi fidati.</item>
/// </list>
/// Firma, nome originale e permessi si controllano una volta per percorso, data di modifica e dimensione: il
/// risultato resta in memoria (al massimo 500 programmi).
/// </summary>
public sealed class RiconoscitoreProgrammi
{
    private const int MassimoMemorie = 500;

    private readonly ISistemaFile fs;
    private readonly string[] cartelleProtette;
    private readonly string cartellaArgus;
    private readonly HashSet<string> percorsiFidati;
    private readonly Dictionary<string, (DateTime, long, Riconoscimento)> memoria = new(StringComparer.OrdinalIgnoreCase);
    private readonly object chiave = new();

    /// <param name="cartelleProtette">Program Files, Program Files (x86), Windows.</param>
    /// <param name="cartellaArgus">C:\Program Files\Argus.</param>
    public RiconoscitoreProgrammi(ISistemaFile fs, IEnumerable<string> cartelleProtette, string cartellaArgus, IEnumerable<string>? percorsiFidati)
    {
        this.fs = fs;
        this.cartelleProtette = cartelleProtette.Where(c => !string.IsNullOrWhiteSpace(c)).Select(Cartella).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        this.cartellaArgus = Cartella(cartellaArgus);
        this.percorsiFidati = new HashSet<string>((percorsiFidati ?? Array.Empty<string>()).Select(Pieno).Where(p => p != null)!, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>Le cartelle protette di questo Windows.</summary>
    public static string[] CartelleDiSistema() => new[]
    {
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
        Environment.GetFolderPath(Environment.SpecialFolder.Windows),
    };

    public static string CartellaArgusDiSerie() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Argus");

    /// <summary>"Soffice.EXE" → "soffice.exe"; "lectio" → "lectio.exe".</summary>
    public static string NomeExe(string? nome)
    {
        var n = (nome ?? "").Trim().ToLowerInvariant();
        if (n.Length == 0) return "";
        return n.EndsWith(".exe", StringComparison.Ordinal) ? n : n + ".exe";
    }

    public Riconoscimento Riconosci(string? exe, string? percorso)
    {
        string nomeFile = Confronto.NormalizzaProgramma(string.IsNullOrWhiteSpace(exe) ? Path.GetFileName(percorso ?? "") : exe);
        var pieno = Pieno(percorso);
        if (pieno == null) return new Riconoscimento(nomeFile, null, ComeRiconosciuto.SenzaPercorso);
        nomeFile = Confronto.NormalizzaProgramma(Path.GetFileName(pieno));

        var impronta = fs.Impronta(pieno);
        if (impronta is (DateTime m, long b))
        {
            lock (chiave)
            {
                if (memoria.TryGetValue(pieno, out var v) && v.Item1 == m && v.Item2 == b) return v.Item3;
            }
        }
        var r = Calcola(nomeFile, pieno);
        if (impronta is (DateTime m2, long b2))
        {
            lock (chiave)
            {
                if (memoria.Count >= MassimoMemorie) memoria.Clear();
                memoria[pieno] = (m2, b2, r);
            }
        }
        return r;
    }

    private Riconoscimento Calcola(string nomeFile, string pieno)
    {
        var cartella = Path.GetDirectoryName(pieno) ?? "";
        bool nomeArgus = nomeFile.StartsWith("argus", StringComparison.Ordinal);

        // 1. Argus: solo C:\Program Files\Argus\<nome esatto>.
        if (GiudiceFinestra.ProgrammiArgus.Contains(nomeFile) && string.Equals(Cartella(cartella), cartellaArgus, StringComparison.OrdinalIgnoreCase))
            return new Riconoscimento(nomeFile, nomeFile, ComeRiconosciuto.Argus);

        // 2. Percorsi fidati (app fatte in casa, senza firma).
        if (percorsiFidati.Contains(pieno))
            return nomeArgus
                ? new Riconoscimento(nomeFile, null, ComeRiconosciuto.NonRiconosciuto)
                : new Riconoscimento(nomeFile, nomeFile, ComeRiconosciuto.PercorsoFidato);

        // 3. Cartelle di sistema dove lo studente non scrive: vale il nome.
        bool protetta = cartelleProtette.Any(c => (Cartella(cartella) + "\\").StartsWith(c + "\\", StringComparison.OrdinalIgnoreCase));
        if (protetta && !fs.Scrivibile(pieno))
            return nomeArgus
                ? new Riconoscimento(nomeFile, null, ComeRiconosciuto.NonRiconosciuto)
                : new Riconoscimento(nomeFile, nomeFile, ComeRiconosciuto.CartellaProtetta);

        // 4. Cartella dello studente: firma valida + nome originale.
        string? originale = null;
        var grezzo = fs.NomeOriginale(pieno);
        if (!string.IsNullOrWhiteSpace(grezzo)) originale = NomeExe(Path.GetFileName(grezzo.Trim()));
        if (originale != null && !originale.StartsWith("argus", StringComparison.Ordinal) && fs.FirmaValida(pieno))
            return new Riconoscimento(nomeFile, originale, ComeRiconosciuto.Firma, originale);
        return new Riconoscimento(nomeFile, null, ComeRiconosciuto.NonRiconosciuto, originale);
    }

    private static string Cartella(string c) => c.Trim().TrimEnd('\\', '/').Replace('/', '\\');

    /// <summary>Il percorso completo e normalizzato, o null se non è un percorso completo.</summary>
    public static string? Pieno(string? percorso)
    {
        if (string.IsNullOrWhiteSpace(percorso)) return null;
        var p = percorso.Trim().Trim('"');
        if (p.StartsWith(@"\\?\", StringComparison.Ordinal)) p = p[4..];
        if (!Path.IsPathFullyQualified(p)) return null;
        try
        {
            return Path.GetFullPath(p).TrimEnd('\\');
        }
        catch (Exception e) when (e is ArgumentException or NotSupportedException or PathTooLongException)
        {
            return null;
        }
    }
}
