using System.ComponentModel;
using System.Runtime.InteropServices;

namespace Argus.Guardiano;

/// <summary>Le sessioni di Windows (WTS) e l'avvio di un programma nella sessione dell'utente.</summary>
internal static class Sessioni
{
    public const uint NessunaSessione = 0xFFFFFFFF;
    private const int WTSUserName = 5;
    private const int WTSConnectState = 8;
    private const int WTSActive = 0;

    [DllImport("kernel32.dll")]
    private static extern uint WTSGetActiveConsoleSessionId();

    [DllImport("wtsapi32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool WTSQueryUserToken(uint sessionId, out IntPtr token);

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool WTSQuerySessionInformation(IntPtr server, uint sessionId, int infoClass, out IntPtr buffer, out uint bytes);

    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(IntPtr memory);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("userenv.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateEnvironmentBlock(out IntPtr ambiente, IntPtr token, [MarshalAs(UnmanagedType.Bool)] bool eredita);

    [DllImport("userenv.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool DestroyEnvironmentBlock(IntPtr ambiente);

    /// <summary>La sessione attiva della console (quella davanti allo schermo), o NessunaSessione.</summary>
    public static uint SessioneConsole() => WTSGetActiveConsoleSessionId();

    public static string? Utente(uint sessione) => Testo(sessione, WTSUserName);

    public static bool Attiva(uint sessione)
    {
        if (!WTSQuerySessionInformation(IntPtr.Zero, sessione, WTSConnectState, out var buffer, out var byte_)) return false;
        try
        {
            return byte_ >= 4 && Marshal.ReadInt32(buffer) == WTSActive;
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
    }

    private static string? Testo(uint sessione, int classe)
    {
        if (!WTSQuerySessionInformation(IntPtr.Zero, sessione, classe, out var buffer, out _)) return null;
        try
        {
            var s = Marshal.PtrToStringUni(buffer);
            return string.IsNullOrWhiteSpace(s) ? null : s;
        }
        finally
        {
            WTSFreeMemory(buffer);
        }
    }

    /// <summary>
    /// Avvia <paramref name="exe"/> nella sessione data, con il token dell'utente di quella sessione (WTSQueryUserToken,
    /// solo da LocalSystem), sul desktop "winsta0\default", con l'ambiente dell'utente, protetto (revisione B6:
    /// <see cref="AvvioProtetto"/>). <paramref name="ingresso"/> arriva al programma sull'ingresso standard (una
    /// conduttura privata, mai sulla riga di comando); il battito torna dall'uscita standard.
    /// </summary>
    public static ProcessoProtetto Avvia(uint sessione, string exe, byte[] ingresso)
    {
        if (!WTSQueryUserToken(sessione, out var token)) throw new Win32Exception(Marshal.GetLastWin32Error(), "WTSQueryUserToken");
        IntPtr ambiente = IntPtr.Zero;
        try
        {
            if (!CreateEnvironmentBlock(out ambiente, token, false)) ambiente = IntPtr.Zero;
            return AvvioProtetto.Avvia(token, exe, null, ingresso, @"winsta0\default", ambiente);
        }
        finally
        {
            if (ambiente != IntPtr.Zero) DestroyEnvironmentBlock(ambiente);
            CloseHandle(token);
        }
    }
}
