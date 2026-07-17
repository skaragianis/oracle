<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import Message from 'primevue/message'
import Button from 'primevue/button'

import DocumentUpload from './components/DocumentUpload.vue'
import DocumentTable from './components/DocumentTable.vue'
import SearchPanel from './components/SearchPanel.vue'
import { ApiError, listDocuments, waitForDocument, type OracleDocument } from './api'
import { colorScheme, toggleColorScheme } from './colorScheme'

const documents = ref<OracleDocument[]>([])
const selected = ref<OracleDocument[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const readyCount = computed(
  () => documents.value.filter((document) => document.status === 'ready').length,
)

const polls = new AbortController()
const watched = new Set<number>()
// Ids the user deleted while their poll was still in flight: the poll's next
// request 404s, which is expected, not a failure worth showing.
const deleted = new Set<number>()

async function refresh() {
  loading.value = true
  error.value = null
  try {
    documents.value = await listDocuments()
    pruneSelection()
    watchPending()
  } catch (exception) {
    error.value =
      exception instanceof ApiError ? exception.message : 'Could not load documents.'
  } finally {
    loading.value = false
  }
}

function pruneSelection() {
  const ready = new Set(
    documents.value
      .filter((document) => document.status === 'ready')
      .map((document) => document.id),
  )
  selected.value = selected.value.filter((document) => ready.has(document.id))
}

function watchPending() {
  for (const document of documents.value) {
    if (document.status !== 'pending' || watched.has(document.id)) continue

    watched.add(document.id)
    waitForDocument(document.id, { signal: polls.signal })
      .then(settle)
      .catch((exception) => {
        if (exception instanceof DOMException && exception.name === 'AbortError') return
        if (deleted.has(document.id)) return
        error.value =
          exception instanceof ApiError
            ? exception.message
            : `Could not get the status of ${document.filename}.`
      })
      .finally(() => {
        watched.delete(document.id)
        deleted.delete(document.id)
      })
  }
}

function handleDeleted(id: number) {
  deleted.add(id)
  refresh()
}

function settle(settled: OracleDocument) {
  const index = documents.value.findIndex((document) => document.id === settled.id)
  if (index === -1 || documents.value[index].status !== 'pending') return
  documents.value[index] = settled
}

onMounted(refresh)
onUnmounted(() => polls.abort())
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-row">
          <div class="brand-mark">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" fill="#0B0C0F" />
            </svg>
          </div>
          <h1 class="brand-name">Oracle</h1>
        </div>
        <p class="tagline">Ask questions of your documents.</p>
      </div>

      <div class="library-header">
        <span class="library-label">Library</span>
        <span class="library-count">{{ readyCount }} of {{ documents.length }} ready</span>
      </div>

      <DocumentUpload @uploaded="refresh" />

      <DocumentTable
        v-model:selection="selected"
        :documents="documents"
        :loading="loading"
        class="library-list"
        @deleted="handleDeleted"
      />
    </aside>

    <main class="main">
      <div class="topbar">
        <Button
          class="theme-toggle"
          :icon="colorScheme === 'dark' ? 'pi pi-sun' : 'pi pi-moon'"
          rounded
          :title="colorScheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
          :aria-label="colorScheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'"
          @click="toggleColorScheme"
        />
      </div>

      <Message v-if="error" severity="error" :closable="false" class="page-error">{{
        error
      }}</Message>

      <SearchPanel :selected="selected" :documents="documents" />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
}

.topbar {
  display: flex;
  justify-content: flex-end;
  padding: 16px 24px 0;
}

.theme-toggle.p-button {
  background: var(--oracle-sidebar-background);
  border: 1px solid var(--p-content-border-color);
  color: var(--p-text-color);
}

.theme-toggle.p-button:hover {
  background: var(--p-content-hover-background);
  color: var(--p-text-color);
}

.sidebar {
  width: 336px;
  flex-shrink: 0;
  background: var(--oracle-sidebar-background);
  border-right: 1px solid var(--p-content-border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.brand {
  padding: 28px 24px 20px;
  border-bottom: 1px solid var(--p-content-border-color);
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(155deg, #34d399, #0ea5a0);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.brand-name {
  margin: 0;
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 500;
  font-size: 26px;
  letter-spacing: 0.2px;
}

.tagline {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--p-text-muted-color);
  line-height: 1.5;
}

.library-header {
  padding: 20px 24px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.library-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--p-text-muted-color);
}

.library-count {
  font-size: 12px;
  color: var(--p-text-muted-color);
}

.library-list {
  flex: 1;
  min-height: 0;
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  min-width: 0;
}

.page-error {
  margin: 20px 40px 0;
}
</style>
