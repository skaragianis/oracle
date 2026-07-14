import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

import DocumentTable from '../src/components/DocumentTable.vue'
import type { OracleDocument } from '../src/api'

const READY: OracleDocument = { id: 1, filename: 'ready.pdf', status: 'ready', error: null }
const PENDING: OracleDocument = {
  id: 2,
  filename: 'pending.docx',
  status: 'pending',
  error: null,
}

function mountTable(documents = [READY, PENDING], loading = false) {
  return mount(DocumentTable, {
    props: { documents, loading, selection: [], 'onUpdate:selection': () => {} },
    global: { plugins: [[PrimeVue, { theme: { preset: Aura } }]] },
  })
}

/** The latest value the table pushed back through v-model:selection. */
function latestSelection(wrapper: ReturnType<typeof mountTable>) {
  const emitted = wrapper.emitted('update:selection')
  return emitted?.[emitted.length - 1]?.[0]
}

describe('DocumentTable', () => {
  it('shows a spinner instead of the table while loading', () => {
    const wrapper = mountTable([], true)

    expect(wrapper.find('.p-progressspinner').exists()).toBe(true)
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('renders a status tag for each document', () => {
    const wrapper = mountTable()

    expect(wrapper.findAll('.p-tag').map((tag) => tag.text())).toEqual(['ready', 'pending'])
  })

  it('selects a ready document when its checkbox is checked', async () => {
    const wrapper = mountTable()

    await wrapper.findAll('tbody input.p-checkbox-input')[0].trigger('change')

    expect(latestSelection(wrapper)).toEqual([READY])
  })

  it('keeps a document that is not ready out of the selection', async () => {
    const wrapper = mountTable()

    await wrapper.findAll('tbody input.p-checkbox-input')[1].trigger('change')

    // Either nothing was emitted, or it was emitted without the unready row.
    expect(latestSelection(wrapper) ?? []).toEqual([])
  })

  it('marks rows that are not ready as unavailable', () => {
    const wrapper = mountTable()

    const rows = wrapper.findAll('tbody tr')
    expect(rows[0].classes()).not.toContain('row-unavailable')
    expect(rows[1].classes()).toContain('row-unavailable')
  })

  it('select-all picks up only the ready documents', async () => {
    const wrapper = mountTable()

    await wrapper.find('thead input.p-checkbox-input').trigger('change')

    expect(latestSelection(wrapper)).toEqual([READY])
  })

  it('shows why a failed document is not searchable', () => {
    const failed: OracleDocument = {
      id: 3,
      filename: 'notes.docx',
      status: 'failed',
      error: 'Cannot chunk .docx documents yet, so this file is not searchable.',
    }

    const wrapper = mountTable([failed])

    expect(wrapper.text()).toContain('Cannot chunk .docx documents yet')
    expect(wrapper.find('.p-tag').text()).toBe('failed')
  })
})
