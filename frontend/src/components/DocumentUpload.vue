<script setup lang="ts">
import { ref } from 'vue'
import FileUpload, { type FileUploadUploaderEvent } from 'primevue/fileupload'
import Message from 'primevue/message'

import { ApiError, uploadDocument } from '../api'

const emit = defineEmits<{ uploaded: [] }>()

// PrimeVue's public methods type omits clear(), though the component exposes it.
const fileUpload = ref<InstanceType<typeof FileUpload> & { clear(): void }>()
const uploading = ref(false)
const errors = ref<string[]>([])

/**
 * FileUpload hands us the files rather than posting them itself (customUpload),
 * so each one goes through our own API client.
 */
async function upload(event: FileUploadUploaderEvent) {
  const files = Array.isArray(event.files) ? event.files : [event.files]
  uploading.value = true
  errors.value = []

  const outcomes = await Promise.allSettled(files.map((file) => uploadDocument(file)))

  errors.value = outcomes.flatMap((outcome, index) =>
    outcome.status === 'rejected'
      ? [
          `${files[index].name}: ${
            outcome.reason instanceof ApiError ? outcome.reason.message : 'Upload failed.'
          }`,
        ]
      : [],
  )

  uploading.value = false
  // customUpload leaves the chosen files staged with a permanent "Pending"
  // badge; the real status lives in the document table, so drop the staging row.
  fileUpload.value?.clear()
  // Even a partly failed batch may have added documents, so always refresh.
  emit('uploaded')
}
</script>

<template>
  <section>
    <FileUpload
      ref="fileUpload"
      name="file"
      accept=".pdf,.docx"
      :multiple="true"
      :custom-upload="true"
      :disabled="uploading"
      :show-cancel-button="false"
      choose-label="Choose documents"
      upload-label="Upload"
      @uploader="upload"
    >
      <template #empty>
        <p class="upload-hint">Drop PDF or DOCX files here, or choose them above.</p>
      </template>
    </FileUpload>

    <Message
      v-for="error in errors"
      :key="error"
      severity="error"
      :closable="false"
      class="upload-error"
    >
      {{ error }}
    </Message>
  </section>
</template>

<style scoped>
.upload-hint {
  margin: 0;
  color: var(--p-text-muted-color);
}

.upload-error {
  margin-top: 0.75rem;
}

/* PDF/DOCX have no image preview, so FileUpload's thumbnail <img> renders as a
   broken icon squeezing the filename (its alt text) into a narrow column. */
:deep(.p-fileupload-file-thumbnail) {
  display: none;
}
</style>
