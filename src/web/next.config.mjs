/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output for Docker — copies only the required files for production
  output: "standalone",
  // Disable image optimization for external URLs in dev
  images: {
    unoptimized: true,
  },
  // Custom dev server port
  // Run with: next dev -p 3022
};

export default nextConfig;
