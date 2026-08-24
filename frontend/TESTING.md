# Testing Guide for PrakritiDesk Frontend

Complete testing documentation for the PrakritiDesk frontend, including unit tests and E2E tests.

## Table of Contents

1. [Overview](#overview)
2. [Test Suites](#test-suites)
3. [Running Tests](#running-tests)
4. [Bluetooth/Smartwatch Tests](#bluetoothsmartwatchstests)
5. [Writing Tests](#writing-tests)
6. [CI/CD](#cicd)
7. [Troubleshooting](#troubleshooting)

## Overview

PrakritiDesk uses a comprehensive testing strategy:

- **Unit Tests**: Component-level tests using Vitest + React Testing Library
- **E2E Tests**: Full user workflow tests using Playwright
- **Integration Tests**: API integration and multi-component interactions

### Test Statistics

- **Total Test Files**: 5
- **Unit Tests**: ~30 test cases
- **E2E Tests**: ~25 test cases
- **Coverage**: Components, workflows, edge cases, accessibility

## Test Suites

### Unit Tests (Vitest)

Located in `__tests__/`

#### SmartwatchBridge.test.tsx ⭐ NEW

**Bluetooth Low Energy Integration Testing**

Coverage:
- ✅ GATT payload parsing (Heart Rate, SpO2)
- ✅ IEEE-11073 SFLOAT decoder
- ✅ Stability detection algorithm (5-reading window, 4 bpm tolerance)
- ✅ Web Bluetooth API mocking
- ✅ Device pairing workflow
- ✅ Real-time notification handling
- ✅ Auto-sync logic and cooldown (20 seconds)
- ✅ Red flag detection from vitals
- ✅ Browser compatibility detection

**Key Test Cases:**

```typescript
// Payload parsing
✓ Parse 8-bit heart rate measurement
✓ Parse 16-bit heart rate measurement
✓ Parse SpO2 from PLX Continuous Measurement

// Stability detection
✓ Reject when < 5 readings
✓ Accept when within 4 bpm tolerance
✓ Reject when exceeding tolerance
✓ Use sliding window correctly

// Component behavior
✓ Show unsupported message (no Web Bluetooth)
✓ Display device name after pairing
✓ Handle user cancellation (NotFoundError)
✓ Show error for pairing failures
✓ Display real-time heart rate
✓ Display real-time SpO2
✓ Auto-sync when stable
✓ Trigger red flag callback
```

### E2E Tests (Playwright)

Located in `e2e/tests/`

#### smartwatch-vitals.spec.ts ⭐ NEW

**Complete Smartwatch Workflow Testing**

Coverage:
- ✅ Device pairing from vitals screen
- ✅ Heart rate and SpO2 display
- ✅ Auto-sync when readings stabilize
- ✅ Manual vitals entry fallback
- ✅ Red flag detection from vitals
- ✅ Skip vitals option
- ✅ Continue to intake after vitals
- ✅ Device disconnection
- ✅ Browser compatibility warning

**Key Test Cases:**

```typescript
// Pairing workflow
✓ Show pair button on vitals screen
✓ Successfully pair device
✓ Show device name after pairing
✓ Display heart rate (72 bpm)
✓ Display SpO2 (98%)
✓ Allow disconnecting device

// Auto-sync
✓ Auto-sync vitals when stable
✓ Show sync status indicators
✓ Show vitals recorded confirmation
✓ Continue button changes to "Continue to Symptoms"

// Manual entry
✓ Show manual entry form
✓ Submit manual vitals (HR, SpO2, BP)
✓ Continue to intake after manual entry

// Red flags
✓ Trigger red flag for low SpO2
✓ Show emergency alert screen

// Browser compatibility
✓ Show unsupported message when no Web Bluetooth
✓ Still allow manual entry and skip
```

#### Other E2E Tests

- **patient-intake.spec.ts**: Check-in → OTP → consent → intake flow
- **doctor-dashboard.spec.ts**: Queue management and patient review
- **realtime-sync.spec.ts**: Kiosk ↔ Dashboard data synchronization

## Running Tests

### Quick Start

```bash
# Install dependencies
cd frontend
npm install

# Run all tests (unit + E2E)
npm run test:all

# Run only unit tests
npm test

# Run only E2E tests
npm run test:e2e
```

### Unit Tests (Vitest)

```bash
# Run once
npm test

# Watch mode (re-run on file changes)
npm test -- --watch

# UI mode (interactive test runner)
npm run test:ui

# Coverage report
npm run test:coverage

# Run specific test file
npm test SmartwatchBridge

# Run tests matching pattern
npm test -- --grep "stability"
```

### E2E Tests (Playwright)

```bash
# Run all E2E tests
npm run test:e2e

# UI mode (recommended for debugging)
npm run test:e2e:ui

# Run specific test file
npx playwright test smartwatch-vitals

# Run specific test by name
npx playwright test -g "should pair device"

# Headed mode (see browser)
npx playwright test --headed

# Debug mode (step through)
npx playwright test --debug

# Generate test code
npx playwright codegen http://localhost:3000
```

## Bluetooth/Smartwatch Tests

### Understanding BLE Test Coverage

The smartwatch tests cover the complete Bluetooth Low Energy workflow:

#### 1. **GATT Protocol Layer** (Unit Tests)

Tests the low-level Bluetooth GATT (Generic Attribute Profile) data parsing:

- **Heart Rate Service (0x180D)**
  - 8-bit format: BPM 0-255
  - 16-bit format: BPM > 255
  - Flags byte parsing

- **Pulse Oximeter Service (0x1822)**
  - IEEE-11073 SFLOAT encoding
  - Mantissa/exponent extraction
  - Special values (NaN, Infinity)

#### 2. **Stability Detection** (Unit Tests)

Critical algorithm for reliable vitals:

```
Window size: 5 readings
Tolerance: ±4 bpm
Logic: max(last5) - min(last5) <= 4
```

Example:
- `[70, 71, 72, 73, 74]` → STABLE ✓ (range = 4)
- `[70, 71, 72, 73, 75]` → UNSTABLE ✗ (range = 5)

#### 3. **Auto-sync Logic** (Unit + E2E Tests)

Prevents flooding backend with unstable readings:

- Wait for 5 consecutive stable readings
- Sync to backend automatically
- 20-second cooldown between syncs
- Red flag detection on sync response

#### 4. **User Workflows** (E2E Tests)

Complete user journeys:

```
Happy Path:
Check-in → OTP → Consent → [Pair Device] → Capture Vitals → Auto-sync → Continue

Alternative Paths:
- Manual entry: Skip device, enter vitals by hand
- Skip entirely: No vitals, straight to intake
- Red flag: Low SpO2 → Emergency alert

Error Paths:
- User cancels device chooser
- Device pairing fails
- Sync API fails
- Browser doesn't support Web Bluetooth
```

### Web Bluetooth API Mocking

Tests mock the complete BLE stack:

```typescript
// Mock device hierarchy
navigator.bluetooth.requestDevice()
  → BleDevice
    → gatt.connect()
      → BleRemoteGATTServer
        → getPrimaryService('heart_rate')
          → BleService
            → getCharacteristic('heart_rate_measurement')
              → BleCharacteristic
                → startNotifications()
                → 'characteristicvaluechanged' events
```

This allows testing without physical hardware while ensuring the real API contract is respected.

### Running Bluetooth-Specific Tests

```bash
# Unit tests - GATT parsing and stability
npm test SmartwatchBridge

# E2E tests - complete workflows
npx playwright test smartwatch-vitals

# Watch specific test suites
npm test -- --watch SmartwatchBridge

# Debug E2E pairing workflow
npx playwright test --debug -g "pair device"
```

## Writing Tests

### Unit Test Template

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import MyComponent from '../components/MyComponent';

describe('MyComponent', () => {
  beforeEach(() => {
    // Setup
  });

  it('should render correctly', () => {
    render(<MyComponent />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('should handle user interaction', async () => {
    render(<MyComponent />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => {
      expect(screen.getByText('Success')).toBeVisible();
    });
  });
});
```

### E2E Test Template

```typescript
import { expect, test } from "../fixtures/test-fixtures";

test.describe("My Feature", () => {
  test.beforeEach(async ({ page }) => {
    // Setup mocks
  });

  test("should complete workflow", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    
    await expect(page.getByText("Success")).toBeVisible();
  });
});
```

### Best Practices

1. **Descriptive test names**: "should X when Y"
2. **Arrange-Act-Assert pattern**
3. **Use stable selectors**: `getByRole` > `getByLabel` > `getByText`
4. **Async handling**: Always `await` for async operations
5. **Isolated tests**: Each test should be independent
6. **Mock external dependencies**: APIs, timers, media devices
7. **Test user behavior, not implementation**

## CI/CD

Tests run automatically in GitHub Actions:

```yaml
# .github/workflows/test.yml
- Run unit tests with coverage
- Run E2E tests in Playwright container
- Upload coverage reports
- Generate HTML report on failure
```

### Local CI Simulation

```bash
# Run what CI runs
npm run test:all

# Check coverage thresholds
npm run test:coverage -- --coverage.statements=80
```

## Troubleshooting

### Common Issues

#### "Cannot find module '@testing-library/react'"

```bash
npm install @testing-library/react @testing-library/jest-dom --save-dev
```

#### "navigator.bluetooth is undefined" (Unit Tests)

This is expected - the tests mock the API. Check `vitest.setup.ts` is loaded.

#### E2E Tests Timeout

```bash
# Increase timeout
npx playwright test --timeout=60000

# Or in playwright.config.ts:
timeout: 60000
```

#### "Web Bluetooth API not available" (E2E)

The tests mock the API with `page.addInitScript()`. Verify the mock is loaded before navigating.

#### Flaky Tests

Common causes:
- Missing `await` keywords
- Race conditions (use `waitFor`)
- Shared state between tests
- Network timing issues

Fix:
```typescript
// Bad
fireEvent.click(button);
expect(screen.getByText('Result')).toBeVisible();

// Good
fireEvent.click(button);
await waitFor(() => {
  expect(screen.getByText('Result')).toBeVisible();
});
```

### Debug Commands

```bash
# Verbose test output
npm test -- --reporter=verbose

# Show browser (E2E)
npx playwright test --headed

# Slow motion (E2E)
npx playwright test --headed --slow-mo=1000

# Step through (E2E)
npx playwright test --debug

# Take screenshot on failure
# (already configured in playwright.config.ts)
```

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [Playwright Documentation](https://playwright.dev/)
- [Web Bluetooth API Spec](https://webbluetoothcg.github.io/web-bluetooth/)
- [GATT Services](https://www.bluetooth.com/specifications/specs/)

## Next Steps

After running tests:

1. **Review coverage report**: `npm run test:coverage`
2. **Fix failing tests**: Focus on root causes
3. **Add tests for new features**: Follow existing patterns
4. **Update docs**: Keep this file current
5. **Run before committing**: `npm run test:all`

---

**Test Status**: ✅ All Bluetooth/BLE functionality is now tested

- ✅ GATT payload parsing
- ✅ Stability detection
- ✅ Web Bluetooth API integration
- ✅ Device pairing workflows
- ✅ Real-time data streaming
- ✅ Auto-sync logic
- ✅ Manual entry fallback
- ✅ Red flag detection
- ✅ Browser compatibility
- ✅ Error handling
