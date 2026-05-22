/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8001/api/:path*",
      },
      {
        source: "/ws/:path*",
        destination: "http://localhost:8001/ws/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
