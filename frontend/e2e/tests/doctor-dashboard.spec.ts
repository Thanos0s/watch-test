import { expect, test } from "../fixtures/test-fixtures";
import { mockDoctorQueueEntry, mockNormalQueueEntry } from "../fixtures/mocks";
import { mockDoctorBackend } from "../fixtures/mockRoutes";

/**
 * E2E coverage of the doctor dashboard: app/doctor/page.tsx (queue
 * sidebar, patient selection, red-flag badges) rendering
 * components/DoctorDesk.tsx (editable summary + FHIR export) for the
 * active case.
 *
 * NOTE ON "priority": app/routes/queue.py's GET /queue/active returns
 * sessions oldest-first -- there is no separate priority score or
 * reordering by urgency in this codebase. What IS implemented, and what
 * this suite verifies, is that a red-flagged patient is visually
 * distinguished with an "URGENT" badge wherever they appear in that list.
 */

test.describe("Doctor dashboard", () => {
  test("shows an empty state when no patients are waiting", async ({ page, doctorPage }) => {
    await mockDoctorBackend(page, []);
    await doctorPage.goto("");
    await expect(doctorPage.noPatientsMessage).toBeVisible();
  });

  test("an urgent (red-flagged) patient is badged, a normal patient is not", async ({ page, doctorPage }) => {
    const urgentPatient = mockDoctorQueueEntry({
      session_id: "urgent-case",
      abha_id: "9111111111",
      trigger_red_flag: true,
      chief_complaint: "Severe chest pain",
    });
    const normalPatient = mockNormalQueueEntry({ session_id: "normal-case", abha_id: "9222222222" });

    await mockDoctorBackend(page, [urgentPatient, normalPatient]);
    await doctorPage.goto("");

    await expect(doctorPage.urgentBadgeFor("9111111111")).toBeVisible();
    await expect(doctorPage.queueEntryByAbhaId("9222222222").getByText("URGENT")).not.toBeVisible();
  });

  test("selecting a patient loads their full case into DoctorDesk", async ({ page, doctorPage }) => {
    const patient = mockDoctorQueueEntry({
      session_id: "case-detail-test",
      abha_id: "9333333333",
      chief_complaint: "Chronic digestive distress",
    });
    await mockDoctorBackend(page, [patient]);
    await doctorPage.goto("");

    await doctorPage.selectPatient("9333333333");

    await expect(page.getByText("Doctor's Review Desk")).toBeVisible();
    // getByDisplayValue is a Testing Library method, not part of
    // Playwright's own Locator API -- match the controlled <input>'s
    // current value via a CSS attribute selector instead.
    await expect(page.locator('input[value="Chronic digestive distress"]')).toBeVisible();
  });

  test("consent-not-given is shown distinctly from consent-verified", async ({ page, doctorPage }) => {
    const noConsentPatient = mockDoctorQueueEntry({
      session_id: "no-consent-case",
      abha_id: "9444444444",
      consent_given: false,
    });
    await mockDoctorBackend(page, [noConsentPatient]);
    await doctorPage.goto("");

    await doctorPage.selectPatient("9444444444");
    await expect(page.getByText("Consent Not Given")).toBeVisible();
    await expect(doctorPage.consentVerifiedBadge).not.toBeVisible();
  });

  test("escalate button only renders for red-flagged patients", async ({ page, doctorPage }) => {
    const urgentPatient = mockDoctorQueueEntry({ session_id: "escalate-test", abha_id: "9555555555", trigger_red_flag: true });
    const normalPatient = mockNormalQueueEntry({ session_id: "no-escalate-test", abha_id: "9666666666" });
    await mockDoctorBackend(page, [urgentPatient, normalPatient]);
    await doctorPage.goto("");

    await doctorPage.selectPatient("9555555555");
    await expect(doctorPage.escalateButton).toBeVisible();

    await doctorPage.selectPatient("9666666666");
    await expect(doctorPage.escalateButton).not.toBeVisible();
  });

  test("export is disabled until the doctor checks the review box, then pushes to FHIR", async ({ page, doctorPage }) => {
    const patient = mockDoctorQueueEntry({ session_id: "export-test", abha_id: "9777777777" });
    await mockDoctorBackend(page, [patient]);
    await doctorPage.goto("");

    await doctorPage.selectPatient("9777777777");
    await doctorPage.approveAndExport(); // asserts disabled -> enabled internally
    await doctorPage.expectExportSuccess();
  });

  test("clicking refresh re-fetches the queue and shows a newly seeded patient", async ({ page, doctorPage }) => {
    const initialPatient = mockDoctorQueueEntry({ session_id: "poll-before", abha_id: "9888888888" });
    await mockDoctorBackend(page, [initialPatient]);
    await doctorPage.goto("");
    await expect(doctorPage.queueEntryByAbhaId("9888888888")).toBeVisible();

    // Simulate a second patient having checked in at the kiosk since the
    // page loaded -- re-registering the route changes what the *next*
    // GET /queue/active call returns.
    const newPatient = mockDoctorQueueEntry({ session_id: "poll-after", abha_id: "9999999999" });
    await mockDoctorBackend(page, [initialPatient, newPatient]);

    await doctorPage.refreshQueue();
    await expect(doctorPage.queueEntryByAbhaId("9999999999")).toBeVisible();
  });
});
