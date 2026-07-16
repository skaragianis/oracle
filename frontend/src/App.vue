<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import Message from 'primevue/message'

import DocumentUpload from './components/DocumentUpload.vue'
import DocumentTable from './components/DocumentTable.vue'
import SearchPanel from './components/SearchPanel.vue'
import { ApiError, listDocuments, waitForDocument, type OracleDocument } from './api'

const documents = ref<OracleDocument[]>([])
const selected = ref<OracleDocument[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

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
  <main class="page">
    <header>
      <h1>Oracle</h1>
      <p class="tagline">Ask questions of your documents.</p>
    </header>

    <Message v-if="error" severity="error" :closable="false">{{ error }}</Message>

    <DocumentUpload @uploaded="refresh" />

    <DocumentTable
      v-model:selection="selected"
      :documents="documents"
      :loading="loading"
      @deleted="handleDeleted"
    />

    <SearchPanel :selected="selected" />
  </main>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  max-width: 60rem;
  margin: 0 auto;
  padding: 2rem 1rem 4rem;
  text-align: left;
}

h1 {
  margin: 0;
}

.tagline {
  margin: 0.25rem 0 0;
  color: var(--p-text-muted-color);
}
</style>
