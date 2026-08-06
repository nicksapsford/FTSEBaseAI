@echo off
title FTSEBase A.I. - Port 5032
cd /d C:\Users\abc\Desktop\AlbionBase\FTSEBaseAI
start /min "FTSEBase A.I. Dashboard" cmd /c C:\Users\abc\AppData\Local\Programs\Python\Python313\python.exe dashboard_ftsebase.py
start /min "FTSEBase A.I. Engine" cmd /c C:\Users\abc\AppData\Local\Programs\Python\Python313\python.exe watchdog_ftsebase.py
timeout /t 5 /nobreak >nul
start http://localhost:5032
