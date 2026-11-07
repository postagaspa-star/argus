using System.Runtime.InteropServices;
using System.Windows.Automation;

namespace Argus.Agente.Sistema;

/// <summary>
/// Legge con UI Automation la barra degli indirizzi del browser (come Pactum) e ne tiene solo il nome del sito.
/// Il testo della barra non esce da qui. Si cerca esattamente la barra (Chromium: classe OmniboxViewViews;
/// Firefox: urlbar-input), mai un campo di testo qualsiasi della pagina.
/// <list type="bullet">
/// <item>cursore nella barra (si sta scrivendo un indirizzo) = non leggibile: partono i 20 secondi;</item>
/// <item>a schermo intero (video, F11) la barra non si vede: vale l'ultimo sito letto in quella finestra.</item>
/// </list>
/// La lettura gira su un compito a parte con un tempo massimo: un browser bloccato non ferma il sensore.
/// </summary>
internal sealed class LettoreIndirizzi
{
    private const int MsMassimiLettura = 800;
    private const long MsPausaDopoRicercaVana = 5_000;

    private readonly object chiave = new();
    private readonly Dictionary<IntPtr, AutomationElement> barre = new();
    private readonly Dictionary<IntPtr, string> ultimoSito = new();
    private readonly Dictionary<IntPtr, long> prossimaRicerca = new();
    private Task<string?>? inCorso;

    /// <summary>Il sito in primo piano in quella finestra del browser, o null (nessun sito leggibile).</summary>
    public string? Leggi(IntPtr hwnd, string exe, bool schermoIntero)
    {
        if (inCorso != null && !inCorso.IsCompleted) return Ripiego(hwnd, schermoIntero);
        var compito = Task.Run(() => LeggiOra(hwnd, exe, schermoIntero));
        inCorso = compito;
        try
        {
            return compito.Wait(MsMassimiLettura) ? compito.Result : Ripiego(hwnd, schermoIntero);
        }
        catch (AggregateException)
        {
            return Ripiego(hwnd, schermoIntero);
        }
    }

    private string? LeggiOra(IntPtr hwnd, string exe, bool schermoIntero)
    {
        AutomationElement? barra;
        lock (chiave)
        {
            barre.TryGetValue(hwnd, out barra);
            if (barra == null && prossimaRicerca.TryGetValue(hwnd, out var quando) && Environment.TickCount64 < quando)
                return RipiegoSenzaLucchetto(hwnd, schermoIntero);
        }
        try
        {
            if (barra == null)
            {
                barra = Trova(hwnd, exe);
                lock (chiave)
                {
                    if (barre.Count > 64) Dimentica();
                    if (barra == null)
                    {
                        prossimaRicerca[hwnd] = Environment.TickCount64 + MsPausaDopoRicercaVana;
                        return RipiegoSenzaLucchetto(hwnd, schermoIntero);
                    }
                    barre[hwnd] = barra;
                    prossimaRicerca.Remove(hwnd);
                }
            }

            // Il cursore è nella barra: si sta scrivendo un indirizzo, la barra non dice la pagina vera.
            if (barra.GetCurrentPropertyValue(AutomationElement.HasKeyboardFocusProperty) is true) return null;

            var sito = Indirizzi.HostDaBarra(barra.GetCurrentPropertyValue(ValuePattern.ValueProperty) as string);
            lock (chiave)
            {
                if (sito != null) ultimoSito[hwnd] = sito;
                else ultimoSito.Remove(hwnd);
            }
            return sito;
        }
        catch (Exception e) when (e is ElementNotAvailableException or COMException or InvalidOperationException or ArgumentException or TimeoutException)
        {
            lock (chiave)
            {
                barre.Remove(hwnd);
                return RipiegoSenzaLucchetto(hwnd, schermoIntero);
            }
        }
    }

    /// <summary>A schermo intero la barra sparisce ma la pagina è la stessa: vale l'ultimo sito letto. Altrimenti niente.</summary>
    private string? Ripiego(IntPtr hwnd, bool schermoIntero)
    {
        lock (chiave) return RipiegoSenzaLucchetto(hwnd, schermoIntero);
    }

    private string? RipiegoSenzaLucchetto(IntPtr hwnd, bool schermoIntero) =>
        schermoIntero && ultimoSito.TryGetValue(hwnd, out var s) ? s : null;

    private static AutomationElement? Trova(IntPtr hwnd, string exe)
    {
        var radice = AutomationElement.FromHandle(hwnd);
        if (exe == "firefox.exe")
        {
            var barra = radice.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
                new PropertyCondition(AutomationElement.AutomationIdProperty, "urlbar-input")));
            if (barra != null) return barra;
            var navigazione = radice.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ToolBar),
                new PropertyCondition(AutomationElement.AutomationIdProperty, "nav-bar")));
            return navigazione?.FindFirst(TreeScope.Descendants, new AndCondition(
                new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
                new PropertyCondition(AutomationElement.IsValuePatternAvailableProperty, true)));
        }
        // Chrome, Edge, Brave (Chromium): la barra ha la classe della vista, uguale in tutte le lingue.
        return radice.FindFirst(TreeScope.Descendants, new AndCondition(
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit),
            new PropertyCondition(AutomationElement.ClassNameProperty, "OmniboxViewViews")));
    }

    private void Dimentica()
    {
        barre.Clear();
        ultimoSito.Clear();
        prossimaRicerca.Clear();
    }
}
