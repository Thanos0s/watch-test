import { expect, test } from "@playwright/test";
import { mockDoctorQueueEntry } from "../fixtures/mocks";
import { mockDoctorBackend, mockKioskBackend } from "../fixtures/mockRoutes";

/**
 * Multi-context test: a kiosk tab and a doctor-dashboard tab, each its own
 * isolated BrowserContext (separate cookies/storage, as two different
 * physical devices would be) sharing one mutable in-memory "backend" via
 * closures in this file.
 *
 * This test drives raw Playwright Pages directly (not the KioskPage /
 * DoctorDashboardPage POM classes used elsewhere in this suite) since it
 * needs two independent contexts open simultaneously with fine-grained
 * control over each -- the POM classes are still the right tool for the
 * single-context specs in patient-intake.spec.ts / doctor-dashboard.spec.ts.
 *
 * IMPORTANT ON "real-time": this codebase's doctor queue is polled, not
 * pushed -- there is no WebSocket/SSE between the kiosk and the dashboard
 * (see app/routes/queue.py). "Near real-time" here means: the moment a
 * patient completes kiosk intake, the NEXT time the doctor dashboard
 * fetches the queue (its refresh button, or selecting a patient) it sees
 * the update -- which is what this test actually exercises. It does not,
 * and should not, assert that the doctor's screen updates without any
 * fetch at all, since that behavior doesn't exist in the app.
 */

test.describe("Kiosk check-in reflected in the doctor queue", () => {
  test("a patient completing kiosk intake appears in the doctor's queue on next refresh", async ({ browser }) => {
    // In-memory "backend" state shared by both contexts' route handlers --
    // stands in for the real SQLite-backed queue for this UI-only test.
    let queue: ReturnType<typeof mockDoctorQueueEntry>[] = [];

    const kioskContext = await browser.newContext();
    const doctorContext = await browser.newContext();

    try {
      const kioskTabPage = await kioskContext.newPage();
      const doctorTabPage = await doctorContext.newPage();

      await mockKioskBackend(kioskTabPage);
      await kioskTabPage.route("**/intake/turn", async (route) => {
        // The final turn of the interview: intake completes and the kiosk
        // "hands off" this session to the doctor queue.
        await route.fulfill({
          json: {
            audio_prompt_text: "Thank you. Please wait, the doctor will see you shortly.",
            touch_options: ["Done"],
            updated_clinical_state: {
              chief_complaint: "Persistent cough",
              socrates: {
                site: null, onset: null, character: null, radiation: null,
                associations: null, timing: null, exacerbating_relieving: null, severity: null,
              },
              ayush_parameters: {
                dupshya: null, desha: null, bala: null, kala: null, anala_agni: null,
                prakriti: null, vaya: null, sattva: null, satmya: null, ahara: null,
              },
            },
            is_complete: true,
            trigger_red_flag: false,
            red_flag_reason: null,
          },
        });
        // The moment the kiosk's final turn resolves, the session becomes
        // visible to the doctor dashboard -- simulating the real backend
        // persisting it (PUT /queue/patient/{id} + a status transition)
        // without needing the real database for this UI-focused test.
        queue = [
          mockDoctorQueueEntry({
            session_id: "realtime-sync-patient",
            abha_id: "9123450000",
            chief_complaint: "Persistent cough",
          }),
        ];
      });

      // Doctor dashboard is already open, queue empty, BEFORE the patient checks in.
      await mockDoctorBackend(doctorTabPage, queue);
      await doctorTabPage.goto("http://127.0.0.1:3000/doctor");
      await expect(doctorTabPage.getByText("No patients waiting.")).toBeVisible();

      // Patient completes the kiosk flow in the other context/tab.
      await kioskTabPage.goto("http://127.0.0.1:3000/");
      await expect(kioskTabPage.getByText("Welcome to PrakritiDesk")).toBeVisible();
      await kioskTabPage.getByPlaceholder("XX-XXXX-XXXX-XXXX or mobile number").fill("9123450000");
      await kioskTabPage.getByRole("button", { name: "Continue ➜" }).click();
      await kioskTabPage.getByPlaceholder("6-digit OTP").fill("123456");
      await kioskTabPage.getByRole("button", { name: "Verify ➜" }).click();
      await kioskTabPage.getByRole("button", { name: "✅ I Agree" }).click();
      await kioskTabPage.getByRole("button", { name: /Skip for now/ }).click();
      await kioskTabPage.getByRole("button", { name: "Pain", exact: true }).click();
      await expect(kioskTabPage.getByText("Thank you!")).toBeVisible();

      // Doctor dashboard hasn't refetched yet -- still shows the stale,
      // empty queue. This is the honest state of a polled UI, not a bug.
      await expect(doctorTabPage.getByText("No patients waiting.")).toBeVisible();

      // Re-register the doctor's route with the now-updated queue (this
      // stands in for the real backend's state having changed) and click
      // refresh -- this is the "near real-time" update this system
      // actually provides.
      await mockDoctorBackend(doctorTabPage, queue);
      await doctorTabPage.getByLabel("Refresh queue").click();

      await expect(doctorTabPage.locator("aside button", { hasText: "9123450000" })).toBeVisible();
      await expect(doctorTabPage.getByText("Persistent cough")).toBeVisible();
    } finally {
      await kioskContext.close();
      await doctorContext.close();
    }
  });
});
