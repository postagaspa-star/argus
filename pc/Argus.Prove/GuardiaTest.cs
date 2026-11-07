using Argus.Nucleo;

namespace Argus.Prove;

public class GuardiaTest
{
    [Fact]
    public void SiRiapreDopoUnSecondo()
    {
        var p = new PoliticaRiavvio();
        Assert.True(p.PuòRiaprire(0));
        p.Uscito(10_000, avviatoMs: 0, daSolo: true);
        Assert.False(p.PuòRiaprire(10_500));
        Assert.True(p.PuòRiaprire(11_000)); // entro 3 secondi
    }

    [Fact]
    public void MorteDaSoloAppenaPartito_5Volte_PausaDi30Secondi()
    {
        var p = new PoliticaRiavvio();
        for (int i = 0; i < 5; i++)
        {
            long uscita = 10_000 + i * 2_000;
            p.Uscito(uscita, avviatoMs: uscita - 1_000, daSolo: true); // morto da solo dopo 1 secondo
        }
        Assert.Equal(5, p.UsciteRecenti(18_000));
        Assert.False(p.PuòRiaprire(19_500));
        Assert.False(p.PuòRiaprire(47_000));
        Assert.True(p.PuòRiaprire(48_000));
        // Passato il minuto si torna al secondo di attesa.
        p.Uscito(200_000, avviatoMs: 199_000, daSolo: true);
        Assert.True(p.PuòRiaprire(201_000));
    }

    [Fact]
    public void AgenteVissutoPiùDi10Secondi_NientePausa()
    {
        // Chiuso 5 volte in un minuto, ma ogni volta dopo 11 secondi di vita: sempre 1 secondo.
        var p = new PoliticaRiavvio();
        for (int i = 0; i < 5; i++)
        {
            long uscita = 12_000 + i * 12_000;
            p.Uscito(uscita, avviatoMs: uscita - 11_000, daSolo: true);
        }
        Assert.Equal(0, p.UsciteRecenti(60_000));
        Assert.True(p.PuòRiaprire(61_000));
    }

    [Fact]
    public void ChiusoDaAltri_NientePausa()
    {
        // Bloccato e chiuso dal guardiano, o WM_QUIT da un altro programma (codice 5): non è "morto da solo".
        var p = new PoliticaRiavvio();
        for (int i = 0; i < 8; i++)
        {
            long uscita = 10_000 + i * 2_000;
            p.Uscito(uscita, avviatoMs: uscita - 1_000, daSolo: false);
        }
        Assert.False(p.PuòRiaprire(24_500));
        Assert.True(p.PuòRiaprire(25_000));
    }

    [Fact]
    public void NonAvviato_ContaComeUscitaBreve()
    {
        var p = new PoliticaRiavvio();
        for (int i = 0; i < 5; i++) p.NonAvviato(10_000 + i * 1_000);
        Assert.False(p.PuòRiaprire(20_000));
        Assert.True(p.PuòRiaprire(44_000));
    }

    [Fact]
    public void Battito()
    {
        // Primo battito: c'è un minuto di tempo (PC lento all'accesso).
        Assert.False(RegoleBattito.Bloccato(adessoMs: 50_000, avviatoMs: 0, ultimoBattitoMs: 0, battiti: 0));
        Assert.True(RegoleBattito.Bloccato(adessoMs: 60_001, avviatoMs: 0, ultimoBattitoMs: 0, battiti: 0));
        // Poi 20 secondi di silenzio al massimo.
        Assert.False(RegoleBattito.Bloccato(adessoMs: 40_000, avviatoMs: 0, ultimoBattitoMs: 20_000, battiti: 4));
        Assert.True(RegoleBattito.Bloccato(adessoMs: 40_001, avviatoMs: 0, ultimoBattitoMs: 20_000, battiti: 4));
    }

    [Theory]
    [InlineData("studente", "studente", true)]
    [InlineData("Studente", "STUDENTE", true)]
    [InlineData("studente", @"PC-CASA\studente", true)]
    [InlineData("studente", "studente@casa.local", true)]
    [InlineData("genitore", "studente", false)]
    [InlineData("studente", "", false)]
    [InlineData(null, "studente", false)]
    [InlineData("studente", null, false)]
    public void UtenteControllato(string? sessione, string? config, bool atteso) =>
        Assert.Equal(atteso, Utenti.ÈControllato(sessione, config));
}
