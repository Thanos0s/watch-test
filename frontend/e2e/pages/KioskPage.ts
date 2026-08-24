import { expect, Locator, Page } from "@playwright/test";

/**
 * Page Object for the patient-facing kiosk flow.
 * Mirrors frontend/components/KioskUI.tsx's screen sequence exactly:
 *   checkin -> otp -> consent -> vitals -> intake -> complete | redflag
 *
 * Locators are built from real, stable text/aria-labels already in the
 * component (see e2e/fixtures/mocks.ts's header comment for how these
 * were verified against the actual source, not guessed).
 */
export class KioskPage {
  readonly page: Page;

  // Check-in screen
  readonly abhaInput: Locator;
  readonly continueButton: Locator;

  // OTP screen
  readonly otpInput: Locator;
  readonly verifyOtpButton: Locator;
  readonly resendOtpButton: Locator;

  // Consent screen
  readonly agreeConsentButton: Locator;
  readonly disagreeConsentButton: Locator;

  // Vitals screen
  readonly pairSmartwatchButton: Locator;
  readonly enterVitalsManuallyButton: Locator;
  readonly skipOrContinueVitalsButton: Locator;

  // Intake screen
  readonly micButton: Locator;
  readonly audioPromptText: Locator;

  // Terminal screens
  readonly redFlagHeading: Locator;
  readonly completeHeading: Locator;

  constructor(page: Page) {
    this.page = page;

    this.abhaInput = page.getByPlaceholder("XX-XXXX-XXXX-XXXX or mobile number");
    this.continueButton = page.getByRole("button", { name: "Continue ➜" });

    this.otpInput = page.getByPlaceholder("6-digit OTP");
    this.verifyOtpButton = page.getByRole("button", { name: "Verify ➜" });
    this.resendOtpButton = page.getByRole("button", { name: /Resend OTP/ });

    this.agreeConsentButton = page.getByRole("button", { name: "✅ I Agree" });
    this.disagreeConsentButton = page.getByRole("button", { name: "❌ I Do Not Agree" });

    this.pairSmartwatchButton = page.getByRole("button", { name: /Tap to Pair Pulse Sensor/ });
    this.enterVitalsManuallyButton = page.getByRole("button", { name: "✍️ Enter Manually" });
    this.skipOrContinueVitalsButton = page.getByRole("button", { name: /Skip for now|Continue to Symptoms/ });

    this.micButton = page.getByRole("button", { name: "Hold to speak your answer" });
    this.audioPromptText = page.locator("p.text-3xl.font-semibold");

    this.redFlagHeading = page.getByText("Please stay seated.");
    this.completeHeading = page.getByText("Thank you!");
  }

  async goto(baseURL: string) {
    await this.page.goto(baseURL);
    await expect(this.page.getByText("Welcome to PrakritiDesk")).toBeVisible();
  }

  /** Steps through check-in with the given ABHA ID/mobile, up to the OTP screen. */
  async submitCheckIn(abhaIdOrMobile: string) {
    await this.abhaInput.fill(abhaIdOrMobile);
    await this.continueButton.click();
    await expect(this.otpInput).toBeVisible();
  }

  /** Enters and submits an OTP, expecting to land on the consent screen. */
  async submitOtp(otp: string) {
    await this.otpInput.fill(otp);
    await this.verifyOtpButton.click();
    await expect(this.agreeConsentButton).toBeVisible();
  }

  /** Agrees to the DPDP consent screen, expecting to land on the vitals screen. */
  async acceptConsent() {
    await this.agreeConsentButton.click();
    await expect(this.skipOrContinueVitalsButton).toBeVisible();
  }

  /** Skips the (optional) vitals step -- exercises the "kiosk flow never
   * blocked" guarantee -- expecting to land on the intake screen. */
  async skipVitals() {
    await this.skipOrContinueVitalsButton.click();
    await expect(this.audioPromptText).toBeVisible();
  }

  /** Clicks a touch-option button by its exact visible label. */
  async selectTouchOption(optionLabel: string) {
    await this.page.getByRole("button", { name: optionLabel, exact: true }).click();
  }

  async expectAudioPrompt(text: string) {
    await expect(this.audioPromptText).toHaveText(text);
  }

  async expectRedFlagAlert() {
    await expect(this.redFlagHeading).toBeVisible();
  }

  async expectCompletionScreen() {
    await expect(this.completeHeading).toBeVisible();
  }
}
