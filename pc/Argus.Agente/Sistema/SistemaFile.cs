using System.Diagnostics;
using System.Runtime.InteropServices;

namespace Argus.Agente.Sistema;

/// <summary>
/// I file visti da Windows, per riconoscere i programmi (revisione B5). "Scrivibile" si chiede a Windows stesso
/// (AccessCheck col token dell'agente, cioè dello studente): così vale anche per le cartelle sotto Windows o
/// Program Files dove gli utenti possono scrivere (per esempio Windows\Temp).
/// </summary>
internal sealed class SistemaFileWindows : ISistemaFile
{
    public (DateTime Modifica, long Byte)? Impronta(string percorso)
    {
        try
        {
            var f = new FileInfo(percorso);
            if (!f.Exists) return null;
            return (f.LastWriteTimeUtc, f.Length);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException or NotSupportedException)
        {
            return null;
        }
    }

    public bool FirmaValida(string percorso) => Firma.ValidaDalComputer(percorso);

    public string? NomeOriginale(string percorso)
    {
        try
        {
            return FileVersionInfo.GetVersionInfo(percorso).OriginalFilename;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException)
        {
            return null;
        }
    }

    // Diritti che permettono di cambiare o sostituire il programma.
    private const uint FILE_WRITE_DATA = 0x0002;       // per una cartella: FILE_ADD_FILE
    private const uint FILE_APPEND_DATA = 0x0004;      // per una cartella: FILE_ADD_SUBDIRECTORY
    private const uint FILE_DELETE_CHILD = 0x0040;
    private const uint DELETE = 0x00010000;
    private const uint WRITE_DAC = 0x00040000;
    private const uint WRITE_OWNER = 0x00080000;
    private const uint MAXIMUM_ALLOWED = 0x02000000;

    private const uint PericolosiFile = FILE_WRITE_DATA | FILE_APPEND_DATA | DELETE | WRITE_DAC | WRITE_OWNER;
    private const uint PericolosiCartella = FILE_WRITE_DATA | FILE_DELETE_CHILD | WRITE_DAC | WRITE_OWNER;

    public bool Scrivibile(string percorso)
    {
        var cartella = Path.GetDirectoryName(percorso);
        if (cartella == null) return true;
        var f = Concessi(percorso);
        var c = Concessi(cartella);
        // Nel dubbio (permessi che non si leggono) si considera scrivibile: il programma allora vale solo con firma.
        if (f == null || c == null) return true;
        return (f.Value & PericolosiFile) != 0 || (c.Value & PericolosiCartella) != 0;
    }

    /// <summary>I diritti che l'utente dell'agente avrebbe su quel file o cartella (AccessCheck), o null se non si sa.</summary>
    internal static uint? Concessi(string percorso)
    {
        IntPtr sd = IntPtr.Zero, token = IntPtr.Zero, imitazione = IntPtr.Zero, privilegi = IntPtr.Zero;
        try
        {
            uint errore = GetNamedSecurityInfo(percorso, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | GROUP_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                out _, out _, out _, out _, out sd);
            if (errore != 0) return null;
            if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY | TOKEN_DUPLICATE, out token)) return null;
            if (!DuplicateToken(token, 2 /* SecurityImpersonation */, out imitazione)) return null;
            var mappa = new GENERIC_MAPPING { GenericRead = 0x120089, GenericWrite = 0x120116, GenericExecute = 0x1200A0, GenericAll = 0x1F01FF };
            uint lunghezza = 1024;
            privilegi = Marshal.AllocHGlobal((int)lunghezza);
            if (!AccessCheck(sd, imitazione, MAXIMUM_ALLOWED, ref mappa, privilegi, ref lunghezza, out uint concessi, out bool esito)) return null;
            return esito ? concessi : 0;
        }
        finally
        {
            if (privilegi != IntPtr.Zero) Marshal.FreeHGlobal(privilegi);
            if (imitazione != IntPtr.Zero) CloseHandle(imitazione);
            if (token != IntPtr.Zero) CloseHandle(token);
            if (sd != IntPtr.Zero) LocalFree(sd);
        }
    }

    private const int SE_FILE_OBJECT = 1;
    private const uint OWNER_SECURITY_INFORMATION = 0x1, GROUP_SECURITY_INFORMATION = 0x2, DACL_SECURITY_INFORMATION = 0x4;
    private const uint TOKEN_DUPLICATE = 0x0002, TOKEN_QUERY = 0x0008;

    [StructLayout(LayoutKind.Sequential)]
    private struct GENERIC_MAPPING
    {
        public uint GenericRead, GenericWrite, GenericExecute, GenericAll;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, EntryPoint = "GetNamedSecurityInfoW")]
    private static extern uint GetNamedSecurityInfo(string nome, int tipo, uint info, out IntPtr proprietario, out IntPtr gruppo,
        out IntPtr dacl, out IntPtr sacl, out IntPtr descrittore);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool OpenProcessToken(IntPtr processo, uint accesso, out IntPtr token);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DuplicateToken(IntPtr token, int livello, out IntPtr copia);

    [DllImport("advapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AccessCheck(IntPtr descrittore, IntPtr token, uint desiderato, ref GENERIC_MAPPING mappa,
        IntPtr privilegi, ref uint lunghezzaPrivilegi, out uint concessi, [MarshalAs(UnmanagedType.Bool)] out bool esito);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GetCurrentProcess();

    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr h);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr h);
}
