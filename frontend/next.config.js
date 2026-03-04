/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable static export for GitHub Pages deployment
  // output: 'export',
  
  // For Vercel deployment
  reactStrictMode: true,
  
  // Image optimization
  images: {
    unoptimized: true,
  },
  
  // Allow fetching from GitHub raw
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=300, stale-while-revalidate=600',
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
