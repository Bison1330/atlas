/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,

  // Same-origin proxy to the FastAPI backend. Client code calls
  // /api/... URLs; Next.js server rewrites them to INTERNAL_API_URL.
  // Keeps cookies single-origin (no SameSite=None / cross-origin
  // credentials dance). In production behind Caddy, Caddy handles
  // this routing upstream and these rewrites are redundant but
  // harmless.
  async rewrites() {
    const api = process.env.INTERNAL_API_URL ?? "http://api:8000";
    return [
      { source: "/api/:path*", destination: `${api}/:path*` },
    ];
  },
};

export default nextConfig;
