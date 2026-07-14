import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

import SearchPanel from '../src/components/SearchPanel.vue'
import { ApiError, search, type OracleDocument, type SearchResult } from '../src/api'

vi.mock('../src/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api')>()),
  search: vi.fn(),
}))

const searchMock = vi.mocked(search)

const READY: OracleDocument = { id: 1, filename: 'first.pdf', status: 'ready', error: null }

const RESULTS: SearchResult[] = [
  {
    doc_id: 1,
    filename: 'first.pdf',
    chunk_id: 10,
    seq: 0,
    text: 'the quick brown fox',
    page_number: 4,
  },
  {
    doc_id: 2,
    filename: 'second.pdf',
    chunk_id: 20,
    seq: 1,
    text: 'a slow brown bear',
    page_number: null,
  },
]

function mountPanel(selected: OracleDocument[] = []) {
  return mount(SearchPanel, {
    props: { selected },
    global: { plugins: [[PrimeVue, { theme: { preset: Aura } }]] },
  })
}

async function runSearch(wrapper: ReturnType<typeof mountPanel>, query = 'brown') {
  await wrapper.find('input').setValue(query)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  searchMock.mockReset()
})

describe('SearchPanel', () => {
  it('renders a card per result with its filename and page', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()

    await runSearch(wrapper)

    expect(searchMock).toHaveBeenCalledWith('brown')
    const cards = wrapper.findAll('.p-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('first.pdf')
    expect(cards[0].text()).toContain('page 4')
    expect(cards[0].text()).toContain('the quick brown fox')
    // The second result has no page number, so no page is claimed for it.
    expect(cards[1].text()).not.toContain('page')
  })

  it('limits results to the selected documents', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel([READY])

    await runSearch(wrapper)

    const cards = wrapper.findAll('.p-card')
    expect(cards).toHaveLength(1)
    expect(cards[0].text()).toContain('first.pdf')
  })

  it('does not search a blank query', async () => {
    const wrapper = mountPanel()

    await runSearch(wrapper, '   ')

    expect(searchMock).not.toHaveBeenCalled()
  })

  it('reports when nothing matched', async () => {
    searchMock.mockResolvedValue([])
    const wrapper = mountPanel()

    await runSearch(wrapper)

    expect(wrapper.text()).toContain('No matches found.')
  })

  it('surfaces an API failure instead of results', async () => {
    searchMock.mockRejectedValue(new ApiError('Could not reach the Oracle API.'))
    const wrapper = mountPanel()

    await runSearch(wrapper)

    expect(wrapper.text()).toContain('Could not reach the Oracle API.')
    expect(wrapper.findAll('.p-card')).toHaveLength(0)
  })
})
