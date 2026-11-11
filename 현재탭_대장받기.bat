@echo off
rem now tab: fetch building ledger within the daily quota, then push to GitHub
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ==== %date% %time% >> data\now.log
python scripts\now.py >> data\now.log 2>&1
git add docs/data/now_*.json data/bjdong.json
git commit -m "now tab data" >nul 2>&1
git push >> data\now.log 2>&1
