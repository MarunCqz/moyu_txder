@echo off
echo === TXT Reader - Windows Build Script ===
echo.
echo This script builds TXTReader.exe using PyInstaller.
echo Requirements: Python 3.7+ and pyinstaller
echo.
echo Installing pyinstaller...
pip install pyinstaller
echo.
echo Building TXTReader.exe...
pyinstaller -F -w main.py -n TXTReader --clean
echo.
echo Build complete! Find TXTReader.exe in the dist\ folder.
echo.
echo Copy dist\TXTReader.exe to any location and run it.
pause
