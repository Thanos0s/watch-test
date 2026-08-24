# 🔗 How to Connect Your Smartwatch to PrakritiDesk

This guide explains how to pair your smartwatch or fitness tracker with the PrakritiDesk kiosk to automatically capture heart rate and SpO2 readings.

---

## ⚙️ Requirements

### Browser Requirements
✅ **Supported Browsers:**
- Google Chrome (version 56+)
- Microsoft Edge (version 79+)
- Opera (version 43+)
- Samsung Internet (version 6.2+)

❌ **Not Supported:**
- Firefox (Web Bluetooth not enabled by default)
- Safari (no Web Bluetooth support)
- Internet Explorer

### Device Requirements
Your smartwatch/fitness tracker must support **Bluetooth Low Energy (BLE)** with the **Heart Rate Service** (GATT UUID 0x180D).

✅ **Compatible Devices (confirmed):**
- Fitbit Charge series (4, 5, 6)
- Fitbit Versa series
- Fitbit Sense series
- Garmin fitness trackers with HR
- Polar H10, H9
- Wahoo TICKR
- Apple Watch (with third-party BLE apps)
- Samsung Galaxy Watch series
- Xiaomi Mi Band series
- Most dedicated HR chest straps

📝 **Note:** Basic heart rate monitors work everywhere. SpO2 (blood oxygen) requires the optional Pulse Oximeter Service (0x1822), which many budget devices don't support.

---

## 🚀 Step-by-Step Connection Guide

### Step 1: Prepare Your Watch

1. **Turn on Bluetooth** on your smartwatch/fitness tracker
2. **Put the device on pairing mode** (consult your device manual):
   - **Fitbit**: Usually automatic when near a compatible device
   - **Garmin**: Settings → Sensors → Heart Rate → Broadcast Mode ON
   - **Polar/Wahoo**: Press and hold the button until it blinks
   - **Apple Watch**: Install a third-party BLE app like "HRM Bridge"
   - **Generic devices**: Check Settings → Connections → Bluetooth

3. **Wear the device properly** on your wrist or chest (for chest straps)
   - Make sure it's snug but comfortable
   - Wait for the HR sensor to activate (usually shows on device screen)

### Step 2: Open PrakritiDesk

1. Open **Chrome** or **Edge** browser on the kiosk computer/tablet
2. Navigate to the PrakritiDesk application
3. Complete the check-in process:
   - Enter your ABHA ID or mobile number
   - Verify with OTP
   - Accept the privacy consent

### Step 3: Pair Your Device

1. When you reach the **"Vitals & Pulse Check"** screen, you'll see a large button:
   ```
   🔗 Tap to Pair Pulse Sensor / Smartwatch
   ```

2. **Click the button**
   - A browser popup will appear showing nearby Bluetooth devices

3. **Select your device** from the list
   - Look for your device name (e.g., "Fitbit Charge 5", "Polar H10 12345678")
   - If you don't see it, make sure it's in pairing mode and try clicking "Scan again"

4. **Wait for connection**
   - The browser will connect to your device
   - You'll see "Connecting..." then "Paired: [Your Device Name]"

### Step 4: View Real-Time Data

Once connected, you'll see two large displays:

```
┌─────────────────┐  ┌─────────────────┐
│  Heart Rate     │  │  SpO2           │
│      75         │  │      98         │
│     bpm         │  │      %          │
└─────────────────┘  └─────────────────┘
```

- **Heart rate** updates every 1-2 seconds (pulsing animation)
- **SpO2** shows if your device supports it (otherwise shows "Not available")

### Step 5: Automatic Sync

The system will **automatically sync** your vitals when readings stabilize:

- **Stability Detection**: System waits for 5 consecutive readings within ±4 bpm
- **Status Messages**:
  - "Waiting for a stable reading..." — Keep still
  - "Syncing vitals..." — Sending to server
  - "✓ Synced (time)" — Successfully saved
  - "Sync failed — will retry" — Network issue, will auto-retry

**💡 Tip:** Stay still for 10-15 seconds to get a stable reading faster!

### Step 6: Continue to Symptoms

After successful sync:
1. You'll see a green confirmation: "✓ Vitals recorded — HR 75 bpm, SpO2 98%"
2. Click **"Continue to Symptoms ➜"** to proceed with the interview

---

## 🔧 Troubleshooting

### "Bluetooth pairing not supported" Error

**Problem:** Browser doesn't support Web Bluetooth API

**Solutions:**
- ✅ Switch to Chrome or Edge browser
- ✅ Update your browser to the latest version
- ✅ Check that you're using HTTPS (not HTTP) in production
- ✅ Enable Web Bluetooth flag in browser settings:
  - Chrome: `chrome://flags/#enable-web-bluetooth-new-permissions-backend`
  - Edge: `edge://flags/#enable-web-bluetooth-new-permissions-backend`

### Device Not Showing in List

**Problem:** Your smartwatch doesn't appear in the pairing popup

**Solutions:**
- ✅ Make sure Bluetooth is ON on your watch
- ✅ Put the watch in explicit pairing/broadcast mode (check manual)
- ✅ Move the watch closer to the kiosk computer
- ✅ Remove the watch from other paired devices (disconnect from phone)
- ✅ Restart your watch
- ✅ Try clicking the pair button again

### "Could not pair with the device" Error

**Problem:** Connection failed during pairing

**Solutions:**
- ✅ Check that your watch has battery charge
- ✅ Make sure the watch isn't already connected to another device (like your phone)
- ✅ Turn Bluetooth off and on again on your watch
- ✅ Restart the watch
- ✅ Try the manual entry option as a fallback

### Heart Rate Shows But No SpO2

**This is normal!** Most fitness trackers only broadcast heart rate via Bluetooth.

- SpO2 requires the **Pulse Oximeter Service** (rare on consumer devices)
- Higher-end devices like Fitbit Sense, Apple Watch Series 6+, or medical-grade pulse oximeters support it
- You can still manually enter SpO2 if you have it from another source

### "Waiting for a stable reading..." Taking Too Long

**Problem:** Readings keep changing, won't stabilize

**Solutions:**
- ✅ **Stay completely still** for 15-20 seconds
- ✅ Make sure the watch is properly positioned on your wrist
- ✅ Relax and breathe normally
- ✅ If it still doesn't work, click **"Disconnect"** and use **"Enter Manually"** option

### Connection Drops Unexpectedly

**Problem:** Device disconnects during reading

**Solutions:**
- ✅ Check battery level on your watch
- ✅ Move closer to the kiosk (reduce distance)
- ✅ Remove sources of interference (other Bluetooth devices, Wi-Fi routers)
- ✅ Try pairing again
- ✅ Use manual entry if problem persists

---

## 🎯 Alternative Options

If you **cannot connect** your smartwatch, you have two options:

### Option 1: Manual Entry

1. Click **"✍️ Enter Manually"** button
2. Enter your vitals:
   - Heart rate (bpm)
   - SpO2 (%)
   - Systolic BP (optional)
   - Diastolic BP (optional)
3. Click **"Save & Continue"**

### Option 2: Skip Vitals

1. Click **"Skip for now ➜"** button
2. Proceed directly to symptom interview
3. Staff can measure vitals later if needed

---

## 🔬 Technical Details

### What Data is Collected?

The system reads **standard Bluetooth GATT services**:

1. **Heart Rate Service (0x180D)** — Required
   - Characteristic: Heart Rate Measurement (0x2A37)
   - Provides: BPM (beats per minute)
   - Format: 8-bit or 16-bit integer per Bluetooth GATT spec

2. **Pulse Oximeter Service (0x1822)** — Optional
   - Characteristic: PLX Continuous Measurement (0x2A5F)
   - Provides: SpO2 percentage
   - Format: IEEE-11073 SFLOAT encoding

### Privacy & Security

✅ **Data stays local**: No permanent pairing with your watch
✅ **Session-based**: Connection ends when you disconnect or leave the screen
✅ **No personal data stored**: Only vitals readings, no device identifiers
✅ **HTTPS required**: Secure connection in production environments
✅ **User-initiated**: You control when to connect and disconnect

### Stability Algorithm

The system uses a **5-reading rolling window** to ensure accuracy:

```
Stability = (Max - Min) of last 5 readings ≤ 4 bpm
```

**Example:**
- Readings: [72, 73, 74, 73, 72] → **Stable** (range = 2 bpm)
- Readings: [70, 75, 80, 85, 90] → **Unstable** (range = 20 bpm)

Only stable readings are auto-synced to prevent false alarms.

### Auto-Sync Cooldown

After a successful sync, the system waits **20 seconds** before auto-syncing again. This prevents:
- Excessive network requests
- Duplicate vitals records
- Server overload during busy periods

---

## 📞 Need Help?

### For Patients:
- Press the **"✍️ Enter Manually"** button to skip pairing
- Or click **"Skip for now"** and ask staff for help
- Raise your hand to get staff assistance

### For Staff/IT Support:
- Check browser compatibility (Chrome/Edge required)
- Verify Web Bluetooth is enabled in browser flags
- Ensure device is in proper pairing mode
- Test with a known-working device to isolate issue
- Check server logs at `/vitals/sync` endpoint

### For Developers:
- See `components/SmartwatchBridge.tsx` for implementation
- See `__tests__/SmartwatchBridge.test.tsx` for test coverage
- Check browser console for detailed error messages
- Enable verbose logging: Set `localStorage.debug = 'bluetooth:*'`

---

## ✅ Quick Reference

| Action | What to Do |
|--------|-----------|
| **Start Pairing** | Click "🔗 Tap to Pair" button |
| **Select Device** | Choose your watch from popup list |
| **Check Status** | Look for "Paired: [Device Name]" |
| **View Readings** | Watch the HR/SpO2 displays update |
| **Wait for Sync** | Stay still until "✓ Synced" appears |
| **Disconnect** | Click "Disconnect" link (top right) |
| **Skip Pairing** | Click "Enter Manually" or "Skip for now" |
| **Get Help** | Raise hand for staff assistance |

---

## 🎊 Success!

Once you see **"✓ Vitals recorded"**, you're all set! The system has captured your vitals and you can continue to the symptom interview.

Your vitals data is now:
- ✅ Stored securely in your session
- ✅ Available to the doctor during consultation  
- ✅ Used for emergency red-flag detection
- ✅ Part of your permanent health record (with consent)

**Ready to continue?** Click **"Continue to Symptoms ➜"**

---

*Last updated: August 24, 2026*  
*For technical support, contact your system administrator*
