param([string]$Out = "$env:TEMP\bab-sense-mf.png", [int]$Width = 1280, [int]$Height = 720)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await-Action($action) {
    $methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
    $m = $methods | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction'
    } | Select-Object -First 1
    $task = $m.Invoke($null, @($action))
    $task.Wait(-1) | Out-Null
}

function Await-Op($op, [Type]$type) {
    $methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
    $m = $methods | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    $task = $m.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}

[Windows.Media.Capture.MediaCapture, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Capture.MediaCaptureInitializationSettings, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.MediaProperties.ImageEncodingProperties, Windows.Media, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataReader, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null

$cap = [Windows.Media.Capture.MediaCapture]::new()
$settings = [Windows.Media.Capture.MediaCaptureInitializationSettings]::new()
$settings.StreamingCaptureMode = [Windows.Media.Capture.StreamingCaptureMode]::Video
$settings.PhotoCaptureSource = [Windows.Media.Capture.PhotoCaptureSource]::VideoPreview
try {
    Await-Action ($cap.InitializeAsync($settings))
    $props = [Windows.Media.MediaProperties.ImageEncodingProperties]::CreatePng()
    $props.Width = $Width
    $props.Height = $Height
    $stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
    Await-Action ($cap.CapturePhotoToStreamAsync($props, $stream))
    $stream.Seek(0) | Out-Null
    $size = [uint32]$stream.Size
    $reader = [Windows.Storage.Streams.DataReader]::new($stream)
    Await-Op ($reader.LoadAsync($size)) ([uint32]) | Out-Null
    $bytes = New-Object byte[] $size
    $reader.ReadBytes($bytes)
    [System.IO.File]::WriteAllBytes($Out, $bytes)
    Write-Output ("OK " + $Out + " " + $size)
} catch {
    Write-Output ("FAIL " + $_.Exception.Message)
    exit 1
} finally {
    try { $cap.Dispose() } catch { }
}
