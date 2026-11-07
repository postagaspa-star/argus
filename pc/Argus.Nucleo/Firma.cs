using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;

namespace Argus.Nucleo;

/// <summary>
/// La firma Authenticode di un eseguibile (come in Pactum). Niente rete: la revoca non si controlla.
/// <list type="bullet">
/// <item><see cref="Soggetto"/>: il nome (CN) di chi ha firmato, solo se la firma è valida. Serve a far partire
/// solo il llama-server.exe firmato da Element Labs (LM Studio).</item>
/// <item><see cref="ValidaDalComputer"/>: firma valida E radice della catena tra quelle del computer
/// (LocalMachine Root o AuthRoot). Un utente normale può aggiungere una radice SOLO per sé (CurrentUser\Root) e
/// Windows la accetterebbe: così una firma fatta in casa non basta a far riconoscere un programma.</item>
/// </list>
/// </summary>
public static class Firma
{
    public static string? Soggetto(string? percorso)
    {
        if (string.IsNullOrEmpty(percorso) || !File.Exists(percorso)) return null;
        try
        {
            if (!ValidaDalComputer(percorso)) return null;
#pragma warning disable SYSLIB0057 // l'API nuova non legge la firma di un eseguibile
            using var cert = new X509Certificate2(X509Certificate.CreateFromSignedFile(percorso));
#pragma warning restore SYSLIB0057
            var nome = cert.GetNameInfo(X509NameType.SimpleName, forIssuer: false);
            return string.IsNullOrWhiteSpace(nome) ? null : nome;
        }
        catch (CryptographicException)
        {
            return null;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or ArgumentException or DllNotFoundException or EntryPointNotFoundException)
        {
            return null;
        }
    }

    /// <summary>Firma valida (file non cambiato, catena fidata) con la radice nei certificati del computer.</summary>
    public static bool ValidaDalComputer(string? percorso)
    {
        if (string.IsNullOrEmpty(percorso) || !File.Exists(percorso)) return false;
        try
        {
            var radice = Verifica(percorso);
            return radice != null && RadiceDelComputer(radice);
        }
        catch (Exception e) when (e is CryptographicException or IOException or UnauthorizedAccessException or ArgumentException
                                       or DllNotFoundException or EntryPointNotFoundException)
        {
            return false;
        }
    }

    private static readonly object chiaveRadici = new();
    private static HashSet<string>? radiciComputer;
    private static long radiciLetteMs = long.MinValue / 2;

    /// <summary>Le impronte delle radici del computer (LocalMachine Root e AuthRoot), rilette ogni 10 minuti.</summary>
    private static bool RadiceDelComputer(string impronta)
    {
        lock (chiaveRadici)
        {
            long ms = Environment.TickCount64;
            if (radiciComputer == null || ms - radiciLetteMs > 600_000)
            {
                var insieme = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var nome in new[] { StoreName.Root, StoreName.AuthRoot })
                {
                    try
                    {
                        using var negozio = new X509Store(nome, StoreLocation.LocalMachine);
                        negozio.Open(OpenFlags.ReadOnly | OpenFlags.OpenExistingOnly);
                        foreach (var c in negozio.Certificates)
                        {
                            insieme.Add(c.Thumbprint);
                            c.Dispose();
                        }
                    }
                    catch (CryptographicException)
                    {
                    }
                }
                radiciComputer = insieme;
                radiciLetteMs = ms;
            }
            return radiciComputer.Contains(impronta);
        }
    }

    private static readonly Guid VerificaGenerica = new("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct WINTRUST_FILE_INFO
    {
        public uint cbStruct;
        public IntPtr pcwszFilePath;
        public IntPtr hFile;
        public IntPtr pgKnownSubject;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WINTRUST_DATA
    {
        public uint cbStruct;
        public IntPtr pPolicyCallbackData;
        public IntPtr pSIPClientData;
        public uint dwUIChoice;
        public uint fdwRevocationChecks;
        public uint dwUnionChoice;
        public IntPtr pFile;
        public uint dwStateAction;
        public IntPtr hWVTStateData;
        public IntPtr pwszURLReference;
        public uint dwProvFlags;
        public uint dwUIContext;
        public IntPtr pSignatureSettings;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct CRYPT_PROVIDER_SGNR
    {
        public uint cbStruct;
        public System.Runtime.InteropServices.ComTypes.FILETIME sftVerifyAsOf;
        public uint csCertChain;
        public IntPtr pasCertChain;
        public uint dwSignerType;
        public IntPtr psSigner;
        public uint dwError;
        public uint csCounterSigners;
        public IntPtr pasCounterSigners;
        public IntPtr pChainContext;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct CRYPT_PROVIDER_CERT
    {
        public uint cbStruct;
        public IntPtr pCert;
    }

    [DllImport("wintrust.dll", ExactSpelling = true, SetLastError = false)]
    private static extern int WinVerifyTrust(IntPtr hwnd, ref Guid azione, ref WINTRUST_DATA dati);

    [DllImport("wintrust.dll", ExactSpelling = true)]
    private static extern IntPtr WTHelperProvDataFromStateData(IntPtr stato);

    [DllImport("wintrust.dll", ExactSpelling = true)]
    private static extern IntPtr WTHelperGetProvSignerFromChain(IntPtr dati, uint firmatario, [MarshalAs(UnmanagedType.Bool)] bool controfirma, uint indiceControfirma);

    private const uint WTD_STATEACTION_VERIFY = 1;
    private const uint WTD_STATEACTION_CLOSE = 2;

    /// <summary>L'impronta (thumbprint) della radice della catena costruita da Windows, o null se la firma non vale.</summary>
    private static string? Verifica(string percorso)
    {
        var testo = Marshal.StringToHGlobalUni(percorso);
        var fileInfo = IntPtr.Zero;
        var azione = VerificaGenerica;
        var dati = new WINTRUST_DATA();
        try
        {
            var f = new WINTRUST_FILE_INFO { cbStruct = (uint)Marshal.SizeOf<WINTRUST_FILE_INFO>(), pcwszFilePath = testo };
            fileInfo = Marshal.AllocHGlobal(Marshal.SizeOf<WINTRUST_FILE_INFO>());
            Marshal.StructureToPtr(f, fileInfo, false);
            dati = new WINTRUST_DATA
            {
                cbStruct = (uint)Marshal.SizeOf<WINTRUST_DATA>(),
                dwUIChoice = 2,            // nessuna finestra
                fdwRevocationChecks = 0,
                dwUnionChoice = 1,         // un file
                pFile = fileInfo,
                dwStateAction = WTD_STATEACTION_VERIFY,
                dwProvFlags = 0x10 | 0x1000, // niente revoca, niente rete
            };
            if (WinVerifyTrust(new IntPtr(-1), ref azione, ref dati) != 0) return null;

            var prov = WTHelperProvDataFromStateData(dati.hWVTStateData);
            if (prov == IntPtr.Zero) return null;
            var pSgnr = WTHelperGetProvSignerFromChain(prov, 0, false, 0);
            if (pSgnr == IntPtr.Zero) return null;
            var sgnr = Marshal.PtrToStructure<CRYPT_PROVIDER_SGNR>(pSgnr);
            if (sgnr.pChainContext != IntPtr.Zero)
            {
                using var catena = new X509Chain(sgnr.pChainContext);
                if (catena.ChainElements.Count == 0) return null;
                return catena.ChainElements[^1].Certificate.Thumbprint;
            }
            if (sgnr.csCertChain == 0 || sgnr.pasCertChain == IntPtr.Zero) return null;
            // Senza contesto della catena: l'ultimo certificato dell'elenco è la radice.
            var primo = Marshal.PtrToStructure<CRYPT_PROVIDER_CERT>(sgnr.pasCertChain);
            var ultimo = Marshal.PtrToStructure<CRYPT_PROVIDER_CERT>(sgnr.pasCertChain + (int)((sgnr.csCertChain - 1) * primo.cbStruct));
            if (ultimo.pCert == IntPtr.Zero) return null;
            using var radice = new X509Certificate2(ultimo.pCert);
            return radice.Thumbprint;
        }
        finally
        {
            if (dati.hWVTStateData != IntPtr.Zero)
            {
                dati.dwStateAction = WTD_STATEACTION_CLOSE;
                WinVerifyTrust(new IntPtr(-1), ref azione, ref dati);
            }
            if (fileInfo != IntPtr.Zero) Marshal.FreeHGlobal(fileInfo);
            Marshal.FreeHGlobal(testo);
        }
    }
}
