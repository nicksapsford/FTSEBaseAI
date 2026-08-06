@echo off
title FTSEBase A.I. Watchdog - Port 5032
cd /d C:\Users\abc\Desktop\AlbionBase\FTSEBaseAI
start /min "FTSEBase A.I. Engine" cmd /c C:\Users\abc\AppData\Local\Programs\Python\Python313\python.exe watchdog_ftsebase.py
