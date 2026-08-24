/**
 * E2E tests for smartwatch pairing and vitals capture workflow.
 * 
 * Tests the complete user journey:
 * - Pairing a Bluetooth device from the vitals screen
 * - Receiving heart rate and SpO2 data
 * - Auto-sync when readings stabilize
 * - Manual vitals entry fallback
 * - Red flag detection from vitals
 * 
 * NOTE: Web Bluetooth API requires user gestures and real device access,
 * so these tests mock the navigator.bluetooth API at the page level.
 */

import { expect, test } from "../fixtures/test-fixtures";
import { mockKioskBackend } from "../fixtures/mockRoutes";

test.describe("Smartwatch vitals capture", () => {
  test.beforeEach(async ({ page }) => {
    await mockKioskBackend(page);
    
    // Mock Web Bluetooth API at the page level
    await page.addInitScript(() => {
      // Create mock Bluetooth device hierarchy
      const createMockDevice = (name: string, heartRate: number, hasSpo2: boolean) => {
        const hrCharacteristic = {
          value: null as DataView | null,
          startNotifications: async function() {
            // Simulate heart rate notifications
            setTimeout(() => {
              const buffer = new ArrayBuffer(2);
              const view = new DataView(buffer);
              view.setUint8(0, 0x00); // 8-bit format
              view.setUint8(1, heartRate);
              this.value = view;
              
              const event = new Event('characteristicvaluechanged');
              Object.defineProperty(event, 'currentTarget', { value: this });
              this.dispatchEvent(event);
            }, 100);
            return this;
          },
          stopNotifications: async function() { return this; },
          addEventListener: (type: string, handler: any) => {
            if (type === 'characteristicvaluechanged') {
              (hrCharacteristic as any)._handler = handler;
            }
          },
          removeEventListener: () => {},
          dispatchEvent: (event: Event) => {
            if ((hrCharacteristic as any)._handler) {
              (hrCharacteristic as any)._handler(event);
            }
          },
        };

        const plxCharacteristic = hasSpo2 ? {
          value: null as DataView | null,
          startNotifications: async function() {
            setTimeout(() => {
              const buffer = new ArrayBuffer(5);
              const view = new DataView(buffer);
              view.setUint8(0, 0x00);
              view.setUint16(1, 98, true); // SpO2 98%
              view.setUint16(3, heartRate, true);
              this.value = view;
              
              const event = new Event('characteristicvaluechanged');
              Object.defineProperty(event, 'currentTarget', { value: this });
              this.dispatchEvent(event);
            }, 150);
            return this;
          },
          stopNotifications: async function() { return this; },
          addEventListener: (type: string, handler: any) => {
            if (type === 'characteristicvaluechanged') {
              (plxCharacteristic as any)._handler = handler;
            }
          },
          removeEventListener: () => {},
          dispatchEvent: (event: Event) => {
            if ((plxCharacteristic as any)._handler) {
              (plxCharacteristic as any)._handler(event);
            }
          },
        } : null;

        return {
          name,
          gatt: {
            connected: true,
            connect: async function() { return this; },
            disconnect: () => {},
            getPrimaryService: async (serviceId: string) => {
              if (serviceId === 'heart_rate') {
                return {
                  getCharacteristic: async () => hrCharacteristic,
                };
              }
              if (serviceId === 'pulse_oximeter') {
                if (plxCharacteristic) {
                  return {
                    getCharacteristic: async () => plxCharacteristic,
                  };
                }
                throw new Error('Service not found');
              }
              throw new Error('Unknown service');
            },
          },
          addEventListener: () => {},
          removeEventListener: () => {},
        };
      };

      // Store mock device for test access
      (window as any).__mockBluetoothDevice = null;

      // Mock navigator.bluetooth
      Object.defineProperty(navigator, 'bluetooth', {
        value: {
          requestDevice: async (options: any) => {
            // Simulate user selecting a device from the chooser
            const device = createMockDevice('Test Smartwatch', 72, true);
            (window as any).__mockBluetoothDevice = device;
            return device;
          },
        },
        configurable: true,
      });
    });
  });

  test("should show pair button on vitals screen", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await expect(kioskPage.pairSmartwatchButton).toBeVisible();
    await expect(page.getByText(/If you're wearing a smartwatch/i)).toBeVisible();
  });

  test("should successfully pair device and show device name", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    // Click pair button
    await kioskPage.pairSmartwatchButton.click();

    // Should show device name after pairing
    await expect(page.getByText(/Paired: Test Smartwatch/i)).toBeVisible({ timeout: 3000 });
    
    // Should show disconnect button
    await expect(page.getByRole('button', { name: /Disconnect/i })).toBeVisible();
  });

  test("should display heart rate after pairing", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.pairSmartwatchButton.click();
    await expect(page.getByText(/Paired:/i)).toBeVisible();

    // Heart rate should appear (mocked as 72 bpm)
    await expect(page.getByText("72")).toBeVisible({ timeout: 2000 });
    await expect(page.getByText("bpm")).toBeVisible();
  });

  test("should display SpO2 when device supports it", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.pairSmartwatchButton.click();
    await expect(page.getByText(/Paired:/i)).toBeVisible();

    // SpO2 should appear (mocked as 98%)
    await expect(page.getByText("98")).toBeVisible({ timeout: 2000 });
    await expect(page.getByText("%")).toBeVisible();
  });

  test("should auto-sync vitals when readings stabilize", async ({ page, kioskPage }) => {
    // Mock the vitals sync endpoint
    await page.route("**/vitals/sync", async (route) => {
      const postData = route.request().postDataJSON();
      expect(postData.heart_rate_bpm).toBeDefined();
      expect(postData.session_id).toBeDefined();
      
      await route.fulfill({
        json: {
          session_id: postData.session_id,
          trigger_red_flag: false,
          red_flag_reason: null,
          nadi_trait_estimate: "Vata-Pitta",
          hrv_sdnn_ms: 45,
          patient_record: {
            device_vitals: {
              heart_rate_bpm: postData.heart_rate_bpm,
              spo2_percent: postData.spo2_percent,
            },
          },
        },
      });
    });

    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.pairSmartwatchButton.click();
    await expect(page.getByText(/Paired:/i)).toBeVisible();

    // Wait for heart rate to appear
    await expect(page.getByText("72")).toBeVisible({ timeout: 2000 });

    // Should show syncing status
    await expect(page.getByText(/Syncing vitals|Synced/i)).toBeVisible({ timeout: 5000 });
    
    // Should show vitals recorded confirmation
    await expect(page.getByText(/✓ Vitals recorded/i)).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/HR 72 bpm/i)).toBeVisible();
  });

  test("should allow manual vitals entry when device pairing fails", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    // Click "Enter Manually" button
    await kioskPage.enterVitalsManuallyButton.click();

    // Should show manual entry form
    await expect(page.getByLabelText(/Heart rate \(bpm\)/i)).toBeVisible();
    await expect(page.getByLabelText(/SpO2 \(%\)/i)).toBeVisible();
    await expect(page.getByLabelText(/Systolic BP/i)).toBeVisible();
    await expect(page.getByLabelText(/Diastolic BP/i)).toBeVisible();
  });

  test("should submit manual vitals and continue to intake", async ({ page, kioskPage }) => {
    // Mock vitals sync endpoint
    await page.route("**/vitals/sync", async (route) => {
      const postData = route.request().postDataJSON();
      await route.fulfill({
        json: {
          session_id: postData.session_id,
          trigger_red_flag: false,
          red_flag_reason: null,
          nadi_trait_estimate: null,
          hrv_sdnn_ms: null,
          patient_record: {
            device_vitals: {
              heart_rate_bpm: postData.heart_rate_bpm,
              spo2_percent: postData.spo2_percent,
              systolic_bp: postData.systolic_bp,
              diastolic_bp: postData.diastolic_bp,
            },
          },
        },
      });
    });

    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.enterVitalsManuallyButton.click();

    // Fill in manual vitals
    await page.getByLabelText(/Heart rate \(bpm\)/i).fill("75");
    await page.getByLabelText(/SpO2 \(%\)/i).fill("97");
    await page.getByLabelText(/Systolic BP/i).fill("120");
    await page.getByLabelText(/Diastolic BP/i).fill("80");

    // Submit
    await page.getByRole('button', { name: /Save & Continue/i }).click();

    // Should proceed to intake screen
    await expect(kioskPage.audioPromptText).toBeVisible({ timeout: 3000 });
  });

  test("should allow skipping vitals entirely", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    // Click skip button
    await kioskPage.skipOrContinueVitalsButton.click();

    // Should proceed to intake screen
    await expect(kioskPage.audioPromptText).toBeVisible();
    await expect(page.getByText(/What is bothering you today/i)).toBeVisible();
  });

  test("should trigger red flag when vitals sync detects emergency", async ({ page, kioskPage }) => {
    // Mock vitals sync with red flag response
    await page.route("**/vitals/sync", async (route) => {
      await route.fulfill({
        json: {
          session_id: "test-session",
          trigger_red_flag: true,
          red_flag_reason: "Critically low oxygen saturation detected (SpO2 < 90%)",
          nadi_trait_estimate: null,
          hrv_sdnn_ms: null,
          patient_record: {
            device_vitals: {
              heart_rate_bpm: 110,
              spo2_percent: 85,
            },
          },
        },
      });
    });

    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.enterVitalsManuallyButton.click();
    
    // Enter concerning vitals
    await page.getByLabelText(/Heart rate \(bpm\)/i).fill("110");
    await page.getByLabelText(/SpO2 \(%\)/i).fill("85");
    await page.getByRole('button', { name: /Save & Continue/i }).click();

    // Should show red flag alert
    await expect(kioskPage.redFlagHeading).toBeVisible({ timeout: 3000 });
    await expect(page.getByText(/oxygen saturation/i)).toBeVisible();
  });

  test("should allow disconnecting paired device", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.pairSmartwatchButton.click();
    await expect(page.getByText(/Paired:/i)).toBeVisible();

    // Click disconnect
    await page.getByRole('button', { name: /Disconnect/i }).click();

    // Should return to unpaired state
    await expect(kioskPage.pairSmartwatchButton).toBeVisible();
    await expect(page.getByText(/Paired:/i)).not.toBeVisible();
  });

  test("should continue to intake after successful vitals capture from device", async ({ page, kioskPage }) => {
    await page.route("**/vitals/sync", async (route) => {
      await route.fulfill({
        json: {
          session_id: "test-session",
          trigger_red_flag: false,
          red_flag_reason: null,
          nadi_trait_estimate: "Kapha",
          hrv_sdnn_ms: 50,
          patient_record: {
            device_vitals: {
              heart_rate_bpm: 72,
              spo2_percent: 98,
            },
          },
        },
      });
    });

    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    await kioskPage.pairSmartwatchButton.click();
    await expect(page.getByText(/Paired:/i)).toBeVisible();

    // Wait for vitals to sync
    await expect(page.getByText(/✓ Vitals recorded/i)).toBeVisible({ timeout: 5000 });

    // Continue button should now say "Continue to Symptoms"
    await expect(page.getByRole('button', { name: /Continue to Symptoms/i })).toBeVisible();
    await page.getByRole('button', { name: /Continue to Symptoms/i }).click();

    // Should proceed to intake
    await expect(kioskPage.audioPromptText).toBeVisible();
  });
});

test.describe("Smartwatch browser compatibility", () => {
  test("should show unsupported message when Web Bluetooth is not available", async ({ page, kioskPage }) => {
    // Remove Web Bluetooth support
    await page.addInitScript(() => {
      Object.defineProperty(navigator, 'bluetooth', {
        value: undefined,
        configurable: true,
      });
    });

    await mockKioskBackend(page);
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();

    // Should show unsupported message
    await expect(page.getByText(/Bluetooth pairing not supported/i)).toBeVisible();
    await expect(page.getByText(/Use Chrome or Edge/i)).toBeVisible();

    // Should not show pair button
    await expect(kioskPage.pairSmartwatchButton).not.toBeVisible();

    // But should still allow manual entry and skip
    await expect(kioskPage.enterVitalsManuallyButton).toBeVisible();
    await expect(kioskPage.skipOrContinueVitalsButton).toBeVisible();
  });
});
