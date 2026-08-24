# Quick Start: Running Bluetooth Tests

## 🚀 First Time Setup

1. **Install test dependencies** (one-time):
   ```bash
   cd frontend
   npm install
   ```

   Or use the setup script:
   ```bash
   setup-tests.bat
   ```

## ⚡ Run Tests

### All Bluetooth/Smartwatch Tests

```bash
# Unit tests (GATT parsing, stability, mocking)
npm test SmartwatchBridge

# E2E tests (complete user workflows)
npx playwright test smartwatch-vitals

# Run everything
npm run test:all
```

### Interactive Test UI (Recommended)

```bash
# Unit tests UI - see tests update in real-time
npm run test:ui

# E2E tests UI - step through browser tests
npm run test:e2e:ui
```

## 📊 What Gets Tested

### ✅ Unit Tests (30+ test cases)
- GATT payload parsing (Heart Rate, SpO2)
- Stability detection algorithm
- Web Bluetooth API mocking
- Device pairing workflow
- Real-time notifications
- Auto-sync logic with cooldown
- Red flag detection
- Error handling

### ✅ E2E Tests (15+ test cases)
- Complete pairing workflow
- Heart rate display
- SpO2 display
- Auto-sync when stable
- Manual vitals entry
- Skip vitals option
- Red flag alerts
- Device disconnection
- Browser compatibility

## 🐛 Debug Failing Tests

### Unit Tests
```bash
# Watch mode (auto-rerun on changes)
npm test -- --watch

# Run single test
npm test -- -t "should parse heart rate"

# Verbose output
npm test -- --reporter=verbose
```

### E2E Tests
```bash
# See the browser in action
npx playwright test smartwatch-vitals --headed

# Step through test with debugger
npx playwright test smartwatch-vitals --debug

# Slow motion
npx playwright test --headed --slow-mo=1000
```

## 📈 Coverage Report

```bash
npm run test:coverage
```

Opens HTML coverage report in browser showing:
- Lines covered
- Branches covered
- Functions covered
- Untested code paths

## ✅ Pre-Commit Checklist

Before committing Bluetooth/vitals changes:

```bash
# 1. Run Bluetooth-specific tests
npm test SmartwatchBridge
npx playwright test smartwatch-vitals

# 2. Check coverage
npm run test:coverage

# 3. Run full test suite
npm run test:all

# 4. Lint check
npm run lint
```

## 🔍 Test File Locations

```
frontend/
├── __tests__/
│   ├── SmartwatchBridge.test.tsx    ← Unit tests
│   └── README.md                     ← Unit test docs
├── e2e/
│   ├── tests/
│   │   ├── smartwatch-vitals.spec.ts ← E2E tests
│   │   ├── patient-intake.spec.ts
│   │   └── ...
│   ├── pages/
│   │   └── KioskPage.ts              ← Page objects
│   └── README.md                     ← E2E test docs
├── vitest.config.ts                  ← Unit test config
├── vitest.setup.ts                   ← Test setup
├── playwright.config.ts              ← E2E test config
└── TESTING.md                        ← Complete guide
```

## 🎯 Quick Reference

| Command | Purpose |
|---------|---------|
| `npm test` | Run all unit tests |
| `npm run test:ui` | Unit tests with UI |
| `npm run test:e2e` | Run E2E tests |
| `npm run test:e2e:ui` | E2E tests with UI |
| `npm run test:all` | Run everything |
| `npm run test:coverage` | Coverage report |

## 💡 Tips

1. **Use UI mode** for development - it's faster and more visual
2. **Run specific tests** during development to save time
3. **Check coverage** to find untested code paths
4. **Use headed mode** for E2E debugging
5. **Read test output** - it tells you what failed and why

## 📚 Learn More

- **TESTING.md** - Complete testing guide
- **__tests__/README.md** - Unit test details
- **e2e/README.md** - E2E test details

## 🆘 Need Help?

Common issues and solutions in TESTING.md under "Troubleshooting"

---

**Status**: ✅ All Bluetooth functionality is tested and ready
