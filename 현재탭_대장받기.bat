@echo off
rem '현재' 탭 자료(서울 아파트 건축물대장)를 이어 받고 깃허브에 올린다. 하루 호출 한도 때문에 며칠에 나눠 받는다.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python scripts\now.py >> data\now.log 2>&1
git add docs/data/now_*.json data/bjdong.json
git commit -m "현재 탭 자료 이어 받기" >nul 2>&1
git push >> data\now.log 2>&1
