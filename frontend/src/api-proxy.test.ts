import { expect, it } from 'vitest';
import { apiProxyTarget, devServerProxy } from '../vite.config';

it('forwards /api to the result API default address when API_PROXY_TARGET is empty', () => {
  expect(apiProxyTarget({})).toBe('http://127.0.0.1:8000');
  expect(apiProxyTarget({ API_PROXY_TARGET: '  ' })).toBe('http://127.0.0.1:8000');
});

it('takes the proxy target from API_PROXY_TARGET', () => {
  expect(apiProxyTarget({ API_PROXY_TARGET: 'http://127.0.0.1:8100' })).toBe(
    'http://127.0.0.1:8100',
  );
});

it.each(['not a url', 'ftp://127.0.0.1:8000'])('refuses API_PROXY_TARGET=%s', (target) => {
  expect(() => apiProxyTarget({ API_PROXY_TARGET: target })).toThrow(
    'API_PROXY_TARGET must be an http(s) URL',
  );
});

it('proxies only /api and keeps the path, so the API is called from the same origin', () => {
  expect(devServerProxy({ API_PROXY_TARGET: 'http://127.0.0.1:8100' })).toEqual({
    '/api': { target: 'http://127.0.0.1:8100' },
  });
});
