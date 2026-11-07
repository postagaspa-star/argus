using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace Argus.Nucleo;

/// <summary>
/// I permessi dell'agente (revisione B6): l'utente dello studente non può chiuderlo, sospenderlo, leggerne o
/// scriverne la memoria, iniettargli codice, duplicarne gli handle, cambiarne le informazioni né i permessi.
/// <list type="bullet">
/// <item>SYSTEM e Administrators: tutto;</item>
/// <item>l'utente: solo attendere la fine, leggere le informazioni di base e i permessi;</item>
/// <item>OWNER RIGHTS: solo leggere i permessi. Senza questa voce il proprietario (lo studente: il processo
/// gira col suo token) potrebbe sempre riscrivere i permessi e ridarsi tutto.</item>
/// </list>
/// "P" = la DACL è protetta (niente permessi ereditati).
/// </summary>
public static class SicurezzaAgente
{
    // Processo: SYNCHRONIZE | READ_CONTROL | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION.
    public const uint DirittiUtenteProcesso = 0x00100000 | 0x00020000 | 0x0400 | 0x1000;

    // Thread: SYNCHRONIZE | READ_CONTROL | THREAD_QUERY_INFORMATION | THREAD_QUERY_LIMITED_INFORMATION.
    public const uint DirittiUtenteThread = 0x00100000 | 0x00020000 | 0x0040 | 0x0800;

    // Evento del collegamento "Argus - terminale": SYNCHRONIZE | EVENT_MODIFY_STATE.
    public const uint DirittiUtenteEvento = 0x00100000 | 0x0002;

    /// <summary>I diritti vietati all'utente (quelli della revisione B6), per le prove.</summary>
    public static readonly (string Nome, uint Diritto)[] VietatiProcesso =
    {
        ("PROCESS_TERMINATE", 0x0001), ("PROCESS_CREATE_THREAD", 0x0002), ("PROCESS_VM_OPERATION", 0x0008),
        ("PROCESS_VM_READ", 0x0010), ("PROCESS_VM_WRITE", 0x0020), ("PROCESS_DUP_HANDLE", 0x0040),
        ("PROCESS_SET_QUOTA", 0x0100), ("PROCESS_SET_INFORMATION", 0x0200), ("PROCESS_SUSPEND_RESUME", 0x0800),
        ("WRITE_DAC", 0x00040000), ("WRITE_OWNER", 0x00080000), ("DELETE", 0x00010000),
    };

    public static readonly (string Nome, uint Diritto)[] VietatiThread =
    {
        ("THREAD_TERMINATE", 0x0001), ("THREAD_SUSPEND_RESUME", 0x0002), ("THREAD_GET_CONTEXT", 0x0008),
        ("THREAD_SET_CONTEXT", 0x0010), ("THREAD_SET_INFORMATION", 0x0020), ("THREAD_SET_THREAD_TOKEN", 0x0080),
        ("THREAD_IMPERSONATE", 0x0100), ("THREAD_DIRECT_IMPERSONATION", 0x0200),
        ("WRITE_DAC", 0x00040000), ("WRITE_OWNER", 0x00080000),
    };

    public static string SddlProcesso(string sidUtente) => Sddl(sidUtente, DirittiUtenteProcesso);
    public static string SddlThread(string sidUtente) => Sddl(sidUtente, DirittiUtenteThread);
    public static string SddlEvento(string sidUtente) => Sddl(sidUtente, DirittiUtenteEvento);

    private static string Sddl(string sid, uint utente) =>
        $"D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x{utente:X};;;{sid})(A;;RC;;;OW)";

    /// <summary>
    /// Un descrittore di sicurezza dalla stringa SDDL (in memoria non gestita: va liberato con <see cref="Libera"/>).
    /// </summary>
    public static IntPtr Descrittore(string sddl)
    {
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1, out var sd, IntPtr.Zero))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "descrittore di sicurezza");
        return sd;
    }

    public static void Libera(IntPtr sd)
    {
        if (sd != IntPtr.Zero) LocalFree(sd);
    }

    /// <summary>
    /// Rimette i permessi stretti a tutti i thread di questo processo. L'agente lo fa ogni 5 secondi: i thread nuovi
    /// nascono con i permessi di serie dell'utente (il thread principale li ha già dal guardiano). Un thread già
    /// protetto non si riapre con WRITE_DAC e si salta. Torna quanti thread ha protetto in questo giro.
    /// </summary>
    public static int ProteggiThreadDelProcesso(string sidUtente)
    {
        var sd = Descrittore(SddlThread(sidUtente));
        try
        {
            int protetti = 0;
            using var processo = System.Diagnostics.Process.GetCurrentProcess();
            foreach (System.Diagnostics.ProcessThread t in processo.Threads)
            {
                using (t)
                {
                    if (ProteggiThread(t.Id, sd)) protetti++;
                }
            }
            return protetti;
        }
        finally
        {
            Libera(sd);
        }
    }

    /// <summary>Mette il descrittore <paramref name="sd"/> a un thread (falso se il thread non si apre per cambiarlo).</summary>
    public static bool ProteggiThread(int tid, IntPtr sd)
    {
        IntPtr h = OpenThread(WRITE_DAC, false, tid);
        if (h == IntPtr.Zero) return false;
        try
        {
            return SetKernelObjectSecurity(h, DACL_SECURITY_INFORMATION, sd);
        }
        finally
        {
            CloseHandle(h);
        }
    }

    /// <summary>Si riesce ad aprire il processo con questi diritti? (Per le prove: l'utente non deve riuscirci.)</summary>
    public static bool ApreProcesso(int pid, uint diritti)
    {
        IntPtr h = OpenProcess(diritti, false, pid);
        if (h == IntPtr.Zero) return false;
        CloseHandle(h);
        return true;
    }

    /// <summary>Si riesce ad aprire il thread con questi diritti? (Per le prove.)</summary>
    public static bool ApreThread(int tid, uint diritti)
    {
        IntPtr h = OpenThread(diritti, false, tid);
        if (h == IntPtr.Zero) return false;
        CloseHandle(h);
        return true;
    }

    private const uint WRITE_DAC = 0x00040000;
    private const uint DACL_SECURITY_INFORMATION = 0x00000004;

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenThread(uint diritti, [MarshalAs(UnmanagedType.Bool)] bool eredita, int tid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint diritti, [MarshalAs(UnmanagedType.Bool)] bool eredita, int pid);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetKernelObjectSecurity(IntPtr handle, uint informazioni, IntPtr sd);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string sddl, uint revisione, out IntPtr sd, IntPtr dimensione);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr h);
}

/// <summary>
/// Avvia l'agente protetto (revisione B6), dal guardiano (con il token dello studente) o, nelle prove, con
/// l'utente che sta usando il PC (token zero):
/// <list type="bullet">
/// <item>processo e thread principale con i permessi di <see cref="SicurezzaAgente"/>;</item>
/// <item>eredita SOLO i due capi di conduttura che gli servono (PROC_THREAD_ATTRIBUTE_HANDLE_LIST): l'ingresso
/// standard con la configurazione e l'uscita standard per il battito. Windows vuole bInheritHandles = TRUE quando
/// si passa l'elenco: è l'elenco che limita l'eredità a quei due handle e a nient'altro del guardiano;</item>
/// <item>le condutture anonime sono condutture con nome casuale e permessi di SYSTEM: nessun altro processo può
/// aprirle per mandare un battito finto;</item>
/// <item>il battito: l'agente scrive un byte ogni 5 secondi; qui si ricorda quando è arrivato l'ultimo.</item>
/// </list>
/// </summary>
public static class AvvioProtetto
{
    public static ProcessoProtetto Avvia(IntPtr token, string exe, string? argomenti, byte[] ingresso, string? desktop = @"winsta0\default",
        IntPtr ambiente = default, bool senzaFinestra = false)
    {
        string sid = token == IntPtr.Zero ? WindowsIdentity.GetCurrent().User!.Value : SidDelToken(token);
        IntPtr sdProcesso = IntPtr.Zero, sdThread = IntPtr.Zero, elenco = IntPtr.Zero, handles = IntPtr.Zero;
        IntPtr ingLettura = IntPtr.Zero, ingScrittura = IntPtr.Zero, uscLettura = IntPtr.Zero, uscScrittura = IntPtr.Zero;
        try
        {
            sdProcesso = SicurezzaAgente.Descrittore(SicurezzaAgente.SddlProcesso(sid));
            sdThread = SicurezzaAgente.Descrittore(SicurezzaAgente.SddlThread(sid));

            var ereditabile = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), bInheritHandle = 1 };
            // 64 KB: la configurazione ci sta tutta, la scrittura non aspetta mai l'agente.
            if (!CreatePipe(out ingLettura, out ingScrittura, ref ereditabile, 64 * 1024)) throw Errore("CreatePipe");
            SetHandleInformation(ingScrittura, HANDLE_FLAG_INHERIT, 0);
            if (!CreatePipe(out uscLettura, out uscScrittura, ref ereditabile, 4096)) throw Errore("CreatePipe");
            SetHandleInformation(uscLettura, HANDLE_FLAG_INHERIT, 0);

            // Solo questi due handle passano all'agente.
            IntPtr dimensione = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref dimensione);
            elenco = Marshal.AllocHGlobal(dimensione);
            if (!InitializeProcThreadAttributeList(elenco, 1, 0, ref dimensione)) throw Errore("InitializeProcThreadAttributeList");
            handles = Marshal.AllocHGlobal(2 * IntPtr.Size);
            Marshal.WriteIntPtr(handles, 0, ingLettura);
            Marshal.WriteIntPtr(handles, IntPtr.Size, uscScrittura);
            if (!UpdateProcThreadAttribute(elenco, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, handles, (IntPtr)(2 * IntPtr.Size), IntPtr.Zero, IntPtr.Zero))
                throw Errore("UpdateProcThreadAttribute");

            var avvio = new STARTUPINFOEX();
            avvio.StartupInfo.cb = Marshal.SizeOf<STARTUPINFOEX>();
            avvio.StartupInfo.lpDesktop = desktop;
            avvio.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            avvio.StartupInfo.hStdInput = ingLettura;
            avvio.StartupInfo.hStdOutput = uscScrittura;
            avvio.lpAttributeList = elenco;

            var saProcesso = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), lpSecurityDescriptor = sdProcesso };
            var saThread = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf<SECURITY_ATTRIBUTES>(), lpSecurityDescriptor = sdThread };
            uint opzioni = EXTENDED_STARTUPINFO_PRESENT | (ambiente != IntPtr.Zero ? CREATE_UNICODE_ENVIRONMENT : 0) | (senzaFinestra ? CREATE_NO_WINDOW : 0);
            var riga = new StringBuilder($"\"{exe}\"" + (string.IsNullOrEmpty(argomenti) ? "" : " " + argomenti));
            PROCESS_INFORMATION info;
            bool fatto = token == IntPtr.Zero
                ? CreateProcess(exe, riga, ref saProcesso, ref saThread, true, opzioni, ambiente, Path.GetDirectoryName(exe), ref avvio, out info)
                : CreateProcessAsUser(token, exe, riga, ref saProcesso, ref saThread, true, opzioni, ambiente, Path.GetDirectoryName(exe), ref avvio, out info);
            if (!fatto) throw Errore(token == IntPtr.Zero ? "CreateProcess" : "CreateProcessAsUser");

            CloseHandle(ingLettura);
            ingLettura = IntPtr.Zero;
            CloseHandle(uscScrittura);
            uscScrittura = IntPtr.Zero;
            using (var flusso = new FileStream(new SafeFileHandle(ingScrittura, ownsHandle: true), FileAccess.Write, 1))
            {
                ingScrittura = IntPtr.Zero;
                flusso.Write(ingresso, 0, ingresso.Length);
            }
            var p = new ProcessoProtetto(info.hProcess, info.hThread, info.dwProcessId, info.dwThreadId, uscLettura);
            uscLettura = IntPtr.Zero;
            return p;
        }
        finally
        {
            foreach (var h in new[] { ingLettura, ingScrittura, uscLettura, uscScrittura })
                if (h != IntPtr.Zero) CloseHandle(h);
            if (elenco != IntPtr.Zero)
            {
                DeleteProcThreadAttributeList(elenco);
                Marshal.FreeHGlobal(elenco);
            }
            if (handles != IntPtr.Zero) Marshal.FreeHGlobal(handles);
            SicurezzaAgente.Libera(sdProcesso);
            SicurezzaAgente.Libera(sdThread);
        }
    }

    /// <summary>Il SID (stringa) dell'utente di un token.</summary>
    public static string SidDelToken(IntPtr token)
    {
        GetTokenInformation(token, 1 /* TokenUser */, IntPtr.Zero, 0, out int lunghezza);
        var buffer = Marshal.AllocHGlobal(lunghezza);
        try
        {
            if (!GetTokenInformation(token, 1, buffer, lunghezza, out _)) throw Errore("GetTokenInformation");
            var sid = Marshal.ReadIntPtr(buffer); // TOKEN_USER.User.Sid
            return new SecurityIdentifier(sid).Value;
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static Win32Exception Errore(string dove) => new(Marshal.GetLastWin32Error(), dove);

    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint CREATE_UNICODE_ENVIRONMENT = 0x00000400;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
    private const uint HANDLE_FLAG_INHERIT = 0x00000001;
    private static readonly IntPtr PROC_THREAD_ATTRIBUTE_HANDLE_LIST = (IntPtr)0x00020002;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO
    {
        public int cb;
        public string? lpReserved;
        public string? lpDesktop;
        public string? lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute;
        public uint dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFOEX
    {
        public STARTUPINFO StartupInfo;
        public IntPtr lpAttributeList;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess, hThread;
        public int dwProcessId, dwThreadId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES
    {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        public int bInheritHandle;
    }

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "CreateProcessAsUserW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcessAsUser(IntPtr token, string? applicazione, StringBuilder rigaComando, ref SECURITY_ATTRIBUTES attributiProcesso,
        ref SECURITY_ATTRIBUTES attributiThread, [MarshalAs(UnmanagedType.Bool)] bool eredita, uint opzioni, IntPtr ambiente, string? cartella,
        ref STARTUPINFOEX avvio, out PROCESS_INFORMATION info);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "CreateProcessW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(string? applicazione, StringBuilder rigaComando, ref SECURITY_ATTRIBUTES attributiProcesso,
        ref SECURITY_ATTRIBUTES attributiThread, [MarshalAs(UnmanagedType.Bool)] bool eredita, uint opzioni, IntPtr ambiente, string? cartella,
        ref STARTUPINFOEX avvio, out PROCESS_INFORMATION info);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(IntPtr elenco, int quanti, int opzioni, ref IntPtr dimensione);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(IntPtr elenco, uint opzioni, IntPtr attributo, IntPtr valore, IntPtr dimensione,
        IntPtr precedente, IntPtr dimensionePrecedente);

    [DllImport("kernel32.dll")]
    private static extern void DeleteProcThreadAttributeList(IntPtr elenco);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(out IntPtr lettura, out IntPtr scrittura, ref SECURITY_ATTRIBUTES attributi, uint dimensione);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetHandleInformation(IntPtr handle, uint maschera, uint valori);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetTokenInformation(IntPtr token, int classe, IntPtr buffer, int lunghezza, out int richiesta);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool CloseHandle(IntPtr handle);
}

/// <summary>Un agente avviato protetto: handle del processo (con tutti i diritti: è del guardiano), battito.</summary>
public sealed class ProcessoProtetto : IDisposable
{
    private IntPtr processo;
    private IntPtr thread;
    private long ultimoBattitoMs;
    private readonly Thread? lettore;

    public ProcessoProtetto(IntPtr processo, IntPtr thread, int pid, int tid, IntPtr battito)
    {
        this.processo = processo;
        this.thread = thread;
        Pid = pid;
        Tid = tid;
        AvviatoMs = Environment.TickCount64;
        ultimoBattitoMs = AvviatoMs;
        Avviato = DateTimeOffset.Now;
        if (battito != IntPtr.Zero)
        {
            var flusso = new FileStream(new SafeFileHandle(battito, ownsHandle: true), FileAccess.Read, 1);
            lettore = new Thread(() => Leggi(flusso)) { IsBackground = true, Name = "Argus battito " + pid };
            lettore.Start();
        }
    }

    public int Pid { get; }
    public int Tid { get; }
    public long AvviatoMs { get; }
    public DateTimeOffset Avviato { get; }

    /// <summary>Quanti battiti sono arrivati (per il registro e le prove).</summary>
    public int Battiti => Volatile.Read(ref battiti);

    private int battiti;

    /// <summary>L'ultimo battito (o l'avvio, se non ne è ancora arrivato nessuno).</summary>
    public long UltimoBattitoMs => Interlocked.Read(ref ultimoBattitoMs);

    private void Leggi(FileStream flusso)
    {
        var buffer = new byte[64];
        try
        {
            using (flusso)
            {
                while (true)
                {
                    int n = flusso.Read(buffer, 0, buffer.Length);
                    if (n <= 0) return; // l'agente ha chiuso l'uscita (o è uscito)
                    Interlocked.Add(ref battiti, n);
                    Interlocked.Exchange(ref ultimoBattitoMs, Environment.TickCount64);
                }
            }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException)
        {
        }
    }

    /// <summary>È uscito? Se sì, con quale codice.</summary>
    public bool Uscito(out uint codice)
    {
        codice = 0;
        if (processo == IntPtr.Zero) return true;
        if (WaitForSingleObject(processo, 0) != 0) return false; // WAIT_OBJECT_0 = 0: uscito
        GetExitCodeProcess(processo, out codice);
        return true;
    }

    /// <summary>Chiude l'agente (solo chi l'ha avviato ha l'handle con questo diritto).</summary>
    public bool Termina(uint codice)
    {
        if (processo == IntPtr.Zero) return false;
        bool ok = TerminateProcess(processo, codice);
        WaitForSingleObject(processo, 5000);
        return ok;
    }

    /// <summary>Solo per le prove: congela l'agente come farebbe chi volesse fermarlo senza chiuderlo.</summary>
    public bool SospendiPerProva() => processo != IntPtr.Zero && NtSuspendProcess(processo) == 0;

    /// <summary>
    /// Solo per le prove: l'agente ha ereditato questo handle del guardiano? Gli handle ereditati tengono lo stesso
    /// valore nel processo figlio: si copia quel valore dal figlio e si guarda se è lo stesso oggetto.
    /// </summary>
    public bool HaEreditatoPerProva(IntPtr handleDelGuardiano)
    {
        if (processo == IntPtr.Zero) return false;
        var qui = GetCurrentProcess();
        if (!DuplicateHandle(processo, handleDelGuardiano, qui, out var copia, 0, false, 2 /* DUPLICATE_SAME_ACCESS */)) return false;
        try
        {
            return CompareObjectHandles(copia, handleDelGuardiano);
        }
        finally
        {
            AvvioProtetto.CloseHandle(copia);
        }
    }

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DuplicateHandle(IntPtr processoSorgente, IntPtr sorgente, IntPtr processoDestinazione, out IntPtr destinazione,
        uint diritti, [MarshalAs(UnmanagedType.Bool)] bool eredita, uint opzioni);

    [DllImport("kernelbase.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CompareObjectHandles(IntPtr primo, IntPtr secondo);

    public void Dispose()
    {
        if (thread != IntPtr.Zero) AvvioProtetto.CloseHandle(thread);
        if (processo != IntPtr.Zero) AvvioProtetto.CloseHandle(processo);
        thread = processo = IntPtr.Zero;
    }

    [DllImport("ntdll.dll")]
    private static extern int NtSuspendProcess(IntPtr processo);

    [DllImport("kernel32.dll")]
    private static extern uint WaitForSingleObject(IntPtr handle, uint ms);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr processo, out uint codice);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(IntPtr processo, uint codice);
}

/// <summary>
/// Il battito dell'agente (revisione B6): un byte ogni 5 secondi verso il guardiano. Se non arriva per 20 secondi
/// (o il primo non arriva entro un minuto dall'avvio, per i PC lenti all'accesso) l'agente è sospeso o bloccato:
/// il guardiano lo chiude, lo riapre e manda <c>agente_bloccato</c>.
/// </summary>
public static class RegoleBattito
{
    public const int OgniMs = 5000;
    public const long VivoEntroMs = 10_000;
    public const long SilenzioMassimoMs = 20_000;
    public const long PrimoBattitoEntroMs = 60_000;

    public static bool Bloccato(long adessoMs, long avviatoMs, long ultimoBattitoMs, int battiti) =>
        battiti == 0 ? adessoMs - avviatoMs > PrimoBattitoEntroMs : adessoMs - ultimoBattitoMs > SilenzioMassimoMs;
}

/// <summary>Codici d'uscita dell'agente che il guardiano distingue.</summary>
public static class CodiciAgente
{
    /// <summary>L'agente ha ricevuto un messaggio di uscita che non ha chiesto lui (WM_QUIT da un altro programma).</summary>
    public const int UscitaNonRichiesta = 5;

    /// <summary>Chiuso dal guardiano perché non batteva più (sospeso o bloccato).</summary>
    public const uint ChiusoPerchéBloccato = 0xA9B0;
}
