# E2E Tests for PrakritiDesk

End-to-end tests using Playwright to verify complete user workflows.

## Test Suites

### patient-intake.spec.ts
Tests the patient kiosk flow from check-in to completion:
- ✅ Check-in with ABHA ID/mobile
- ✅ OTP verification
- ✅ DPDP consent flow
- ✅ Touch option selection
- ✅ Red flag detection
- ✅ Interview completion
- ✅ Error handling (incorrect OTP, consent refusal)

### doctor-dashboard.spec.ts
Tests the doctor's queue and review interface:
- ✅ Empty queue display
- ✅ URGENT badge for red-flag patients
- ✅ Patient selection and case display
- ✅ Consent verification status
- ✅ Red-flag escalation button
- ✅ FHIR export workflow
- ✅ Queue refresh

### realtime-sync.spec.ts
Tests data flow between kiosk and doctor dashboard:
- ✅ Multi-context simulation (two browser tabs)
- ✅ Patient completion → doctor queue update
- ✅ Polling-based "near real-time" sync

### smartwatch-vitals.spec.ts ⭐ NEW
Comprehensive tests for Bluetooth smartwatch integration:

#### Device Pairing
- ✅ Show pair button on vitals screen
- ✅ Successful device pairing
- ✅ Display device name after pairing
- ✅ Allow disconnecting paired device

#### Vitals Capture
- ✅ Display heart rate from BLE device
- ✅ Display SpO2 from BLE device
- ✅ Auto-sync when readings stabilize
- ✅ Show vitals recorded confirmation

#### Manual Entry Fallback
- ✅ Show manual entry form
- ✅ Submit manual vitals (HR, SpO2, BP)
- ✅ Continue to intake after manual entry

#### Error Handling
- ✅ Red flag detection from vitals
- ✅ Allow skipping vitals entirely
- ✅ Browser compatibility (unsupported message)

#### Complete Workflow
- ✅ Device pairing → vitals capture → auto-sync → continue to intake

## Running E2E Tests

```bash
# Run all E2E tests
npm run test:e2e

# Run tests with UI (recommended for debugging)
npm run test:e2e:ui

# Run specific test file
npx playwright test smartwatch-vitals

# Run tests in headed mode (see browser)
npx playwright test --headed

# Run tests in debug mode
npx playwright test --debug

# Run both unit and E2E tests
npm run test:all
```

## Test Architecture

### Page Object Model (POM)
Tests use the Page Object pattern for maintainability:

- **KioskPage** (`pages/KioskPage.ts`): Patient kiosk interactions
- **DoctorDashboardPage** (`pages/DoctorDashboardPage.ts`): Doctor dashboard interactions

### Fixtures
Custom fixtures in `fixtures/test-fixtures.ts` provide:
- Pre-configured page objects
- Shared test utilities
- Consistent test setup

### Mocks
Backend mocking in `fixtures/mockRoutes.ts` and `fixtures/mocks.ts`:
- Mock API responses
- Mock ABHA authentication
- Mock clinical intake turns
- Mock vitals sync
- **NEW**: Mock Web Bluetooth API

## Writing New E2E Tests

1. Add locators to appropriate Page Object:
   ```typescript
   // In KioskPage.ts
   readonly myNewButton: Locator;
   
   constructor(page: Page) {
     this.myNewButton = page.getByRole('button', { name: 'My Button' });
   }
   ```

2. Create test file in `e2e/tests/`:
   ```typescript
   import { expect, test } from "../fixtures/test-fixtures";
   
   test.describe("My Feature", () => {
     test("should do something", async ({ page, kioskPage }) => {
       // Test implementation
     });
   });
   ```

3. Use stable selectors (prefer in order):
   - `getByRole()` with accessible name
   - `getByLabel()`
   - `getByText()` for unique text
   - `getByTestId()` as last resort

## Web Bluetooth Mocking

Smartwatch tests mock the Web Bluetooth API at the page level:

```typescript
await page.addInitScript(() => {
  // Mock navigator.bluetooth
  Object.defineProperty(navigator, 'bluetooth', {
    value: { requestDevice: async () => mockDevice },
  });
});
```

This allows testing the complete BLE workflow without real hardware.

## CI/CD Integration

Tests run in GitHub Actions (see `.github/workflows/test.yml`):
- Runs on every push and PR
- Uses Playwright's Docker image for consistency
- Generates HTML report for failures

## Debugging Tips

1. **Use UI mode** for interactive debugging:
   ```bash
   npm run test:e2e:ui
   ```

2. **Inspect element locators**:
   ```bash
   npx playwright codegen http://localhost:3000
   ```

3. **Take screenshots on failure** (already configured):
   ```typescript
   await page.screenshot({ path: 'screenshot.png' });
   ```

4. **Use trace viewer** for detailed debugging:
   ```bash
   npx playwright show-trace trace.zip
   ```

## Test Isolation

Each test:
- Runs in a fresh browser context
- Has isolated cookies and storage
- Gets a clean mock backend state
- Can be run in parallel (default)

## Coverage Areas

- ✅ Authentication flows
- ✅ Data entry and validation
- ✅ State machine transitions
- ✅ Error handling and recovery
- ✅ Real-time data sync
- ✅ **Bluetooth device integration** ⭐ NEW
- ✅ **Vitals capture workflows** ⭐ NEW
- ✅ Accessibility (ARIA roles, labels)
- ✅ Browser compatibility warnings
