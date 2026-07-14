/**
 * Relative by default, so the API is same-origin with the page: Vite proxies
 * /api to the backend in dev, and a reverse proxy does the same in production.
 * That keeps any host out of the bundle, which matters because Vite inlines
 * this at build time — a built bundle cannot be repointed at runtime.
 *
 * Set VITE_API_BASE_URL to an absolute origin only when the API genuinely lives
 * somewhere else; that is cross-origin and needs CORS on the server.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export type DocumentStatus = 'pending' | 'ready' | 'failed'

export interface OracleDocument {
  id: number
  filename: string
  status: DocumentStatus
}

export interface UploadResult {
  id: number
  filename: string
  replaced: boolean
  status: DocumentStatus
}

export interface SearchResult {
  doc_id: number
  filename: string
  chunk_id: number
  seq: number
  text: string
  page_number: number | null
}

export class ApiError extends Error { }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init)
  } catch {
    throw new ApiError('Could not reach the Oracle API.')
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => null)
    throw new ApiError(
      typeof detail === 'string' ? detail : `Request failed (${response.status}).`,
    )
  }

  return response.json() as Promise<T>
}

export function listDocuments(): Promise<OracleDocument[]> {
  return request<OracleDocument[]>('/documents')
}

export function uploadDocument(file: File): Promise<UploadResult> {
  const body = new FormData()
  body.append('file', file)
  return request<UploadResult>('/documents', { method: 'POST', body })
}

export function search(query: string): Promise<SearchResult[]> {
  return request<{ results: SearchResult[] }>('/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  }).then((body) => body.results)
}
