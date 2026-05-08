/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8080";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backend.replace(/\/$/, "")}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
