import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Unlike next.config.ts's rewrites() - which is resolved once at `next
// build` time into a static routes-manifest.json, baking in whatever
// BACKEND_URL happened to be set at build time - this runs as real code on
// every request the running server actually handles, so BACKEND_URL here
// is read at genuine container-runtime, not build-time.
export function proxy(request: NextRequest) {
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
  const { pathname, search } = request.nextUrl;
  const destination = new URL(pathname.replace(/^\/api/, "") + search, backendUrl);
  return NextResponse.rewrite(destination);
}

export const config = {
  matcher: "/api/:path*",
};
