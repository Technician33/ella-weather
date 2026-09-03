import type { NextConfig } from "next";

// Server-only env var - never exposed to the browser. Locally this defaults
// to the FastAPI dev server; in Docker Compose it's set to the backend
// service's name on the compose network (e.g. http://backend:8000). The
// browser only ever talks to this Next.js origin via /api/*.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
