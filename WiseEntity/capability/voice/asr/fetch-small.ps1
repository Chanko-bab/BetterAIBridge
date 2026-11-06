$ErrorActionPreference = 'Continue'
$dst = Join-Path $PSScriptRoot 'models\faster-whisper-small\model.bin'
$url = 'https://www.modelscope.cn/api/v1/models/pengzhendong/faster-whisper-small/repo?Revision=master&FilePath=model.bin'
$total = 483546902
$log = Join-Path $PSScriptRoot '..\..\..\runtime\logs\model-download.log'
for ($i = 1; $i -le 120; $i++) {
    $size = if (Test-Path $dst) { (Get-Item $dst).Length } else { 0 }
    if ($size -eq $total) { Add-Content $log "$(Get-Date -Format 'HH:mm:ss') DONE size=$size"; break }
    Add-Content $log "$(Get-Date -Format 'HH:mm:ss') attempt $i from $([math]::Round($size/1MB,1))MB"
    & curl.exe -L -C - --connect-timeout 20 --max-time 900 -o $dst $url 2>$null
    Start-Sleep -Seconds 2
}
Add-Content $log "$(Get-Date -Format 'HH:mm:ss') final size=$((Get-Item $dst).Length) / $total"