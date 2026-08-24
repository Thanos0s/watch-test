@echo off
echo ========================================
echo PrakritiDesk Frontend Test Setup
echo ========================================
echo.

echo Installing test dependencies...
call npm install --save-dev vitest @vitest/ui jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @vitejs/plugin-react

echo.
echo ========================================
echo Installation complete!
echo ========================================
echo.
echo Available commands:
echo   npm test              - Run unit tests
echo   npm run test:ui       - Run unit tests with UI
echo   npm run test:coverage - Run tests with coverage
echo   npm run test:e2e      - Run E2E tests
echo   npm run test:e2e:ui   - Run E2E tests with UI
echo   npm run test:all      - Run all tests
echo.
echo To get started:
echo   npm test
echo.
