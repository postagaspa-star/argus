using System.Text;
using System.Windows.Forms;
using Argus.Agente.Interfaccia;

namespace Argus.Agente;

internal static class Program
{
    /// <summary>
    /// Avvio dell'agente. La configurazione arriva:
    /// <list type="bullet">
    /// <item>dal guardiano, sull'ingresso standard (una conduttura privata: il token non passa dalla riga di comando
    /// e non sta in un file leggibile dallo studente);</item>
    /// <item>per le prove, da <c>--config &lt;file&gt;</c>.</item>
    /// </list>
    /// Senza configurazione l'agente gira lo stesso con la regola "senza NAS" e le liste di partenza.
    /// <c>--terminale</c>: chiede alla copia accesa di aprire il terminale (collegamento del menu Start).
    /// Opzioni di prova: <c>--prova-copertura &lt;file.png&gt;</c> (disegna la copertura in un'immagine ed esce),
    /// <c>--prova-terminale &lt;file.png&gt;</c> (terminale vero fuori dallo schermo),
    /// <c>--prova-dominio &lt;pid&gt; &lt;file.txt&gt;</c> (lettura del sito sulle finestre di un browser di prova),
    /// <c>--esci-dopo &lt;secondi&gt;</c>.
    /// </summary>
    [STAThread]
    private static int Main(string[] args)
    {
        Log.Imposta(Path.Combine(Percorsi.CartellaUtente, "log"), "agente.log");
        AppDomain.CurrentDomain.UnhandledException += (_, e) => Log.Errore("errore non gestito", e.ExceptionObject as Exception);

        // "--terminale": il collegamento del menu Start. Chiede alla copia accesa di aprire il terminale ed esce.
        if (Array.IndexOf(args, "--terminale") >= 0) return ChiediTerminale();

        string? fileConfig = Valore(args, "--config");

        // "--prova-programmi <elenco.txt> <esito.txt> [--config <file>]": come si riconoscono i programmi dell'elenco
        // (un percorso completo per riga), con le liste di partenza e i percorsi_fidati della configurazione.
        if (Valore(args, "--prova-programmi") is string elenco) return ProvaProgrammi(elenco, Valore(args, elenco), fileConfig);

        string? provaCopertura = Valore(args, "--prova-copertura");
        int esciDopo = int.TryParse(Valore(args, "--esci-dopo"), out var s) ? s : 0;

        ApplicationConfiguration.Initialize();

        if (provaCopertura != null)
        {
            FinestraCopertura.DisegnaImmagine(new System.Drawing.Rectangle(0, 0, 1600, 900),
                "Adesso è tempo di studio. Mancano 35 minuti.", provaCopertura);
            return 0;
        }

        // Prova del terminale (WebView2 vera, fuori dallo schermo, senza NAS): immagine + storico in un file di testo.
        string? provaTerminale = Valore(args, "--prova-terminale");
        if (provaTerminale != null)
        {
            var finestra = new FinestraTerminale(
                testo => Task.FromResult(new System.Text.Json.Nodes.JsonObject
                {
                    ["ok"] = testo == "aiuto",
                    ["testo"] = testo == "aiuto" ? Nucleo.Testi.Aiuto : Nucleo.Testi.NasNonRisponde,
                }),
                (_, _, _) => Task.FromResult(new System.Text.Json.Nodes.JsonObject { ["ok"] = false, ["testo"] = "prova" }));
            finestra.ImpostaProva();
            string risultato = "";
            finestra.Shown += async (_, _) =>
            {
                try
                {
                    risultato = await finestra.ProvaAsync(provaTerminale);
                }
                catch (Exception e)
                {
                    risultato = "ERRORE: " + e;
                }
                File.WriteAllText(Path.ChangeExtension(provaTerminale, ".txt"), risultato, new UTF8Encoding(false));
                Application.ExitThread();
            };
            Application.Run(finestra);
            return risultato.StartsWith("ERRORE", StringComparison.Ordinal) ? 1 : 0;
        }

        // Prova della lettura del sito (UI Automation) sulle finestre di un browser di prova: "--prova-dominio <pid> <file.txt>".
        if (Valore(args, "--prova-dominio") is string pidTesto && int.TryParse(pidTesto, out int pid))
        {
            var righe = new List<string>();
            var lettore = new Sistema.LettoreIndirizzi();
            var finestre = new List<IntPtr>();
            Sistema.Win32.EnumWindows((h, _) =>
            {
                Sistema.Win32.GetWindowThreadProcessId(h, out uint p);
                if (p == pid && Sistema.Win32.IsWindowVisible(h) && Sistema.Win32.ClasseDi(h) == "Chrome_WidgetWin_1") finestre.Add(h);
                return true;
            }, IntPtr.Zero);
            foreach (var h in finestre)
            {
                var exe = Path.GetFileName(System.Diagnostics.Process.GetProcessById(pid).MainModule?.FileName ?? "msedge.exe").ToLowerInvariant();
                var cronometro = System.Diagnostics.Stopwatch.StartNew();
                string? sito = null;
                for (int i = 0; i < 6 && sito == null; i++)
                {
                    sito = lettore.Leggi(h, exe, schermoIntero: false);
                    if (sito == null) Thread.Sleep(500);
                }
                righe.Add($"finestra {h}: sito={sito ?? "(nessuno)"} in {cronometro.ElapsedMilliseconds} ms");
            }
            if (finestre.Count == 0) righe.Add("nessuna finestra del browser trovata");
            File.WriteAllLines(Valore(args, pidTesto) ?? "prova-dominio.txt", righe, new UTF8Encoding(false));
            return 0;
        }

        ConfigArgus? config = null;
        try
        {
            if (fileConfig != null) config = ConfigArgus.Carica(fileConfig);
            else if (Console.IsInputRedirected) config = DallIngresso();
        }
        catch (ErroreConfig e)
        {
            Log.Errore("configurazione: " + e.Message);
        }
        if (config == null) Log.Avviso("nessuna configurazione ricevuta");

        // Una sola copia. Avviato dal guardiano (configurazione con "istanza"): il nome del mutex contiene l'istanza,
        // che lo studente non conosce, quindi non può occuparlo prima per far uscire l'agente; che ce ne sia uno solo
        // lo garantisce il guardiano. Avviato a mano (prove): il nome fisso di sempre.
        bool dalGuardiano = !string.IsNullOrWhiteSpace(config?.Istanza) && fileConfig == null;
        string nomeUnica = dalGuardiano ? @"Local\Argus.Agente." + config!.Istanza : @"Local\Argus.Agente";
        using var unica = new Mutex(true, nomeUnica, out bool prima);
        if (!prima)
        {
            Log.Avviso("c'è già un agente in questa sessione: esco");
            return 3;
        }

        // Il battito verso il guardiano viaggia sull'uscita standard (la conduttura che ha creato lui).
        Stream? battito = dalGuardiano ? Console.OpenStandardOutput() : null;
        using var contesto = new ContestoAgente(config, battito);
        if (esciDopo > 0)
        {
            var t = new System.Windows.Forms.Timer { Interval = esciDopo * 1000 };
            t.Tick += (_, _) => { t.Stop(); contesto.Esci(); };
            t.Start();
        }
        Application.Run(contesto);
        if (!contesto.UscitaRichiesta)
        {
            // Un messaggio di uscita mandato da un altro programma: il guardiano riapre subito (niente pausa).
            Log.Avviso("ciclo dei messaggi finito senza una richiesta dell'agente: esco con il codice 5");
            return CodiciAgente.UscitaNonRichiesta;
        }
        Log.Info("agente chiuso");
        return 0;
    }

    /// <summary>
    /// Apre il terminale dell'agente acceso in questa sessione. Questo processo l'ha avviato chi usa il PC, quindi
    /// può cedere il primo piano all'agente (altrimenti Windows lascerebbe il terminale dietro).
    /// </summary>
    private static int ChiediTerminale()
    {
        if (!EventWaitHandle.TryOpenExisting(ContestoAgente.NomeSegnaleTerminale, out var segnale))
        {
            Log.Avviso("--terminale: nessun agente acceso in questa sessione");
            return 4;
        }
        using (segnale)
        {
            Sistema.Win32.AllowSetForegroundWindow(-1);
            segnale.Set();
        }
        return 0;
    }

    private static int ProvaProgrammi(string elenco, string? fileEsito, string? fileConfig)
    {
        var fidati = fileConfig != null ? ConfigArgus.Carica(fileConfig).PercorsiFidati : new List<string>();
        var fs = new Sistema.SistemaFileWindows();
        var riconoscitore = new RiconoscitoreProgrammi(fs, RiconoscitoreProgrammi.CartelleDiSistema(),
            RiconoscitoreProgrammi.CartellaArgusDiSerie(), fidati);
        var liste = Liste.Iniziali();
        var righe = new List<string> { "percorso\tcartella\tfirma\tnome originale\triconosciuto come\tnome\tlista" };
        foreach (var percorso in File.ReadAllLines(elenco).Select(r => r.Trim()).Where(r => r.Length > 0 && !r.StartsWith('#')))
        {
            string exe = Path.GetFileName(percorso).ToLowerInvariant();
            var r = riconoscitore.Riconosci(exe, percorso);
            string lista = r.Nome == null ? "-"
                : Confronto.ProgrammaInLista(r.Nome, liste.Mai.Programmi) ? "mai"
                : Confronto.ProgrammaInLista(r.Nome, liste.Sempre.Programmi) ? "sempre"
                : Confronto.ProgrammaInLista(r.Nome, liste.Studio.Programmi) ? "studio"
                : Confronto.ProgrammaInLista(r.Nome, liste.Lavoro.Programmi) ? "lavoro"
                : liste.ÈBrowser(r.Nome) ? "browser" : "nessuna";
            righe.Add(string.Join('\t', percorso,
                File.Exists(percorso) ? (fs.Scrivibile(percorso) ? "scrivibile dallo studente" : "protetta") : "FILE ASSENTE",
                fs.FirmaValida(percorso) ? "valida" : "no",
                fs.NomeOriginale(percorso) ?? "-", r.Come, r.Nome ?? "-", lista));
        }
        File.WriteAllLines(fileEsito ?? "prova-programmi.txt", righe, new UTF8Encoding(false));
        return 0;
    }

    /// <summary>La configurazione mandata dal guardiano sull'ingresso standard (al massimo 5 secondi, 256 KB).</summary>
    private static ConfigArgus? DallIngresso()
    {
        var compito = Task.Run(() =>
        {
            using var flusso = Console.OpenStandardInput();
            using var lettore = new StreamReader(flusso, new UTF8Encoding(false));
            var buffer = new char[256 * 1024];
            int letti = lettore.ReadBlock(buffer, 0, buffer.Length);
            return new string(buffer, 0, letti);
        });
        if (!compito.Wait(TimeSpan.FromSeconds(5)) || string.IsNullOrWhiteSpace(compito.Result)) return null;
        return ConfigArgus.DaJson(compito.Result);
    }

    private static string? Valore(string[] args, string nome)
    {
        int i = Array.IndexOf(args, nome);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
