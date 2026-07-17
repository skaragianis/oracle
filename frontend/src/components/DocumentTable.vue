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
  <section class="library">
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

      <Column selection-mode="multiple" header-style="width: 2.5rem" />
      <Column field="filename" header="Document">
        <template #body="{ data }: { data: OracleDocument }">
          <span class="document-title">{{ data.filename }}</span>
          <div class="document-status">
            <Tag :value="data.status" :severity="SEVERITY_BY_STATUS[data.status]">
              <template #icon>
                <span class="status-dot" :class="`status-dot-${data.status}`" />
              </template>
            </Tag>
          </div>
          <p v-if="data.error" class="document-error">{{ data.error }}</p>
        </template>
      </Column>
      <Column header-style="width: 2.5rem">
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
.library {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0 12px 12px;
}

.documents-loading {
  display: flex;
  justify-content: center;
  padding: 2rem;
}

.documents-empty {
  margin: 0;
  padding: 0 12px;
  color: var(--p-text-muted-color);
  font-size: 13px;
}

.document-title {
  display: block;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.4;
  /* Filenames often contain long unbroken tokens (hashes, ISBNs); without
     this an auto-layout table widens the column to fit them instead of
     wrapping, pushing the delete button out of the sidebar. */
  overflow-wrap: anywhere;
}

.document-status {
  margin-top: 7px;
}

.status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.status-dot-ready {
  color: #34d399;
}

.status-dot-pending {
  color: #fbbf24;
}

.status-dot-failed {
  color: #f87171;
}

.document-error {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
  color: var(--p-text-muted-color);
}

/* The redesign's library list has no visible column headers - it reads as a
   simple checklist - but the header row stays in the DOM so select-all keeps
   working. */
:deep(.p-datatable-thead) {
  display: none;
}

:deep(.p-datatable-table) {
  border-collapse: collapse;
}

:deep(.p-datatable-tbody > tr) {
  background: transparent;
}

:deep(.p-datatable-tbody > tr > td) {
  border: none;
  padding: 12px;
  vertical-align: top;
}

:deep(.row-unavailable) {
  opacity: 0.55;
}

/* A document that isn't ready can't be searched, so its checkbox is inert. */
:deep(.row-unavailable .p-checkbox) {
  pointer-events: none;
}
</style>
