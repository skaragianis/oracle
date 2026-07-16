import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

import App from '../src/App.vue'
import {
  ApiError,
  deleteDocument,
  listDocuments,
  waitForDocument,
  type OracleDocument,
} from '../src/api'

vi.mock('../src/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api')>()),
  listDocuments: vi.fn(),
  waitForDocument: vi.fn(),
  deleteDocument: vi.fn(),
}))

const PENDING: OracleDocument = {
  id: 1,
  filename: 'slow.pdf',
  status: 'pending',
  error: null,
}
const READY: OracleDocument = { ...PENDING, status: 'ready' }
const FAILED: OracleDocument = {
  ...PENDING,
  filename: 'notes.rtf',
  status: 'failed',
  error: 'Cannot chunk .rtf documents yet, so this file is not searchable.',
}

function mountApp() {
  return mount(App, { global: { plugins: [[PrimeVue, { theme: { preset: Aura } }]] } })
}

function statuses(wrapper: ReturnType<typeof mountApp>) {
  return wrapper.findAll('.p-tag').map((tag) => tag.text())
}

beforeEach(() => {
  vi.mocked(listDocuments).mockReset()
  vi.mocked(waitForDocument).mockReset()
  vi.mocked(deleteDocument).mockReset()
})

describe('App', () => {
  it('polls a pending document and shows the status it settles on', async () => {
    vi.mocked(listDocuments).mockResolvedValue([PENDING])
    vi.mocked(waitForDocument).mockResolvedValue(READY)

    const wrapper = mountApp()
    await flushPromises()

    expect(vi.mocked(waitForDocument).mock.calls[0][0]).toBe(PENDING.id)
    expect(statuses(wrapper)).toEqual(['ready'])
  })

  it('shows the reason when a polled document fails', async () => {
    vi.mocked(listDocuments).mockResolvedValue([{ ...FAILED, status: 'pending' }])
    vi.mocked(waitForDocument).mockResolvedValue(FAILED)

    const wrapper = mountApp()
    await flushPromises()

    expect(statuses(wrapper)).toEqual(['failed'])
    expect(wrapper.text()).toContain('Cannot chunk .rtf documents yet')
  })

  it('does not poll documents that already have a terminal status', async () => {
    vi.mocked(listDocuments).mockResolvedValue([READY, FAILED])

    mountApp()
    await flushPromises()

    expect(waitForDocument).not.toHaveBeenCalled()
  })

  it('does not surface an error when a document is deleted mid-poll', async () => {
    vi.mocked(listDocuments)
      .mockResolvedValueOnce([PENDING])
      .mockResolvedValueOnce([])
    let rejectPoll: (error: unknown) => void = () => {}
    vi.mocked(waitForDocument).mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectPoll = reject
      }),
    )
    vi.mocked(deleteDocument).mockResolvedValue(undefined)

    const wrapper = mountApp()
    await flushPromises()

    await wrapper.find('tbody button').trigger('click')
    await flushPromises()

    // The still-running poll for the now-deleted document catches up and 404s.
    rejectPoll(new ApiError('Document not found'))
    await flushPromises()

    expect(wrapper.find('.p-message').exists()).toBe(false)
  })

  it('stops polling when the view goes away', async () => {
    vi.mocked(listDocuments).mockResolvedValue([PENDING])
    vi.mocked(waitForDocument).mockReturnValue(new Promise(() => {}))

    const wrapper = mountApp()
    await flushPromises()
    const signal = vi.mocked(waitForDocument).mock.calls[0][1]?.signal
    expect(signal?.aborted).toBe(false)

    wrapper.unmount()

    expect(signal?.aborted).toBe(true)
  })
})
