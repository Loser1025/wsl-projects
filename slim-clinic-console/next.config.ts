import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: "dist_next",
  serverExternalPackages: ["googleapis", "google-auth-library"],
};

export default nextConfig;
