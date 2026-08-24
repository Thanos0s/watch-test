/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Expose the backend URL to client-side code.
  // On Vercel: set NEXT_PUBLIC_API_BASE_URL in project env vars to your Railway URL.
  // Locally: create frontend/.env.local with NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001
  env: {
    NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8001",
  },
};

export default nextConfig;

