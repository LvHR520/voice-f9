# 把 voice-f9 加入开机自启（当前用户，无需管理员）
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$vbs = Join-Path $dir 'start-voice-f9.vbs'
if (-not (Test-Path $vbs)) { throw "找不到 $vbs" }
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'voice-f9.lnk'
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $vbs
$s.WorkingDirectory = $dir
$s.Description = 'voice-f9 全局按住说话语音输入'
$s.Save()
Write-Output "已加入开机自启: $lnk"
Write-Output "取消自启: 删除上面的快捷方式"
