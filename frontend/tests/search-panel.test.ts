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
    sources: ['bm25', 'vector'],
  },
  {
    doc_id: 2,
    filename: 'second.pdf',
    chunk_id: 20,
    seq: 1,
    text: 'a slow brown bear',
    page_number: null,
    sources: ['vector'],
  },
]

function mountPanel(selected: OracleDocument[] = [], documents: OracleDocument[] = [READY]) {
  return mount(SearchPanel, {
    props: { selected, documents },
    global: { plugins: [[PrimeVue, { theme: { preset: Aura } }]] },
  })
}

async function runSearch(wrapper: ReturnType<typeof mountPanel>, query = 'brown') {
  await wrapper.find('input').setValue(query)
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

const writeTextMock = vi.fn()

beforeEach(() => {
  searchMock.mockReset()
  writeTextMock.mockReset().mockResolvedValue(undefined)
  // jsdom has no navigator.clipboard; define one so the copy button is testable.
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    configurable: true,
  })
})

function copyButton(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper.findAll('button').find((button) => button.text().includes('Cop'))
}

function excerptHeads(wrapper: ReturnType<typeof mountPanel>) {
  return wrapper.findAll('.excerpt-head')
}

describe('SearchPanel', () => {
  it('renders a card per result with its filename and page', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()

    await runSearch(wrapper)

    expect(searchMock).toHaveBeenCalledWith('brown', ['bm25', 'vector'])
    const cards = wrapper.findAll('.p-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].text()).toContain('first.pdf')
    expect(cards[0].text()).toContain('page 4')
    // The second result has no page number, so no page is claimed for it.
    expect(cards[1].text()).not.toContain('page')

    // The snippet itself is collapsed until the excerpt is expanded.
    expect(cards[0].text()).not.toContain('the quick brown fox')
    await excerptHeads(wrapper)[0].trigger('click')
    expect(wrapper.findAll('.p-card')[0].text()).toContain('the quick brown fox')
  })

  it('collapses an expanded excerpt again on a second click', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()
    await runSearch(wrapper)

    const head = excerptHeads(wrapper)[0]
    await head.trigger('click')
    expect(wrapper.findAll('.p-card')[0].text()).toContain('the quick brown fox')

    await head.trigger('click')
    expect(wrapper.findAll('.p-card')[0].text()).not.toContain('the quick brown fox')
  })

  it('starts every excerpt collapsed again on a new search, even with identical results', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()
    await runSearch(wrapper)

    await excerptHeads(wrapper)[0].trigger('click')
    expect(wrapper.findAll('.p-card')[0].text()).toContain('the quick brown fox')

    // Same query, same results returned again.
    await runSearch(wrapper)

    expect(wrapper.findAll('.p-card')[0].text()).not.toContain('the quick brown fox')
  })

  it('labels each result with the indexes that returned it', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()

    await runSearch(wrapper)

    const cards = wrapper.findAll('.p-card')
    // The first result was fused from both indexes, so it carries both tags.
    expect(cards[0].findAll('.p-tag').map((tag) => tag.text())).toEqual(['BM25', 'Vector'])
    expect(cards[1].findAll('.p-tag').map((tag) => tag.text())).toEqual(['Vector'])
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

  it('shows no copy button until results are available', async () => {
    searchMock.mockResolvedValue([])
    const wrapper = mountPanel()
    expect(copyButton(wrapper)).toBeUndefined()

    await runSearch(wrapper)

    // An empty result set has nothing worth pasting into an LLM either.
    expect(copyButton(wrapper)).toBeUndefined()
  })

  it('copies the question and every visible result for an LLM', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()
    await runSearch(wrapper, 'brown animals')

    await copyButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(writeTextMock).toHaveBeenCalledTimes(1)
    const copied = writeTextMock.mock.calls[0][0] as string
    expect(copied).toContain('Question: brown animals')
    expect(copied).toContain('[1] (first.pdf, p. 4)')
    expect(copied).toContain('the quick brown fox')
    expect(copied).toContain('[2] (second.pdf)')
    expect(copied).toContain('a slow brown bear')
    expect(copyButton(wrapper)!.text()).toContain('Copied')
  })

  it('copies the submitted question even after the input is edited', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()
    await runSearch(wrapper, 'brown animals')

    await wrapper.find('input').setValue('something else entirely')
    await copyButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(writeTextMock.mock.calls[0][0]).toContain('Question: brown animals')
  })

  it('copies only the results scoped to the selected documents', async () => {
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel([READY])
    await runSearch(wrapper)

    await copyButton(wrapper)!.trigger('click')
    await flushPromises()

    const copied = writeTextMock.mock.calls[0][0] as string
    expect(copied).toContain('first.pdf')
    expect(copied).not.toContain('second.pdf')
  })

  it('reports a clipboard failure', async () => {
    writeTextMock.mockRejectedValue(new Error('denied'))
    searchMock.mockResolvedValue(RESULTS)
    const wrapper = mountPanel()
    await runSearch(wrapper)

    await copyButton(wrapper)!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Could not copy to the clipboard.')
    expect(copyButton(wrapper)!.text()).not.toContain('Copied')
  })

  it('surfaces an API failure instead of results', async () => {
    searchMock.mockRejectedValue(new ApiError('Could not reach the Oracle API.'))
    const wrapper = mountPanel()

    await runSearch(wrapper)

    expect(wrapper.text()).toContain('Could not reach the Oracle API.')
    expect(wrapper.findAll('.p-card')).toHaveLength(0)
  })
})

describe('source selection', () => {
  function sourceCheckboxes(wrapper: ReturnType<typeof mountPanel>) {
    return wrapper.findAll('input.p-checkbox-input')
  }

  it('renders a checkbox for each source, both checked by default', async () => {
    const wrapper = mountPanel()

    const checkboxes = sourceCheckboxes(wrapper)
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes.every((checkbox) => (checkbox.element as HTMLInputElement).checked)).toBe(
      true,
    )
    expect(wrapper.text()).toContain('BM25')
    expect(wrapper.text()).toContain('Vector')
  })

  it('disables the Ask button when both sources are unchecked', async () => {
    searchMock.mockResolvedValue([])
    const wrapper = mountPanel()
    await wrapper.find('input').setValue('brown')

    const [bm25, vector] = sourceCheckboxes(wrapper)
    await bm25.setValue(false)
    await vector.setValue(false)

    expect(wrapper.find('.ask-button').attributes('disabled')).toBeDefined()

    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(searchMock).not.toHaveBeenCalled()
  })

  it('sends only the checked sources to search', async () => {
    searchMock.mockResolvedValue([])
    const wrapper = mountPanel()
    const [bm25] = sourceCheckboxes(wrapper)
    await bm25.setValue(false)

    await runSearch(wrapper)

    expect(searchMock).toHaveBeenCalledWith('brown', ['vector'])
  })
})
