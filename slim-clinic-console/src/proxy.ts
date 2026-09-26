import { auth } from "@/auth";

export const proxy = auth((req) => {
  const isLoggedIn = !!req.auth;
  const { pathname } = req.nextUrl;
  
  if (!isLoggedIn && pathname !== "/login") {
    return Response.redirect(new URL("/login", req.url));
  }
  
  if (isLoggedIn && pathname === "/login") {
    return Response.redirect(new URL("/", req.url));
  }
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
