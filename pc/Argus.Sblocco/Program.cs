using System.Globalization;
using System.Security.Principal;

namespace Argus.Sblocco;

internal static class Program
{
    [STAThread]
    private static int Main()
    {
        ApplicationConfiguration.Initialize();
        Log.Imposta(Percorsi.LogGuardiano, "sblocco.log");
        // Il manifest lo chiede già; se qualcuno lo avvia senza (per esempio da un altro programma), si ferma qui.
        using (var io = WindowsIdentity.GetCurrent())
        {
            if (!new WindowsPrincipal(io).IsInRole(WindowsBuiltInRole.Administrator))
            {
                MessageBox.Show("Lo sblocco d'emergenza serve la password dell'amministratore.", "Argus",
                    MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 1;
            }
        }
        Application.Run(new FinestraSblocco());
        return 0;
    }
}

/// <summary>
/// Lo sblocco d'emergenza (regole 12): il PC è libero per 1-48 ore. Finisce nel registro di Argus (evento
/// sblocco_emergenza al NAS; se il NAS non risponde lo manda il guardiano appena può).
/// </summary>
internal sealed class FinestraSblocco : Form
{
    private static readonly CultureInfo Italiano = CultureInfo.GetCultureInfo("it-IT");
    private readonly NumericUpDown ore;
    private readonly Label stato;
    private readonly Label esito;
    private readonly Button sblocca;
    private readonly Button togli;

    public FinestraSblocco()
    {
        Text = "Argus - sblocco d'emergenza";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        AutoScaleMode = AutoScaleMode.Font;
        Font = new Font("Segoe UI", 10f);
        Padding = new Padding(16);
        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;

        var colonna = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false, Dock = DockStyle.Fill };
        colonna.Controls.Add(new Label
        {
            Text = "Sblocca il PC per qualche ora: Argus non copre niente finché dura.\nFinisce nel registro di Argus.",
            AutoSize = true,
            MaximumSize = new Size(440, 0),
            Margin = new Padding(0, 0, 0, 12),
        });
        stato = new Label { AutoSize = true, MaximumSize = new Size(440, 0), Margin = new Padding(0, 0, 0, 12), Font = new Font("Segoe UI Semibold", 10f) };
        colonna.Controls.Add(stato);

        var riga = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = new Padding(0, 0, 0, 12) };
        riga.Controls.Add(new Label { Text = "Ore:", AutoSize = true, Anchor = AnchorStyles.Left, Margin = new Padding(0, 6, 8, 0) });
        ore = new NumericUpDown { Minimum = Nucleo.Sblocco.OreMinime, Maximum = Nucleo.Sblocco.OreMassime, Value = 2, Width = 70 };
        riga.Controls.Add(ore);
        riga.Controls.Add(new Label { Text = "(da 1 a 48)", AutoSize = true, Margin = new Padding(8, 6, 0, 0), ForeColor = SystemColors.GrayText });
        colonna.Controls.Add(riga);

        var pulsanti = new FlowLayoutPanel { AutoSize = true, WrapContents = false };
        sblocca = new Button { Text = "Sblocca", AutoSize = true };
        togli = new Button { Text = "Togli lo sblocco", AutoSize = true };
        var chiudi = new Button { Text = "Chiudi", AutoSize = true, DialogResult = DialogResult.Cancel };
        sblocca.Click += async (_, _) => await SbloccaAsync((int)ore.Value);
        togli.Click += async (_, _) => await TogliAsync();
        chiudi.Click += (_, _) => Close();
        pulsanti.Controls.AddRange(new Control[] { sblocca, togli, chiudi });
        colonna.Controls.Add(pulsanti);

        esito = new Label { AutoSize = true, MaximumSize = new Size(440, 0), Margin = new Padding(0, 12, 0, 0) };
        colonna.Controls.Add(esito);

        Controls.Add(colonna);
        AcceptButton = sblocca;
        CancelButton = chiudi;
        MostraStato();
    }

    private void MostraStato()
    {
        var s = Nucleo.Sblocco.Leggi(Percorsi.Sblocco);
        if (s != null && s.Attivo(DateTimeOffset.Now) && s.FinoData is DateTimeOffset fino)
        {
            stato.Text = "Adesso: sbloccato fino " + Quando(fino) + ".";
            togli.Enabled = true;
        }
        else
        {
            stato.Text = "Adesso: nessuno sblocco.";
            togli.Enabled = false;
        }
    }

    private static string Quando(DateTimeOffset t)
    {
        var locale = t.ToLocalTime();
        var oggi = DateTimeOffset.Now.Date;
        if (locale.Date == oggi) return "alle " + locale.ToString("HH:mm", Italiano) + " di oggi";
        if (locale.Date == oggi.AddDays(1)) return "alle " + locale.ToString("HH:mm", Italiano) + " di domani";
        return "alle " + locale.ToString("HH:mm", Italiano) + " di " + locale.ToString("dddd d MMMM", Italiano);
    }

    private async Task SbloccaAsync(int quante)
    {
        var s = Nucleo.Sblocco.Nuovo(quante, DateTimeOffset.Now);
        await ScriviEAvvisaAsync(s, $"Sbloccato per {quante} {(quante == 1 ? "ora" : "ore")}, fino " + Quando(s.FinoData!.Value) + ".");
        Log.Info($"sblocco d'emergenza: {quante} ore");
    }

    private async Task TogliAsync()
    {
        var s = Nucleo.Sblocco.Tolto(DateTimeOffset.Now);
        await ScriviEAvvisaAsync(s, "Sblocco tolto: Argus riprende subito.");
        Log.Info("sblocco d'emergenza tolto");
    }

    private async Task ScriviEAvvisaAsync(Nucleo.Sblocco s, string fatto)
    {
        sblocca.Enabled = togli.Enabled = false;
        try
        {
            try
            {
                FileSicuri.ScriviAtomico(Percorsi.Sblocco, s.InJson());
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                esito.Text = "Non riesco a scrivere lo sblocco: " + e.Message;
                return;
            }
            string nasDetto;
            try
            {
                var config = ConfigArgus.Carica(Percorsi.Config);
                using var nas = new ClientNas(config.NasUrl, config.Token);
                if (string.IsNullOrWhiteSpace(config.SegretoSblocco))
                {
                    esito.Text = fatto + " Manca il segreto dello sblocco in config.json: il NAS non lo saprà. Rilancia installa.ps1 con -SegretoSblocco.";
                    return;
                }
                var r = await nas.EventoAsync(TipiEvento.SbloccoEmergenza, s.DettagliEvento(), DateTimeOffset.Now,
                    segretoSblocco: config.SegretoSblocco);
                if (r.Ok)
                {
                    s.Inviato = true;
                    FileSicuri.ScriviAtomico(Percorsi.Sblocco, s.InJson());
                    nasDetto = "Il NAS è avvisato.";
                }
                else
                {
                    nasDetto = r.Raggiunto
                        ? "Il NAS ha risposto con un errore: " + r.Errore + " Il guardiano riproverà."
                        : "Il NAS non risponde: vale lo stesso, e il guardiano lo avviserà appena torna.";
                }
            }
            catch (Exception e) when (e is ErroreConfig or IOException or UnauthorizedAccessException)
            {
                nasDetto = "Non riesco a leggere la configurazione: vale lo stesso, il guardiano avviserà il NAS.";
            }
            esito.Text = fatto + " " + nasDetto;
        }
        finally
        {
            sblocca.Enabled = true;
            MostraStato();
        }
    }
}
