# Windows built-in OCR (Windows.Media.Ocr) via WinRT.
# Keep this file pure ASCII: Windows PowerShell 5.1 reads .ps1 as ANSI when there is no BOM,
# so any non-ASCII literal here would turn into mojibake. All paths come in as arguments.
#
#   powershell -File ocr.ps1 -Path shot.png -Out text.txt [-Lang zh-Hans-CN]
#
# Writes the recognised lines to -Out as UTF-8 (no BOM). Nothing goes to stdout on success.
param(
  [Parameter(Mandatory=$true)][string]$Path,
  [Parameter(Mandatory=$true)][string]$Out,
  [string]$Lang = ""
)
$ErrorActionPreference = "Stop"

$null = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
  $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
  $t.Wait(-1) | Out-Null
  $t.Result
}

$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]

$engine = $null
if ($Lang -ne "") {
  $language = New-Object Windows.Globalization.Language $Lang
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
  if ($null -eq $engine) { Write-Error "OCR language not installed: $Lang"; exit 3 }
} else {
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  if ($null -eq $engine) { Write-Error "no OCR language available"; exit 3 }
}

# Feed the bytes through memory: StorageFile brokering is fenced off for some install paths.
$bytes = [System.IO.File]::ReadAllBytes($Path)
$stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$writer = New-Object Windows.Storage.Streams.DataWriter $stream
$writer.WriteBytes($bytes)
$null = Await ($writer.StoreAsync()) ([uint32])
$null = Await ($writer.FlushAsync()) ([bool])
$writer.DetachStream() | Out-Null
$stream.Seek(0)

$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = New-Object System.Collections.Generic.List[string]
foreach ($line in $result.Lines) {
  $t = $line.Text
  if ($null -ne $t -and $t.Trim() -ne "") { $lines.Add($t) }
}
$text = [string]::Join("`n", $lines)
[System.IO.File]::WriteAllText($Out, $text, (New-Object System.Text.UTF8Encoding $false))
exit 0
