@echo off
setlocal enabledelayedexpansion

echo ========================================
echo PrakritiDesk Test Suite Verification
echo ========================================
echo.

set ERRORS=0

echo Checking test files...
echo.

REM Check unit test files
if exist "__tests__\SmartwatchBridge.test.tsx" (
    echo [OK] Unit tests: __tests__\SmartwatchBridge.test.tsx
) else (
    echo [MISSING] __tests__\SmartwatchBridge.test.tsx
    set /a ERRORS+=1
)

REM Check E2E test files
if exist "e2e\tests\smartwatch-vitals.spec.ts" (
    echo [OK] E2E tests: e2e\tests\smartwatch-vitals.spec.ts
) else (
    echo [MISSING] e2e\tests\smartwatch-vitals.spec.ts
    set /a ERRORS+=1
)

REM Check config files
if exist "vitest.config.ts" (
    echo [OK] Config: vitest.config.ts
) else (
    echo [MISSING] vitest.config.ts
    set /a ERRORS+=1
)

if exist "vitest.setup.ts" (
    echo [OK] Setup: vitest.setup.ts
) else (
    echo [MISSING] vitest.setup.ts
    set /a ERRORS+=1
)

if exist "playwright.config.ts" (
    echo [OK] Config: playwright.config.ts
) else (
    echo [MISSING] playwright.config.ts
    set /a ERRORS+=1
)

echo.
echo Checking documentation...
echo.

if exist "TESTING.md" (
    echo [OK] TESTING.md
) else (
    echo [MISSING] TESTING.md
    set /a ERRORS+=1
)

if exist "RUN_TESTS.md" (
    echo [OK] RUN_TESTS.md
) else (
    echo [MISSING] RUN_TESTS.md
    set /a ERRORS+=1
)

if exist "TEST_COVERAGE_SUMMARY.md" (
    echo [OK] TEST_COVERAGE_SUMMARY.md
) else (
    echo [MISSING] TEST_COVERAGE_SUMMARY.md
    set /a ERRORS+=1
)

if exist "__tests__\README.md" (
    echo [OK] __tests__\README.md
) else (
    echo [MISSING] __tests__\README.md
    set /a ERRORS+=1
)

if exist "e2e\README.md" (
    echo [OK] e2e\README.md
) else (
    echo [MISSING] e2e\README.md
    set /a ERRORS+=1
)

echo.
echo Checking package.json scripts...
echo.

findstr /C:"\"test\"" package.json >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] npm test script found
) else (
    echo [MISSING] npm test script
    set /a ERRORS+=1
)

findstr /C:"\"test:e2e\"" package.json >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] npm run test:e2e script found
) else (
    echo [MISSING] npm run test:e2e script
    set /a ERRORS+=1
)

findstr /C:"\"test:all\"" package.json >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] npm run test:all script found
) else (
    echo [MISSING] npm run test:all script
    set /a ERRORS+=1
)

echo.
echo ========================================
if %ERRORS% EQU 0 (
    echo Result: ALL CHECKS PASSED [32m✓[0m
    echo.
    echo Your test suite is complete and ready!
    echo.
    echo Next steps:
    echo   1. Install dependencies: npm install
    echo   2. Run tests: npm test
    echo   3. Read TESTING.md for detailed guide
) else (
    echo Result: %ERRORS% CHECKS FAILED [31m✗[0m
    echo.
    echo Some files are missing. Please check the output above.
)
echo ========================================
echo.

pause
