import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

import App from '../src/App.vue'
import { listDocuments, waitForDocument, type OracleDocument } from '../src/api'

vi.mock('../src/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api')>()),
  listDocuments: vi.fn(),
  waitForDocument: vi.fn(),
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
  filename: 'notes.docx',
  status: 'failed',
  error: 'Cannot chunk .docx documents yet, so this file is not searchable.',
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
    expect(wrapper.text()).toContain('Cannot chunk .docx documents yet')
  })

  it('does not poll documents that already have a terminal status', async () => {
    vi.mocked(listDocuments).mockResolvedValue([READY, FAILED])

    mountApp()
    await flushPromises()

    expect(waitForDocument).not.toHaveBeenCalled()
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
