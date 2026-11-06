' BetterAIBridge - run a powershell script without a console window
Option Explicit
Dim sh, fso, here, target
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
target = here & "\start-all.ps1"
If Not fso.FileExists(target) Then
  WScript.Quit 1
End If
sh.Run "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & Chr(34) & target & Chr(34), 0, False
