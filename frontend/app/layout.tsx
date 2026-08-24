import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter is chosen for kiosk legibility: a tall x-height and clear
// digit/letter distinction at the large sizes used throughout
// components/KioskUI.tsx, DoctorDesk.tsx, and app/doctor/page.tsx.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PrakritiDesk",
  description: "OPD kiosk: conversational clinical intake, prescription OCR, and FHIR/ABDM export.",
};

// Locks the viewport for a fixed touch-screen kiosk terminal -- pinch-zoom
// and arbitrary scaling are appropriate for a personal device, not a
// walk-up kiosk where every screen is hand-tuned for one fixed size.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  themeColor: "#020617",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen bg-slate-950 font-sans text-slate-100 antialiased">{children}</body>
    </html>
  );
}
