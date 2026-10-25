import { expect, test, type Page } from '@playwright/test'

import type { OracleDocument, SearchResult } from '../../src/api'

const DOCUMENTS: OracleDocument[] = [
  { id: 1, filename: 'annual-report-2025.pdf', status: 'ready', error: null },
  { id: 2, filename: 'meeting-notes.docx', status: 'ready', error: null },
  { id: 3, filename: 'research-paper-draft.pdf', status: 'ready', error: null },
  { id: 4, filename: 'quarterly-forecast.pdf', status: 'pending', error: null },
  { id: 5, filename: 'scanned-contract.pdf', status: 'failed', error: 'No extractable text found.' },
]

const RESULTS: SearchResult[] = [
  {
    doc_id: 1,
    filename: 'annual-report-2025.pdf',
    chunk_id: 101,
    seq: 12,
    text: 'Revenue grew 14% year over year, driven by subscription renewals and the launch of the enterprise tier.',
    page_number: 7,
    sources: ['bm25', 'vector'],
  },
  {
    doc_id: 2,
    filename: 'meeting-notes.docx',
    chunk_id: 102,
    seq: 3,
    text: 'Action items: finalize the budget, schedule the follow-up review, and circulate the revised timeline.',
    page_number: null,
    sources: ['vector'],
  },
  {
    doc_id: 3,
    filename: 'research-paper-draft.pdf',
    chunk_id: 103,
    seq: 40,
    text: 'The main limitation of this approach is its sensitivity to noisy labels in small training sets.',
    page_number: 21,
    sources: ['bm25'],
  },
]

// The Google Fonts stylesheet in index.html would otherwise decide the
// typeface by network availability; with it blocked the fallback stack renders
// the same in every run of the container.
async function mockApi(
  page: Page,
  { documents = DOCUMENTS, failList = false }: { documents?: OracleDocument[]; failList?: boolean } = {},
) {
  await page.route(/fonts\.(googleapis|gstatic)\.com/, (route) => route.abort())
  await page.route('**/api/**', (route) => {
    const { pathname } = new URL(route.request().url())
    const method = route.request().method()

    if (pathname === '/api/documents' && method === 'GET') {
      return failList
        ? route.fulfill({ status: 503, json: { detail: 'The Oracle API is unavailable.' } })
        : route.fulfill({ json: documents })
    }
    if (pathname === '/api/search' && method === 'POST') {
      return route.fulfill({ json: { results: RESULTS } })
    }
    const pending = pathname.match(/^\/api\/documents\/(\d+)$/)
    if (pending && method === 'GET') {
      return route.fulfill({ json: documents.find((d) => d.id === Number(pending[1])) })
    }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${method} ${pathname}` } })
  })
}

async function showLibrary(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Oracle' })).toBeVisible()
  await expect(page.locator('.p-progressspinner')).toBeHidden()
}

async function search(page: Page) {
  await page.getByLabel('Search query').fill('What drove revenue growth?')
  await page.getByRole('button', { name: 'Ask Oracle' }).click()
  await expect(page.getByText('Supporting excerpts (3)')).toBeVisible()
  await page.locator('.excerpt-head').first().click()
  await page.mouse.move(0, 0)
}

test('empty library', async ({ page }) => {
  await mockApi(page, { documents: [] })
  await showLibrary(page)
  await expect(page.getByText('No documents yet')).toBeVisible()
  await expect(page).toHaveScreenshot('empty-library.png')
})

test('library with ready, pending and failed documents, partly selected', async ({ page }) => {
  await mockApi(page)
  await showLibrary(page)
  await page.getByRole('row').filter({ hasText: 'research-paper-draft.pdf' }).getByRole('checkbox').uncheck()
  await page.mouse.move(0, 0)
  await expect(page).toHaveScreenshot('library-mixed-statuses.png')
})

test('search results with both sources and with and without a page number', async ({ page }) => {
  await mockApi(page)
  await showLibrary(page)
  await search(page)
  await expect(page).toHaveScreenshot('search-results.png')
})

test('search results in the dark theme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await mockApi(page)
  await showLibrary(page)
  await search(page)
  await expect(page).toHaveScreenshot('search-results-dark.png')
})

test('API error message', async ({ page }) => {
  await mockApi(page, { failList: true })
  await page.goto('/')
  await expect(page.getByText('The Oracle API is unavailable.')).toBeVisible()
  await page.mouse.move(0, 0)
  await expect(page).toHaveScreenshot('api-error.png')
})
