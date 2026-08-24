@echo off
echo ========================================
echo   Pushing PrakritiDesk to GitHub
echo ========================================
echo.
echo Repository: https://github.com/Thanos0s/watch-test.git
echo Branch: main
echo.
echo This may take a few minutes for the first push...
echo.

cd /d "%~dp0"

git push -u origin main

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo   SUCCESS! Push completed.
    echo ========================================
    echo.
    echo View your repository at:
    echo https://github.com/Thanos0s/watch-test
    echo.
) else (
    echo.
    echo ========================================
    echo   FAILED! Push encountered an error.
    echo ========================================
    echo.
    echo Common issues:
    echo 1. Authentication required - GitHub may ask for credentials
    echo 2. Repository doesn't exist - Create it at github.com first
    echo 3. Network issues - Check your internet connection
    echo.
    echo Try running manually:
    echo   git push -u origin main
    echo.
)

pause
