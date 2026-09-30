import { NextResponse } from "next/server";
import { isProtectedPath, loginPathFor } from "./lib/authPaths";

export function middleware(request) {
  const { pathname, search } = request.nextUrl;
  if (!isProtectedPath(pathname)) {
    return NextResponse.next();
  }
  const session = request.cookies.get("ga_session");
  if (!session?.value) {
    return NextResponse.redirect(new URL(loginPathFor(`${pathname}${search}`), request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/jobs/:path*",
    "/fleet/:path*",
    "/profiles/:path*",
    "/annotations/:path*",
    "/admin/:path*",
  ],
};
