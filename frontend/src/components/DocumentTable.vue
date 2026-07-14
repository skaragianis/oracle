<script setup lang="ts">
import { computed } from 'vue'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import ProgressSpinner from 'primevue/progressspinner'

import type { DocumentStatus, OracleDocument } from '../api'

defineProps<{ documents: OracleDocument[]; loading: boolean }>()

/** Two-way bound to the parent: the checkbox state is the search scope. */
const selection = defineModel<OracleDocument[]>('selection', { required: true })

const SEVERITY_BY_STATUS: Record<DocumentStatus, 'success' | 'warn' | 'danger'> = {
  ready: 'success',
  pending: 'warn',
  failed: 'danger',
}

/** Only chunked documents have anything to search. */
function isReady(document: OracleDocument) {
  return document.status === 'ready'
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
      <Column field="filename" header="Document" />
      <Column field="status" header="Status" header-style="width: 8rem">
        <template #body="{ data }: { data: OracleDocument }">
          <Tag :value="data.status" :severity="SEVERITY_BY_STATUS[data.status]" />
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

:deep(.row-unavailable) {
  opacity: 0.55;
}

/* A document that isn't ready can't be searched, so its checkbox is inert. */
:deep(.row-unavailable .p-checkbox) {
  pointer-events: none;
}
</style>
