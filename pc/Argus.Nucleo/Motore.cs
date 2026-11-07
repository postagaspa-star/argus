using System.ComponentModel;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;

namespace Argus.Nucleo;

/// <summary>La risposta del motore a una domanda.</summary>
public sealed record RispostaMotore(bool Ok, string? Corpo, string? Errore, bool Annullata = false);

/// <summary>Il motore del modello: acceso al bisogno, mai due copie (regole 10).</summary>
public interface IMotore : IDisposable
{
    bool Acceso { get; }

    /// <summary>Accende il motore e aspetta che il modello sia caricato. Null se va bene, altrimenti il motivo.</summary>
    Task<string?> AvviaAsync(CancellationToken ct);

    Task<RispostaMotore> ChiediAsync(string corpoJson, TimeSpan tempo, CancellationToken ct);

    void Spegni(string motivo);

    /// <summary>Memoria usata dal motore (byte), 0 se spento.</summary>
    long Memoria();

    /// <summary>Tempo di processore usato dal motore finora (unità da 100 ns), 0 se spento.</summary>
    long TempoCpu();
}

/// <summary>
/// llama-server.exe di LM Studio (preso dalla sua cartella, mai modificato): solo processore, solo 127.0.0.1,
/// priorità bassa, dentro un "job" di Windows che lo chiude se l'agente muore (niente motori orfani).
/// </summary>
public sealed class MotoreLlama : IMotore
{
    private readonly ConfigMotore cfg;
    private readonly string? fileLog;
    private readonly Func<string, string?>? firmaDi;
    private readonly HttpClient http = new() { Timeout = Timeout.InfiniteTimeSpan };
    private readonly object chiave = new();
    private Process? processo;
    private IntPtr job;
    private long cpuMotoriPrecedenti;

    /// <param name="firmaDi">Il soggetto della firma valida di un file (o null). Serve se cfg.FirmaMotore è impostato.</param>
    public MotoreLlama(ConfigMotore cfg, string? fileLog, Func<string, string?>? firmaDi)
    {
        this.cfg = cfg;
        this.fileLog = fileLog;
        this.firmaDi = firmaDi;
    }

    public bool Acceso
    {
        get
        {
            lock (chiave) return processo != null && !HaFinito(processo);
        }
    }

    private Uri Base => new($"http://127.0.0.1:{cfg.Porta}/");

    public async Task<string?> AvviaAsync(CancellationToken ct)
    {
        lock (chiave)
        {
            if (processo != null && !HaFinito(processo)) return null;
        }
        var exe = TrovaMotore.LlamaServer(cfg, d => Directory.EnumerateDirectories(d), File.Exists, out var motivo);
        if (exe == null) return motivo;
        if (!File.Exists(cfg.Modello)) return $"manca il modello ({cfg.Modello})";
        if (!File.Exists(cfg.Mmproj)) return $"manca la parte visiva del modello ({cfg.Mmproj})";
        if (!string.IsNullOrWhiteSpace(cfg.FirmaMotore))
        {
            var soggetto = firmaDi?.Invoke(exe);
            if (soggetto == null || !soggetto.Contains(cfg.FirmaMotore!, StringComparison.OrdinalIgnoreCase))
                return $"il motore non ha una firma valida di {cfg.FirmaMotore}";
        }
        if (await PortaOccupataAsync(cfg.Porta).ConfigureAwait(false))
            return $"la porta {cfg.Porta} è già occupata da un altro programma";

        var info = new ProcessStartInfo(exe)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(exe)!,
        };
        foreach (var a in TrovaMotore.Argomenti(cfg, fileLog)) info.ArgumentList.Add(a);
        Process p;
        try
        {
            p = Process.Start(info) ?? throw new InvalidOperationException("processo non partito");
        }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException or IOException)
        {
            return $"il motore non parte: {e.Message}";
        }
        try
        {
            p.PriorityClass = ProcessPriorityClass.BelowNormal;
        }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException)
        {
        }
        lock (chiave)
        {
            processo = p;
            job = Job.Lega(p);
        }
        Log.Info($"motore acceso (pid {p.Id}, {cfg.ThreadEffettivi()} thread)");

        // Si aspetta che il modello sia caricato: /health risponde 200 solo a modello pronto.
        var limite = Stopwatch.StartNew();
        while (limite.Elapsed < TimeSpan.FromSeconds(cfg.SecondiCaricamento))
        {
            if (ct.IsCancellationRequested)
            {
                Spegni("caricamento annullato");
                return "caricamento annullato";
            }
            if (HaFinito(p))
            {
                int codice = SafeExitCode(p);
                Spegni("uscito durante il caricamento");
                return $"il motore si è chiuso durante il caricamento (codice {codice})";
            }
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(TimeSpan.FromSeconds(2));
                using var r = await http.GetAsync(new Uri(Base, "health"), cts.Token).ConfigureAwait(false);
                if (r.IsSuccessStatusCode) return null;
            }
            catch (Exception e) when (e is HttpRequestException or OperationCanceledException or IOException)
            {
            }
            try
            {
                await Task.Delay(500, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
        Spegni("caricamento troppo lungo");
        return $"il modello non si è caricato in {cfg.SecondiCaricamento} secondi";
    }

    public async Task<RispostaMotore> ChiediAsync(string corpoJson, TimeSpan tempo, CancellationToken ct)
    {
        if (!Acceso) return new RispostaMotore(false, null, "motore spento");
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(tempo);
        try
        {
            using var contenuto = new StringContent(corpoJson, Encoding.UTF8);
            contenuto.Headers.ContentType = new MediaTypeHeaderValue("application/json");
            using var r = await http.PostAsync(new Uri(Base, "v1/chat/completions"), contenuto, cts.Token).ConfigureAwait(false);
            var testo = await r.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
            if (!r.IsSuccessStatusCode)
                return new RispostaMotore(false, testo, $"il motore ha risposto {(int)r.StatusCode}");
            return new RispostaMotore(true, testo, null);
        }
        catch (OperationCanceledException)
        {
            return new RispostaMotore(false, null, ct.IsCancellationRequested ? "domanda annullata" : "il motore ci ha messo troppo", Annullata: ct.IsCancellationRequested);
        }
        catch (Exception e) when (e is HttpRequestException or IOException)
        {
            return new RispostaMotore(false, null, "il motore non risponde");
        }
    }

    public void Spegni(string motivo)
    {
        Process? p;
        IntPtr j;
        lock (chiave)
        {
            p = processo;
            j = job;
            processo = null;
            job = IntPtr.Zero;
        }
        if (p == null) return;
        try
        {
            cpuMotoriPrecedenti += SafeCpu(p);
            if (!HaFinito(p))
            {
                p.Kill(entireProcessTree: true);
                p.WaitForExit(5000);
            }
        }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException or NotSupportedException)
        {
        }
        finally
        {
            p.Dispose();
            Job.Chiudi(j);
        }
        Log.Info($"motore spento ({motivo})");
    }

    public long Memoria()
    {
        lock (chiave)
        {
            if (processo == null || HaFinito(processo)) return 0;
            try
            {
                processo.Refresh();
                return processo.WorkingSet64;
            }
            catch (InvalidOperationException)
            {
                return 0;
            }
        }
    }

    /// <summary>Tempo di processore di tutti i motori accesi finora (così la misura non torna mai indietro).</summary>
    public long TempoCpu()
    {
        lock (chiave)
        {
            return cpuMotoriPrecedenti + (processo == null ? 0 : SafeCpu(processo));
        }
    }

    private static long SafeCpu(Process p)
    {
        try
        {
            p.Refresh();
            return p.TotalProcessorTime.Ticks;
        }
        catch (Exception e) when (e is InvalidOperationException or Win32Exception or NotSupportedException)
        {
            return 0;
        }
    }

    private static bool HaFinito(Process p)
    {
        try
        {
            return p.HasExited;
        }
        catch (Exception e) when (e is InvalidOperationException or Win32Exception)
        {
            return true;
        }
    }

    private static int SafeExitCode(Process p)
    {
        try
        {
            return p.ExitCode;
        }
        catch (InvalidOperationException)
        {
            return -1;
        }
    }

    /// <summary>
    /// Qualcuno ascolta già sulla porta? (Su Windows due programmi possono legare la stessa porta senza errori:
    /// meglio controllare prima.)
    /// </summary>
    public static async Task<bool> PortaOccupataAsync(int porta)
    {
        using var c = new TcpClient();
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromMilliseconds(400));
            await c.ConnectAsync("127.0.0.1", porta, cts.Token).ConfigureAwait(false);
            return true;
        }
        catch (Exception e) when (e is SocketException or OperationCanceledException)
        {
            return false;
        }
    }

    public void Dispose()
    {
        Spegni("chiusura");
        http.Dispose();
    }

    /// <summary>Un "job" di Windows che chiude il motore quando si chiude l'ultimo handle (cioè se l'agente muore).</summary>
    private static class Job
    {
        private const int InfoLimitiEstesi = 9;
        private const uint ChiudiConIlJob = 0x2000;

        [StructLayout(LayoutKind.Sequential)]
        private struct LimitiBase
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct ContatoriIo
        {
            public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount, ReadTransferCount, WriteTransferCount, OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct LimitiEstesi
        {
            public LimitiBase BasicLimitInformation;
            public ContatoriIo IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributi, string? nome);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetInformationJobObject(IntPtr job, int classe, ref LimitiEstesi info, uint lunghezza);

        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr processo);

        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr h);

        public static IntPtr Lega(Process p)
        {
            try
            {
                var j = CreateJobObject(IntPtr.Zero, null);
                if (j == IntPtr.Zero) return IntPtr.Zero;
                var info = new LimitiEstesi { BasicLimitInformation = new LimitiBase { LimitFlags = ChiudiConIlJob } };
                if (!SetInformationJobObject(j, InfoLimitiEstesi, ref info, (uint)Marshal.SizeOf<LimitiEstesi>())
                    || !AssignProcessToJobObject(j, p.Handle))
                {
                    CloseHandle(j);
                    return IntPtr.Zero;
                }
                return j;
            }
            catch (Exception e) when (e is DllNotFoundException or EntryPointNotFoundException or InvalidOperationException or Win32Exception)
            {
                return IntPtr.Zero;
            }
        }

        public static void Chiudi(IntPtr j)
        {
            if (j != IntPtr.Zero) CloseHandle(j);
        }
    }
}

/// <summary>Una misura del PC per le condizioni del modello.</summary>
/// <param name="CpuTotale">Tempo totale del processore finora (kernel + utente, tutti i processori), unità da 100 ns.</param>
/// <param name="CpuInattivo">Di cui inattivo.</param>
public readonly record struct MisuraPc(long CpuTotale, long CpuInattivo, bool? AllaCorrente, bool HaBatteria, long MemoriaLibera);

public interface IMisure
{
    MisuraPc Leggi();
}

/// <summary>
/// Il giro dei lavori per le foto dubbie (regole 10, contratto GET/POST /api/pc/lavori): ogni 5 secondi misura il
/// PC; solo se le condizioni valgono chiede un lavoro ogni 15 secondi; accende il motore al bisogno; lo spegne
/// dopo 5 minuti senza lavori o appena le condizioni non valgono più (anche a metà di un lavoro).
/// </summary>
public sealed class GestoreLavori
{
    public static readonly TimeSpan Passo = TimeSpan.FromSeconds(5);
    public const long IntervalloRichiesteMs = 15_000;
    public const long PausaDopoErroreMs = 10 * 60_000;

    private readonly ConfigMotore cfg;
    private readonly ClientNas nas;
    private readonly IMotore motore;
    private readonly IMisure misure;
    private readonly IOrologio orologio;
    private readonly CondizioniModello condizioni;
    private readonly HashSet<string> scartati = new(StringComparer.Ordinal);

    private MisuraPc? precedente;
    private long cpuMotorePrecedente;
    private long ultimaRichiestaMs = long.MinValue / 2;
    private long ultimoLavoroMs;
    private long pausaFinoMs = long.MinValue / 2;

    public GestoreLavori(ConfigMotore cfg, ClientNas nas, IMotore motore, IMisure misure, IOrologio orologio)
    {
        this.cfg = cfg;
        this.nas = nas;
        this.motore = motore;
        this.misure = misure;
        this.orologio = orologio;
        condizioni = new CondizioniModello(cfg.MemoriaMinimaGb, cfg.CpuMassimaPercento);
    }

    /// <summary>L'ultimo controllo delle condizioni (per il diario e le prove).</summary>
    public VerificaCondizioni UltimaVerifica { get; private set; } = new(false, "non ancora misurato");

    public int LavoriFatti { get; private set; }
    public string? UltimoErrore { get; private set; }

    public async Task CicloAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                await PassoAsync(ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception e)
            {
                Log.Errore("giro dei lavori", e);
            }
            try
            {
                await Task.Delay(Passo, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
        }
        motore.Spegni("fine del programma");
    }

    /// <summary>Misura il PC e aggiorna le condizioni. Restituisce la verifica.</summary>
    public VerificaCondizioni Misura()
    {
        long ms = orologio.Ms;
        var m = misure.Leggi();
        long cpuMotore = motore.TempoCpu();
        if (precedente is MisuraPc p)
            condizioni.AggiungiCpu(ms, m.CpuTotale - p.CpuTotale, m.CpuInattivo - p.CpuInattivo, cpuMotore - cpuMotorePrecedente);
        precedente = m;
        cpuMotorePrecedente = cpuMotore;
        UltimaVerifica = condizioni.Valuta(ms, m.AllaCorrente, m.HaBatteria, m.MemoriaLibera, motore.Memoria());
        return UltimaVerifica;
    }

    public async Task PassoAsync(CancellationToken ct)
    {
        if (!cfg.Attivo) return;
        var v = Misura();
        long ms = orologio.Ms;
        if (!v.Valide)
        {
            if (motore.Acceso) motore.Spegni("condizioni non più valide: " + v.Motivo);
            return;
        }
        if (motore.Acceso && ms - ultimoLavoroMs >= cfg.MinutiSpegnimento * 60_000L)
            motore.Spegni($"{cfg.MinutiSpegnimento} minuti senza lavori");
        if (ms < pausaFinoMs) return;
        if (ms - ultimaRichiestaMs < IntervalloRichiesteMs) return;
        ultimaRichiestaMs = ms;

        var r = await nas.LavoroAsync(ct).ConfigureAwait(false);
        if (!r.Ok || r.Dati == null) return;
        await EseguiAsync(r.Dati, ct).ConfigureAwait(false);
    }

    private async Task EseguiAsync(Lavoro l, CancellationToken ct)
    {
        if (scartati.Contains(l.Id)) return;
        if (Tempo.Leggi(l.Scade) is DateTimeOffset scade && scade < orologio.Adesso)
        {
            Log.Avviso($"lavoro {l.Id} già scaduto: non lo faccio");
            Scarta(l.Id);
            return;
        }
        var problema = DomandeModello.ProblemaLavoro(l);
        if (problema != null)
        {
            Log.Avviso($"lavoro {l.Id} non valido: {problema}");
            UltimoErrore = problema;
            Scarta(l.Id);
            return;
        }

        if (!motore.Acceso)
        {
            var errore = await motore.AvviaAsync(ct).ConfigureAwait(false);
            if (errore != null)
            {
                Log.Avviso("motore non acceso: " + errore);
                UltimoErrore = errore;
                pausaFinoMs = orologio.Ms + PausaDopoErroreMs;
                return;
            }
            ultimoLavoroMs = orologio.Ms;
        }

        var corpo = DomandeModello.CorpoRichiesta(l, cfg.NomeModello);
        using var annulla = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var cronometro = Stopwatch.StartNew();
        var domanda = motore.ChiediAsync(corpo, TimeSpan.FromSeconds(cfg.SecondiRisposta), annulla.Token);
        string? motivoStop = null;
        // Mentre il modello pensa si continua a misurare: se le condizioni cadono, si ferma tutto.
        while (!domanda.IsCompleted)
        {
            var finito = await Task.WhenAny(domanda, Task.Delay(Passo, ct)).ConfigureAwait(false);
            if (finito == domanda) break;
            var v = Misura();
            if (!v.Valide)
            {
                motivoStop = v.Motivo;
                annulla.Cancel();
                break;
            }
        }
        var risposta = await domanda.ConfigureAwait(false);
        cronometro.Stop();
        ultimoLavoroMs = orologio.Ms;
        if (motivoStop != null)
        {
            motore.Spegni("condizioni non più valide durante un lavoro: " + motivoStop);
            return;
        }
        if (!risposta.Ok || risposta.Corpo == null)
        {
            Log.Avviso($"lavoro {l.Id}: {risposta.Errore}");
            UltimoErrore = risposta.Errore;
            return;
        }
        var esito = DomandeModello.LeggiRisposta(risposta.Corpo, l);
        if (!esito.Ok || esito.Risposte == null)
        {
            Log.Avviso($"lavoro {l.Id}: {esito.Errore}");
            UltimoErrore = esito.Errore;
            return;
        }
        if (esito.Sostituite.Count > 0) Log.Avviso($"lavoro {l.Id}: risposte fuori elenco diventate non_si_capisce ({string.Join(", ", esito.Sostituite)})");
        var invio = await nas.RispondiLavoroAsync(l.Id, new RispostaLavoro
        {
            Risposte = esito.Risposte,
            Millisecondi = cronometro.ElapsedMilliseconds,
            Modello = cfg.NomeModello,
        }, ct).ConfigureAwait(false);
        if (invio.Ok)
        {
            LavoriFatti++;
            Log.Info($"lavoro {l.Id} fatto in {cronometro.ElapsedMilliseconds} ms");
        }
        else
        {
            Log.Avviso($"lavoro {l.Id}: il NAS non ha preso la risposta ({invio.Stato}: {invio.Errore})");
            UltimoErrore = invio.Errore;
        }
    }

    private void Scarta(string id)
    {
        if (scartati.Count > 200) scartati.Clear();
        scartati.Add(id);
    }
}
