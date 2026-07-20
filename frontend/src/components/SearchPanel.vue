<script setup lang="ts">
import { computed, ref } from 'vue'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Checkbox from 'primevue/checkbox'
import Message from 'primevue/message'
import Tag from 'primevue/tag'

import {
  ApiError,
  DEFAULT_SEARCH_SOURCES,
  search,
  type OracleDocument,
  type SearchResult,
  type SearchSource,
} from '../api'
import { buildLlmPrompt } from '../llmPrompt'
import { copyText } from '../clipboard'

const SOURCE_LABELS: Record<SearchSource, string> = {
  bm25: 'BM25',
  vector: 'Vector',
}

const SOURCE_OPTIONS = Object.keys(SOURCE_LABELS) as SearchSource[]

const EXAMPLE_PROMPTS = [
  'Summarize the key points',
  'What are the main risks or limitations?',
  'Compare the approaches described',
]

const COPIED_FEEDBACK_MS = 2_000

const props = defineProps<{ selected: OracleDocument[]; documents: OracleDocument[] }>()

const query = ref('')
const selectedSources = ref<SearchSource[]>([...DEFAULT_SEARCH_SOURCES])
const searching = ref(false)
const error = ref<string | null>(null)
const results = ref<SearchResult[] | null>(null)
// The submitted question, not the live input: the user can edit the box after
// searching, and the copied text must match the results actually shown.
const submittedQuery = ref('')
const copied = ref(false)
let copiedTimer: ReturnType<typeof setTimeout> | undefined
// Keyed by chunk_id. Cleared on every search so excerpts always start
// collapsed, even when the same chunks come back again.
const expandedIds = ref<Set<number>>(new Set())

const canSearch = computed(
  () =>
    query.value.trim().length > 0 &&
    selectedSources.value.length > 0 &&
    props.selected.length > 0 &&
    !searching.value,
)

const readyCount = computed(
  () => props.documents.filter((document) => document.status === 'ready').length,
)
const processingCount = computed(
  () => props.documents.filter((document) => document.status === 'pending').length,
)
const selectedReadyCount = computed(() => props.selected.length)
const excludedNote = computed(() =>
  processingCount.value > 0 ? `${processingCount.value} still processing` : 'all documents included',
)

async function runSearch() {
  if (!canSearch.value) return

  searching.value = true
  error.value = null
  copied.value = false
  expandedIds.value = new Set()
  try {
    results.value = await search(
      query.value,
      selectedSources.value,
      props.selected.map((document) => document.id),
    )
    submittedQuery.value = query.value.trim()
  } catch (exception) {
    results.value = null
    error.value =
      exception instanceof ApiError ? exception.message : 'Something went wrong searching.'
  } finally {
    searching.value = false
  }
}

function runExample(prompt: string) {
  query.value = prompt
  runSearch()
}

function toggleExpand(chunkId: number) {
  const next = new Set(expandedIds.value)
  if (next.has(chunkId)) {
    next.delete(chunkId)
  } else {
    next.add(chunkId)
  }
  expandedIds.value = next
}

async function copyForLlm() {
  if (!results.value?.length) return
  try {
    await copyText(buildLlmPrompt(submittedQuery.value, results.value))
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
  <section class="panel">
    <div class="search-bar">
      <form class="search-form" @submit.prevent="runSearch">
        <div class="search-input-wrap">
          <i class="pi pi-search search-icon" aria-hidden="true" />
          <InputText
            v-model="query"
            placeholder="Ask anything about your library…"
            aria-label="Search query"
            class="search-input"
            fluid
          />
        </div>
        <Button
          type="submit"
          label="Ask Oracle"
          icon="pi pi-sparkles"
          class="ask-button"
          :disabled="!canSearch"
        />
      </form>

      <div class="source-picker">
        <label v-for="source in SOURCE_OPTIONS" :key="source" class="source-option">
          <Checkbox v-model="selectedSources" :value="source" />
          {{ SOURCE_LABELS[source] }}
        </label>
      </div>

      <p v-if="results !== null" class="search-scope">
        Searching
        <strong>{{ selectedReadyCount }} of {{ readyCount }}</strong>
        ready documents · {{ excludedNote }}
      </p>
    </div>

    <div class="panel-body">
      <div v-if="!searching && results?.length" class="copy-bar">
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
        <div class="skeleton skeleton-lg" />
        <div class="skeleton skeleton-sm" />
        <div class="skeleton skeleton-sm" />
      </div>

      <div v-else-if="results === null" class="empty-state">
        <div class="empty-title">What do you want to know?</div>
        <p class="empty-hint">
          Oracle searches across your library and surfaces the passages that answer your question.
        </p>
        <div class="example-prompts">
          <button
            v-for="prompt in EXAMPLE_PROMPTS"
            :key="prompt"
            type="button"
            class="example-prompt"
            @click="runExample(prompt)"
          >
            {{ prompt }}
          </button>
        </div>
      </div>

      <template v-else>
        <p v-if="results.length === 0" class="search-empty">No matches found.</p>

        <template v-else>
          <div class="excerpts-heading">
            <span>Supporting excerpts ({{ results.length }})</span>
            <div class="excerpts-rule" />
          </div>

          <ol class="results">
            <li v-for="(result, index) in results" :key="result.chunk_id">
              <Card class="excerpt-card">
                <template #content>
                  <div
                    class="excerpt-head"
                    role="button"
                    tabindex="0"
                    :aria-expanded="expandedIds.has(result.chunk_id)"
                    @click="toggleExpand(result.chunk_id)"
                    @keydown.enter="toggleExpand(result.chunk_id)"
                    @keydown.space.prevent="toggleExpand(result.chunk_id)"
                  >
                    <div class="excerpt-rank">{{ index + 1 }}</div>
                    <div class="excerpt-title">
                      {{ result.filename }}
                      <span v-if="result.page_number !== null" class="excerpt-page"
                        >· page {{ result.page_number }}</span
                      >
                    </div>
                    <div class="excerpt-tags">
                      <Tag
                        v-for="source in result.sources"
                        :key="source"
                        :value="SOURCE_LABELS[source]"
                        :severity="source === 'bm25' ? 'secondary' : 'info'"
                      />
                    </div>
                    <svg
                      class="excerpt-chevron"
                      :class="{ 'excerpt-chevron-open': expandedIds.has(result.chunk_id) }"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                    >
                      <path
                        d="M6 9l6 6 6-6"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </div>
                  <p v-if="expandedIds.has(result.chunk_id)" class="excerpt-snippet">
                    {{ result.text }}
                  </p>
                </template>
              </Card>
            </li>
          </ol>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  min-width: 0;
}

.search-bar {
  padding: 26px 40px 20px;
  border-bottom: 1px solid var(--p-content-border-color);
}

.search-form {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.search-input-wrap {
  flex: 1 1 260px;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--p-form-field-background);
  border: 1.5px solid var(--p-form-field-border-color);
  border-radius: 12px;
  padding: 0 16px;
  height: 52px;
}

.search-icon {
  color: var(--p-text-muted-color);
  flex-shrink: 0;
}

.search-input.p-inputtext {
  flex: 1;
  min-width: 0;
  background: none;
  border: none;
  box-shadow: none;
  padding: 0;
  height: 100%;
  font-size: 15px;
}

.ask-button.p-button {
  height: 52px;
  padding: 0 22px;
  border-radius: 12px;
  border: none;
  background: linear-gradient(155deg, #34d399, #0ea5a0);
  color: #06201a;
  font-size: 14.5px;
  font-weight: 700;
  flex-shrink: 0;
  white-space: nowrap;
}

.ask-button.p-button:not(:disabled):hover {
  background: linear-gradient(155deg, #34d399, #0ea5a0);
  filter: brightness(1.06);
}

.source-picker {
  display: flex;
  gap: 18px;
  margin-top: 12px;
}

.source-option {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--p-text-muted-color);
  cursor: pointer;
}

.search-scope {
  margin: 12px 0 0;
  font-size: 12.5px;
  color: var(--p-text-muted-color);
}

.search-scope strong {
  color: var(--p-text-color);
  font-weight: 600;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 36px 40px 60px;
}

.copy-bar {
  margin-bottom: 0.75rem;
}

.search-loading {
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

@keyframes oracle-pulse {
  0%,
  100% {
    opacity: 0.5;
  }
  50% {
    opacity: 1;
  }
}

.skeleton {
  border-radius: 14px;
  background: var(--p-content-background);
  animation: oracle-pulse 1.3s ease-in-out infinite;
}

.skeleton-lg {
  height: 120px;
}

.skeleton-sm {
  height: 80px;
}

.empty-state {
  max-width: 600px;
  margin: 40px auto 0;
  text-align: center;
}

.empty-title {
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 22px;
  color: var(--p-text-color);
  margin-bottom: 10px;
}

.empty-hint {
  font-size: 14px;
  color: var(--p-text-muted-color);
  margin: 0 0 24px;
  line-height: 1.6;
}

.example-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.example-prompt {
  padding: 9px 14px;
  border-radius: 20px;
  border: 1px solid var(--p-content-border-color);
  background: var(--p-content-background);
  color: var(--p-text-color);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
}

.example-prompt:hover {
  border-color: rgba(52, 211, 153, 0.4);
  color: var(--p-text-color);
}

.search-empty {
  color: var(--p-text-muted-color);
}

.excerpts-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 0 16px;
  max-width: 760px;
}

.excerpts-heading span {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--p-text-muted-color);
  white-space: nowrap;
}

.excerpts-rule {
  flex: 1;
  height: 1px;
  background: var(--p-content-border-color);
}

.results {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
  max-width: 760px;
}

.excerpt-card.p-card {
  background: var(--p-content-background);
  border: 1px solid var(--p-content-border-color);
}

.excerpt-head {
  display: flex;
  align-items: center;
  gap: 14px;
  cursor: pointer;
}

.excerpt-chevron {
  color: var(--p-text-muted-color);
  flex-shrink: 0;
  transition: transform 0.15s;
}

.excerpt-chevron-open {
  transform: rotate(180deg);
}

.excerpt-rank {
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--p-content-hover-background);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--p-text-muted-color);
  flex-shrink: 0;
}

.excerpt-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
}

.excerpt-page {
  color: var(--p-text-muted-color);
  font-weight: 500;
}

.excerpt-tags {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.excerpt-snippet {
  margin: 14px 0 0 40px;
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.7;
  color: var(--p-text-color);
  border-left: 2px solid rgba(52, 211, 153, 0.3);
  padding-left: 14px;
}
</style>
