import { Page } from "@playwright/test";
import {
  mockDoctorQueueEntry,
  mockFhirBundle,
  mockInitOtpResponse,
  mockIntakeTurnResponse,
  mockSilentWavBytes,
  mockVerifyOtpResponse,
} from "./mocks";

const API_BASE_URL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8001";

/**
 * Wires up every backend call KioskUI.tsx makes to a mock response, so the
 * "patient intake" E2E suite runs against zero real Groq/Bhashini/ABDM
 * traffic. Each route can still be overridden per-test after calling this
 * (Playwright routes are last-registered-wins), e.g. to make a specific
 * /intake/turn call return a red-flag response.
 */
export async function mockKioskBackend(page: Page) {
  await page.route(`${API_BASE_URL}/auth/abha/init-otp`, async (route) => {
    await route.fulfill({ json: mockInitOtpResponse() });
  });

  await page.route(`${API_BASE_URL}/auth/abha/verify-otp`, async (route) => {
    await route.fulfill({ json: mockVerifyOtpResponse() });
  });

  await page.route(`${API_BASE_URL}/audio/synthesize`, async (route) => {
    await route.fulfill({ body: mockSilentWavBytes(), contentType: "audio/wav" });
  });

  await page.route(`${API_BASE_URL}/intake/opening-question`, async (route) => {
    await route.fulfill({ json: mockIntakeTurnResponse() });
  });

  await page.route(`${API_BASE_URL}/intake/turn`, async (route) => {
    await route.fulfill({ json: mockIntakeTurnResponse({ audio_prompt_text: "Where exactly do you feel it?" }) });
  });
}

/**
 * Wires up every backend call the doctor dashboard makes. `queueEntries`
 * seeds GET /queue/active's response; pass your own array (built with
 * mockDoctorQueueEntry/mockNormalQueueEntry from ./mocks) to control
 * exactly which patients -- and which are flagged urgent -- appear.
 */
export async function mockDoctorBackend(page: Page, queueEntries = [mockDoctorQueueEntry()]) {
  await page.route(`${API_BASE_URL}/queue/active`, async (route) => {
    await route.fulfill({ json: queueEntries });
  });

  await page.route(new RegExp(`${API_BASE_URL}/queue/patient/.*`), async (route) => {
    if (route.request().method() === "GET") {
      const sessionId = route.request().url().split("/").pop();
      const match = queueEntries.find((e) => e.session_id === sessionId) ?? queueEntries[0];
      await route.fulfill({ json: match });
    } else if (route.request().method() === "PUT") {
      const body = route.request().postDataJSON();
      const sessionId = route.request().url().split("/").pop();
      const match = queueEntries.find((e) => e.session_id === sessionId) ?? queueEntries[0];
      await route.fulfill({ json: { ...match, ...body } });
    }
  });

  await page.route(`${API_BASE_URL}/fhir/generate`, async (route) => {
    await route.fulfill({ json: mockFhirBundle() });
  });
}
