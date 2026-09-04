import type { NextConfig } from "next";

// /api/* forwarding to the backend lives in proxy.ts, not here. rewrites()
// is resolved once at `next build` time into a static routes-manifest.json
// - it can't read BACKEND_URL at container-runtime, only at build-time,
// which breaks the "one image, per-environment BACKEND_URL" design this
// project relies on. proxy.ts runs as real code per-request instead.
const nextConfig: NextConfig = {
  // Produces .next/standalone - a minimal, self-contained server bundle
  // for the Docker image, with only the required node_modules copied in.
  output: "standalone",
};

export default nextConfig;
