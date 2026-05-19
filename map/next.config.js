/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';
const nextConfig = {
  output: 'export',
  basePath: isProd ? '/icechunk_github_actions_demo' : '',
  assetPrefix: isProd ? '/icechunk_github_actions_demo' : '',
  reactStrictMode: true,
  webpack: (config) => {
    config.experiments = { ...config.experiments, asyncWebAssembly: true }
    return config
  },
}

module.exports = nextConfig
