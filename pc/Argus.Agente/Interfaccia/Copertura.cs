using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Argus.Agente.Sistema;
using Microsoft.Win32;

namespace Argus.Agente.Interfaccia;

/// <summary>
/// La copertura di uno schermo (regole 12), come quella dei lavori di casa di Pactum: finestra senza bordi,
/// grande come lo schermo, sopra tutto. Non chiude, non minimizza e non tocca le altre app: le copre e basta.
/// Niente hook di tastiera né trucchi. Non si chiude a mano e non si sposta; la chiude solo Argus.
/// </summary>
internal sealed class FinestraCopertura : Form
{
    private static readonly Color Sfondo = Color.FromArgb(14, 16, 20);
    private static readonly Color Testo = Color.FromArgb(232, 236, 241);
    private static readonly Color TestoTenue = Color.FromArgb(150, 160, 172);

    private readonly Rectangle schermo;
    private readonly bool perImmagine;
    private string messaggio;
    private string secondaRiga;
    private bool consentiChiusura;

    /// <summary>Un clic sulla copertura apre il terminale (serve soprattutto se il tasto del terminale è preso).</summary>
    public event Action? Cliccata;

    public FinestraCopertura(Rectangle schermo, string messaggio, bool perImmagine = false, string? secondaRiga = null)
    {
        this.schermo = schermo;
        this.messaggio = messaggio;
        this.secondaRiga = secondaRiga ?? Nucleo.Testi.SecondaRigaCopertura(Nucleo.TastoTerminale.DiSerie);
        this.perImmagine = perImmagine;
        Text = "Argus";
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        Bounds = schermo;
        AutoScaleMode = AutoScaleMode.None;
        TopMost = !perImmagine;
        ShowInTaskbar = false;
        ControlBox = false;
        MinimizeBox = false;
        MaximizeBox = false;
        BackColor = Sfondo;
        DoubleBuffered = true;
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        AccessibleName = messaggio + " " + this.secondaRiga;
    }

    /// <summary>Quando compare prende il primo piano: la tastiera va a lei, non alla cosa coperta.</summary>
    protected override bool ShowWithoutActivation => false;

    public void ConsentiChiusura() => consentiChiusura = true;

    public void Imposta(string nuovo, string nuovaSeconda)
    {
        if (nuovo == messaggio && nuovaSeconda == secondaRiga) return;
        messaggio = nuovo;
        secondaRiga = nuovaSeconda;
        AccessibleName = messaggio + " " + secondaRiga;
        Invalidate();
    }

    protected override void OnMouseClick(MouseEventArgs e)
    {
        base.OnMouseClick(e);
        if (e.Button == MouseButtons.Left) Cliccata?.Invoke();
    }

    public void RiportaInCima()
    {
        if (IsDisposed || perImmagine) return;
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        if (IsHandleCreated) Win32.SetWindowPos(Handle, Win32.HWND_TOPMOST, 0, 0, 0, 0, Win32.SWP_NOACTIVATE | Win32.SWP_NOMOVE | Win32.SWP_NOSIZE);
    }

    public void Attiva()
    {
        if (IsDisposed || perImmagine) return;
        RiportaInCima();
        try
        {
            Activate();
            if (IsHandleCreated) Win32.SetForegroundWindow(Handle);
        }
        catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException)
        {
        }
    }

    protected override void WndProc(ref Message m)
    {
        // Un messaggio di fine sessione finto (Windows non si sta chiudendo) non deve chiudere la copertura.
        if ((m.Msg == Win32.WM_QUERYENDSESSION || m.Msg == Win32.WM_ENDSESSION) && !Win32.SessioneSiChiude())
        {
            if (m.Msg == Win32.WM_QUERYENDSESSION) m.Result = (IntPtr)1;
            return;
        }
        // Ferma e grande come il suo schermo: ogni tentativo di spostarla o ridimensionarla si annulla.
        if (!perImmagine && m.Msg == Win32.WM_WINDOWPOSCHANGING && m.LParam != IntPtr.Zero)
        {
            var pos = Marshal.PtrToStructure<Win32.WINDOWPOS>(m.LParam);
            pos.x = schermo.X;
            pos.y = schermo.Y;
            pos.cx = schermo.Width;
            pos.cy = schermo.Height;
            pos.flags &= ~(Win32.SWP_NOMOVE | Win32.SWP_NOSIZE);
            Marshal.StructureToPtr(pos, m.LParam, false);
        }
        base.WndProc(ref m);
    }

    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        // Né a mano (Alt+F4) né da un altro programma: solo Argus o lo spegnimento di Windows.
        if (!consentiChiusura && e.CloseReason != CloseReason.WindowsShutDown)
        {
            e.Cancel = true;
            return;
        }
        base.OnFormClosing(e);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var g = e.Graphics;
        g.Clear(Sfondo);
        g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
        float scala = DeviceDpi / 96f;
        int Px(float v) => (int)Math.Round(v * scala);
        using var titolo = new Font("Segoe UI Semibold", 26f * scala, FontStyle.Regular, GraphicsUnit.Pixel);
        using var riga = new Font("Segoe UI", 17f * scala, FontStyle.Regular, GraphicsUnit.Pixel);
        using var marchio = new Font("Segoe UI", 13f * scala, FontStyle.Regular, GraphicsUnit.Pixel);
        const TextFormatFlags Flags = TextFormatFlags.WordBreak | TextFormatFlags.NoPrefix | TextFormatFlags.HorizontalCenter;
        int larghezza = Math.Max(Px(240), Math.Min(Px(720), ClientSize.Width - 2 * Px(40)));
        var h1 = TextRenderer.MeasureText(g, messaggio, titolo, new Size(larghezza, int.MaxValue), Flags).Height;
        var h2 = TextRenderer.MeasureText(g, secondaRiga, riga, new Size(larghezza, int.MaxValue), Flags).Height;
        int totale = h1 + Px(18) + h2;
        int x = (ClientSize.Width - larghezza) / 2;
        int y = Math.Max(Px(40), (ClientSize.Height - totale) / 2);
        TextRenderer.DrawText(g, messaggio, titolo, new Rectangle(x, y, larghezza, h1), Testo, Flags);
        TextRenderer.DrawText(g, secondaRiga, riga, new Rectangle(x, y + h1 + Px(18), larghezza, h2), TestoTenue, Flags);
        TextRenderer.DrawText(g, "Argus", marchio, new Rectangle(0, ClientSize.Height - Px(48), ClientSize.Width, Px(24)), TestoTenue, Flags);
    }

    /// <summary>Solo per le prove: la copertura disegnata in un'immagine, senza aprirla sullo schermo di nessuno.</summary>
    public static void DisegnaImmagine(Rectangle schermo, string messaggio, string file, string? secondaRiga = null)
    {
        using var f = new FinestraCopertura(schermo, messaggio, perImmagine: true, secondaRiga: secondaRiga);
        _ = f.Handle;
        using var bmp = new Bitmap(Math.Max(1, f.Width), Math.Max(1, f.Height));
        f.DrawToBitmap(bmp, new Rectangle(Point.Empty, f.Size));
        bmp.Save(file, ImageFormat.Png);
    }
}

/// <summary>
/// Una copertura per ogni schermo (Screen.AllScreens), rimesse in cima ogni mezzo secondo, rifatte se gli
/// schermi cambiano o se qualcuno le nasconde o le rende trasparenti. Il terminale resta sopra.
/// </summary>
internal sealed class GestoreCopertura : IDisposable
{
    private readonly List<FinestraCopertura> finestre = new();
    private readonly System.Windows.Forms.Timer inCima;
    private readonly StatoAgente stato;
    private string messaggio = DecisoreModalita.MessaggioDiRiserva;

    /// <summary>Falso se il tasto del terminale è preso da un altro programma: allora la copertura dice "fai clic qui".</summary>
    public bool TastoAttivo { get; set; } = true;

    /// <summary>Il tasto del terminale come lo legge lo studente ("Ctrl+Alt+T").</summary>
    public string TestoTasto { get; set; } = Nucleo.TastoTerminale.DiSerie;

    /// <summary>Clic su una copertura: si apre il terminale.</summary>
    public Action? ApriTerminale { get; set; }

    private string SecondaRiga => TastoAttivo ? Nucleo.Testi.SecondaRigaCopertura(TestoTasto) : Nucleo.Testi.SecondaRigaCoperturaSenzaTasto;

    public GestoreCopertura(StatoAgente stato)
    {
        this.stato = stato;
        inCima = new System.Windows.Forms.Timer { Interval = 500 };
        inCima.Tick += (_, _) => InCima();
        SystemEvents.DisplaySettingsChanged += SuSchermiCambiati;
    }

    /// <summary>Le finestre da tenere sopra le coperture (il terminale), rimesse in cima dopo di loro.</summary>
    public Action? DopoInCima { get; set; }

    public bool Visibile { get; private set; }

    public void Applica(DecisioneCopertura d)
    {
        if (!d.Copri)
        {
            Nascondi();
            return;
        }
        messaggio = d.Messaggio;
        if (!Visibile || finestre.Count == 0)
        {
            Visibile = true;
            stato.CoperturaVisibile = true;
            Ricostruisci();
            inCima.Start();
            Log.Info("copertura accesa");
        }
        else
        {
            foreach (var f in finestre) f.Imposta(messaggio, SecondaRiga);
        }
        if (d.Attiva) finestre.FirstOrDefault()?.Attiva();
        DopoInCima?.Invoke();
    }

    public void Nascondi()
    {
        if (!Visibile && finestre.Count == 0) return;
        Visibile = false;
        stato.CoperturaVisibile = false;
        inCima.Stop();
        Chiudi();
        Log.Info("copertura spenta");
    }

    private void InCima()
    {
        if (!Visibile) return;
        // Coperture chiuse, nascoste da Windows (altro desktop virtuale) o rese trasparenti: si rifanno.
        finestre.RemoveAll(f => f.IsDisposed || !f.IsHandleCreated);
        foreach (var f in finestre.ToList())
        {
            var h = f.Handle;
            bool daRifare = Win32.Nascosta(h)
                            || (Win32.StileEsteso(h) & (Win32.WS_EX_LAYERED | Win32.WS_EX_TRANSPARENT)) != 0
                            || Win32.HaRegione(h);
            if (daRifare)
            {
                finestre.Remove(f);
                f.ConsentiChiusura();
                f.Close();
                f.Dispose();
                continue;
            }
            if (!Win32.IsWindowVisible(h)) Win32.ShowWindow(h, Win32.SW_SHOWNOACTIVATE);
        }
        if (finestre.Count < Screen.AllScreens.Length)
        {
            Ricostruisci();
            return;
        }
        foreach (var f in finestre) f.RiportaInCima();
        DopoInCima?.Invoke();
    }

    private void Ricostruisci()
    {
        Chiudi();
        foreach (var schermo in Screen.AllScreens)
        {
            try
            {
                var f = new FinestraCopertura(schermo.Bounds, messaggio, secondaRiga: SecondaRiga);
                f.Cliccata += () => ApriTerminale?.Invoke();
                finestre.Add(f);
                f.Show();
                f.RiportaInCima();
            }
            catch (Exception e)
            {
                Log.Errore("copertura di uno schermo non aperta (riprovo)", e);
            }
        }
    }

    private void Chiudi()
    {
        foreach (var f in finestre)
        {
            try
            {
                f.ConsentiChiusura();
                f.Close();
                f.Dispose();
            }
            catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException)
            {
            }
        }
        finestre.Clear();
    }

    private void SuSchermiCambiati(object? mittente, EventArgs e)
    {
        try
        {
            if (Visibile) Ricostruisci();
        }
        catch (Exception ex)
        {
            Log.Errore("coperture non rifatte dopo il cambio degli schermi", ex);
        }
    }

    public void Dispose()
    {
        SystemEvents.DisplaySettingsChanged -= SuSchermiCambiati;
        inCima.Stop();
        inCima.Dispose();
        Chiudi();
        stato.CoperturaVisibile = false;
    }
}
