<script setup lang="ts">
import { computed, ref } from 'vue'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import Tag from 'primevue/tag'

import {
  ApiError,
  search,
  type OracleDocument,
  type SearchResult,
  type SearchSource,
} from '../api'

const SOURCE_LABELS: Record<SearchSource, string> = {
  bm25: 'BM25',
  vector: 'Vector',
}

const COPIED_FEEDBACK_MS = 2_000

const props = defineProps<{ selected: OracleDocument[] }>()

const query = ref('')
const searching = ref(false)
const error = ref<string | null>(null)
const results = ref<SearchResult[] | null>(null)
// The submitted question, not the live input: the user can edit the box after
// searching, and the copied text must match the results actually shown.
const submittedQuery = ref('')
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | undefined

const canSearch = computed(() => query.value.trim().length > 0 && !searching.value)

/**
 * The API searches every document, so scoping to the checked rows happens here.
 * An empty selection means "search everything" rather than "search nothing",
 * which would make the page look broken before you've picked anything.
 */
const scopedResults = computed(() => {
  if (results.value === null) return null
  if (props.selected.length === 0) return results.value
  const selectedIds = new Set(props.selected.map((document) => document.id))
  return results.value.filter((result) => selectedIds.has(result.doc_id))
})

async function runSearch() {
  if (!canSearch.value) return

  searching.value = true
  error.value = null
  copied.value = false
  try {
    results.value = await search(query.value)
    submittedQuery.value = query.value.trim()
  } catch (exception) {
    results.value = null
    error.value =
      exception instanceof ApiError ? exception.message : 'Something went wrong searching.'
  } finally {
    searching.value = false
  }
}

function formatForLlm(question: string, searchResults: SearchResult[]): string {
  const blocks = searchResults.map((result, index) => {
    const page = result.page_number !== null ? `, page ${result.page_number}` : ''
    const sources = result.sources.join(', ')
    const header = `--- Result ${index + 1}: ${result.filename}${page} (found by: ${sources}) ---`
    return `${header}\n${result.text.trim()}`
  })
  return [
    'I searched my documents for the question below. Answer it using the search results.',
    `Question: ${question}`,
    'Search results:',
    ...blocks,
  ].join('\n\n')
}

async function copyForLlm() {
  if (!scopedResults.value?.length) return
  try {
    await navigator.clipboard.writeText(
      formatForLlm(submittedQuery.value, scopedResults.value),
    )
  } catch {
    error.value = 'Could not copy to the clipboard.'
    return
  }
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => (copied.value = false), COPIED_FEEDBACK_MS)
}
</script>

<template>
  <section>
    <form class="search-bar" @submit.prevent="runSearch">
      <InputText
        v-model="query"
        placeholder="Search your documents…"
        aria-label="Search query"
        fluid
      />
      <Button type="submit" label="Search" icon="pi pi-search" :disabled="!canSearch" />
    </form>

    <p v-if="selected.length" class="search-scope">
      Searching {{ selected.length }} selected document<span v-if="selected.length > 1">s</span>.
    </p>

    <div v-if="!searching && scopedResults?.length" class="copy-bar">
      <Button
        :label="copied ? 'Copied' : 'Copy question & results for an LLM'"
        :icon="copied ? 'pi pi-check' : 'pi pi-copy'"
        severity="secondary"
        outlined
        size="small"
        @click="copyForLlm"
      />
    </div>

    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>

    <div v-if="searching" class="search-loading">
      <ProgressSpinner style="width: 2.5rem; height: 2.5rem" aria-label="Searching" />
    </div>

    <template v-else-if="scopedResults">
      <p v-if="scopedResults.length === 0" class="search-empty">No matches found.</p>

      <ol v-else class="results">
        <li v-for="result in scopedResults" :key="result.chunk_id">
          <Card>
            <template #subtitle>
              <span class="result-subtitle">
                <Tag
                  v-for="source in result.sources"
                  :key="source"
                  :value="SOURCE_LABELS[source]"
                  :severity="source === 'bm25' ? 'secondary' : 'info'"
                />
                {{ result.filename }}
                <span v-if="result.page_number !== null">— page {{ result.page_number }}</span>
              </span>
            </template>
            <template #content>
              <p class="snippet">{{ result.text }}</p>
            </template>
          </Card>
        </li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.search-bar {
  display: flex;
  gap: 0.5rem;
}

.search-scope,
.search-empty {
  color: var(--p-text-muted-color);
}

.copy-bar {
  margin-top: 0.75rem;
}

.search-loading {
  display: flex;
  justify-content: center;
  padding: 2rem;
}

.results {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin: 1rem 0 0;
  padding: 0;
  list-style: none;
}

.result-subtitle {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}

.snippet {
  margin: 0;
  white-space: pre-wrap;
}
</style>
