import { NextResponse } from "next/server";
import { isProtectedPath } from "./lib/authPaths";

export function middleware(request) {
  const { pathname } = request.nextUrl;
  if (!isProtectedPath(pathname)) {
    return NextResponse.next();
  }
  const session = request.cookies.get("ga_session");
  if (!session?.value) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/jobs/:path*", "/fleet/:path*", "/profiles/:path*", "/annotations/:path*"],
};
