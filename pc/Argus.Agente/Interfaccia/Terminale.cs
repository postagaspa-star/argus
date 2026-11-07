using System.Drawing;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows.Forms;
using Argus.Agente.Sistema;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Argus.Agente.Interfaccia;

/// <summary>
/// Il terminale (regole 8 e 12): finestra scura, una riga dove si scrive, storico delle risposte sopra. Si apre
/// col tasto del terminale (di serie Ctrl+Alt+T, "tasto_terminale" in config.json), Esc la nasconde, nessuna icona nella barra delle applicazioni (finestra-strumento).
/// La pagina (ui/terminale.html) gira in una WebView2 con i dati in %LOCALAPPDATA%\Argus\WebView2; parla con
/// questa finestra solo con messaggi (mai col NAS): il token resta qui.
/// </summary>
internal sealed class FinestraTerminale : Form
{
    private const string Origine = "https://argus.locale/";
    private readonly WebView2 vista;
    private readonly Func<string, Task<JsonObject>> comando;
    private readonly Func<string, string?, List<ImmagineFoto>, Task<JsonObject>> foto;
    private bool pronta;
    private string? erroreAvvio;
    private readonly Label ripiego;

    public FinestraTerminale(Func<string, Task<JsonObject>> comando, Func<string, string?, List<ImmagineFoto>, Task<JsonObject>> foto)
    {
        this.comando = comando;
        this.foto = foto;
        Text = "Argus";
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        ShowInTaskbar = false;
        TopMost = true;
        StartPosition = FormStartPosition.Manual;
        BackColor = Color.FromArgb(12, 14, 17);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(860, 480);
        KeyPreview = true;
        vista = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(12, 14, 17) };
        ripiego = new Label
        {
            Dock = DockStyle.Fill,
            ForeColor = Color.FromArgb(215, 221, 228),
            BackColor = Color.FromArgb(12, 14, 17),
            Font = new Font("Consolas", 11f),
            Padding = new Padding(16),
            Visible = false,
        };
        Controls.Add(vista);
        Controls.Add(ripiego);
    }

    /// <summary>Si nasconde invece di chiudersi.</summary>
    protected override void OnFormClosing(FormClosingEventArgs e)
    {
        if (e.CloseReason == CloseReason.UserClosing)
        {
            e.Cancel = true;
            Nascondi();
            return;
        }
        base.OnFormClosing(e);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Escape)
        {
            Nascondi();
            e.Handled = true;
        }
        base.OnKeyDown(e);
    }

    public async Task PreparaAsync()
    {
        try
        {
            var dati = Path.Combine(Percorsi.CartellaUtente, "WebView2");
            Directory.CreateDirectory(dati);
            var ambiente = await CoreWebView2Environment.CreateAsync(null, dati);
            await vista.EnsureCoreWebView2Async(ambiente);
            var w = vista.CoreWebView2;
            w.Settings.AreDefaultContextMenusEnabled = false;
            w.Settings.AreDevToolsEnabled = false;
            w.Settings.IsZoomControlEnabled = false;
            w.Settings.IsStatusBarEnabled = false;
            w.Settings.AreBrowserAcceleratorKeysEnabled = false;
            w.Settings.IsPasswordAutosaveEnabled = false;
            w.Settings.IsGeneralAutofillEnabled = false;
            w.Settings.IsBuiltInErrorPageEnabled = false;
            var cartellaUi = Path.Combine(AppContext.BaseDirectory, "ui");
            w.SetVirtualHostNameToFolderMapping("argus.locale", cartellaUi, CoreWebView2HostResourceAccessKind.Deny);
            w.PermissionRequested += SuPermesso;
            w.NavigationStarting += (_, a) =>
            {
                if (!a.Uri.StartsWith(Origine, StringComparison.OrdinalIgnoreCase)) a.Cancel = true;
            };
            w.NewWindowRequested += (_, a) => a.Handled = true;
            w.WebMessageReceived += SuMessaggio;
            w.Navigate(Origine + "terminale.html");
            pronta = true;
        }
        catch (Exception e)
        {
            // Senza WebView2 il terminale non c'è: lo si dice nella finestra stessa.
            erroreAvvio = e.Message;
            Log.Errore("terminale (WebView2) non pronto", e);
            vista.Visible = false;
            ripiego.Text = "Il terminale non si apre su questo PC (manca il componente WebView2 di Windows). " +
                           "Chiedi a chi ha installato Argus di installare \"Microsoft Edge WebView2 Runtime\".";
            ripiego.Visible = true;
        }
    }

    /// <summary>La webcam solo per la pagina del terminale; tutto il resto no.</summary>
    private static void SuPermesso(object? s, CoreWebView2PermissionRequestedEventArgs a)
    {
        bool nostra = a.Uri.StartsWith(Origine, StringComparison.OrdinalIgnoreCase);
        a.State = nostra && a.PermissionKind == CoreWebView2PermissionKind.Camera
            ? CoreWebView2PermissionState.Allow
            : CoreWebView2PermissionState.Deny;
        a.Handled = true;
    }

    public void Apri()
    {
        var schermo = Screen.FromPoint(Cursor.Position).WorkingArea;
        Location = new Point(schermo.X + (schermo.Width - Width) / 2, schermo.Y + Math.Max(0, (schermo.Height - Height) / 3));
        if (!Visible) Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        TienInCima();
        Activate();
        Win32.SetForegroundWindow(Handle);
        if (pronta)
        {
            vista.Focus();
            Posta(new JsonObject { ["tipo"] = "mostrato" });
        }
    }

    public void Nascondi()
    {
        if (pronta) Posta(new JsonObject { ["tipo"] = "nascosto" });
        Hide();
    }

    public void Alterna()
    {
        if (Visible && Win32.GetForegroundWindow() == Handle) Nascondi();
        else Apri();
    }

    /// <summary>Sopra le coperture (anche loro sempre in primo piano).</summary>
    public void TienInCima()
    {
        if (Visible && IsHandleCreated)
            Win32.SetWindowPos(Handle, Win32.HWND_TOPMOST, 0, 0, 0, 0, Win32.SWP_NOACTIVATE | Win32.SWP_NOMOVE | Win32.SWP_NOSIZE);
    }

    private void Posta(JsonObject messaggio)
    {
        if (!pronta || IsDisposed) return;
        void Fai()
        {
            try
            {
                vista.CoreWebView2?.PostWebMessageAsJson(messaggio.ToJsonString());
            }
            catch (Exception e) when (e is InvalidOperationException or ObjectDisposedException or System.Runtime.InteropServices.COMException)
            {
            }
        }
        if (InvokeRequired) BeginInvoke(Fai);
        else Fai();
    }

    private void SuMessaggio(object? s, CoreWebView2WebMessageReceivedEventArgs a)
    {
        if (!a.Source.StartsWith(Origine, StringComparison.OrdinalIgnoreCase)) return;
        JsonObject? m;
        try
        {
            m = JsonNode.Parse(a.WebMessageAsJson) as JsonObject;
        }
        catch (JsonException)
        {
            return;
        }
        var tipo = m?["tipo"]?.GetValue<string>();
        switch (tipo)
        {
            case "nascondi":
                Nascondi();
                break;
            case "comando":
                var testo = (m!["testo"]?.GetValue<string>() ?? "").Trim();
                if (testo.Length == 0 || testo.Length > 500) return;
                _ = Task.Run(async () =>
                {
                    JsonObject risposta;
                    try
                    {
                        risposta = await comando(testo).ConfigureAwait(false);
                    }
                    catch (Exception e)
                    {
                        Log.Errore("comando", e);
                        risposta = new JsonObject { ["ok"] = false, ["testo"] = Nucleo.Testi.NasNonRisponde };
                    }
                    risposta["tipo"] = "risposta";
                    Posta(risposta);
                });
                break;
            case "foto":
                var fototipo = m!["fototipo"]?.GetValue<string>() ?? "";
                var nome = m["nome"]?.GetValue<string>();
                var immagini = new List<ImmagineFoto>();
                if (m["immagini"] is JsonArray elenco)
                {
                    foreach (var n in elenco.Take(20))
                    {
                        try
                        {
                            var b64 = n?.GetValue<string>() ?? "";
                            int virgola = b64.IndexOf(',');
                            if (b64.StartsWith("data:", StringComparison.Ordinal) && virgola > 0) b64 = b64[(virgola + 1)..];
                            var dati = Convert.FromBase64String(b64);
                            bool png = dati.Length > 4 && dati[0] == 0x89 && dati[1] == 0x50;
                            immagini.Add(new ImmagineFoto(dati, png ? "image/png" : "image/jpeg"));
                        }
                        catch (FormatException)
                        {
                        }
                    }
                }
                _ = Task.Run(async () =>
                {
                    JsonObject risposta;
                    try
                    {
                        risposta = await foto(fototipo, nome, immagini).ConfigureAwait(false);
                    }
                    catch (Exception e)
                    {
                        Log.Errore("foto", e);
                        risposta = new JsonObject { ["ok"] = false, ["testo"] = "Le foto non sono partite: riprova tra poco." };
                    }
                    risposta["tipo"] = "risposta";
                    Posta(risposta);
                });
                break;
        }
    }

    public string? ErroreAvvio => erroreAvvio;

    // ------------------------------------------------------------------ solo per le prove

    private bool prova;

    /// <summary>In prova la finestra non prende mai il primo piano (sta fuori dallo schermo).</summary>
    protected override bool ShowWithoutActivation => prova;

    /// <summary>
    /// Prova del terminale senza disturbare chi usa il PC: la finestra fuori dallo schermo e senza primo piano,
    /// si scrivono due comandi nella pagina vera e si salva un'immagine. Restituisce il testo dello storico.
    /// La webcam non si apre.
    /// </summary>
    public void ImpostaProva()
    {
        prova = true;
        Location = new Point(-20000, -20000);
    }

    public async Task<string> ProvaAsync(string filePng)
    {
        await PreparaAsync();
        if (!pronta) return "ERRORE: " + erroreAvvio;
        var caricata = new TaskCompletionSource();
        vista.CoreWebView2.NavigationCompleted += (_, _) => caricata.TrySetResult();
        await Task.WhenAny(caricata.Task, Task.Delay(10_000));
        async Task Scrivi(string testo)
        {
            await vista.CoreWebView2.ExecuteScriptAsync(
                "(() => { const r = document.getElementById('riga'); r.value = " + JsonSerializer.Serialize(testo) +
                "; r.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); })()");
            await Task.Delay(800);
        }
        await Scrivi("aiuto");
        await Scrivi("ps m: bagno & t: 10");
        var storia = await vista.CoreWebView2.ExecuteScriptAsync("document.getElementById('storia').innerText");
        using (var file = File.Create(filePng))
            await vista.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, file);
        return JsonSerializer.Deserialize<string>(storia) ?? "";
    }
}
