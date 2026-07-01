@echo off
REM One-click build of the SkillOpt Studio desktop app (Windows).
setlocal
cd /d "%~dp0\.."

python -m pip install --upgrade pip || goto :err
pip install -e ".[build]" || goto :err

echo Building SkillOpt Studio with PyInstaller...
pyinstaller --noconfirm packaging\skillopt_studio.spec || goto :err

echo.
echo Done. App is in: dist\SkillOptStudio\
echo Run it:  dist\SkillOptStudio\SkillOptStudio.exe
goto :eof

:err
echo Build failed.
exit /b 1
