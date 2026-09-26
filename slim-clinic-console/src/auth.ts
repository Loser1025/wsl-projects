import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  callbacks: {
    async signIn({ user }) {
      const allowlist = (process.env.STAFF_EMAIL_ALLOWLIST || "")
        .split(",")
        .map((e) => e.trim().toLowerCase())
        .filter(Boolean);
      if (allowlist.length === 0) return false;
      return allowlist.includes((user.email || "").toLowerCase());
    },
  },
});

export const { GET, POST } = handlers;
