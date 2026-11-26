# 下载 SenseVoice 语音识别模型（约 155 MB）
# 默认走 hf-mirror.com（国内可达）；已存在则跳过，中断后重跑会续传。
#
#   powershell -ExecutionPolicy Bypass -File download-model.ps1
#
# 想用官方源：先设 $env:HF_HOST = 'huggingface.co'
param(
    [string]$Dest = (Join-Path $PSScriptRoot 'models\sensevoice')
)

$ErrorActionPreference = 'Stop'
$repo = 'csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17'
$host_ = if ($env:HF_HOST) { $env:HF_HOST } else { 'hf-mirror.com' }

New-Item -ItemType Directory -Force -Path $Dest | Out-Null

foreach ($f in @('model.int8.onnx', 'tokens.txt')) {
    $out = Join-Path $Dest $f
    if ((Test-Path $out) -and (Get-Item $out).Length -gt 0) {
        Write-Host "已存在，跳过: $f" -ForegroundColor DarkGray
        continue
    }
    $url = "https://$host_/$repo/resolve/main/$f"
    Write-Host "下载 $f ..." -ForegroundColor Cyan
    & curl.exe -sSL --retry 5 --retry-delay 3 -C - -o $out $url
    if ($LASTEXITCODE -ne 0) { throw "下载失败: $url" }
}

Get-ChildItem $Dest | ForEach-Object {
    Write-Host ("  {0,-20} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB))
}
Write-Host ""
Write-Host "模型就绪。双击 start-voice-f9.vbs 即可。" -ForegroundColor Green