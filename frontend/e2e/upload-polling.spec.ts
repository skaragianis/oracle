import { expect, test, type Page } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const LARGE_PDF = fileURLToPath(new URL('./fixtures/large.pdf', import.meta.url))
const DOCX = fileURLToPath(new URL('./fixtures/notes.docx', import.meta.url))

function row(page: Page, filename: string) {
  return page.getByRole('row').filter({ hasText: filename })
}

async function upload(page: Page, file: string) {
  await page.locator('input[type="file"]').setInputFiles(file)
}

async function arrivesPending(page: Page, filename: string) {
  let rewritten = false
  await page.route('**/api/documents', async (route, request) => {
    if (request.method() !== 'GET' || rewritten) return route.fallback()
    rewritten = true

    const response = await route.fetch()
    const documents = (await response.json()) as { filename: string }[]
    await route.fulfill({
      json: documents.map((document) =>
        document.filename === filename
          ? { ...document, status: 'pending', error: null }
          : document,
      ),
    })
  })
}

test('a pending upload becomes ready on its own, with no reload', async ({ page }) => {
  await page.goto('/')

  await upload(page, LARGE_PDF)

  await expect(row(page, 'large.pdf').getByText('pending')).toBeVisible()
  await expect(row(page, 'large.pdf').getByText('ready')).toBeVisible({ timeout: 60_000 })
})

test('the uploader clears its staging row once the upload completes', async ({ page }) => {
  await page.goto('/')

  const uploader = page.locator('.p-fileupload')
  await page.locator('input[type="file"]').setInputFiles(LARGE_PDF)
  await expect(uploader.getByText('large.pdf')).toBeVisible()

  await expect(uploader.getByText('large.pdf')).toBeHidden()
  await expect(row(page, 'large.pdf').getByText('ready')).toBeVisible({ timeout: 60_000 })
})

test('a docx upload is chunked and becomes ready, just like a PDF', async ({ page }) => {
  await page.goto('/')

  await upload(page, DOCX)

  await expect(row(page, 'notes.docx').getByText('ready')).toBeVisible({ timeout: 20_000 })
})

test('a document found pending on load is polled to completion', async ({ page }) => {
  await page.goto('/')
  await upload(page, LARGE_PDF)
  await expect(row(page, 'large.pdf').getByText('ready')).toBeVisible({ timeout: 60_000 })

  await arrivesPending(page, 'large.pdf')
  await page.reload()

  await expect(row(page, 'large.pdf').getByText('ready')).toBeVisible({ timeout: 60_000 })
})
