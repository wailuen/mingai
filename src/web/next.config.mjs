/** @type {import('next').NextConfig} */
const nextConfig = {
  // Disable image optimization for external URLs in dev
  images: {
    unoptimized: true,
  },
  // Custom dev server port
  // Run with: next dev -p 3022
};

export default nextConfig;
