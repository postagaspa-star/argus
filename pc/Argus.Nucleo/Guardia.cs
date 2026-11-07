namespace Argus.Nucleo;

/// <summary>
/// Quando il guardiano può riaprire l'agente uscito (regole 12: "entro pochi secondi"; brief: entro 3 s).
/// Di regola dopo 1 secondo. Solo se l'agente muore DA SOLO poco dopo l'avvio (entro 10 secondi) per 5 volte in
/// un minuto (per esempio manca un pezzo e si chiude subito) si aspetta 30 secondi tra un tentativo e l'altro,
/// per non girare a vuoto. Un agente chiuso da altri (dal guardiano perché bloccato, o da un messaggio di uscita
/// mandato da un altro programma: codice 5) o vissuto più di 10 secondi si riapre sempre dopo 1 secondo: così
/// chiuderlo di continuo non regala mai la pausa di 30 secondi.
/// </summary>
public sealed class PoliticaRiavvio
{
    public const long AttesaMs = 1000;
    public const int UsciteMassime = 5;
    public const long FinestraMs = 60_000;
    public const long PausaMs = 30_000;
    public const long VitaBreveMs = 10_000;

    private readonly List<long> usciteBrevi = new();
    private long ultimaUscita;
    private bool uscito;

    /// <param name="adessoMs">quando è uscito</param>
    /// <param name="avviatoMs">quando era partito</param>
    /// <param name="daSolo">falso se l'ha chiuso qualcun altro (il guardiano perché bloccato, codice 5)</param>
    public void Uscito(long adessoMs, long avviatoMs, bool daSolo)
    {
        uscito = true;
        ultimaUscita = adessoMs;
        if (daSolo && adessoMs - avviatoMs < VitaBreveMs) usciteBrevi.Add(adessoMs);
        usciteBrevi.RemoveAll(u => adessoMs - u > FinestraMs);
    }

    /// <summary>Non è nemmeno partito (CreateProcessAsUser fallito): conta come un'uscita breve.</summary>
    public void NonAvviato(long adessoMs) => Uscito(adessoMs, adessoMs, daSolo: true);

    public bool PuòRiaprire(long adessoMs)
    {
        if (!uscito) return true;
        if (UsciteRecenti(adessoMs) >= UsciteMassime && adessoMs - usciteBrevi[^1] < PausaMs) return false;
        return adessoMs - ultimaUscita >= AttesaMs;
    }

    /// <summary>Le uscite brevi "da solo" dell'ultimo minuto.</summary>
    public int UsciteRecenti(long adessoMs) => usciteBrevi.Count(u => adessoMs - u <= FinestraMs);
}

public static class Utenti
{
    /// <summary>
    /// L'utente della sessione è quello controllato? Senza maiuscole/minuscole; in config si accetta anche
    /// "DOMINIO\utente" o "utente@dominio" (conta solo il nome). Un utente controllato vuoto non vale per nessuno.
    /// </summary>
    public static bool ÈControllato(string? utenteSessione, string? utenteControllato)
    {
        static string Nome(string s)
        {
            var t = s.Trim();
            int barra = t.LastIndexOf('\\');
            if (barra >= 0) t = t[(barra + 1)..];
            int chiocciola = t.IndexOf('@');
            if (chiocciola > 0) t = t[..chiocciola];
            return t;
        }
        if (string.IsNullOrWhiteSpace(utenteSessione) || string.IsNullOrWhiteSpace(utenteControllato)) return false;
        return string.Equals(Nome(utenteSessione), Nome(utenteControllato), StringComparison.OrdinalIgnoreCase);
    }
}
