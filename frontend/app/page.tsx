"use client";

import KioskUI from "@/components/KioskUI";

// KioskUI manages its own session id internally (minted fresh per mount),
// so reloading this page between patients naturally starts a new session.
export default function HomePage() {
  return <KioskUI />;
}
