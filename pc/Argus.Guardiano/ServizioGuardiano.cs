using System.Diagnostics;
using System.ServiceProcess;
using System.Text;

namespace Argus.Guardiano;

/// <summary>
/// Il servizio "ArgusGuardiano" (LocalSystem, avvio automatico, riavvio in caso di errore: lo imposta installa.ps1).
/// <list type="bullet">
/// <item>avvia Argus.Agente nella sessione attiva della console SOLO se l'utente di quella sessione è
/// <c>utente_controllato</c> del config (mai nel codice);</item>
/// <item>se l'agente esce lo riapre entro 3 secondi (di regola dopo 1) e lo dice al NAS:
/// <c>agente_chiuso</c> quando esce, <c>agente_riaperto</c> quando lo riapre, <c>agente_avviato</c> al primo
/// avvio dopo un accesso; un'uscita per fine sessione (disconnessione, spegnimento) non è un "chiuso";</item>
/// <item>segue accessi, disconnessioni e cambi utente (OnSessionChange) oltre a un controllo ogni secondo;</item>
/// <item>passa la configurazione (con il token, SENZA il segreto dello sblocco) all'agente su una conduttura privata;</item>
/// <item>avvia l'agente protetto (revisione B6): lo studente non può chiuderlo, sospenderlo né leggerne la memoria;
/// l'agente batte ogni 5 secondi e se tace per 20 secondi il guardiano lo chiude, lo riapre e manda
/// <c>agente_bloccato</c>;</item>
/// <item>legge lo sblocco d'emergenza e manda <c>sblocco_emergenza</c> al NAS se Argus.Sblocco non ci è riuscito.</item>
/// </list>
/// </summary>
internal sealed class ServizioGuardiano : ServiceBase
{
    public const string Nome = "ArgusGuardiano";

    private readonly AutoResetEvent sveglia = new(false);
    private readonly Dictionary<uint, ProcessoProtetto> agenti = new();
    private readonly Dictionary<uint, PoliticaRiavvio> riavvii = new();
    private readonly HashSet<uint> giàAvviatoInQuestoAccesso = new();
    private readonly Dictionary<uint, long> fineSessioneMs = new();
    private readonly Queue<(string Tipo, Dictionary<string, object?> Dettagli, DateTimeOffset Ts)> eventi = new();
    private readonly object chiaveEventi = new();
    private Thread? lavoratore;
    private volatile bool fermo;

    private ConfigArgus? config;
    private DateTime configLetto = DateTime.MinValue;
    private long configProvatoMs = long.MinValue / 2;
    private ClientNas? nas;
    private long sbloccoMs = long.MinValue / 2, eventiMs = long.MinValue / 2;
    private string? ultimoProblema;

    public ServizioGuardiano()
    {
        ServiceName = Nome;
        CanHandleSessionChangeEvent = true;
        CanShutdown = true;
        CanStop = true;
        AutoLog = false;
    }

    public string PercorsoAgente { get; set; } = Path.Combine(AppContext.BaseDirectory, "Argus.Agente.exe");

    protected override void OnStart(string[] args)
    {
        Log.Imposta(Percorsi.LogGuardiano, "guardiano.log");
        Log.Info($"guardiano avviato (versione {typeof(ServizioGuardiano).Assembly.GetName().Version})");
        Avvia();
    }

    /// <summary>Per le prove da console (come amministratore): lo stesso lavoro, senza il gestore dei servizi.</summary>
    public void Avvia()
    {
        fermo = false;
        lavoratore = new Thread(Ciclo) { IsBackground = true, Name = "Argus guardiano" };
        lavoratore.Start();
    }

    protected override void OnStop()
    {
        Log.Info("guardiano fermato");
        Ferma();
    }

    protected override void OnShutdown()
    {
        Log.Info("Windows si spegne");
        Ferma();
    }

    public void Ferma()
    {
        fermo = true;
        sveglia.Set();
        lavoratore?.Join(5000);
        foreach (var a in agenti.Values) a.Dispose();
        agenti.Clear();
        nas?.Dispose();
    }

    protected override void OnSessionChange(SessionChangeDescription d)
    {
        uint s = (uint)d.SessionId;
        lock (fineSessioneMs)
        {
            switch (d.Reason)
            {
                case SessionChangeReason.SessionLogon:
                    giàAvviatoInQuestoAccesso.Remove(s);
                    fineSessioneMs.Remove(s);
                    break;
                case SessionChangeReason.SessionLogoff:
                    fineSessioneMs[s] = Environment.TickCount64;
                    break;
            }
        }
        Log.Info($"sessione {s}: {d.Reason}");
        sveglia.Set();
    }

    private void Ciclo()
    {
        while (!fermo)
        {
            try
            {
                Giro();
            }
            catch (Exception e)
            {
                Log.Errore("giro del guardiano", e);
            }
            sveglia.WaitOne(1000);
        }
    }

    private void Giro()
    {
        long ms = Environment.TickCount64;
        CaricaConfig(ms);

        // 1. Agenti usciti o bloccati (niente battito: sospesi o fermi).
        foreach (var (sessione, agente) in agenti.ToList())
        {
            bool bloccato = false;
            if (!agente.Uscito(out uint codice))
            {
                if (!RegoleBattito.Bloccato(ms, agente.AvviatoMs, agente.UltimoBattitoMs, agente.Battiti)) continue;
                long secondi = (ms - agente.UltimoBattitoMs) / 1000;
                Log.Avviso($"l'agente nella sessione {sessione} (pid {agente.Pid}) non batte da {secondi} secondi: lo chiudo e lo riapro");
                agente.Termina(CodiciAgente.ChiusoPerchéBloccato);
                Accoda(TipiEvento.AgenteBloccato, new() { ["pid"] = agente.Pid, ["secondi"] = secondi });
                bloccato = true;
                agente.Uscito(out codice);
            }
            agenti.Remove(sessione);
            agente.Dispose();
            // Il ritardo di 30 secondi vale solo se l'agente muore da solo appena partito (PoliticaRiavvio).
            Riavvii(sessione).Uscito(ms, agente.AvviatoMs, daSolo: !bloccato && codice != CodiciAgente.UscitaNonRichiesta);
            if (bloccato) continue;
            bool fineSessione;
            lock (fineSessioneMs)
                fineSessione = fineSessioneMs.TryGetValue(sessione, out var f) && ms - f < 30_000;
            fineSessione |= !Sessioni.Attiva(sessione) || !Utenti.ÈControllato(Sessioni.Utente(sessione), config?.UtenteControllato);
            if (fineSessione)
            {
                Log.Info($"agente uscito per la fine della sessione {sessione} (codice {codice})");
            }
            else
            {
                Log.Avviso($"agente chiuso nella sessione {sessione} (codice {codice}): lo riapro");
                Accoda(TipiEvento.AgenteChiuso, new()
                {
                    ["codice_uscita"] = codice,
                    ["minuti_acceso"] = Math.Round((DateTimeOffset.Now - agente.Avviato).TotalMinutes, 1),
                });
            }
        }

        // 2. La sessione davanti allo schermo: se è dell'utente controllato, l'agente deve esserci.
        uint console = Sessioni.SessioneConsole();
        if (config != null && console != Sessioni.NessunaSessione && console != 0 && !agenti.ContainsKey(console)
            && Sessioni.Attiva(console) && Utenti.ÈControllato(Sessioni.Utente(console), config.UtenteControllato)
            && Riavvii(console).PuòRiaprire(ms))
        {
            AvviaAgente(console);
        }

        // 3. Sblocco d'emergenza ed eventi verso il NAS.
        if (ms - sbloccoMs >= 15_000)
        {
            sbloccoMs = ms;
            ControllaSblocco();
        }
        if (ms - eventiMs >= 5_000)
        {
            eventiMs = ms;
            MandaEventi();
        }
    }

    private PoliticaRiavvio Riavvii(uint sessione)
    {
        if (!riavvii.TryGetValue(sessione, out var p)) riavvii[sessione] = p = new PoliticaRiavvio();
        return p;
    }

    private void AvviaAgente(uint sessione)
    {
        if (!File.Exists(PercorsoAgente))
        {
            Problema($"non trovo l'agente ({PercorsoAgente})");
            return;
        }
        ChiudiCopieEstranee(sessione);
        try
        {
            // Una "istanza" nuova a ogni avvio: l'agente la usa per il nome del suo mutex (lo studente non la
            // conosce, quindi non può occupare il nome prima di lui). Il segreto dello sblocco resta qui.
            string istanza = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(16));
            var ingresso = Encoding.UTF8.GetBytes(config!.PerAgente(istanza));
            var agente = Sessioni.Avvia(sessione, PercorsoAgente, ingresso);
            agenti[sessione] = agente;
            bool riaperto;
            lock (fineSessioneMs) riaperto = !giàAvviatoInQuestoAccesso.Add(sessione);
            Log.Info($"agente {(riaperto ? "riaperto" : "avviato")} nella sessione {sessione} (pid {agente.Pid})");
            Accoda(riaperto ? TipiEvento.AgenteRiaperto : TipiEvento.AgenteAvviato, new() { ["pid"] = agente.Pid });
            ultimoProblema = null;
        }
        catch (Exception e)
        {
            Riavvii(sessione).NonAvviato(Environment.TickCount64);
            Problema($"agente non avviato nella sessione {sessione}: {e.Message}");
        }
    }

    /// <summary>Una copia dell'agente nella sessione che il guardiano non ha avviato (senza token) non deve tenere il posto.</summary>
    private void ChiudiCopieEstranee(uint sessione)
    {
        foreach (var p in Process.GetProcessesByName("Argus.Agente"))
        {
            try
            {
                if ((uint)p.SessionId != sessione) continue;
                Log.Avviso($"copia dell'agente non avviata dal guardiano (pid {p.Id}): la chiudo");
                p.Kill();
                p.WaitForExit(3000);
            }
            catch (Exception e) when (e is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException)
            {
            }
            finally
            {
                p.Dispose();
            }
        }
    }

    private void CaricaConfig(long ms)
    {
        DateTime scritto;
        try
        {
            scritto = File.Exists(Percorsi.Config) ? File.GetLastWriteTimeUtc(Percorsi.Config) : DateTime.MinValue;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            scritto = DateTime.MinValue;
        }
        if (config != null && scritto == configLetto) return;
        if (config == null && ms - configProvatoMs < 60_000 && scritto == configLetto) return;
        configProvatoMs = ms;
        configLetto = scritto;
        try
        {
            var nuovo = ConfigArgus.Carica(Percorsi.Config);
            var problema = nuovo.ProblemaNas();
            if (string.IsNullOrWhiteSpace(nuovo.UtenteControllato)) problema = "manca utente_controllato";
            if (problema != null)
            {
                Problema("configurazione incompleta: " + problema);
                config = null;
                return;
            }
            config = nuovo;
            nas?.Dispose();
            nas = new ClientNas(nuovo.NasUrl, nuovo.Token);
            Log.Info("configurazione caricata");
        }
        catch (ErroreConfig e)
        {
            Problema(e.Message);
            config = null;
        }
    }

    private void ControllaSblocco()
    {
        if (nas == null) return;
        var s = Sblocco.Leggi(Percorsi.Sblocco);
        if (s == null || s.Inviato) return;
        var adesso = DateTimeOffset.Now;
        bool tolto = s.Ore == 0;
        if (!tolto && !s.Attivo(adesso)) return;
        if (string.IsNullOrWhiteSpace(config?.SegretoSblocco))
        {
            Problema("manca segreto_sblocco in config.json: lo sblocco non si può mandare al NAS");
            return;
        }
        var r = nas.EventoAsync(TipiEvento.SbloccoEmergenza, s.DettagliEvento(), Tempo.Leggi(s.Creato) ?? adesso,
            segretoSblocco: config!.SegretoSblocco).GetAwaiter().GetResult();
        if (!r.Ok)
        {
            if (r.Raggiunto) Log.Avviso($"sblocco non accettato dal NAS: {r.Errore}");
            return;
        }
        s.Inviato = true;
        try
        {
            FileSicuri.ScriviAtomico(Percorsi.Sblocco, s.InJson());
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            Log.Errore("sblocco.json non aggiornato", e);
        }
        Log.Info(tolto ? "sblocco tolto: avvisato il NAS" : $"sblocco d'emergenza ({s.Ore} ore) mandato al NAS");
    }

    private void Accoda(string tipo, Dictionary<string, object?> dettagli)
    {
        lock (chiaveEventi)
        {
            eventi.Enqueue((tipo, dettagli, DateTimeOffset.Now));
            while (eventi.Count > 100) eventi.Dequeue();
        }
        eventiMs = long.MinValue / 2; // subito al prossimo giro
    }

    private void MandaEventi()
    {
        if (nas == null) return;
        while (true)
        {
            (string Tipo, Dictionary<string, object?> Dettagli, DateTimeOffset Ts) e;
            lock (chiaveEventi)
            {
                if (!eventi.TryPeek(out e)) return;
            }
            var r = nas.EventoAsync(e.Tipo, e.Dettagli, e.Ts).GetAwaiter().GetResult();
            if (!r.Ok && !r.Raggiunto) return; // il NAS non risponde: si riprova tra poco
            if (!r.Ok) Log.Avviso($"evento {e.Tipo} rifiutato dal NAS: {r.Errore}");
            lock (chiaveEventi) eventi.TryDequeue(out _);
        }
    }

    private void Problema(string testo)
    {
        if (testo == ultimoProblema) return;
        ultimoProblema = testo;
        Log.Errore(testo);
    }
}
