import { auth } from "@/auth";

export const proxy = auth((req) => {
  const isLoggedIn = !!req.auth;
  const { pathname } = req.nextUrl;

  if (pathname.startsWith("/api/line/webhook")) return;
  if (pathname.startsWith("/api/cron")) return;

  if (!isLoggedIn && pathname !== "/login") {
    return Response.redirect(new URL("/login", req.url));
  }

  if (isLoggedIn && pathname === "/login") {
    return Response.redirect(new URL("/", req.url));
  }
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/auth|api/line/webhook|api/cron).*)"],
};
