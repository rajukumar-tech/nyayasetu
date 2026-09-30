import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // no on-screen development badge (it overlapped page content); build/runtime errors are still shown
  devIndicators: false,
  // hardening for a deployed site: no framing (clickjacking), no MIME sniffing, no referrer leaking prisoner URLs,
  // and no access to camera/microphone/location
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
      ],
    }];
  },
};

export default nextConfig;
