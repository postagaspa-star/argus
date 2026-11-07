namespace Argus.Nucleo;

/// <summary>Il risultato del controllo delle condizioni, con il perché in italiano.</summary>
public readonly record struct VerificaCondizioni(bool Valide, string Motivo);

/// <summary>
/// Le condizioni per far lavorare il modello sul PC (regole 10): attaccato alla corrente, almeno 8 GB di
/// memoria libera, processore sotto il 50% nell'ultimo minuto.
/// <list type="bullet">
/// <item>il processore si misura escludendo il motore stesso (altrimenti, mentre lavora, il motore
/// spegnerebbe sé stesso); la memoria conta come libera anche quella che il motore sta usando;</item>
/// <item>serve un minuto intero di misure (almeno 55 secondi) prima di dire sì;</item>
/// <item>un PC senza batteria è sempre "alla corrente"; con la batteria, uno stato sconosciuto vale no.</item>
/// </list>
/// Non è thread-safe: la usa un solo thread.
/// </summary>
public sealed class CondizioniModello
{
    private readonly long memoriaMinima;
    private readonly double cpuMassima;
    private readonly long finestraMs;
    private readonly Queue<(long Ms, long Totale, long Inattivo, long Motore)> misure = new();

    public CondizioniModello(double memoriaMinimaGb = 8, double cpuMassimaPercento = 50, long finestraMs = 60_000)
    {
        memoriaMinima = (long)(memoriaMinimaGb * 1024 * 1024 * 1024);
        cpuMassima = cpuMassimaPercento / 100.0;
        this.finestraMs = finestraMs;
    }

    /// <summary>
    /// Una misura del processore dall'ultima: tempo totale (somma di tutti i processori, in unità qualsiasi purché
    /// uguali), di cui inattivo, e quanto ne ha usato il motore.
    /// </summary>
    public void AggiungiCpu(long adessoMs, long deltaTotale, long deltaInattivo, long deltaMotore)
    {
        if (deltaTotale <= 0) return;
        misure.Enqueue((adessoMs, deltaTotale, Math.Clamp(deltaInattivo, 0, deltaTotale), Math.Max(0, deltaMotore)));
        while (misure.Count > 0 && adessoMs - misure.Peek().Ms > finestraMs) misure.Dequeue();
    }

    /// <summary>Il processore usato dagli altri programmi (0-1) nell'ultimo minuto, o null se le misure non bastano.</summary>
    public double? CpuAltri(long adessoMs)
    {
        while (misure.Count > 0 && adessoMs - misure.Peek().Ms > finestraMs) misure.Dequeue();
        if (misure.Count == 0) return null;
        // La prima misura copre l'intervallo che la precede: serve che l'insieme copra quasi tutto il minuto.
        long piùVecchia = misure.Peek().Ms;
        if (adessoMs - piùVecchia < finestraMs - 10_000) return null;
        long totale = 0, occupato = 0;
        foreach (var m in misure)
        {
            totale += m.Totale;
            occupato += Math.Max(0, m.Totale - m.Inattivo - m.Motore);
        }
        return totale <= 0 ? null : (double)occupato / totale;
    }

    public VerificaCondizioni Valuta(long adessoMs, bool? allaCorrente, bool haBatteria, long memoriaLibera, long memoriaMotore)
    {
        bool corrente = !haBatteria || allaCorrente == true;
        if (!corrente) return new VerificaCondizioni(false, "il PC va a batteria");
        long libera = memoriaLibera + Math.Max(0, memoriaMotore);
        if (libera < memoriaMinima)
            return new VerificaCondizioni(false, $"memoria libera {libera / (1024.0 * 1024 * 1024):0.0} GB, ne servono {memoriaMinima / (1024.0 * 1024 * 1024):0.#}");
        var cpu = CpuAltri(adessoMs);
        if (cpu is null) return new VerificaCondizioni(false, "misuro ancora il processore (serve un minuto)");
        if (cpu.Value >= cpuMassima)
            return new VerificaCondizioni(false, $"processore al {cpu.Value * 100:0}% nell'ultimo minuto");
        return new VerificaCondizioni(true, "ok");
    }
}
