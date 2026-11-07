using System.Text.Json;

namespace Argus.Nucleo;

/// <summary>
/// Lo sblocco d'emergenza (regole 12): scritto da Argus.Sblocco (amministratore) in
/// C:\ProgramData\Argus\sblocco.json, che solo amministratori e SYSTEM possono scrivere. L'agente lo legge
/// (PC libero finché vale), il guardiano lo legge e manda l'evento al NAS se Argus.Sblocco non ci è riuscito.
/// </summary>
public sealed class Sblocco
{
    public int Ore { get; set; }
    public string Fino { get; set; } = "";
    public string Creato { get; set; } = "";

    /// <summary>Il NAS ha già ricevuto l'evento sblocco_emergenza.</summary>
    public bool Inviato { get; set; }

    public const int OreMinime = 1;
    public const int OreMassime = 48;

    public static Sblocco Nuovo(int ore, DateTimeOffset adesso)
    {
        if (ore < OreMinime || ore > OreMassime)
            throw new ArgumentOutOfRangeException(nameof(ore), $"Le ore vanno da {OreMinime} a {OreMassime}.");
        return new Sblocco { Ore = ore, Creato = Tempo.Iso(adesso), Fino = Tempo.Iso(adesso.AddHours(ore)) };
    }

    /// <summary>Lo sblocco tolto prima del tempo: 0 ore, finito adesso.</summary>
    public static Sblocco Tolto(DateTimeOffset adesso) =>
        new() { Ore = 0, Creato = Tempo.Iso(adesso), Fino = Tempo.Iso(adesso) };

    /// <summary>
    /// Vale adesso? Ore 1-48, fine nel futuro, durata coerente con le ore, creato non nel futuro (un orologio
    /// spostato indietro non allunga lo sblocco).
    /// </summary>
    public bool Attivo(DateTimeOffset adesso)
    {
        if (Ore < OreMinime || Ore > OreMassime) return false;
        if (Tempo.Leggi(Fino) is not DateTimeOffset fino || Tempo.Leggi(Creato) is not DateTimeOffset creato) return false;
        if (fino <= adesso) return false;
        if (fino - creato > TimeSpan.FromHours(Ore) + TimeSpan.FromMinutes(1)) return false;
        if (creato > adesso + TimeSpan.FromMinutes(5)) return false;
        return true;
    }

    public DateTimeOffset? FinoData => Tempo.Leggi(Fino);

    public string InJson() => JsonSerializer.Serialize(this, JsonArgus.Indentate);

    /// <summary>Lo sblocco dal file, o null (manca, rovinato, illeggibile). Mai un'eccezione.</summary>
    public static Sblocco? Leggi(string percorso)
    {
        try
        {
            if (!File.Exists(percorso)) return null;
            return JsonSerializer.Deserialize<Sblocco>(File.ReadAllText(percorso), JsonArgus.Opzioni);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }
    }

    public static bool AttivoNelFile(string percorso, DateTimeOffset adesso) => Leggi(percorso)?.Attivo(adesso) == true;

    /// <summary>
    /// Contratto (evento sblocco_emergenza): solo <c>ore</c>, intero 0-48 (0 = togli lo sblocco). La fine la calcola
    /// il NAS col suo orologio: il PC non manda più <c>fino</c>.
    /// </summary>
    public Dictionary<string, object?> DettagliEvento() => new() { ["ore"] = Math.Clamp(Ore, 0, OreMassime) };
}
