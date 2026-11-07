using System.Text.Json;

namespace Argus.Nucleo;

/// <summary>
/// C:\ProgramData\Argus\config.json, scritto dall'installatore e leggibile solo da SYSTEM e amministratori
/// (contratto, sezione 1). Il guardiano lo legge e lo passa all'agente al momento dell'avvio, su una
/// conduttura privata (mai sulla riga di comando): così il token non sta in un file leggibile dallo studente.
/// Niente nomi veri, indirizzi o token nel codice: tutto qui.
/// </summary>
public sealed class ConfigArgus
{
    /// <summary>Indirizzo del NAS, per esempio "http://indirizzo-del-nas:8700".</summary>
    public string NasUrl { get; set; } = "";

    /// <summary>Il token del PC (contratto, sezione 1).</summary>
    public string Token { get; set; } = "";

    /// <summary>Il nome dell'account Windows dello studente: solo in quella sessione parte l'agente.</summary>
    public string? UtenteControllato { get; set; }

    /// <summary>Il sabato è giorno di scuola? (regole 2: spento di serie). Serve alla regola "senza NAS".</summary>
    public bool SabatoScuola { get; set; }

    /// <summary>Il patrono del comune, "GG/MM" (regole 2: vuoto di serie).</summary>
    public string? Patrono { get; set; }

    /// <summary>La combinazione che apre il terminale, per esempio "Ctrl+Alt+T" (di serie, se manca o non va bene).</summary>
    public string? TastoTerminale { get; set; }

    /// <summary>Il tasto del terminale da usare: quello della configurazione se è valido, altrimenti Ctrl+Alt+T.</summary>
    public TastoTerminale Tasto() => Nucleo.TastoTerminale.Leggi(TastoTerminale) ?? Nucleo.TastoTerminale.Predefinito;

    /// <summary>Cosa non va in "tasto_terminale" (null se va bene o se manca).</summary>
    public string? ProblemaTasto() =>
        string.IsNullOrWhiteSpace(TastoTerminale) || Nucleo.TastoTerminale.Leggi(TastoTerminale) != null
            ? null
            : $"\"tasto_terminale\" non valido ({TastoTerminale}): uso {Nucleo.TastoTerminale.DiSerie}";

    public ConfigMotore Motore { get; set; } = new();

    /// <summary>
    /// Il secondo segreto, solo per lo sblocco (contratto sezione 1): lo leggono Argus.Sblocco e il guardiano.
    /// <b>Mai passato all'agente</b>: <see cref="PerAgente"/> lo toglie.
    /// </summary>
    public string? SegretoSblocco { get; set; }

    /// <summary>
    /// Percorsi completi di programmi senza firma fatti in casa che valgono anche se stanno in cartelle dove lo
    /// studente può scrivere (regole 12, "programmi riconosciuti davvero").
    /// </summary>
    public List<string> PercorsiFidati { get; set; } = new();

    /// <summary>
    /// Solo nella configurazione che il guardiano passa all'agente: un segreto casuale di quell'avvio. Dice
    /// all'agente che l'ha avviato il guardiano (allora niente mutex con nome: l'istanza unica la garantisce il
    /// guardiano) e manda il battito. Non sta mai in config.json.
    /// </summary>
    public string? Istanza { get; set; }

    /// <summary>
    /// La configurazione da passare all'agente: senza il segreto dello sblocco, con il segreto dell'avvio.
    /// </summary>
    public string PerAgente(string istanza)
    {
        var copia = DaJson(InJson());
        copia.SegretoSblocco = null;
        copia.Istanza = istanza;
        return JsonSerializer.Serialize(copia, JsonArgus.Opzioni);
    }

    public static ConfigArgus DaJson(string json)
    {
        ConfigArgus? c;
        try
        {
            c = JsonSerializer.Deserialize<ConfigArgus>(json, JsonArgus.Opzioni);
        }
        catch (JsonException e)
        {
            throw new ErroreConfig($"Il file di configurazione non è scritto bene: {e.Message}");
        }
        if (c == null) throw new ErroreConfig("Il file di configurazione è vuoto.");
        c.Motore ??= new ConfigMotore();
        c.PercorsiFidati ??= new List<string>();
        return c;
    }

    public static ConfigArgus Carica(string percorso)
    {
        string testo;
        try
        {
            testo = File.ReadAllText(percorso);
        }
        catch (FileNotFoundException)
        {
            throw new ErroreConfig($"Non trovo il file di configurazione ({percorso}).");
        }
        catch (DirectoryNotFoundException)
        {
            throw new ErroreConfig($"Non trovo la cartella della configurazione ({percorso}).");
        }
        catch (UnauthorizedAccessException)
        {
            throw new ErroreConfig("Non ho il permesso di leggere il file di configurazione.");
        }
        catch (IOException e)
        {
            throw new ErroreConfig($"Non riesco a leggere il file di configurazione: {e.Message}");
        }
        return DaJson(testo);
    }

    public string InJson() => JsonSerializer.Serialize(this, JsonArgus.Indentate);

    /// <summary>Cosa non va per parlare col NAS, anche senza nessuna configurazione (null se va bene).</summary>
    public static string? Problema(ConfigArgus? config) => config == null ? "manca la configurazione" : config.ProblemaNas();

    /// <summary>Cosa non va per parlare col NAS (null se va bene). Testi in italiano.</summary>
    public string? ProblemaNas()
    {
        if (string.IsNullOrWhiteSpace(NasUrl)) return "Manca l'indirizzo del NAS.";
        if (!Uri.TryCreate(NasUrl.Trim(), UriKind.Absolute, out var u) || (u.Scheme != "http" && u.Scheme != "https"))
            return "L'indirizzo del NAS non è valido (deve cominciare con http:// o https://).";
        if (string.IsNullOrWhiteSpace(Token)) return "Manca il token del PC.";
        return null;
    }
}

/// <summary>Il motore del modello per le foto dubbie (regole 10). Tutto configurabile.</summary>
public sealed class ConfigMotore
{
    /// <summary>Spento: il PC non prende mai lavori.</summary>
    public bool Attivo { get; set; } = true;

    /// <summary>Dove cercare i motori di LM Studio. Vuoto: %USERPROFILE%\.lmstudio\extensions\backends (dell'utente dell'agente).</summary>
    public string? CartellaBackends { get; set; }

    /// <summary>Si usa la cartella con la versione più alta tra quelle che cominciano così.</summary>
    public string PrefissoBackend { get; set; } = "llama.cpp-win-x86_64-avx2-";

    /// <summary>Percorso esplicito di llama-server.exe (vince sulla ricerca nella cartella dei motori).</summary>
    public string? LlamaServer { get; set; }

    /// <summary>Il motore parte solo se l'eseguibile ha una firma valida il cui nome contiene questo testo. Vuoto: nessun controllo.</summary>
    public string? FirmaMotore { get; set; } = "Element Labs";

    public string Modello { get; set; } = Path.Combine(Percorsi.Modelli, "Qwen3.5-9B-Q4_K_M.gguf");
    public string Mmproj { get; set; } = Path.Combine(Percorsi.Modelli, "mmproj-Qwen3.5-9B-BF16.gguf");
    public string NomeModello { get; set; } = "Qwen3.5-9B-Q4_K_M";
    public int Porta { get; set; } = 8781;

    /// <summary>Thread del processore per il motore. Vuoto: metà dei processori logici (il PC resta usabile).</summary>
    public int? Thread { get; set; }

    public int Contesto { get; set; } = 4096;
    public int MinutiSpegnimento { get; set; } = 5;
    public double MemoriaMinimaGb { get; set; } = 8;
    public double CpuMassimaPercento { get; set; } = 50;

    /// <summary>Quanto si aspetta che il motore carichi il modello.</summary>
    public int SecondiCaricamento { get; set; } = 300;

    /// <summary>Quanto si aspetta la risposta su un lavoro (il NAS tiene il lavoro "preso" 3 minuti).</summary>
    public int SecondiRisposta { get; set; } = 170;

    public int ThreadEffettivi() => Thread is int t && t > 0 ? t : Math.Max(1, Environment.ProcessorCount / 2);
}

public sealed class ErroreConfig : Exception
{
    public ErroreConfig(string messaggio) : base(messaggio)
    {
    }
}
