<#
  发布闸门 —— 一个仓库能不能推送、能不能发版，由这一份脚本判定。

  用法：
    pwsh _factory\gate.ps1 -RepoPath voice-f9
    pwsh _factory\gate.ps1 -RepoPath voice-f9 -ForRelease -CheckRemote
    pwsh _factory\gate.ps1 -RepoPath voice-f9 -Json

  退出码：0 = 无阻断项（可能有提醒）；1 = 有阻断项；2 = 用法错误

  这份脚本会被复制进每个仓库的 .github/gate.ps1（由 sync-gate.ps1 完成）。
  【不要直接改副本】改 _factory/gate.ps1，然后重新同步。
#>
[CmdletBinding()]
param(
  [string]$RepoPath = '.',

  # project = 正常项目；plugin = 插件；profile = 个人主页仓库（只要求 README）
  [ValidateSet('project', 'plugin', 'profile')]
  [string]$Kind = 'project',

  # 发版模式：多加几条只在发版时才该拦的红线（演示 GIF 等）
  [switch]$ForRelease,

  # 近端检查：查 GitHub 上最新 Release 有没有资产（需要 gh 已登录）
  [switch]$CheckRemote,

  [switch]$Json,

  [string]$GhPath = 'gh',

  # 额外要扫描的敏感词（姓名、学号、私人目录等）
  [string[]]$ExtraPatterns = @()
)

$ErrorActionPreference = 'Stop'

$results = New-Object System.Collections.ArrayList

function Add-Result([string]$Id, [string]$Title, [string]$Level, [string]$Message) {
  [void]$results.Add([pscustomobject]@{ id = $Id; title = $Title; level = $Level; message = $Message })
}
function Test-Ok([string]$Id, [string]$Title, [string]$Message) { Add-Result $Id $Title 'ok' $Message }
function Test-Warn([string]$Id, [string]$Title, [string]$Message) { Add-Result $Id $Title 'warn' $Message }
function Test-Fail([string]$Id, [string]$Title, [string]$Message) { Add-Result $Id $Title 'error' $Message }

function Fmt-Bytes([double]$b) {
  if ($b -ge 1GB) { return ('{0:N1} GB' -f ($b / 1GB)) }
  if ($b -ge 1MB) { return ('{0:N1} MB' -f ($b / 1MB)) }
  return ('{0:N0} KB' -f ($b / 1KB))
}

function Fmt-Time([double]$bytes, [double]$rate) {
  $s = $bytes / $rate
  if ($s -lt 90) { return ('{0:N0} 秒' -f $s) }
  return ('{0:N0} 分钟' -f ($s / 60))
}

# ---------- 0. 定位仓库 ----------
try {
  $root = (Resolve-Path -LiteralPath $RepoPath).Path
}
catch {
  Write-Host ("::error::仓库路径不存在：{0}" -f $RepoPath)
  exit 2
}
if (-not (Test-Path -LiteralPath (Join-Path $root '.git'))) {
  Write-Host ("::error::不是 git 仓库根目录：{0}" -f $root)
  exit 2
}

$tracked = @()
$rawTracked = & git -C $root ls-files 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host '::error::git ls-files 执行失败（仓库可能还没有提交）'
  exit 2
}
$tracked = @($rawTracked | Where-Object { $_ -ne '' })

# ---------- 1. 必备文件 ----------
$required = @('README.md', 'LICENSE', 'CHANGELOG.md', 'AGENTS.md', '.gitignore')
if ($Kind -eq 'profile') { $required = @('README.md') }
if ($Kind -eq 'plugin') { $required = @('README.md', 'LICENSE', 'package.json', '.gitignore') }

$missing = @($required | Where-Object { -not (Test-Path -LiteralPath (Join-Path $root $_)) })
if ($missing.Count -gt 0) {
  Test-Fail 'required-files' '必备文件' ('缺：{0}' -f ($missing -join '、'))
}
else {
  Test-Ok 'required-files' '必备文件' ('齐全（{0}）' -f ($required -join '、'))
}

# ---------- 2. 令牌 / 私钥 ----------
$tokenPatterns = @(
  'ghp_[A-Za-z0-9]{30,}',
  'gho_[A-Za-z0-9]{30,}',
  'ghu_[A-Za-z0-9]{30,}',
  'github_pat_[A-Za-z0-9_]{20,}',
  'sk-[A-Za-z0-9]{20,}',
  'AKIA[0-9A-Z]{16}',
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
)
$tokenHits = @()
foreach ($p in $tokenPatterns) {
  $r = & git -C $root grep -I -n -E -e $p -- . ':(exclude).github/gate.ps1' 2>$null
  if ($LASTEXITCODE -eq 0 -and $r) { $tokenHits += @($r) }
}
if ($tokenHits.Count -gt 0) {
  Test-Fail 'secrets' '令牌 / 私钥' ('发现 {0} 处：{1}' -f $tokenHits.Count, (($tokenHits | Select-Object -First 3) -join ' | '))
}
else {
  Test-Ok 'secrets' '令牌 / 私钥' '未发现'
}

# ---------- 3. 本机路径 / 私人信息 ----------
$personalPatterns = @(
  'D:\\+AI工作区',
  'C:\\+Users\\+[^\\/]+\\+',
  '/home/[a-z0-9_]+/',
  'AI学校任务'
)

# 额外词表：命令行参数 > 环境变量 > 同目录的 sensitive.local.txt（只在本地产线里存在）
$extra = @()
if ($ExtraPatterns.Count -gt 0) { $extra += $ExtraPatterns }
if ($env:GATE_EXTRA_PATTERNS) {
  $extra += @($env:GATE_EXTRA_PATTERNS -split ';' | Where-Object { $_ -and $_.Trim() })
}
$localFile = Join-Path $PSScriptRoot 'sensitive.local.txt'
if (Test-Path -LiteralPath $localFile) {
  $extra += @(Get-Content -LiteralPath $localFile -Encoding UTF8 |
      Where-Object { $_ -and $_.Trim() -and -not $_.TrimStart().StartsWith('#') } |
      ForEach-Object { $_.Trim() })
}
$extra = @($extra | Select-Object -Unique)

$personalHits = @()
foreach ($p in $personalPatterns) {
  $r = & git -C $root grep -I -n -E -e $p -- . ':(exclude).github/gate.ps1' 2>$null
  if ($LASTEXITCODE -eq 0 -and $r) { $personalHits += @($r) }
}
foreach ($p in $extra) {
  $r = & git -C $root grep -I -n -F -e $p -- . ':(exclude).github/gate.ps1' 2>$null
  if ($LASTEXITCODE -eq 0 -and $r) { $personalHits += @($r) }
}
if ($personalHits.Count -gt 0) {
  Test-Fail 'personal' '本机路径 / 私人信息' ('发现 {0} 处：{1}' -f $personalHits.Count, (($personalHits | Select-Object -First 3) -join ' | '))
}
else {
  $note = if ($extra.Count -gt 0) { ('未发现（词表 {0} 条）' -f $extra.Count) } else { '未发现（注意：本次没有额外词表，姓名/学号未覆盖）' }
  if ($extra.Count -gt 0) { Test-Ok 'personal' '本机路径 / 私人信息' $note }
  else { Test-Warn 'personal' '本机路径 / 私人信息' $note }
}

# ---------- 4. 脚本换行必须是 CRLF ----------
$scriptFiles = @($tracked | Where-Object { $_ -match '\.(vbs|ps1|bat|cmd)$' })
$badEol = @()
foreach ($f in $scriptFiles) {
  $p = Join-Path $root ($f -replace '/', [System.IO.Path]::DirectorySeparatorChar)
  if (-not (Test-Path -LiteralPath $p)) { continue }
  $bytes = [System.IO.File]::ReadAllBytes($p)
  $hasCrlf = $false
  for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
    if ($bytes[$i] -eq 13 -and $bytes[$i + 1] -eq 10) { $hasCrlf = $true; break }
  }
  if (-not $hasCrlf) { $badEol += $f }
}

$attrFile = Join-Path $root '.gitattributes'
$attrOk = $false
if (Test-Path -LiteralPath $attrFile) {
  $attrText = Get-Content -LiteralPath $attrFile -Raw -Encoding UTF8
  $attrOk = ($attrText -match '\*\.ps1\s+text\s+eol=crlf') -and ($attrText -match '\*\.vbs\s+text\s+eol=crlf')
}
if ($badEol.Count -gt 0) {
  Test-Fail 'crlf' '脚本换行' ('这些文件不是 CRLF，双击会语法错误：{0}' -f ($badEol -join '、'))
}
elseif (-not $attrOk -and $scriptFiles.Count -gt 0) {
  Test-Warn 'crlf' '脚本换行' '当前文件都是 CRLF，但 .gitattributes 没锁死 *.ps1/*.vbs 的 eol=crlf，别人克隆后可能变 LF'
}
elseif ($scriptFiles.Count -eq 0) {
  Test-Ok 'crlf' '脚本换行' '没有 .ps1/.vbs/.bat 需要检查'
}
else {
  Test-Ok 'crlf' '脚本换行' ('{0} 个脚本均为 CRLF，且 .gitattributes 已锁死' -f $scriptFiles.Count)
}

# ---------- 5. 不许进仓库的东西 ----------
$junkBlocking = '^(models/|.*/models/|.*\.log$|.*__pycache__/|.*\.pyc$|\.venv/|.*/\.venv/|node_modules/)'
$junkWarn = '.*\.(zip|exe|dll|7z|msi)$'
$blocked = @($tracked | Where-Object { $_ -match $junkBlocking })
$heavy = @($tracked | Where-Object { $_ -match $junkWarn })
if ($blocked.Count -gt 0) {
  Test-Fail 'junk' '禁止入库文件' ('这些不该被跟踪：{0}' -f (($blocked | Select-Object -First 6) -join '、'))
}
elseif ($heavy.Count -gt 0) {
  Test-Warn 'junk' '禁止入库文件' ('跟踪了二进制产物：{0}' -f (($heavy | Select-Object -First 4) -join '、'))
}
else {
  Test-Ok 'junk' '禁止入库文件' '没有 models/、*.log、__pycache__、虚拟环境'
}

# ---------- 6. README 首屏 ----------
if ($Kind -ne 'profile') {
  $readmePath = Join-Path $root 'README.md'
  if (Test-Path -LiteralPath $readmePath) {
    $allLines = @(Get-Content -LiteralPath $readmePath -Encoding UTF8)
    $headCount = [Math]::Min(80, $allLines.Count)
    $topCount = [Math]::Min(20, $allLines.Count)
    $head = @($allLines | Select-Object -First $headCount)
    $top = @($allLines | Select-Object -First $topCount)
    $headText = $head -join "`n"
    $topText = $top -join "`n"
    $hasQuote = $topText -match '(?m)^\s*>\s*.{10,}'
    $hasImage = $headText -match '!\[[^\]]*\]\([^)]+\)'
    $hasStart = $headText -match '(?m)^#{1,4}\s*(快速开始|快速上手|三步上手|安装|Quick\s*[Ss]tart|Getting\s*[Ss]tarted|Install|Usage)'

    # 首屏图片：必须真的存在，不能只是写了个不存在的路径
    $imgOk = $false
    $imgMissing = @()
    foreach ($m in [regex]::Matches($headText, '!\[[^\]]*\]\(([^)]+)\)')) {
      $src = $m.Groups[1].Value.Trim()
      if ($src -match '^https?://') { $imgOk = $true; continue }
      $local = Join-Path $root ($src -replace '/', [System.IO.Path]::DirectorySeparatorChar)
      if (Test-Path -LiteralPath $local) { $imgOk = $true } else { $imgMissing += $src }
    }
    $hasImage = $imgOk

    # 快速事实表允许出现在后面，但位置越靠后，被看到的概率越低
    $factsLine = -1
    for ($i = 0; $i -lt $allLines.Count; $i++) {
      if ($allLines[$i] -match '快速事实|Quick\s*[Ff]acts|快速信息') { $factsLine = $i + 1; break }
    }

    $lack = @()
    if (-not $hasQuote) { $lack += '一句话（引用行）' }
    if ($factsLine -lt 0) { $lack += '快速事实表' }
    if (-not $hasStart) { $lack += '快速开始小节' }

    if ($lack.Count -gt 0) {
      if ($Kind -eq 'project') { Test-Fail 'readme-hero' 'README 首屏' ('前 80 行缺：{0}' -f ($lack -join '、')) }
      else { Test-Warn 'readme-hero' 'README 首屏' ('前 80 行缺：{0}（插件/工具类不强制）' -f ($lack -join '、')) }
    }
    elseif ($factsLine -gt 40) {
      Test-Warn 'readme-hero' 'README 首屏' ('快速事实表在第 {0} 行，首屏看不到；建议挪到前 20 行' -f $factsLine)
    }
    elseif ($hasImage) {
      Test-Ok 'readme-hero' 'README 首屏' '一句话 + 快速事实 + 快速开始 + 有图'
    }
    elseif ($imgMissing.Count -gt 0) {
      $m2 = ('首屏引用了图但文件不存在：{0}' -f ($imgMissing -join '、'))
      if ($ForRelease) { Test-Fail 'readme-hero' 'README 首屏' $m2 }
      else { Test-Warn 'readme-hero' 'README 首屏' $m2 }
    }
    else {
      if ($ForRelease) { Test-Fail 'readme-hero' 'README 首屏' '首屏没有图（发版必须有 GIF）' }
      else { Test-Warn 'readme-hero' 'README 首屏' '结构齐了，但没有图；发版前必须补 GIF' }
    }
  }
}

# ---------- 7. 演示物料 ----------
$gifs = @($tracked | Where-Object { $_ -match '\.gif$' })
if ($gifs.Count -eq 0) {
  if ($ForRelease) {
    Test-Fail 'demo-gif' '演示 GIF' '仓库里没有 GIF。按规则 8：没有 GIF 不算发布完成'
  }
  else {
    Test-Warn 'demo-gif' '演示 GIF' '还没有 GIF（推送不拦，发版会拦）'
  }
}
else {
  $sizes = @()
  foreach ($g in $gifs) {
    $p = Join-Path $root ($g -replace '/', [System.IO.Path]::DirectorySeparatorChar)
    if (Test-Path -LiteralPath $p) { $sizes += (Get-Item -LiteralPath $p).Length }
  }
  $totalGif = ($sizes | Measure-Object -Sum).Sum
  if ($totalGif -lt 200KB) {
    Test-Warn 'demo-gif' '演示 GIF' ('有 {0} 个 GIF，但总共只有 {1}，大概率是坏图或占位图' -f $gifs.Count, (Fmt-Bytes $totalGif))
  }
  else {
    Test-Ok 'demo-gif' '演示 GIF' ('{0} 个，共 {1}' -f $gifs.Count, (Fmt-Bytes $totalGif))
  }
}

# ---------- 8. AGENTS.md 有没有「改完怎么验证」 ----------
if ($Kind -ne 'profile') {
  $agentsPath = Join-Path $root 'AGENTS.md'
  if (Test-Path -LiteralPath $agentsPath) {
    $agentsText = Get-Content -LiteralPath $agentsPath -Raw -Encoding UTF8
    if ($agentsText -match '验证' -and $agentsText -match '```') {
      Test-Ok 'agents-verify' 'AGENTS.md 验收' '有验证小节和可复制命令'
    }
    else {
      Test-Warn 'agents-verify' 'AGENTS.md 验收' '缺「改完怎么验证」的代码块，下一个人（或 AI）不知道改完该跑什么'
    }
  }
}

# ---------- 9. CHANGELOG 有版本条目 ----------
if ($Kind -ne 'profile') {
  $clPath = Join-Path $root 'CHANGELOG.md'
  if (Test-Path -LiteralPath $clPath) {
    $clHead = @(Get-Content -LiteralPath $clPath -TotalCount 25 -Encoding UTF8)
    $verLine = $clHead | Where-Object { $_ -match '^#{2,3}\s*\[?v?\d+\.\d+\.\d+' } | Select-Object -First 1
    if ($verLine) { Test-Ok 'changelog' 'CHANGELOG' ('最新条目：{0}' -f $verLine.Trim()) }
    else { Test-Fail 'changelog' 'CHANGELOG' '前 25 行找不到形如「## v1.0.0」的版本条目' }
  }
}

# ---------- 10. LICENSE 是不是空架子 ----------
$licensePath = Join-Path $root 'LICENSE'
if (Test-Path -LiteralPath $licensePath) {
  $licText = Get-Content -LiteralPath $licensePath -Raw -Encoding UTF8
  if (-not $licText -or $licText.Length -lt 200) {
    Test-Fail 'license' 'LICENSE' ('只有 {0} 字节，不是有效许可证' -f $licText.Length)
  }
  elseif ($licText -notmatch 'MIT|Apache|GPL|BSD|Mozilla|Unlicense') {
    Test-Fail 'license' 'LICENSE' '认不出许可证类型（要有 MIT/Apache/GPL 等字样）'
  }
  else {
    Test-Ok 'license' 'LICENSE' '有效'
  }
}

# ---------- 11. 体积与下载时间 ----------
if ($Kind -eq 'project') {
  $totalBytes = 0
  foreach ($f in $tracked) {
    $p = Join-Path $root ($f -replace '/', [System.IO.Path]::DirectorySeparatorChar)
    if (Test-Path -LiteralPath $p) { $totalBytes += (Get-Item -LiteralPath $p).Length }
  }
  # 打包时会被塞进去、但不在仓库里的模型目录
  $modelsDir = Join-Path $root 'models'
  $hasModels = Test-Path -LiteralPath $modelsDir
  if ($hasModels) {
    $ms = Get-ChildItem -LiteralPath $modelsDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum
    if ($ms -and $ms.Sum) { $totalBytes += $ms.Sum }
  }

  $slowSec = $totalBytes / 26KB
  $fastSec = $totalBytes / 300KB
  $msg = '预计发布包 {0}{1}；直连 26 KB/s ≈ {2}；镜像 300 KB/s ≈ {3}' -f `
    (Fmt-Bytes $totalBytes), $(if ($hasModels) { '（含 models/）' } else { '' }), (Fmt-Time $totalBytes 26KB), (Fmt-Time $totalBytes 300KB)

  # 规则 3 允许「拆包、换托管、给镜像」三选一，所以先看有没有镜像链接
  $mirrorDoc = ''
  foreach ($doc in @('README.md', 'AGENTS.md')) {
    $dp = Join-Path $root $doc
    if (Test-Path -LiteralPath $dp) {
      $dt = Get-Content -LiteralPath $dp -Raw -Encoding UTF8
      if ($dt -match 'ghfast|ghproxy|mirror|镜像') { $mirrorDoc = $doc; break }
    }
  }

  if ($fastSec -gt 300) {
    if ($mirrorDoc) {
      Test-Warn 'size' '体积 / 下载时间' ($msg + (' —— 镜像速度仍超 5 分钟，但 {0} 已给镜像链接，可发布' -f $mirrorDoc))
    }
    else {
      Test-Fail 'size' '体积 / 下载时间' ($msg + ' —— 超过 5 分钟且没给镜像，必须拆包、换托管或补镜像')
    }
  }
  elseif ($slowSec -gt 300) {
    if ($mirrorDoc) { Test-Ok 'size' '体积 / 下载时间' ($msg + (' —— 已给镜像（{0}）' -f $mirrorDoc)) }
    else { Test-Warn 'size' '体积 / 下载时间' ($msg + ' —— 直连超 5 分钟，README 里补一条镜像链接') }
  }
  else {
    Test-Ok 'size' '体积 / 下载时间' $msg
  }
}

# ---------- 12. 远端 Release 资产（可选） ----------
if ($CheckRemote -and $Kind -eq 'project') {
  $remote = $null
  try { $remote = (& git -C $root remote get-url origin 2>$null) } catch { $remote = $null }
  if ($LASTEXITCODE -ne 0 -or -not $remote) {
    Test-Warn 'remote' 'Release 资产' '没有 origin 远端'
  }
  else {
    $json = $null
    try { $json = (& $GhPath release view --json assets 2>$null) } catch { $json = $null }
    if ($LASTEXITCODE -ne 0 -or -not $json) {
      Test-Fail 'remote' 'Release 资产' '仓库没有 Release（或 gh 未登录）'
    }
    else {
      try {
        $rel = $json | ConvertFrom-Json
        if ($rel.PSObject.Properties.Name -notcontains 'assets') {
          Test-Warn 'remote' 'Release 资产' '查不到 Release 信息'
        }
        else {
          # 注意：@($null).Count 等于 1，必须先把 null 过滤掉
          $count = @($rel.assets | Where-Object { $_ }).Count
          if ($count -eq 0) { Test-Fail 'remote' 'Release 资产' '最新 Release 没有资产，用户下了也没东西' }
          else { Test-Ok 'remote' 'Release 资产' ('最新 Release 有 {0} 个资产' -f $count) }
        }
      }
      catch {
        Test-Warn 'remote' 'Release 资产' 'Release 信息解析失败'
      }
    }
  }
}

# ---------- 汇总 ----------
$errors = @($results | Where-Object { $_.level -eq 'error' })
$warns = @($results | Where-Object { $_.level -eq 'warn' })
$oks = @($results | Where-Object { $_.level -eq 'ok' })

if ($Json) {
  $payload = [pscustomobject]@{
    repo       = $root
    kind       = $Kind
    forRelease = [bool]$ForRelease
    ok         = $oks.Count
    warn       = $warns.Count
    error      = $errors.Count
    results    = @($results)
  }
  $payload | ConvertTo-Json -Depth 6
  if ($errors.Count -gt 0) { exit 1 } else { exit 0 }
}

Write-Host ''
Write-Host ('闸门  {0}   [{1}{2}]' -f $root, $Kind, $(if ($ForRelease) { ' · 发版模式' } else { '' }))
Write-Host ('-' * 72)
foreach ($r in $results) {
  switch ($r.level) {
    'ok' { Write-Host ('  [ ok ] ' + $r.title) -ForegroundColor DarkGray; Write-Host ('         ' + $r.message) -ForegroundColor DarkGray }
    'warn' { Write-Host ('  [warn] ' + $r.title) -ForegroundColor Yellow; Write-Host ('         ' + $r.message) -ForegroundColor Yellow }
    'error' { Write-Host ('  [FAIL] ' + $r.title) -ForegroundColor Red; Write-Host ('         ' + $r.message) -ForegroundColor Red }
  }
}
Write-Host ('-' * 72)
Write-Host ('通过 {0} / 提醒 {1} / 阻断 {2}' -f $oks.Count, $warns.Count, $errors.Count)

if ($errors.Count -gt 0) {
  if ($env:GITHUB_ACTIONS -eq 'true') {
    foreach ($e in $errors) { Write-Host ('::error::{0}：{1}' -f $e.title, $e.message) }
  }
  Write-Host '结论：不能发版。上面标记 FAIL 的就是必须先修的东西。'
  exit 1
}
Write-Host '结论：可以推送；发版前再用 -ForRelease 跑一次。'
exit 0