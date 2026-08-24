# Unit Tests for PrakritiDesk Frontend

This directory contains unit tests for React components using Vitest and React Testing Library.

## Test Coverage

### SmartwatchBridge.test.tsx

Comprehensive tests for the Bluetooth smartwatch pairing and vitals capture:

#### GATT Payload Parsing
- ✅ Parse 8-bit heart rate measurements
- ✅ Parse 16-bit heart rate measurements (for HR > 255 bpm)
- ✅ Parse SpO2 from PLX Continuous Measurement (IEEE-11073 SFLOAT format)

#### Stability Detection Algorithm
- ✅ Reject readings when fewer than 5 samples
- ✅ Accept readings within 4 bpm tolerance
- ✅ Reject readings exceeding tolerance
- ✅ Use sliding window (last 5 readings only)
- ✅ Handle edge cases at tolerance boundary

#### Component Rendering
- ✅ Show unsupported message when Web Bluetooth unavailable
- ✅ Show pair button when supported
- ✅ Display device name after pairing
- ✅ Show SpO2 unavailable for devices without pulse oximeter
- ✅ Handle user cancellation gracefully
- ✅ Show error messages for pairing failures

#### Heart Rate and SpO2 Display
- ✅ Display heart rate from BLE notifications
- ✅ Display SpO2 from PLX notifications
- ✅ Update display in real-time

#### Auto-sync Logic
- ✅ Do NOT sync when readings are unstable
- ✅ Trigger red flag callback for emergency vitals
- ✅ Respect 20-second cooldown between syncs
- ✅ Send correct payload to backend API

## Running Tests

```bash
# Run all unit tests
npm test

# Run tests in watch mode
npm test -- --watch

# Run tests with UI
npm run test:ui

# Run tests with coverage report
npm run test:coverage

# Run specific test file
npm test SmartwatchBridge
```

## Test Structure

Tests follow the Arrange-Act-Assert pattern:

1. **Arrange**: Set up test data and mocks
2. **Act**: Execute the code under test
3. **Assert**: Verify the results

### Mocking Strategy

- Web Bluetooth API is fully mocked at the `navigator.bluetooth` level
- Mock GATT services, characteristics, and notifications
- Mock backend API calls with `fetch`
- Use realistic DataView payloads matching Bluetooth GATT spec

## Writing New Tests

When adding new component tests:

1. Create a new file: `ComponentName.test.tsx`
2. Import testing utilities:
   ```typescript
   import { describe, it, expect, beforeEach, vi } from 'vitest';
   import { render, screen, fireEvent, waitFor } from '@testing-library/react';
   import '@testing-library/jest-dom';
   ```
3. Group related tests in `describe` blocks
4. Use descriptive test names: `it('should do X when Y happens', ...)`
5. Clean up mocks in `afterEach` hooks

## Coverage Goals

- **Statements**: > 80%
- **Branches**: > 75%
- **Functions**: > 80%
- **Lines**: > 80%

Focus on testing:
- User interactions
- Edge cases and error handling
- State transitions
- API integrations
