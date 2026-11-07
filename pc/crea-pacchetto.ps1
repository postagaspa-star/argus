#Requires -Version 5.1
<#
.SYNOPSIS
    Compila Argus per il PC e prepara la cartella da installare.

.DESCRIPTION
    Non serve essere amministratore. Da Windows PowerShell, nella cartella pc:

        .\crea-pacchetto.ps1

    Risultato (fuori da OneDrive): C:\Users\<tu>\argus-build\pc\pacchetto\Argus-pc
        programma\        i tre programmi con il loro .NET (autonomi: sul PC non serve installare .NET)
        installa.ps1      da lanciare come amministratore sul PC da controllare
        disinstalla.ps1
        README.md
        IMPRONTE.txt      sha256 dei tre programmi

    Il pacchetto è una CARTELLA con tanti file, non un solo .exe "single-file": un single-file di Pactum era
    finito in quarantena con Bitdefender.

.PARAMETER Uscita
    Dove mettere il pacchetto (di serie: %USERPROFILE%\argus-build\pc\pacchetto).

.PARAMETER SenzaProve
    Non lancia le prove automatiche prima di compilare.
#>
[CmdletBinding()]
param(
    [string]$Uscita = (Join-Path $env:USERPROFILE 'argus-build\pc\pacchetto'),
    [switch]$SenzaProve
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$radice = $PSScriptRoot

function Passo([string]$testo) { Write-Host ''; Write-Host "== $testo" -ForegroundColor Cyan }
function Ferma([string]$testo) { Write-Host ''; Write-Host "Pacchetto non creato: $testo" -ForegroundColor Red; exit 1 }

# Il dotnet: quello dell'SDK 8 nel profilo, se c'è, altrimenti quello nel PATH.
$dotnet = Join-Path $env:LOCALAPPDATA 'Microsoft\dotnet-sdk-8\dotnet.exe'
if (-not (Test-Path -LiteralPath $dotnet)) {
    $trovato = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if (-not $trovato) { Ferma 'non trovo dotnet (serve l''SDK di .NET 8).' }
    $dotnet = $trovato.Source
}
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'

if ($Uscita -like '*OneDrive*') { Ferma 'il pacchetto non va dentro OneDrive (file grossi e sincronizzazione a metà): scegli un''altra cartella.' }

$pacchetto = Join-Path $Uscita 'Argus-pc'
$programma = Join-Path $pacchetto 'programma'

# Circa 400 MB tra compilazione e pacchetto.
$disco = Get-PSDrive -Name $Uscita.Substring(0, 1)
if ($disco.Free -lt 600MB) { Ferma "poco spazio sul disco $($disco.Name): liberi $([math]::Round($disco.Free / 1MB)) MB, ne servono almeno 600." }

if (-not $SenzaProve) {
    Passo 'Prove automatiche'
    & $dotnet test (Join-Path $radice 'Argus.Prove\Argus.Prove.csproj') -c Release --nologo -v q
    if ($LASTEXITCODE -ne 0) { Ferma 'qualche prova non passa.' }
}

Passo "Compilo in $programma"
if (Test-Path -LiteralPath $pacchetto) { Remove-Item -LiteralPath $pacchetto -Recurse -Force }
New-Item -ItemType Directory -Path $programma -Force | Out-Null
foreach ($progetto in @('Argus.Guardiano', 'Argus.Sblocco', 'Argus.Agente')) {
    Write-Host "   $progetto"
    $csproj = Join-Path $radice "$progetto\$progetto.csproj"
    & $dotnet publish $csproj -c Release -r win-x64 -p:PubblicazioneArgus=true -o $programma --nologo -v q
    if ($LASTEXITCODE -ne 0) { Ferma "la compilazione di $progetto non è riuscita." }
}

Passo 'Controllo'
$attesi = @('Argus.Guardiano.exe', 'Argus.Agente.exe', 'Argus.Sblocco.exe', 'Argus.Nucleo.dll', 'coreclr.dll',
            'Microsoft.Web.WebView2.Core.dll', 'WebView2Loader.dll', 'ui\terminale.html')
foreach ($f in $attesi) {
    if (-not (Test-Path -LiteralPath (Join-Path $programma $f))) { Ferma "nel pacchetto manca $f." }
}
# Nessun pdb o file di prova nel pacchetto.
Get-ChildItem -LiteralPath $programma -Recurse -File -Filter '*.pdb' | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }

Copy-Item -LiteralPath (Join-Path $radice 'installa.ps1') -Destination $pacchetto
Copy-Item -LiteralPath (Join-Path $radice 'disinstalla.ps1') -Destination $pacchetto
Copy-Item -LiteralPath (Join-Path $radice 'README.md') -Destination $pacchetto

$righe = @("Argus per il PC - impronte sha256", "")
foreach ($f in @('Argus.Guardiano.exe', 'Argus.Agente.exe', 'Argus.Sblocco.exe', 'Argus.Nucleo.dll')) {
    $h = (Get-FileHash -LiteralPath (Join-Path $programma $f) -Algorithm SHA256).Hash.ToLowerInvariant()
    $righe += "$h  $f"
}
[System.IO.File]::WriteAllLines((Join-Path $pacchetto 'IMPRONTE.txt'), [string[]]$righe, (New-Object System.Text.UTF8Encoding $false))

$file = Get-ChildItem -LiteralPath $programma -Recurse -File
$mb = [math]::Round((($file | Measure-Object -Property Length -Sum).Sum) / 1MB)
Write-Host ''
Write-Host "Pacchetto pronto: $pacchetto ($($file.Count) file, $mb MB)" -ForegroundColor Green
Write-Host 'Sul PC da controllare: copia la cartella Argus-pc, apri Windows PowerShell come amministratore e lancia installa.ps1 (vedi README.md).'
