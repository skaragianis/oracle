<script setup lang="ts">
import { computed, ref } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'

import { ApiError, deleteDocument, type DocumentStatus, type OracleDocument } from '../api'

defineProps<{ documents: OracleDocument[]; loading: boolean }>()

/** Emitted once a document is actually gone, so the parent can refetch and stop polling it. */
const emit = defineEmits<{ deleted: [id: number] }>()

/** Two-way bound to the parent: the checkbox state is the search scope. */
const selection = defineModel<OracleDocument[]>('selection', { required: true })

const SEVERITY_BY_STATUS: Record<DocumentStatus, 'success' | 'warn' | 'danger'> = {
  ready: 'success',
  pending: 'warn',
  failed: 'danger',
}

const deletingIds = ref<Set<number>>(new Set())
const deleteError = ref<string | null>(null)

/** Only chunked documents have anything to search. */
function isReady(document: OracleDocument) {
  return document.status === 'ready'
}

async function remove(document: OracleDocument) {
  deletingIds.value.add(document.id)
  deleteError.value = null
  try {
    await deleteDocument(document.id)
    emit('deleted', document.id)
  } catch (exception) {
    deleteError.value =
      exception instanceof ApiError ? exception.message : `Could not delete ${document.filename}.`
  } finally {
    deletingIds.value.delete(document.id)
  }
}

/**
 * DataTable has no prop for making a row unselectable, so the rule is enforced
 * here instead: unready rows are filtered out of whatever the table hands back,
 * which also keeps the header's select-all from picking them up. The rows
 * themselves are made unclickable in CSS.
 */
const selectableSelection = computed({
  get: () => selection.value,
  set: (rows: OracleDocument[]) => {
    selection.value = rows.filter(isReady)
  },
})
</script>

<template>
  <section>
    <Message v-if="deleteError" severity="error" :closable="false">{{ deleteError }}</Message>

    <div v-if="loading" class="documents-loading">
      <ProgressSpinner style="width: 2.5rem; height: 2.5rem" aria-label="Loading documents" />
    </div>

    <DataTable
      v-else
      v-model:selection="selectableSelection"
      :value="documents"
      data-key="id"
      :row-class="(row: OracleDocument) => (isReady(row) ? '' : 'row-unavailable')"
    >
      <template #empty>
        <p class="documents-empty">No documents yet. Upload one to get started.</p>
      </template>

      <Column selection-mode="multiple" header-style="width: 3rem" />
      <Column field="filename" header="Document">
        <template #body="{ data }: { data: OracleDocument }">
          <span>{{ data.filename }}</span>
          <p v-if="data.error" class="document-error">{{ data.error }}</p>
        </template>
      </Column>
      <Column field="status" header="Status" header-style="width: 8rem">
        <template #body="{ data }: { data: OracleDocument }">
          <Tag :value="data.status" :severity="SEVERITY_BY_STATUS[data.status]" />
        </template>
      </Column>
      <Column header-style="width: 3rem">
        <template #body="{ data }: { data: OracleDocument }">
          <Button
            icon="pi pi-trash"
            severity="danger"
            text
            rounded
            :loading="deletingIds.has(data.id)"
            :aria-label="`Delete ${data.filename}`"
            @click="remove(data)"
          />
        </template>
      </Column>
    </DataTable>
  </section>
</template>

<style scoped>
.documents-loading {
  display: flex;
  justify-content: center;
  padding: 2rem;
}

.documents-empty {
  margin: 0;
  color: var(--p-text-muted-color);
}

.document-error {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
  color: var(--p-text-muted-color);
}

:deep(.row-unavailable) {
  opacity: 0.55;
}

/* A document that isn't ready can't be searched, so its checkbox is inert. */
:deep(.row-unavailable .p-checkbox) {
  pointer-events: none;
}
</style>
