import { expect, Locator, Page } from "@playwright/test";

/**
 * Page Object for the doctor's OPD dashboard (app/doctor/page.tsx, which
 * renders components/DoctorDesk.tsx for the active case).
 *
 * NOTE: the queue is polled, not pushed -- there is no WebSocket/SSE in
 * this codebase. `refreshQueue()` performs the explicit refetch a real
 * doctor would trigger by clicking the refresh icon (or by the automatic
 * refetch that happens on selecting a different patient).
 */
export class DoctorDashboardPage {
  readonly page: Page;

  readonly refreshQueueButton: Locator;
  readonly noPatientsMessage: Locator;

  readonly reviewedCheckbox: Locator;
  readonly exportButton: Locator;
  readonly escalateButton: Locator;
  readonly consentVerifiedBadge: Locator;
  readonly redFlagBadge: Locator;

  constructor(page: Page) {
    this.page = page;

    this.refreshQueueButton = page.getByLabel("Refresh queue");
    this.noPatientsMessage = page.getByText("No patients waiting.");

    this.reviewedCheckbox = page.getByLabel(/I have reviewed and verified this summary/);
    this.exportButton = page.getByRole("button", { name: /Export to ABDM/ });
    this.escalateButton = page.getByRole("button", { name: /Escalate Emergency/ });
    this.consentVerifiedBadge = page.getByText("Consent Verified");
    this.redFlagBadge = page.getByText("Red Flag", { exact: true });
  }

  async goto(baseURL: string) {
    await this.page.goto(`${baseURL}/doctor`);
    await expect(this.page.getByText("Patient Queue")).toBeVisible();
  }

  /** The sidebar queue-entry button for a given ABHA ID (queue entries
   * render the ABHA ID in a monospace span; that's the stable identifier
   * to select by, since patient name can be null). */
  queueEntryByAbhaId(abhaId: string): Locator {
    return this.page.locator("aside button", { hasText: abhaId });
  }

  /** The "URGENT" badge scoped to one queue entry, so this only matches
   * when that specific patient is flagged -- not just any urgent patient
   * present elsewhere in the list. */
  urgentBadgeFor(abhaId: string): Locator {
    return this.queueEntryByAbhaId(abhaId).getByText("URGENT");
  }

  async selectPatient(abhaId: string) {
    await this.queueEntryByAbhaId(abhaId).click();
  }

  async refreshQueue() {
    await this.refreshQueueButton.click();
  }

  /** Checks the review checkbox and clicks Export -- mirrors exactly what
   * a doctor does in components/DoctorDesk.tsx before a case is pushed to
   * ABDM (the button is disabled until the checkbox is checked). */
  async approveAndExport() {
    await expect(this.exportButton).toBeDisabled();
    await this.reviewedCheckbox.check();
    await expect(this.exportButton).toBeEnabled();
    await this.exportButton.click();
  }

  async expectExportSuccess() {
    await expect(this.page.getByText("FHIR bundle generated successfully.")).toBeVisible();
  }
}
