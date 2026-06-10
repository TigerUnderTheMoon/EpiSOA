Set WshShell = CreateObject("WScript.Shell") 
WshShell.Run "cmd /c cd /d D:\Workplace\EpiSOA && python auto_run_when_api_ready.py > auto_run_api_recovery.out.log 2> auto_run_api_recovery.err.log", 0, False
Set WshShell = Nothing
