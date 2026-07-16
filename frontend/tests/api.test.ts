import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  deleteDocument,
  listDocuments,
  search,
  uploadDocument,
  waitForDocument,
} from '../src/api'

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

  it('deletes a document with a DELETE request and no body to parse', async () => {
    const fetchMock = mockFetch({ status: 204, json: async () => { throw new Error('no body') } })

    await deleteDocument(1)

    expect(fetchMock.mock.calls[0]).toEqual(['/api/documents/1', { method: 'DELETE' }])
  })
})

describe('waitForDocument', () => {
  const document = (status: string, error: string | null = null) => ({
    id: 1,
    filename: 'a.pdf',
    status,
    error,
  })

  function mockFetchSequence(bodies: unknown[]) {
    const fetchMock = vi.fn()
    for (const body of bodies) {
      fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => body })
    }
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  it('polls until the document is ready', async () => {
    vi.useFakeTimers()
    const fetchMock = mockFetchSequence([
      document('pending'),
      document('pending'),
      document('ready'),
    ])

    const settled = waitForDocument(1)
    await vi.runAllTimersAsync()

    expect(await settled).toEqual(document('ready'))
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/1')
    vi.useRealTimers()
  })

  it('resolves with a failed document rather than throwing', async () => {
    vi.useFakeTimers()
    mockFetchSequence([document('pending'), document('failed', 'Cannot chunk .rtf yet.')])

    const settled = waitForDocument(1)
    await vi.runAllTimersAsync()

    expect((await settled).error).toBe('Cannot chunk .rtf yet.')
    vi.useRealTimers()
  })

  it('backs off instead of hammering the API', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => document('pending'),
    })
    vi.stubGlobal('fetch', fetchMock)

    const settled = waitForDocument(1)
    settled.catch(() => {})
    await vi.advanceTimersByTimeAsync(10_000)

    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(6)
    vi.useRealTimers()
  })

  it('gives up rather than polling forever', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => document('pending'),
      }),
    )

    const settled = waitForDocument(1)
    const outcome = settled.catch((exception) => exception)
    await vi.runAllTimersAsync()

    expect(await outcome).toBeInstanceOf(ApiError)
    vi.useRealTimers()
  })

  it('stops polling when aborted', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => document('pending'),
    })
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()

    const settled = waitForDocument(1, { signal: controller.signal })
    const outcome = settled.catch((exception) => exception)
    await vi.advanceTimersByTimeAsync(600)
    const callsBeforeAbort = fetchMock.mock.calls.length
    controller.abort()
    await vi.advanceTimersByTimeAsync(60_000)

    expect((await outcome).name).toBe('AbortError')
    expect(fetchMock.mock.calls.length).toBe(callsBeforeAbort)
    vi.useRealTimers()
  })
})
