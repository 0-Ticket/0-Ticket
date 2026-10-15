import { config } from '../config';
import type { ErrorCode } from './types';

export class ApiError extends Error {
  constructor(
    public readonly code: ErrorCode,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isApiErrorBody(body: unknown): body is { error: { code: ErrorCode; message: string } } {
  if (!body || typeof body !== 'object' || !('error' in body)) return false;
  const error = body.error;
  return (
    !!error &&
    typeof error === 'object' &&
    'code' in error &&
    'message' in error &&
    ['not_found', 'invalid_input', 'conflict', 'internal'].includes(String(error.code)) &&
    typeof error.message === 'string'
  );
}

function isAbortError(error: unknown): boolean {
  // Check the name rather than instanceof: errors may come from another realm.
  return (
    typeof error === 'object' && error !== null && 'name' in error && error.name === 'AbortError'
  );
}

export async function request<T>(
  path: string,
  options: {
    method?: 'GET' | 'POST' | 'PATCH';
    query?: object;
    body?: unknown;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const base = new URL(config.apiBaseUrl.replace(/\/$/, '') + '/', window.location.origin);
  const url = new URL(path.replace(/^\//, ''), base);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers: {
        Accept: 'application/json',
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted || isAbortError(error)) throw error;
    throw new ApiError('internal', 'API 연결에 실패했습니다.', 0);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError('internal', 'API 응답을 읽을 수 없습니다.', response.status);
  }
  if (!response.ok) {
    if (isApiErrorBody(body))
      throw new ApiError(body.error.code, body.error.message, response.status);
    throw new ApiError('internal', 'API 요청에 실패했습니다.', response.status);
  }
  // Runtime domain validation belongs to soc.contracts on the server.
  return body as T;
}
