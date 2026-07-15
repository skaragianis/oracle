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

const props = defineProps<{ selected: OracleDocument[] }>()

const query = ref('')
const searching = ref(false)
const error = ref<string | null>(null)
const results = ref<SearchResult[] | null>(null)

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
  try {
    results.value = await search(query.value)
  } catch (exception) {
    results.value = null
    error.value =
      exception instanceof ApiError ? exception.message : 'Something went wrong searching.'
  } finally {
    searching.value = false
  }
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
