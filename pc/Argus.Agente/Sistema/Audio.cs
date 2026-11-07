using System.Runtime.InteropServices;

namespace Argus.Agente.Sistema;

/// <summary>
/// Quali programmi stanno suonando: le sessioni audio ATTIVE (Core Audio) di tutti gli altoparlanti e le cuffie
/// accesi. Serve al NAS (per esempio Lectio con le cuffie, o un video coperto che suona ancora). Niente audio
/// registrato, si guarda solo chi sta suonando.
/// </summary>
internal sealed class LettoreAudio
{
    private const uint DispositiviAttivi = 0x1;
    private const int StatoAttivo = 1;
    private static readonly Guid IidGestoreSessioni = new("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F");
    private static readonly uint MioPid = Win32.GetCurrentProcessId();
    private bool rotto;

    /// <summary>
    /// I programmi che hanno una sessione audio attiva adesso, col nome dato da <paramref name="nomina"/>
    /// (nome riconosciuto dal percorso, o "non_riconosciuto:..."). Il processo si rilegge ogni volta: un numero di
    /// processo può essere riusato da un altro programma.
    /// </summary>
    public List<string> Processi(Func<string, string?, string> nomina)
    {
        var trovati = new SortedSet<string>(StringComparer.Ordinal);
        if (rotto) return trovati.ToList();
        IMMDeviceEnumerator? elenco = null;
        IMMDeviceCollection? dispositivi = null;
        try
        {
            elenco = (IMMDeviceEnumerator)new MMDeviceEnumeratorCom();
            elenco.EnumAudioEndpoints(0 /* eRender */, DispositiviAttivi, out dispositivi);
            dispositivi.GetCount(out uint quanti);
            for (uint i = 0; i < quanti; i++)
            {
                IMMDevice? dispositivo = null;
                IAudioSessionManager2? gestore = null;
                IAudioSessionEnumerator? sessioni = null;
                try
                {
                    dispositivi.Item(i, out dispositivo);
                    var iid = IidGestoreSessioni;
                    dispositivo.Activate(ref iid, 0x17 /* CLSCTX_ALL */, IntPtr.Zero, out var oggetto);
                    gestore = (IAudioSessionManager2)oggetto;
                    gestore.GetSessionEnumerator(out sessioni);
                    sessioni.GetCount(out int n);
                    for (int s = 0; s < n; s++)
                    {
                        IAudioSessionControl? controllo = null;
                        try
                        {
                            sessioni.GetSession(s, out controllo);
                            controllo.GetState(out int stato);
                            if (stato != StatoAttivo) continue;
                            if (controllo is not IAudioSessionControl2 c2) continue;
                            if (c2.IsSystemSoundsSession() == 0) continue; // S_OK = suoni di sistema
                            c2.GetProcessId(out uint pid);
                            if (pid == 0 || pid == MioPid) continue;
                            var (exe, percorso) = PrimoPiano.Processo(pid);
                            if (exe != null)
                            {
                                var nome = nomina(exe, percorso);
                                if (nome.Length > 0) trovati.Add(nome);
                            }
                        }
                        catch (Exception e) when (e is COMException or InvalidCastException)
                        {
                        }
                        finally
                        {
                            Rilascia(controllo);
                        }
                    }
                }
                catch (Exception e) when (e is COMException or InvalidCastException)
                {
                }
                finally
                {
                    Rilascia(sessioni);
                    Rilascia(gestore);
                    Rilascia(dispositivo);
                }
            }
        }
        catch (Exception e) when (e is COMException or InvalidCastException)
        {
            // Senza audio di Windows (servizio fermo): si va avanti senza.
        }
        catch (Exception e) when (e is TypeLoadException or NotSupportedException)
        {
            rotto = true;
            Log.Errore("audio non disponibile", e);
        }
        finally
        {
            Rilascia(dispositivi);
            Rilascia(elenco);
        }
        return trovati.ToList();
    }

    private static void Rilascia(object? o)
    {
        if (o != null && Marshal.IsComObject(o)) Marshal.ReleaseComObject(o);
    }

    // ------------------------------------------------------------------ interfacce COM di Core Audio

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    private class MMDeviceEnumeratorCom
    {
    }

    [ComImport, Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceEnumerator
    {
        void EnumAudioEndpoints(int dataFlow, uint stateMask, out IMMDeviceCollection devices);
        void GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
        void GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
        void RegisterEndpointNotificationCallback(IntPtr client);
        void UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [ComImport, Guid("0BD7A1BE-7A1A-44DB-8397-CC5392387B5E"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDeviceCollection
    {
        void GetCount(out uint count);
        void Item(uint index, out IMMDevice device);
    }

    [ComImport, Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IMMDevice
    {
        void Activate(ref Guid iid, uint clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object iface);
        void OpenPropertyStore(uint access, out IntPtr properties);
        void GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        void GetState(out uint state);
    }

    [ComImport, Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioSessionManager2
    {
        void GetAudioSessionControl(IntPtr sessionGuid, uint flags, out IntPtr control);
        void GetSimpleAudioVolume(IntPtr sessionGuid, uint flags, out IntPtr volume);
        void GetSessionEnumerator(out IAudioSessionEnumerator enumerator);
        void RegisterSessionNotification(IntPtr notification);
        void UnregisterSessionNotification(IntPtr notification);
        void RegisterDuckNotification([MarshalAs(UnmanagedType.LPWStr)] string sessionId, IntPtr notification);
        void UnregisterDuckNotification(IntPtr notification);
    }

    [ComImport, Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioSessionEnumerator
    {
        void GetCount(out int count);
        void GetSession(int index, out IAudioSessionControl session);
    }

    [ComImport, Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioSessionControl
    {
        void GetState(out int state);
        void GetDisplayName(out IntPtr name);
        void SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string value, ref Guid eventContext);
        void GetIconPath(out IntPtr path);
        void SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string value, ref Guid eventContext);
        void GetGroupingParam(out Guid groupingParam);
        void SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
        void RegisterAudioSessionNotification(IntPtr notification);
        void UnregisterAudioSessionNotification(IntPtr notification);
    }

    [ComImport, Guid("bfb7ff88-7239-4fc9-8fa2-07c950be9c6d"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IAudioSessionControl2
    {
        void GetState(out int state);
        void GetDisplayName(out IntPtr name);
        void SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string value, ref Guid eventContext);
        void GetIconPath(out IntPtr path);
        void SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string value, ref Guid eventContext);
        void GetGroupingParam(out Guid groupingParam);
        void SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
        void RegisterAudioSessionNotification(IntPtr notification);
        void UnregisterAudioSessionNotification(IntPtr notification);
        void GetSessionIdentifier(out IntPtr id);
        void GetSessionInstanceIdentifier(out IntPtr id);
        void GetProcessId(out uint pid);

        [PreserveSig]
        int IsSystemSoundsSession();

        void SetDuckingPreference([MarshalAs(UnmanagedType.Bool)] bool optOut);
    }
}
