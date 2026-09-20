@echo off
title MAD G Hub
cd /d "%~dp0"
start "" pythonw app.py 2>nul || start "" python app.py
exit
