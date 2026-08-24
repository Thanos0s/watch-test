/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./app/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        // High-contrast kiosk palette (see frontend/components/KioskUI.tsx,
        // DoctorDesk.tsx, SmartwatchBridge.tsx for usage).
        "ayush-green": {
          light: "#4ade80",
          DEFAULT: "#16a34a",
          dark: "#15803d",
        },
        "warning-yellow": {
          light: "#facc15",
          DEFAULT: "#eab308",
          dark: "#a16207",
        },
        "alert-red": {
          light: "#f87171",
          DEFAULT: "#dc2626",
          dark: "#991b1b",
        },
      },
    },
  },
  plugins: [],
};
