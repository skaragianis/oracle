<script setup lang="ts">
import { ref } from 'vue'
import FileUpload, { type FileUploadUploaderEvent } from 'primevue/fileupload'
import Message from 'primevue/message'

import { ApiError, uploadDocument } from '../api'

const emit = defineEmits<{ uploaded: [] }>()

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
  // Even a partly failed batch may have added documents, so always refresh.
  emit('uploaded')
}
</script>

<template>
  <section>
    <FileUpload
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
</style>
