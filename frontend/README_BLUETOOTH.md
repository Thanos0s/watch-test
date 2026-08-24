# 📘 Bluetooth Connectivity Guide for PrakritiDesk

## Overview

PrakritiDesk supports **direct Bluetooth pairing** with smartwatches and fitness trackers to automatically capture vital signs during patient check-in. This feature uses the **Web Bluetooth API** to connect directly from the browser without requiring any additional software or drivers.

---

## 📚 Documentation Files

We've created comprehensive documentation to help you connect your smartwatch:

### For Patients & Quick Reference:
- **[SMARTWATCH_QUICK_START.md](./SMARTWATCH_QUICK_START.md)** - 5-step visual guide (1 min read)

### For Detailed Instructions:
- **[HOW_TO_CONNECT_SMARTWATCH.md](./HOW_TO_CONNECT_SMARTWATCH.md)** - Complete guide with troubleshooting (10 min read)

### For Developers & Testing:
- **[BLUETOOTH_TESTS_COMPLETE.md](./BLUETOOTH_TESTS_COMPLETE.md)** - Test coverage summary
- **[TEST_RESULTS.md](./TEST_RESULTS.md)** - Latest test results
- **[TESTING.md](./TESTING.md)** - Full testing guide

---

## 🎯 Quick Overview

### What You Can Do

✅ **Pair smartwatches** directly from the browser (no app needed)  
✅ **Auto-capture heart rate** in real-time from your device  
✅ **Auto-capture SpO2** if your device supports it  
✅ **Automatic sync** when readings stabilize  
✅ **Red flag detection** for emergency vitals  
✅ **Manual entry fallback** if pairing fails  
✅ **Skip option** to proceed without vitals  

### What You Need

- **Browser**: Chrome or Edge (Web Bluetooth required)
- **Device**: Any smartwatch/fitness tracker with Heart Rate Service (BLE)
- **Examples**: Fitbit, Garmin, Polar, Wahoo, Apple Watch, Samsung, Xiaomi

---

## 🚀 Getting Started

### For Patients (Simple Steps):

1. **Prepare your watch**: Turn on Bluetooth, put in pairing mode
2. **Open PrakritiDesk**: Use Chrome/Edge browser
3. **Reach vitals screen**: Complete check-in and consent
4. **Click "Tap to Pair"**: Select your device from popup
5. **Stay still 10-15 seconds**: Let readings stabilize
6. **Continue**: Proceed to symptom interview

👉 See **[SMARTWATCH_QUICK_START.md](./SMARTWATCH_QUICK_START.md)** for visual guide

### For Developers (Running the App):

```bash
# 1. Install dependencies
cd frontend
npm install

# 2. Start development server
npm run dev

# 3. Open in Chrome/Edge
open http://localhost:3000

# 4. Navigate to doctor or kiosk page
# Doctor: http://localhost:3000/doctor
# Kiosk: http://localhost:3000/
```

### For Testing:

```bash
# Run unit tests
npm test -- --run

# Run with UI
npm run test:ui

# Run E2E tests
npm run test:e2e

# Run all tests
npm run test:all
```

---

## 🔧 Technical Architecture

### How It Works

```
┌─────────────┐
│ Smartwatch  │ ← Bluetooth Low Energy (BLE)
│  (BLE)      │
└──────┬──────┘
       │ GATT Protocol
       │ • Heart Rate Service (0x180D)
       │ • Pulse Oximeter Service (0x1822)
       ↓
┌─────────────────────┐
│  Browser            │
│  (Web Bluetooth)    │
│  - Chrome/Edge      │
└──────┬──────────────┘
       │ Component: SmartwatchBridge.tsx
       │ • Parse GATT payloads
       │ • Detect stability (5 readings)
       │ • Auto-sync with cooldown
       ↓
┌─────────────────────┐
│  Backend API        │
│  POST /vitals/sync  │
│  - Validate vitals  │
│  - Store in session │
│  - Red flag check   │
└─────────────────────┘
```

### Standards Compliance

✅ **Bluetooth GATT Specification**
- Heart Rate Service (UUID: 0x180D)
- Heart Rate Measurement Characteristic (UUID: 0x2A37)
- Pulse Oximeter Service (UUID: 0x1822)
- PLX Continuous Measurement Characteristic (UUID: 0x2A5F)

✅ **IEEE-11073 SFLOAT Encoding**
- Proper parsing of 16-bit floating point values
- Handles special values (NaN, infinity, reserved)

✅ **Web Bluetooth API**
- Browser-native implementation
- No external drivers or apps needed
- Secure HTTPS-only in production

---

## 🛠️ Component Reference

### Main Component: `SmartwatchBridge.tsx`

**Location**: `frontend/components/SmartwatchBridge.tsx`

**Props**:
```typescript
interface SmartwatchBridgeProps {
  apiBaseUrl?: string;        // Backend API URL
  sessionId: string;          // Patient session ID
  onSynced?: (result) => void;    // Callback on successful sync
  onRedFlag?: (reason) => void;   // Callback on emergency detection
}
```

**Features**:
- Device discovery and pairing
- Real-time data streaming via GATT notifications
- Stability detection (5-reading window, ±4 bpm tolerance)
- Auto-sync with 20-second cooldown
- Error handling and recovery
- Browser compatibility detection

**Usage**:
```tsx
<SmartwatchBridge
  sessionId="abc123"
  apiBaseUrl="http://localhost:8001"
  onSynced={(result) => console.log('Synced!', result)}
  onRedFlag={(reason) => alert('Emergency: ' + reason)}
/>
```

---

## 🧪 Test Coverage

### Unit Tests (18 tests)

**File**: `__tests__/SmartwatchBridge.test.tsx`

✅ GATT payload parsing (3 tests)  
✅ Stability detection algorithm (5 tests)  
✅ Component rendering & Bluetooth API (6 tests)  
✅ Heart rate display & notifications (2 tests)  
✅ Auto-sync logic (2 tests)  

**Run**: `npm test -- --run`

### E2E Tests (15+ tests)

**File**: `e2e/tests/smartwatch-vitals.spec.ts`

✅ Device pairing workflow  
✅ Real-time vitals display  
✅ Auto-sync triggers  
✅ Manual entry fallback  
✅ Red flag detection  
✅ Browser compatibility  

**Run**: `npm run test:e2e`

---

## 📊 Browser Compatibility

| Browser | Version | Status | Notes |
|---------|---------|--------|-------|
| Chrome | 56+ | ✅ Full support | Recommended |
| Edge | 79+ | ✅ Full support | Chromium-based |
| Opera | 43+ | ✅ Full support | Chromium-based |
| Samsung Internet | 6.2+ | ✅ Full support | Mobile browser |
| Firefox | All | ❌ Not supported | Flag not enabled by default |
| Safari | All | ❌ Not supported | No Web Bluetooth API |
| IE | All | ❌ Not supported | Legacy browser |

---

## 🔒 Privacy & Security

### Data Handling

✅ **No permanent pairing**: Connection ends when you leave the screen  
✅ **Session-based**: Vitals tied to current patient session only  
✅ **No device tracking**: Device identifiers not stored  
✅ **HTTPS required**: Production requires secure connection  
✅ **User consent**: Explicit privacy consent before vitals capture  
✅ **Red flag alerts**: Emergency detection triggers staff notification  

### Data Flow

```
1. User pairs device → Temporary BLE connection
2. Vitals captured → Stored in session (RAM)
3. Readings stabilize → Auto-sync to backend
4. Backend validates → Stored in patient record
5. User disconnects → BLE connection terminated
```

---

## ❓ FAQ

### Can I use my Apple Watch?

Yes, but you need to install a third-party BLE broadcaster app (e.g., "HRM Bridge") since Apple Watch doesn't broadcast HR by default.

### Why doesn't SpO2 show up?

Most consumer fitness trackers only broadcast heart rate via BLE. SpO2 requires the optional Pulse Oximeter Service which is rare on budget devices. High-end devices like Fitbit Sense or medical pulse oximeters support it.

### What if pairing fails?

You have two options:
1. Click "Enter Manually" to type in your vitals
2. Click "Skip for now" to proceed without vitals (staff can measure later)

### Is this secure?

Yes! The connection is:
- Temporary (session-based)
- Local (browser to watch only)
- Encrypted (BLE security)
- No personal data stored from watch

### Do I need an app?

No! Web Bluetooth works directly in the browser. No app, no driver, no installation needed.

### Will this work on mobile?

Yes! As long as you use Chrome or Samsung Internet browser on Android. iOS Safari doesn't support Web Bluetooth yet.

---

## 🆘 Troubleshooting

### Common Issues

| Issue | Quick Fix |
|-------|-----------|
| "Not supported" error | Use Chrome or Edge |
| Device not showing | Put watch in pairing mode |
| Can't connect | Disconnect from phone first |
| Readings unstable | Stay still for 15 seconds |
| No SpO2 | Normal for most devices |

👉 See **[HOW_TO_CONNECT_SMARTWATCH.md](./HOW_TO_CONNECT_SMARTWATCH.md)** for detailed troubleshooting

---

## 📞 Support

### For Patients:
- Use "Enter Manually" button as fallback
- Ask staff for assistance
- See Quick Start guide

### For Staff:
- Check browser compatibility (Chrome/Edge)
- Verify device is in pairing mode
- Guide patient through troubleshooting steps

### For Developers:
- Check browser console for errors
- Review test suite for examples
- See component source code
- Enable debug logging: `localStorage.debug = 'bluetooth:*'`

---

## 🎓 Learn More

### Documentation
- [Web Bluetooth API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Bluetooth_API)
- [Bluetooth GATT Services](https://www.bluetooth.com/specifications/specs/)
- [Heart Rate Service Specification](https://www.bluetooth.com/specifications/specs/heart-rate-service-1-0/)

### PrakritiDesk Guides
- [Testing Guide](./TESTING.md)
- [Test Coverage](./BLUETOOTH_TESTS_COMPLETE.md)
- [Run Tests](./RUN_TESTS.md)

---

## ✅ Status

**Feature**: Production Ready ✅  
**Tests**: 18/18 unit tests passing ✅  
**E2E Tests**: 15+ scenarios covered ✅  
**Documentation**: Complete ✅  
**Browser Support**: Chrome, Edge ✅  

---

*Last updated: August 24, 2026*  
*Version: 1.0.0*  
*Component: `components/SmartwatchBridge.tsx`*
