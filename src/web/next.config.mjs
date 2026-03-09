/** @type {import('next').NextConfig} */

// connect-src includes the runtime API URL if set via NEXT_PUBLIC_API_URL,
// plus the localhost fallback for local dev.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8022";
// Derive ws:// equivalent for SSE / WebSocket connections on the same host.
const apiWs = apiUrl.replace(/^http/, "ws");

// SECURITY NOTE (GAP-002 Phase 1):
// Next.js 14 runtime hydration requires 'unsafe-inline' in style-src.
// 'unsafe-eval' is only required in development mode (hot-reload, source maps).
// SECURITY DEBT: Migrate script-src to nonce-based CSP via Next.js middleware
// to eliminate 'unsafe-inline' for scripts. Target: Phase 2 security hardening.
// Ref: https://nextjs.org/docs/app/building-your-application/configuring/content-security-policy
const isDev = process.env.NODE_ENV === "development";

const cspDirectives = [
  "default-src 'self'",
  // 'unsafe-inline' required by Next.js for inline event handlers during hydration.
  // 'unsafe-eval' removed in production; only needed for dev hot-reload.
  isDev
    ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
    : "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${apiUrl} ${apiWs} http://localhost:8022 ws://localhost:8022`,
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: cspDirectives,
  },
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
];

const nextConfig = {
  // Standalone output for Docker — copies only the required files for production
  output: "standalone",
  // Disable image optimization for external URLs in dev
  images: {
    unoptimized: true,
  },
  // Custom dev server port
  // Run with: next dev -p 3022

  // GAP-002: HTTP security headers applied to all routes
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
