import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages can't send headers, so production builds carry their Content-Security-Policy
// in a <meta> tag. It matches the one the backend sends, plus the API's origin when the API
// is on another site. (frame-ancestors only works as a header, so it's left out.)
function contentSecurityPolicy(apiBaseUrl: string): Plugin {
  const connect = apiBaseUrl ? `'self' ${new URL(apiBaseUrl).origin}` : "'self'"
  const csp = [
    "default-src 'self'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "script-src 'self'",
    `connect-src ${connect}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
  return {
    name: 'content-security-policy',
    apply: 'build',  // the dev server injects inline scripts for hot reload
    transformIndexHtml: () => [
      { tag: 'meta', attrs: { 'http-equiv': 'Content-Security-Policy', content: csp }, injectTo: 'head-prepend' },
    ],
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), contentSecurityPolicy(loadEnv(mode, process.cwd(), '').VITE_API_BASE_URL ?? '')],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  },
}))
