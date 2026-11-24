' J.A.R.V.I.S. desktop fallback: hidden server + standalone app-mode window.
Option Explicit
Dim sh, fso, base, ps1, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
ps1 = fso.BuildPath(base, "windows\desktop.ps1")
cmd = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & ps1 & """ -InstallDir """ & base & """"
sh.Run cmd, 0, False
