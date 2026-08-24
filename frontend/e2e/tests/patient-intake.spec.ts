import { expect, test } from "../fixtures/test-fixtures";
import { mockIntakeTurnResponse, mockRedFlagTurnResponse } from "../fixtures/mocks";
import { mockKioskBackend } from "../fixtures/mockRoutes";

/**
 * E2E coverage of the patient-facing kiosk flow in
 * frontend/components/KioskUI.tsx:
 *   check-in -> OTP -> DPDP consent -> vitals (skip) -> conversational
 *   intake -> completion, plus the emergency red-flag short-circuit.
 *
 * All backend calls are mocked (see fixtures/mockRoutes.ts) -- this suite
 * exercises the UI's state machine and network wiring, not Groq/Bhashini
 * themselves (those are covered by the backend's own test suite, see
 * intake-engine/tests/).
 */

test.describe("Patient intake flow", () => {
  test.beforeEach(async ({ page }) => {
    await mockKioskBackend(page);
  });

  test("completes check-in through to the first intake question", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");

    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456"); // matches mockVerifyOtpResponse's sandbox_otp_hint
    await kioskPage.acceptConsent();
    await kioskPage.skipVitals(); // exercises the "kiosk flow never blocked" guarantee

    await kioskPage.expectAudioPrompt("What is bothering you today?");
    await expect(page.getByRole("button", { name: "Pain", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Fever", exact: true })).toBeVisible();
  });

  test("selecting a touch option submits it and advances to the next question", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();
    await kioskPage.skipVitals();

    // Override the default /intake/turn mock for this specific submission.
    await page.route("**/intake/turn", async (route) => {
      const body = route.request().postDataJSON();
      expect(body.user_input).toBe("Pain");
      await route.fulfill({
        json: mockIntakeTurnResponse({
          audio_prompt_text: "Where exactly do you feel it?",
          touch_options: ["Head", "Chest", "Stomach", "Other/Describe"],
        }),
      });
    });

    await kioskPage.selectTouchOption("Pain");
    await kioskPage.expectAudioPrompt("Where exactly do you feel it?");
  });

  test("an emergency answer short-circuits straight to the red-flag alert screen", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();
    await kioskPage.skipVitals();

    await page.route("**/intake/turn", async (route) => {
      await route.fulfill({
        json: mockRedFlagTurnResponse("Possible acute coronary event (chest pain with radiation/associated symptoms)"),
      });
    });

    await kioskPage.selectTouchOption("Pain");

    await kioskPage.expectRedFlagAlert();
    await expect(page.getByText("A staff member is being called")).toBeVisible();
    await expect(page.getByText(/acute coronary event/)).toBeVisible();
  });

  test("reaching is_complete shows the completion screen", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");
    await kioskPage.acceptConsent();
    await kioskPage.skipVitals();

    await page.route("**/intake/turn", async (route) => {
      await route.fulfill({
        json: mockIntakeTurnResponse({
          audio_prompt_text: "Thank you. Please wait, the doctor will see you shortly.",
          touch_options: ["Done"],
          is_complete: true,
        }),
      });
    });

    await kioskPage.selectTouchOption("Pain");
    await kioskPage.expectCompletionScreen();
  });

  test("declining consent returns the patient to check-in rather than proceeding", async ({ kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");
    await kioskPage.submitOtp("123456");

    await kioskPage.disagreeConsentButton.click();

    // Back at check-in -- intake must never be reachable without consent.
    await expect(kioskPage.abhaInput).toBeVisible();
  });

  test("an incorrect OTP shows an error and does not advance past the OTP screen", async ({ page, kioskPage }) => {
    await kioskPage.goto("/");
    await kioskPage.submitCheckIn("9876543210");

    await page.route("**/auth/abha/verify-otp", async (route) => {
      await route.fulfill({
        status: 400,
        json: { error: "invalid_otp", message: "The OTP entered is incorrect." },
      });
    });

    await kioskPage.otpInput.fill("000000");
    await kioskPage.verifyOtpButton.click();

    // KioskUI.tsx's verifyOtp() surfaces the backend's `message` field
    // verbatim (falling back to a generic "OTP verification failed (status)"
    // only when the backend response has none) -- assert the real text.
    await expect(page.getByText("The OTP entered is incorrect.")).toBeVisible();
    await expect(kioskPage.otpInput).toBeVisible(); // still on the OTP screen
  });
});
