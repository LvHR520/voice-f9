' voice-f9 启动器：无黑窗口常驻。
' 依次查找：本目录 .venv → 本目录 venv → 本目录 pythonw.exe → PATH 里的 pythonw.exe
Option Explicit
Dim fso, sh, base, pyw, cmd, envPath, parts, i, cand

Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
pyw = ""

cand = Array(base & "\.venv\Scripts\pythonw.exe", base & "\venv\Scripts\pythonw.exe", base & "\pythonw.exe")
For i = 0 To UBound(cand)
    If pyw = "" Then
        If fso.FileExists(cand(i)) Then pyw = cand(i)
    End If
Next

If pyw = "" Then
    envPath = sh.ExpandEnvironmentStrings("%PATH%")
    parts = Split(envPath, ";")
    For i = 0 To UBound(parts)
        If pyw = "" And parts(i) <> "" Then
            If fso.FileExists(parts(i) & "\pythonw.exe") Then pyw = parts(i) & "\pythonw.exe"
        End If
    Next
End If

If pyw = "" Then
    MsgBox "没有找到 pythonw.exe。" & vbCrLf & vbCrLf & _
           "请先安装 Python 3.10 或更高版本，安装时勾选「Add Python to PATH」，" & vbCrLf & _
           "然后在命令行运行：" & vbCrLf & _
           "    pip install -r requirements.txt", 16, "voice-f9"
    WScript.Quit 1
End If

sh.CurrentDirectory = base
cmd = """" & pyw & """ """ & base & "\voice_f9.py"""
sh.Run cmd, 0, False