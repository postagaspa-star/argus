using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Argus.Nucleo;

/// <summary>L'orologio, da fuori: così le prove possono far passare il tempo come vogliono.</summary>
public interface IOrologio
{
    /// <summary>L'ora del PC (con il fuso).</summary>
    DateTimeOffset Adesso { get; }

    /// <summary>Millisecondi di un cronometro che va solo avanti (non cambia se si sposta l'ora del PC).</summary>
    long Ms { get; }
}

public sealed class OrologioSistema : IOrologio
{
    public static readonly OrologioSistema Istanza = new();
    public DateTimeOffset Adesso => DateTimeOffset.Now;
    public long Ms => Environment.TickCount64;
}

public static class Tempo
{
    /// <summary>ISO 8601 con l'offset e i millisecondi: "2026-11-09T15:20:00.000+01:00" (lo legge anche Python).</summary>
    public static string Iso(DateTimeOffset t) =>
        t.ToString("yyyy-MM-dd'T'HH:mm:ss.fffzzz", CultureInfo.InvariantCulture);

    public static DateTimeOffset? Leggi(string? testo) =>
        !string.IsNullOrWhiteSpace(testo)
        && DateTimeOffset.TryParse(testo, CultureInfo.InvariantCulture, DateTimeStyles.None, out var t)
            ? t
            : null;

    /// <summary>Il fuso che conta per le regole (Europe/Rome), anche se qualcuno cambia il fuso del PC.</summary>
    public static TimeZoneInfo FusoItalia { get; } = TrovaFuso();

    private static TimeZoneInfo TrovaFuso()
    {
        foreach (var id in new[] { "Europe/Rome", "W. Europe Standard Time" })
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById(id);
            }
            catch (Exception e) when (e is TimeZoneNotFoundException or InvalidTimeZoneException)
            {
            }
        }
        return TimeZoneInfo.Local;
    }

    /// <summary>L'ora "da orologio da muro" in Italia.</summary>
    public static DateTime OraItaliana(DateTimeOffset t) => TimeZoneInfo.ConvertTime(t, FusoItalia).DateTime;

    /// <summary>"15:52" per i testi.</summary>
    public static string OreMinuti(DateTimeOffset t) => OraItaliana(t).ToString("HH:mm", CultureInfo.InvariantCulture);
}

/// <summary>Le opzioni JSON comuni: nomi in snake_case come nel contratto, lettere accentate leggibili.</summary>
public static class JsonArgus
{
    public static readonly JsonSerializerOptions Opzioni = Crea(false);
    public static readonly JsonSerializerOptions Indentate = Crea(true);

    private static JsonSerializerOptions Crea(bool indentate) => new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = indentate,
    };
}

/// <summary>Le cartelle di Argus sul PC.</summary>
public static class Percorsi
{
    /// <summary>C:\ProgramData\Argus: config, sblocco, modelli, log del guardiano. Scrivono solo SYSTEM e amministratori.</summary>
    public static string CartellaDati { get; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "Argus");

    public static string Config => Path.Combine(CartellaDati, "config.json");
    public static string Sblocco => Path.Combine(CartellaDati, "sblocco.json");
    public static string Modelli => Path.Combine(CartellaDati, "modelli");
    public static string LogGuardiano => Path.Combine(CartellaDati, "log");

    /// <summary>%LOCALAPPDATA%\Argus dell'utente: log dell'agente, dati della WebView2.</summary>
    public static string CartellaUtente =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Argus");
}

/// <summary>
/// Un diario tecnico semplice su file, a prova di più thread, che si rinnova a 1 MB. Mai token, mai indirizzi
/// completi, mai titoli delle finestre: solo cosa fa il programma.
/// </summary>
public static class Log
{
    private static readonly object Chiave = new();
    private static string? file;
    private const long Massimo = 1_000_000;

    public static void Imposta(string cartella, string nome)
    {
        try
        {
            Directory.CreateDirectory(cartella);
            lock (Chiave) file = Path.Combine(cartella, nome);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            // Senza cartella si va avanti senza diario.
        }
    }

    public static void Info(string testo) => Scrivi("INFO", testo);
    public static void Avviso(string testo) => Scrivi("AVVISO", testo);
    public static void Errore(string testo, Exception? e = null) =>
        Scrivi("ERRORE", e == null ? testo : $"{testo}: {e.GetType().Name}: {e.Message}");

    private static void Scrivi(string livello, string testo)
    {
        lock (Chiave)
        {
            if (file == null) return;
            try
            {
                var info = new FileInfo(file);
                if (info.Exists && info.Length > Massimo)
                {
                    var vecchio = file + ".1";
                    File.Delete(vecchio);
                    File.Move(file, vecchio);
                }
                File.AppendAllText(file,
                    $"{DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture)} {livello} {testo}{Environment.NewLine}",
                    Encoding.UTF8);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
            }
        }
    }
}

public static class FileSicuri
{
    /// <summary>Scrittura atomica: file temporaneo accanto, poi rinomina. Un file a metà non resta mai.</summary>
    public static void ScriviAtomico(string percorso, string testo)
    {
        var cartella = Path.GetDirectoryName(percorso);
        if (!string.IsNullOrEmpty(cartella)) Directory.CreateDirectory(cartella);
        var temporaneo = percorso + ".tmp";
        File.WriteAllText(temporaneo, testo, new UTF8Encoding(false));
        File.Move(temporaneo, percorso, overwrite: true);
    }
}
