using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using Argus.Nucleo;

namespace Argus.Prove;

/// <summary>
/// Le prove dei permessi dell'agente (revisione B6) senza amministratore: un processo qualsiasi (ping) avviato come
/// fa il guardiano, con gli stessi permessi; poi, da questo stesso utente (come farebbe lo studente), si prova ad
/// aprirlo per chiuderlo, sospenderlo, leggerlo. Da amministratore le prove non dicono niente (Administrators ha
/// tutto) e si saltano.
/// </summary>
public sealed class ProvaDaUtenteAttribute : FactAttribute
{
    public ProvaDaUtenteAttribute()
    {
        using var io = WindowsIdentity.GetCurrent();
        if (new WindowsPrincipal(io).IsInRole(WindowsBuiltInRole.Administrator))
            Skip = "Da amministratore Administrators può tutto: la prova vale solo da utente normale.";
    }
}

public class AvvioProtettoTest
{
    private static readonly string Ping = Path.Combine(Environment.SystemDirectory, "PING.EXE");

    [ProvaDaUtente]
    public void LoStessoUtenteNonPuòChiuderloNéSospenderloNéLeggerlo()
    {
        IntPtr ereditabile = CreaEventoEreditabile();
        using var p = AvvioProtetto.Avvia(IntPtr.Zero, Ping, "-n 30 127.0.0.1", Encoding.UTF8.GetBytes("{}"), desktop: null, senzaFinestra: true);
        try
        {
            foreach (var (nome, diritto) in SicurezzaAgente.VietatiProcesso)
                Assert.False(SicurezzaAgente.ApreProcesso(p.Pid, diritto), "processo: " + nome);
            Assert.True(SicurezzaAgente.ApreProcesso(p.Pid, 0x00100000 | 0x1000), "attendere la fine e leggere le informazioni di base sì");

            foreach (var (nome, diritto) in SicurezzaAgente.VietatiThread)
                Assert.False(SicurezzaAgente.ApreThread(p.Tid, diritto), "thread principale: " + nome);
            Assert.True(SicurezzaAgente.ApreThread(p.Tid, 0x00100000 | 0x0800));

            // Come "taskkill /f" o Gestione attività.
            using (var visto = Process.GetProcessById(p.Pid))
                Assert.Throws<Win32Exception>(() => visto.Kill());

            // Eredita solo i due capi di conduttura, non gli altri handle ereditabili di chi lo avvia.
            Assert.False(p.HaEreditatoPerProva(ereditabile));

            // L'uscita standard arriva (qui è il testo di ping; per l'agente è il battito).
            var limite = Environment.TickCount64 + 10_000;
            while (p.Battiti == 0 && Environment.TickCount64 < limite) Thread.Sleep(100);
            Assert.True(p.Battiti > 0);
            Assert.False(p.Uscito(out _));
        }
        finally
        {
            // Solo chi l'ha avviato (con l'handle della creazione) può chiuderlo.
            Assert.True(p.Termina(CodiciAgente.ChiusoPerchéBloccato));
            CloseHandle(ereditabile);
        }
        Assert.True(p.Uscito(out uint codice));
        Assert.Equal(CodiciAgente.ChiusoPerchéBloccato, codice);
    }

    [ProvaDaUtente]
    public void ThreadProtetto_NonSiSospende()
    {
        int tid = 0;
        using var pronto = new ManualResetEventSlim();
        using var fine = new ManualResetEventSlim();
        var t = new Thread(() =>
        {
            tid = GetCurrentThreadId();
            pronto.Set();
            fine.Wait(10_000);
        }) { IsBackground = true };
        t.Start();
        pronto.Wait();
        try
        {
            Assert.True(SicurezzaAgente.ApreThread(tid, 0x0002 /* THREAD_SUSPEND_RESUME */)); // prima: permessi di serie
            var sd = SicurezzaAgente.Descrittore(SicurezzaAgente.SddlThread(WindowsIdentity.GetCurrent().User!.Value));
            try
            {
                Assert.True(SicurezzaAgente.ProteggiThread(tid, sd));
                Assert.False(SicurezzaAgente.ProteggiThread(tid, sd)); // già protetto: non si riapre per cambiarlo
            }
            finally
            {
                SicurezzaAgente.Libera(sd);
            }
            foreach (var (nome, diritto) in SicurezzaAgente.VietatiThread)
                Assert.False(SicurezzaAgente.ApreThread(tid, diritto), nome);
            Assert.True(SicurezzaAgente.ApreThread(tid, 0x00100000));
        }
        finally
        {
            fine.Set();
            t.Join();
        }
    }

    [Fact]
    public void Sddl()
    {
        const string sid = "S-1-5-21-1-2-3-1001";
        Assert.Equal("D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x121400;;;S-1-5-21-1-2-3-1001)(A;;RC;;;OW)", SicurezzaAgente.SddlProcesso(sid));
        // Nessun diritto vietato nella voce dell'utente.
        foreach (var (_, diritto) in SicurezzaAgente.VietatiProcesso) Assert.Equal(0u, SicurezzaAgente.DirittiUtenteProcesso & diritto);
        foreach (var (_, diritto) in SicurezzaAgente.VietatiThread) Assert.Equal(0u, SicurezzaAgente.DirittiUtenteThread & diritto);
        var sd = SicurezzaAgente.Descrittore(SicurezzaAgente.SddlThread(sid));
        Assert.NotEqual(IntPtr.Zero, sd);
        SicurezzaAgente.Libera(sd);
    }

    private static IntPtr CreaEventoEreditabile()
    {
        var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), bInheritHandle = 1 };
        var h = CreateEvent(ref sa, true, false, null);
        Assert.NotEqual(IntPtr.Zero, h);
        return h;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        public int bInheritHandle;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateEventW")]
    private static extern IntPtr CreateEvent(ref SECURITY_ATTRIBUTES sa, [MarshalAs(UnmanagedType.Bool)] bool manuale,
        [MarshalAs(UnmanagedType.Bool)] bool segnalato, string? nome);

    [DllImport("kernel32.dll")]
    private static extern int GetCurrentThreadId();

    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr h);
}
