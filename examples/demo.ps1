<#
  examples\demo.ps1 —— 不用麦克风、不用按键的可复现演示。

  做法：用 Windows 自带的中文 TTS 合成三句话，再交给 voice_f9 的文件模式识别。
  跑的就是同一套模型和推理链路，只是入口从「按键录音」换成「读 wav」。
  README 的 demo.gif 由它生成。

  用法：
    powershell -ExecutionPolicy Bypass -File examples\demo.ps1
    powershell -ExecutionPolicy Bypass -File examples\demo.ps1 -Python C:\Python312\python.exe
#>
param(
    [string]$Python = "",
    [string]$Voice = "Microsoft Huihui Desktop"
)

$ErrorActionPreference = 'Stop'

if (-not $Python) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if ($found) { $Python = $found.Source } else { $Python = 'python' }
}

$root = Split-Path -Parent $PSScriptRoot
$demo = Join-Path $env:TEMP 'voice-f9-demo'
if (Test-Path $demo) { Remove-Item $demo -Recurse -Force }
New-Item -ItemType Directory -Path $demo | Out-Null

$sentences = @(
    '今天下午三点开会，记得把报表带上。',
    '这个工具挺好用的，我以后写周报就用它了。',
    '帮我看看这段话说的对不对，有没有需要改的地方。'
)

Add-Type -AssemblyName System.Speech
$tts = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $tts.SelectVoice($Voice) } catch { }

$wavs = @()
for ($i = 0; $i -lt $sentences.Count; $i++) {
    $wav = Join-Path $demo ("s$($i + 1).wav")
    $tts.SetOutputToWaveFile($wav)
    $tts.Speak($sentences[$i])
    $tts.SetOutputToNull()
    $wavs += $wav
}
$tts.Dispose()

$env:PYTHONIOENCODING = 'utf-8'
Push-Location $root
try {
    Write-Host "voice-f9 离线识别实测（TTS 合成语音 -> 本地模型）" -ForegroundColor DarkGray
    Write-Host ''
    for ($i = 0; $i -lt $wavs.Count; $i++) {
        & $Python voice_f9.py --file $wavs[$i]
    }
}
finally {
    Pop-Location
    Remove-Item $demo -Recurse -Force -ErrorAction SilentlyContinue
}