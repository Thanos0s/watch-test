import { test as base } from "@playwright/test";
import { DoctorDashboardPage } from "../pages/DoctorDashboardPage";
import { KioskPage } from "../pages/KioskPage";

/**
 * Extends Playwright's base `test` with ready-to-use Page Object instances,
 * so spec files never construct `new KioskPage(page)` themselves --
 * matches the Page Object Model + fixture-driven setup requested.
 */
export const test = base.extend<{
  kioskPage: KioskPage;
  doctorPage: DoctorDashboardPage;
}>({
  kioskPage: async ({ page }, use) => {
    await use(new KioskPage(page));
  },
  doctorPage: async ({ page }, use) => {
    await use(new DoctorDashboardPage(page));
  },
});

export { expect } from "@playwright/test";
