using System.Diagnostics;
using System.ServiceProcess;
using System.Text;

namespace Argus.Guardiano;

internal static class Program
{
    /// <summary>
    /// Di solito lo avvia il gestore dei servizi di Windows. Per le prove:
    /// <list type="bullet">
    /// <item><c>--sessioni</c>: stampa la sessione della console, il suo utente e se è attiva (non serve essere amministratore);</item>
    /// <item><c>--console</c>: fa il lavoro del servizio nella console (serve LocalSystem per WTSQueryUserToken: da
    /// amministratore non basta, quindi si prova davvero solo da servizio);</item>
    /// <item><c>--prova-avvio &lt;config.json&gt; &lt;secondi&gt; [--congela &lt;secondi&gt;] [--argomenti "..."] [--agente &lt;exe&gt;]</c>: avvia
    /// l'agente protetto come fa il servizio ma con l'utente di adesso (non serve essere amministratore), controlla da
    /// questo stesso utente che non si possa chiudere, sospendere o leggere, conta i battiti e, con
    /// <c>--congela</c>, lo sospende per vedere che dopo 20 secondi senza battito viene chiuso.</item>
    /// </list>
    /// </summary>
    private static int Main(string[] args)
    {
        if (args.Contains("--sessioni"))
        {
            uint s = Sessioni.SessioneConsole();
            Console.WriteLine($"sessione della console: {s}");
            if (s != Sessioni.NessunaSessione)
            {
                Console.WriteLine($"utente: {Sessioni.Utente(s) ?? "(nessuno)"}");
                Console.WriteLine($"attiva: {Sessioni.Attiva(s)}");
            }
            return 0;
        }
        if (Valore(args, "--prova-avvio") is string fileConfig)
        {
            int secondi = int.TryParse(Valore(args, fileConfig), out var n) ? n : 30;
            int congela = int.TryParse(Valore(args, "--congela"), out var c) ? c : 0;
            return ProvaAvvio(fileConfig, secondi, congela, Valore(args, "--argomenti"), Valore(args, "--agente"));
        }
        if (args.Contains("--console"))
        {
            Log.Imposta(Path.Combine(Path.GetTempPath(), "argus-guardiano-prova"), "guardiano.log");
            var g = new ServizioGuardiano();
            g.Avvia();
            Console.WriteLine("Guardiano in prova. Invio per fermare.");
            Console.ReadLine();
            g.Ferma();
            return 0;
        }
        ServiceBase.Run(new ServizioGuardiano());
        return 0;
    }

    private static int ProvaAvvio(string fileConfig, int secondi, int congelaDopo, string? argomenti, string? agenteExe)
    {
        var config = ConfigArgus.Carica(fileConfig);
        string istanza = Convert.ToHexString(System.Security.Cryptography.RandomNumberGenerator.GetBytes(16));
        string exe = agenteExe ?? Path.Combine(AppContext.BaseDirectory, "Argus.Agente.exe");
        int errori = 0;
        using var agente = AvvioProtetto.Avvia(IntPtr.Zero, exe, argomenti, Encoding.UTF8.GetBytes(config.PerAgente(istanza)), desktop: null);
        Console.WriteLine($"agente avviato protetto: pid {agente.Pid}, thread principale {agente.Tid}");

        Console.WriteLine("permessi sul processo visti da questo utente (lo stesso dell'agente):");
        foreach (var (nome, diritto) in SicurezzaAgente.VietatiProcesso)
        {
            bool aperto = SicurezzaAgente.ApreProcesso(agente.Pid, diritto);
            if (aperto) errori++;
            Console.WriteLine($"  {nome,-26} {(aperto ? "CONCESSO (sbagliato)" : "negato")}");
        }
        bool attesa = SicurezzaAgente.ApreProcesso(agente.Pid, 0x00100000 | 0x1000);
        if (!attesa) errori++;
        Console.WriteLine($"  {"SYNCHRONIZE+QUERY_LIMITED",-26} {(attesa ? "concesso (giusto)" : "NEGATO (sbagliato)")}");
        foreach (var (nome, diritto) in SicurezzaAgente.VietatiThread)
        {
            bool aperto = SicurezzaAgente.ApreThread(agente.Tid, diritto);
            if (aperto) errori++;
            Console.WriteLine($"  thread principale {nome,-28} {(aperto ? "CONCESSO (sbagliato)" : "negato")}");
        }

        long fine = Environment.TickCount64 + secondi * 1000L;
        bool congelato = false, controllatiThread = false;
        string esito = $"ancora acceso dopo {secondi} s";
        while (Environment.TickCount64 < fine)
        {
            long ms = Environment.TickCount64;
            if (agente.Uscito(out uint codice))
            {
                esito = $"uscito da solo con il codice {codice} dopo {(ms - agente.AvviatoMs) / 1000} s";
                break;
            }
            // Dopo 8 secondi l'agente ha già protetto i suoi thread: nessuno deve potersi sospendere da qui.
            if (!controllatiThread && ms - agente.AvviatoMs >= 8000 && agente.Battiti > 0)
            {
                controllatiThread = true;
                var (apribili, totale) = ThreadApribili(agente.Pid);
                Console.WriteLine($"thread dell'agente sospendibili da questo utente dopo 8 s: {apribili} su {totale}");
                if (apribili > 0) errori++;
            }
            if (congelaDopo > 0 && !congelato && ms - agente.AvviatoMs >= congelaDopo * 1000L)
            {
                congelato = agente.SospendiPerProva();
                Console.WriteLine($"{(ms - agente.AvviatoMs) / 1000} s: agente congelato ({agente.Battiti} battiti finora)");
            }
            if (RegoleBattito.Bloccato(ms, agente.AvviatoMs, agente.UltimoBattitoMs, agente.Battiti))
            {
                agente.Termina(CodiciAgente.ChiusoPerchéBloccato);
                esito = $"senza battito da {(ms - agente.UltimoBattitoMs) / 1000} s: chiuso dal guardiano dopo {(ms - agente.AvviatoMs) / 1000} s (agente_bloccato)";
                break;
            }
            Thread.Sleep(250);
        }
        Console.WriteLine($"battiti ricevuti: {agente.Battiti}");
        Console.WriteLine($"esito: {esito}");
        if (!agente.Uscito(out _)) agente.Termina(0); // chiude solo l'agente avviato qui (handle della creazione)
        Console.WriteLine(errori == 0 ? "PERMESSI OK" : $"PERMESSI SBAGLIATI: {errori}");
        return errori == 0 ? 0 : 1;
    }

    private static (int Apribili, int Totale) ThreadApribili(int pid)
    {
        int apribili = 0, totale = 0;
        try
        {
            using var p = Process.GetProcessById(pid);
            foreach (ProcessThread t in p.Threads)
            {
                using (t)
                {
                    totale++;
                    if (SicurezzaAgente.ApreThread(t.Id, 0x0002 /* THREAD_SUSPEND_RESUME */)) apribili++;
                }
            }
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException)
        {
        }
        return (apribili, totale);
    }

    private static string? Valore(string[] args, string nome)
    {
        int i = Array.IndexOf(args, nome);
        return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
    }
}
