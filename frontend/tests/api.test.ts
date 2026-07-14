import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, listDocuments, search, uploadDocument } from '../src/api'

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api', () => {
  it('lists documents', async () => {
    const documents = [{ id: 1, filename: 'a.pdf', status: 'ready' }]
    mockFetch({ json: async () => documents })

    expect(await listDocuments()).toEqual(documents)
  })

  it('calls the API on the page origin so no backend host is baked in', async () => {
    const fetchMock = mockFetch({ json: async () => [] })

    await listDocuments()

    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents')
  })

  it('posts an upload as multipart form data under the "file" field', async () => {
    const fetchMock = mockFetch({ json: async () => ({ id: 1, filename: 'a.pdf', replaced: false }) })
    const file = new File(['contents'], 'a.pdf', { type: 'application/pdf' })

    await uploadDocument(file)

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
    expect((init.body as FormData).get('file')).toBe(file)
  })

  it('unwraps the results array from a search', async () => {
    const results = [
      { doc_id: 1, filename: 'a.pdf', chunk_id: 1, seq: 0, text: 'hit', page_number: 2 },
    ]
    mockFetch({ json: async () => ({ results }) })

    expect(await search('hit')).toEqual(results)
  })

  it("raises the API's detail message on a failed request", async () => {
    mockFetch({
      ok: false,
      status: 415,
      json: async () => ({ detail: "Unsupported file type '.txt'" }),
    })
    const file = new File(['contents'], 'notes.txt', { type: 'text/plain' })

    await expect(uploadDocument(file)).rejects.toThrow(new ApiError("Unsupported file type '.txt'"))
  })

  it('raises a readable error when the API is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await expect(listDocuments()).rejects.toThrow(ApiError)
  })
})
