<script setup lang="ts">
import { ref } from 'vue'
import FileUpload, { type FileUploadUploaderEvent } from 'primevue/fileupload'
import Message from 'primevue/message'

import { ApiError, uploadDocument } from '../api'

const emit = defineEmits<{ uploaded: [] }>()

// PrimeVue's public methods type omits choose()/clear(), though the component exposes both.
const fileUpload = ref<InstanceType<typeof FileUpload> & { choose(): void; clear(): void }>()
const uploading = ref(false)
const errors = ref<string[]>([])

/**
 * FileUpload hands us the files rather than posting them itself (customUpload),
 * so each one goes through our own API client. `auto` means this fires as soon
 * as files are chosen or dropped, matching the dropzone's single-step design.
 */
async function upload(event: FileUploadUploaderEvent) {
  const files = Array.isArray(event.files) ? event.files : [event.files]
  uploading.value = true
  errors.value = []

  const outcomes = await Promise.allSettled(files.map((file) => uploadDocument(file)))

  errors.value = outcomes.flatMap((outcome, index) =>
    outcome.status === 'rejected'
      ? [
        `${files[index].name}: ${outcome.reason instanceof ApiError ? outcome.reason.message : 'Upload failed.'
        }`,
      ]
      : [],
  )

  uploading.value = false
  fileUpload.value?.clear()
  // Even a partly failed batch may have added documents, so always refresh.
  emit('uploaded')
}
</script>

<template>
  <section class="upload">
    <FileUpload ref="fileUpload" name="file" accept=".pdf,.docx" :multiple="true" :auto="true" :custom-upload="true"
      :disabled="uploading" @uploader="upload">
      <template #empty>
        <div class="dropzone-content" @click="fileUpload?.choose()">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" class="dropzone-icon">
            <path d="M12 16V4M12 4L7 9M12 4L17 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
              stroke-linejoin="round" />
            <path d="M4 16.5V18a2 2 0 002 2h12a2 2 0 002-2v-1.5" stroke="currentColor" stroke-width="1.8"
              stroke-linecap="round" />
          </svg>
          <div class="dropzone-title">Drop files or browse</div>
          <div class="dropzone-hint">PDF or DOCX</div>
        </div>
      </template>
    </FileUpload>

    <Message v-for="error in errors" :key="error" severity="error" :closable="false" class="upload-error">
      {{ error }}
    </Message>
  </section>
</template>

<style scoped>
.upload {
  margin: 0 24px 16px;
}

:deep(.p-fileupload-header) {
  display: none;
}

:deep(.p-fileupload-content) {
  border: 1.5px dashed var(--p-content-border-color);
  border-radius: 12px;
  padding: 0;
  background: transparent;
  transition:
    border-color 0.15s,
    background 0.15s;
}

:deep(.p-fileupload-content[data-p-highlight='true']) {
  border-color: rgba(52, 211, 153, 0.5);
  background: rgba(52, 211, 153, 0.05);
}

.dropzone-content {
  padding: 18px 16px;
  text-align: center;
  cursor: pointer;
  color: var(--p-text-muted-color);
}

.dropzone-icon {
  margin: 0 auto 8px;
  display: block;
}

.dropzone-title {
  font-size: 13px;
  color: var(--p-text-color);
  font-weight: 500;
}

.dropzone-hint {
  font-size: 11.5px;
  margin-top: 3px;
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
