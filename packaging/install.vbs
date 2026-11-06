' BetterAIBridge installer bootstrap (no console window).
' Runs install.ps1 hidden and waits; shows an error box only if it failed.
Option Explicit
Dim fso, sh, base, ps, cmd, code
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
ps = sh.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
cmd = """" & ps & """ -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & base & "\install.ps1"""

code = sh.Run(cmd, 0, True)
Dim silent, probe
probe = "%BAB_TEST_DIR%"
silent = (sh.ExpandEnvironmentStrings(probe) <> probe)
If code <> 0 And Not silent Then
  MsgBox "BetterAIBridge installer failed (exit " & code & ")." & vbCrLf & vbCrLf & _
         "Log: " & sh.ExpandEnvironmentStrings("%TEMP%") & "\bab-install.log", 16, "BetterAIBridge"
End If
WScript.Quit code
