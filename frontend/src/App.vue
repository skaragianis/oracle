<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Message from 'primevue/message'

import DocumentUpload from './components/DocumentUpload.vue'
import DocumentTable from './components/DocumentTable.vue'
import SearchPanel from './components/SearchPanel.vue'
import { ApiError, listDocuments, type OracleDocument } from './api'

const documents = ref<OracleDocument[]>([])
const selected = ref<OracleDocument[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

async function refresh() {
  loading.value = true
  error.value = null
  try {
    documents.value = await listDocuments()
    // Drop selections for documents that no longer exist.
    const ids = new Set(documents.value.map((document) => document.id))
    selected.value = selected.value.filter((document) => ids.has(document.id))
  } catch (exception) {
    error.value =
      exception instanceof ApiError ? exception.message : 'Could not load documents.'
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
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
