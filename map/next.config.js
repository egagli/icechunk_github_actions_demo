/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: '/icechunk_github_actions_demo',
  assetPrefix: '/icechunk_github_actions_demo',
  reactStrictMode: true,
  webpack: (config) => {
    config.experiments = { ...config.experiments, asyncWebAssembly: true }
    return config
  },
}

module.exports = nextConfig
