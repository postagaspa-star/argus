using System.Media;
using System.Text.Json.Nodes;
using System.Windows.Forms;
using Argus.Agente.Interfaccia;
using Argus.Agente.Sistema;
using Microsoft.Win32;

namespace Argus.Agente;

/// <summary>
/// L'agente acceso: sensore, giri verso il NAS, copertura, terminale col suo tasto (di serie Ctrl+Alt+T), voce di ripiego,
/// lavori del modello. Tutto parte da qui e si ferma da qui.
/// </summary>
internal sealed class ContestoAgente : ApplicationContext
{
    private readonly ConfigArgus? config;
    private readonly StatoAgente stato;
    private readonly Control ponte;
    private readonly GestoreCopertura copertura;
    private readonly TastoRapido tasto;
    private readonly Sensore sensore;
    private readonly ClientNas? nas;
    private readonly ReteAgente? rete;
    private readonly MotoreLlama? motore;
    private readonly CancellationTokenSource fine = new();
    private readonly System.Windows.Forms.Timer riprovaTasto;
    private readonly EventWaitHandle? segnaleTerminale;
    private readonly RegisteredWaitHandle? attesaSegnale;
    private readonly BattitoAgente? battito;
    private FinestraTerminale? terminale;

    /// <summary>
    /// L'uscita l'ha chiesta l'agente stesso (fine della sessione, prova a tempo)? Se il ciclo dei messaggi finisce
    /// senza (un WM_QUIT mandato da un altro programma) l'agente esce con il codice 5 e il guardiano lo riapre subito.
    /// </summary>
    public bool UscitaRichiesta { get; private set; }

    /// <summary>
    /// Il segnale con cui "Argus.Agente.exe --terminale" (il collegamento nel menu Start) chiede alla copia
    /// accesa di aprire il terminale: serve se il tasto del terminale è preso da un altro programma.
    /// </summary>
    public const string NomeSegnaleTerminale = @"Local\Argus.Agente.Terminale";

    /// <param name="battitoVersoGuardiano">l'uscita standard verso il guardiano (solo se l'ha avviato lui), per il battito</param>
    public ContestoAgente(ConfigArgus? config, Stream? battitoVersoGuardiano = null)
    {
        this.config = config;
        var calendario = new CalendarioScolastico(config?.SabatoScuola ?? false, config?.Patrono);
        stato = new StatoAgente(calendario, Percorsi.Sblocco);

        // Un controllo invisibile per far arrivare le decisioni del sensore al thread delle finestre.
        ponte = new ControlloPonte();
        ponte.CreateControl();
        _ = ponte.Handle;

        // Il tasto del terminale: "tasto_terminale" in config.json, di serie Ctrl+Alt+T.
        var tastoTerminale = config?.Tasto() ?? TastoTerminale.Predefinito;
        if (config?.ProblemaTasto() is string problemaTasto) Log.Avviso(problemaTasto);

        copertura = new GestoreCopertura(stato);
        copertura.DopoInCima = () => terminale?.TienInCima();
        copertura.ApriTerminale = () => ApriTerminale(alterna: false);
        copertura.TestoTasto = tastoTerminale.Testo;

        tasto = new TastoRapido(tastoTerminale);
        tasto.Premuto += () => ApriTerminale(alterna: true);
        tasto.FineSessione += Esci;
        riprovaTasto = new System.Windows.Forms.Timer { Interval = 30_000 };
        riprovaTasto.Tick += (_, _) =>
        {
            if (tasto.Registra())
            {
                riprovaTasto.Stop();
                copertura.TastoAttivo = true;
                Log.Info($"{tastoTerminale.Testo} registrato");
            }
        };
        if (tasto.Registra())
        {
            Log.Info($"tasto del terminale: {tastoTerminale.Testo}");
        }
        else
        {
            // Senza hook di tastiera non si può "rubare" la combinazione: la copertura dirà "fai clic qui"
            // e resta il collegamento "Argus - terminale" nel menu Start.
            Log.Avviso($"{tastoTerminale.Testo} è già preso da un altro programma: riprovo ogni 30 secondi");
            copertura.TastoAttivo = false;
            riprovaTasto.Start();
        }

        // Il segnale del collegamento "Argus - terminale". Se un altro programma ha già preso il nome (con permessi che
        // lo tengono fuori) l'agente parte lo stesso: restano il tasto e il clic sulla copertura.
        try
        {
            segnaleTerminale = new EventWaitHandle(false, EventResetMode.AutoReset, NomeSegnaleTerminale, out bool nuovo);
            if (!nuovo) Log.Avviso("il segnale del terminale c'era già (un'altra copia o un altro programma)");
            attesaSegnale = ThreadPool.RegisterWaitForSingleObject(segnaleTerminale, (_, _) =>
            {
                try
                {
                    ponte.BeginInvoke(() => ApriTerminale(alterna: false));
                }
                catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException)
                {
                }
            }, null, Timeout.Infinite, executeOnlyOnce: false);
        }
        catch (Exception e) when (e is UnauthorizedAccessException or IOException or WaitHandleCannotBeOpenedException)
        {
            Log.Avviso("collegamento del menu Start non disponibile: " + e.Message);
            segnaleTerminale = null;
            attesaSegnale = null;
        }

        string? problema = ConfigArgus.Problema(config);
        if (problema == null)
        {
            nas = new ClientNas(config!.NasUrl, config.Token);
            rete = new ReteAgente(nas, stato, Riproduci);
            rete.Avvia();
            if (config.Motore.Attivo)
            {
                motore = new MotoreLlama(config.Motore, Path.Combine(Percorsi.CartellaUtente, "log", "motore.log"), Firma.Soggetto);
                var lavori = new GestoreLavori(config.Motore, nas, motore, new MisureWindows(), OrologioSistema.Istanza);
                _ = Task.Run(() => lavori.CicloAsync(fine.Token));
            }
        }
        else
        {
            Log.Avviso($"senza NAS: {problema}. Vale la regola \"senza NAS\" con le liste di partenza.");
        }

        // I programmi si riconoscono dal percorso (revisione B5): firma e nome originale fuori dalle cartelle protette.
        var riconoscitore = new RiconoscitoreProgrammi(new SistemaFileWindows(), RiconoscitoreProgrammi.CartelleDiSistema(),
            RiconoscitoreProgrammi.CartellaArgusDiSerie(), config?.PercorsiFidati);
        sensore = new Sensore(stato, riconoscitore, d =>
        {
            try
            {
                ponte.BeginInvoke(() => copertura.Applica(d));
            }
            catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException)
            {
            }
        });
        sensore.Avvia();

        if (battitoVersoGuardiano != null)
        {
            battito = new BattitoAgente(battitoVersoGuardiano, ponte, () => sensore.UltimoGiroMs);
            battito.Avvia();
        }

        SystemEvents.SessionEnding += SuFineSessione;
        Log.Info($"agente avviato (versione {typeof(ContestoAgente).Assembly.GetName().Version})");
    }

    private void SuFineSessione(object? s, SessionEndingEventArgs e)
    {
        if (!Win32.SessioneSiChiude()) return;
        Log.Info("fine della sessione di Windows: l'agente esce");
        Esci();
    }

    /// <summary>Uscita chiesta dall'agente stesso (fine sessione, prova a tempo).</summary>
    public void Esci()
    {
        UscitaRichiesta = true;
        ExitThread();
    }

    /// <summary>Il tasto del terminale apre o nasconde; clic sulla copertura e collegamento del menu Start aprono e basta.</summary>
    private void ApriTerminale(bool alterna)
    {
        if (terminale == null)
        {
            terminale = new FinestraTerminale(ComandoAsync, FotoAsync);
            _ = terminale.Handle;
            _ = terminale.PreparaAsync();
        }
        if (alterna) terminale.Alterna();
        else terminale.Apri();
    }

    private async Task<JsonObject> ComandoAsync(string testo)
    {
        if (nas == null)
            return new JsonObject { ["ok"] = false, ["testo"] = ComandiLocali.Rispondi(testo, stato.Modalita(DateTimeOffset.Now)) };
        var r = await nas.ComandoAsync(testo).ConfigureAwait(false);
        if (!r.Raggiunto)
            return new JsonObject { ["ok"] = false, ["testo"] = ComandiLocali.Rispondi(testo, stato.Modalita(DateTimeOffset.Now)) };
        if (r.Dati?.Risposta is string risposta && risposta.Length > 0)
        {
            var o = new JsonObject { ["ok"] = r.Dati.Ok, ["testo"] = risposta };
            if (r.Dati.ChiedeFoto is ChiedeFoto cf && cf.Scatti > 0)
                o["chiede_foto"] = new JsonObject { ["tipo"] = cf.Tipo, ["nome"] = cf.Nome, ["scatti"] = cf.Scatti, ["consiglio"] = cf.Consiglio };
            return o;
        }
        return new JsonObject { ["ok"] = false, ["testo"] = r.Errore ?? "Il NAS non ha risposto niente." };
    }

    private async Task<JsonObject> FotoAsync(string tipo, string? nome, List<ImmagineFoto> immagini)
    {
        if (nas == null) return new JsonObject { ["ok"] = false, ["testo"] = Nucleo.Testi.NasNonRisponde };
        if (immagini.Count == 0) return new JsonObject { ["ok"] = false, ["testo"] = "Nessuna foto da mandare." };
        var r = await nas.FotoAsync(tipo, nome, immagini).ConfigureAwait(false);
        if (!r.Raggiunto) return new JsonObject { ["ok"] = false, ["testo"] = "Il NAS non risponde: le foto non sono partite. Riprova tra poco." };
        if (r.Dati?.Risposta is string risposta && risposta.Length > 0) return new JsonObject { ["ok"] = r.Dati.Ok, ["testo"] = risposta };
        return new JsonObject { ["ok"] = false, ["testo"] = r.Errore ?? "Le foto non sono state prese." };
    }

    /// <summary>La voce di ripiego: un wav dal NAS, riprodotto una volta.</summary>
    private static void Riproduci(byte[] wav)
    {
        _ = Task.Run(() =>
        {
            try
            {
                using var flusso = new MemoryStream(wav);
                using var lettore = new SoundPlayer(flusso);
                lettore.PlaySync();
            }
            catch (Exception e)
            {
                Log.Errore("voce non riprodotta", e);
            }
        });
    }

    protected override void ExitThreadCore()
    {
        try
        {
            SystemEvents.SessionEnding -= SuFineSessione;
            fine.Cancel();
            battito?.Dispose();
            attesaSegnale?.Unregister(null);
            segnaleTerminale?.Dispose();
            sensore.Dispose();
            rete?.Dispose();
            motore?.Dispose();
            nas?.Dispose();
            riprovaTasto.Dispose();
            tasto.Dispose();
            copertura.Dispose();
            terminale?.Dispose();
            ponte.Dispose();
        }
        catch (Exception e)
        {
            Log.Errore("chiusura", e);
        }
        base.ExitThreadCore();
    }
}

/// <summary>
/// Il controllo invisibile che porta le decisioni al thread delle finestre. Ignora WM_CLOSE: un altro programma
/// potrebbe mandarlo per distruggerlo e lasciare l'agente acceso ma senza coperture (il battito se ne accorgerebbe
/// comunque, perché passa da qui).
/// </summary>
internal sealed class ControlloPonte : Control
{
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == Win32.WM_CLOSE) return;
        base.WndProc(ref m);
    }
}

/// <summary>Il tasto del terminale da qualsiasi punto (RegisterHotKey, niente hook di tastiera).</summary>
internal sealed class TastoRapido : NativeWindow, IDisposable
{
    private const int Id = 0xA27;
    private readonly TastoTerminale combinazione;
    private bool registrato;

    public event Action? Premuto;
    public event Action? FineSessione;

    public TastoRapido(TastoTerminale combinazione)
    {
        this.combinazione = combinazione;
        CreateHandle(new CreateParams { Caption = "Argus tasto" });
    }

    public bool Registra()
    {
        if (registrato) return true;
        registrato = Win32.RegisterHotKey(Handle, Id, combinazione.Modificatori | Win32.MOD_NOREPEAT, combinazione.TastoVirtuale);
        return registrato;
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == Win32.WM_HOTKEY && m.WParam == (IntPtr)Id)
        {
            try
            {
                Premuto?.Invoke();
            }
            catch (Exception e)
            {
                Log.Errore("terminale", e);
            }
            return;
        }
        if (m.Msg == Win32.WM_CLOSE) return; // da un altro programma: la finestra del tasto resta
        if (m.Msg == Win32.WM_ENDSESSION && m.WParam != IntPtr.Zero && Win32.SessioneSiChiude())
        {
            FineSessione?.Invoke();
        }
        base.WndProc(ref m);
    }

    public void Dispose()
    {
        if (registrato) Win32.UnregisterHotKey(Handle, Id);
        DestroyHandle();
    }
}
