using System.Diagnostics;
using System.Drawing;
using System.Text;

namespace Argus.Agente.Sistema;

/// <summary>La finestra in primo piano: processo, classe, schermo intero. Il titolo NON si legge qui.</summary>
/// <param name="Nostra">È una finestra di Argus stesso (copertura o terminale).</param>
internal sealed record FinestraAttiva(IntPtr Hwnd, int Pid, string Exe, string? Percorso, string Classe, bool SchermoIntero, bool Nostra);

internal static class PrimoPiano
{
    private static readonly uint MioPid = Win32.GetCurrentProcessId();
    public static string MioExe { get; } = (Path.GetFileName(Environment.ProcessPath) ?? "argus.agente.exe").ToLowerInvariant();

    private static readonly HashSet<string> ClassiDesktop = new(StringComparer.Ordinal)
    {
        "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    };

    public static FinestraAttiva? Leggi() => DaFinestra(Win32.GetForegroundWindow());

    public static FinestraAttiva? DaFinestra(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return null;
        Win32.GetWindowThreadProcessId(hwnd, out uint pid);
        if (pid == 0) return null;
        var (exe, percorso) = Processo(pid);
        if (exe == null) return null;
        // Le app dello Store vivono dentro ApplicationFrameHost: il processo vero è quello di una finestra figlia.
        if (exe == "applicationframehost.exe")
        {
            uint vero = ProcessoFiglio(hwnd, pid);
            if (vero != 0)
            {
                var (e2, p2) = Processo(vero);
                if (e2 != null)
                {
                    pid = vero;
                    exe = e2;
                    percorso = p2;
                }
            }
        }
        var classe = Win32.ClasseDi(hwnd);
        bool schermoIntero = !ClassiDesktop.Contains(classe) && SchermoIntero(hwnd);
        return new FinestraAttiva(hwnd, (int)pid, exe, percorso, classe, schermoIntero, pid == MioPid);
    }

    /// <summary>Nome dell'eseguibile (minuscolo) e percorso del file di un processo.</summary>
    public static (string? Exe, string? Percorso) Processo(uint pid)
    {
        var h = Win32.OpenProcess(Win32.PROCESS_QUERY_LIMITED_INFORMATION, false, pid);
        if (h != IntPtr.Zero)
        {
            try
            {
                var sb = new StringBuilder(1024);
                uint lunghezza = (uint)sb.Capacity;
                if (Win32.QueryFullProcessImageName(h, 0, sb, ref lunghezza))
                {
                    var percorso = sb.ToString();
                    return (Path.GetFileName(percorso).ToLowerInvariant(), percorso);
                }
            }
            finally
            {
                Win32.CloseHandle(h);
            }
        }
        try
        {
            using var p = Process.GetProcessById((int)pid);
            return (p.ProcessName.ToLowerInvariant() + ".exe", null);
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException)
        {
            return (null, null);
        }
    }

    private static uint ProcessoFiglio(IntPtr cornice, uint pidCornice)
    {
        uint trovato = 0;
        Win32.EnumChildWindows(cornice, (figlia, _) =>
        {
            Win32.GetWindowThreadProcessId(figlia, out uint p);
            if (p != 0 && p != pidCornice)
            {
                trovato = p;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return trovato;
    }

    private static bool SchermoIntero(IntPtr hwnd)
    {
        if (Win32.IsIconic(hwnd)) return false;
        if (!Win32.GetWindowRect(hwnd, out var r)) return false;
        var monitor = Win32.MonitorFromWindow(hwnd, Win32.MONITOR_DEFAULTTONEAREST);
        if (monitor == IntPtr.Zero) return false;
        var info = new Win32.MONITORINFO { cbSize = System.Runtime.InteropServices.Marshal.SizeOf<Win32.MONITORINFO>() };
        if (!Win32.GetMonitorInfo(monitor, ref info)) return false;
        var m = info.rcMonitor;
        return r.Left <= m.Left && r.Top <= m.Top && r.Right >= m.Right && r.Bottom >= m.Bottom;
    }
}

/// <summary>Inattività e schermo bloccato della sessione.</summary>
internal static class Sessione
{
    public static int SecondiInattivo()
    {
        var info = new Win32.LASTINPUTINFO { cbSize = (uint)System.Runtime.InteropServices.Marshal.SizeOf<Win32.LASTINPUTINFO>() };
        if (!Win32.GetLastInputInfo(ref info)) return 0;
        uint ms = unchecked((uint)Environment.TickCount - info.dwTime);
        return (int)Math.Min(int.MaxValue, ms / 1000);
    }

    /// <summary>Con lo schermo bloccato (o la richiesta di UAC) il desktop di input non è "Default".</summary>
    public static bool SchermoBloccato()
    {
        var desktop = Win32.OpenInputDesktop(0, false, Win32.DESKTOP_READOBJECTS);
        if (desktop == IntPtr.Zero) return true;
        try
        {
            var sb = new StringBuilder(64);
            return !(Win32.GetUserObjectInformation(desktop, Win32.UOI_NAME, sb, sb.Capacity * 2, out _)
                     && string.Equals(sb.ToString(), "Default", StringComparison.OrdinalIgnoreCase));
        }
        finally
        {
            Win32.CloseDesktop(desktop);
        }
    }
}

/// <summary>Pactum sta coprendo? Si guardano le finestre di pactum.exe (regole 12).</summary>
internal sealed class SentinellaPactum
{
    private readonly RiconoscitoreProgrammi riconoscitore;
    private Dictionary<uint, bool> pidPactum = new();
    private long ultimoElencoMs = long.MinValue / 2;

    public SentinellaPactum(RiconoscitoreProgrammi riconoscitore) => this.riconoscitore = riconoscitore;

    public bool Copre()
    {
        long ms = Environment.TickCount64;
        if (ms - ultimoElencoMs > 5000)
        {
            ultimoElencoMs = ms;
            // Solo un Pactum riconosciuto dal percorso (come gli altri programmi): un "Pactum.exe" qualsiasi no.
            var nuovi = new Dictionary<uint, bool>();
            foreach (var p in Process.GetProcessesByName("Pactum"))
            {
                var (exe, percorso) = PrimoPiano.Processo((uint)p.Id);
                nuovi[(uint)p.Id] = riconoscitore.Riconosci(exe, percorso).Nome == "pactum.exe";
                p.Dispose();
            }
            pidPactum = nuovi;
        }
        if (pidPactum.Count == 0) return false;
        var finestre = new List<FinestraVisibile>();
        Win32.EnumWindows((h, _) =>
        {
            Win32.GetWindowThreadProcessId(h, out uint pid);
            if (!pidPactum.TryGetValue(pid, out bool riconosciuto)) return true;
            if (!Win32.IsWindowVisible(h)) return true;
            if (Win32.RettangoloVisibile(h) is not Win32.RECT r) return true;
            long stile = Win32.StileEsteso(h);
            // Le coperture vere di Pactum non sono mai trasparenti (Pactum stesso le rifà se lo diventano).
            bool trasparente = (stile & (Win32.WS_EX_LAYERED | Win32.WS_EX_TRANSPARENT)) != 0 || Win32.HaRegione(h);
            finestre.Add(new FinestraVisibile("pactum.exe", true, Win32.Nascosta(h), Win32.IsIconic(h),
                (stile & Win32.WS_EX_TOPMOST) != 0, Rectangle.FromLTRB(r.Left, r.Top, r.Right, r.Bottom), riconosciuto, trasparente));
            return true;
        }, IntPtr.Zero);
        var aree = System.Windows.Forms.Screen.AllScreens.Select(s => s.WorkingArea).ToList();
        return CoperturaPactum.Copre(finestre, aree);
    }
}

/// <summary>Le misure del PC per le condizioni del modello (regole 10).</summary>
internal sealed class MisureWindows : IMisure
{
    public MisuraPc Leggi()
    {
        long totale = 0, inattivo = 0;
        if (Win32.GetSystemTimes(out var idle, out var kernel, out var user))
        {
            // Il tempo "kernel" comprende quello inattivo.
            totale = kernel.Valore + user.Valore;
            inattivo = idle.Valore;
        }
        var mem = new Win32.MEMORYSTATUSEX { dwLength = (uint)System.Runtime.InteropServices.Marshal.SizeOf<Win32.MEMORYSTATUSEX>() };
        long libera = Win32.GlobalMemoryStatusEx(ref mem) ? (long)Math.Min(mem.ullAvailPhys, long.MaxValue) : 0;
        bool? corrente = null;
        bool batteria = true;
        if (Win32.GetSystemPowerStatus(out var s))
        {
            corrente = s.ACLineStatus switch { 0 => false, 1 => true, _ => null };
            // 128 = nessuna batteria; 255 = stato sconosciuto: nel dubbio come se la batteria ci fosse.
            batteria = s.BatteryFlag == 255 || (s.BatteryFlag & 128) == 0;
        }
        return new MisuraPc(totale, inattivo, corrente, batteria, libera);
    }
}
