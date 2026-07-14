/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    const api = process.env.API_INTERNAL_URL || "http://localhost:8000";
    return [
      { source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
