import { securityHeaders } from "./lib/securityHeaders.js";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // LAN hosts that open the Next dev server by IP (not localhost). Without these,
  // client JS/HMR is blocked and auth forms fall back to a native GET reload
  // (see FE log: GET /signup?) so signup never hits the backend.
  allowedDevOrigins: ["10.158.45.197", "192.168.86.37", "100.126.226.101"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders({ production: process.env.NODE_ENV === "production" }),
      },
    ];
  },
};

export default nextConfig;
