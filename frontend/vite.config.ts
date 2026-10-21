import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

// Same as the [api] host and port in config/default.toml.
const DEFAULT_API_PROXY_TARGET = 'http://127.0.0.1:8000';

// The dev server forwards /api to the result API, so the screen calls it from the same
// origin and the API needs no CORS. API_PROXY_TARGET has no VITE_ prefix: it stays out
// of the browser bundle. Mock mode is unaffected because MSW answers before the proxy.
export function apiProxyTarget(env: Record<string, string | undefined>): string {
  const target = env.API_PROXY_TARGET?.trim() || DEFAULT_API_PROXY_TARGET;
  let url: URL;
  try {
    url = new URL(target);
  } catch {
    throw new Error('API_PROXY_TARGET must be an http(s) URL');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('API_PROXY_TARGET must be an http(s) URL');
  }
  return url.origin;
}

// Only /api is forwarded, with its path kept: the API routes already start with /api.
export function devServerProxy(env: Record<string, string | undefined>) {
  return { '/api': { target: apiProxyTarget(env) } };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    fs: {
      allow: [
        fileURLToPath(new URL('.', import.meta.url)),
        fileURLToPath(new URL('../tests/fixtures/frontend', import.meta.url)),
      ],
    },
    proxy: devServerProxy({ ...loadEnv(mode, process.cwd(), ''), ...process.env }),
  },
  test: {
    environment: 'jsdom',
    environmentOptions: { jsdom: { url: 'http://localhost/' } },
    setupFiles: ['./src/test/setup.ts'],
    clearMocks: true,
  },
}));
