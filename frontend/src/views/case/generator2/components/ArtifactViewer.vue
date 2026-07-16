<template>
  <div v-if="showDelivery && finalXmindArtifact" class="xmind-download-card">
    <div>
      <div class="xmind-download-card__title">最终 XMind 用例</div>
      <div class="xmind-download-card__desc">{{ finalXmindArtifact.file_name }}</div>
    </div>
    <el-button type="primary" @click="emit('download', finalXmindArtifact)">下载 .xmind</el-button>
  </div>
  <el-alert
    v-else-if="showDelivery && !trusted && ['SUCCESS', 'CONDITIONAL'].includes(jobStatus)"
    title="当前任务未找到 .xmind 产物"
    type="warning"
    :closable="false"
  />
  <el-alert
    v-if="showDelivery && exportLogArtifact"
    :title="formatArtifactContent(exportLogArtifact)"
    type="error"
    :closable="false"
    class="export-log-alert"
  />
  <div v-if="artifacts.length" class="artifact-panel">
    <div class="artifact-toolbar">
      <el-radio-group v-model="activeArtifactType" size="small">
        <el-radio-button v-for="artifact in artifacts" :key="artifact.id" :label="artifact.artifact_type">
          {{ artifactLabel(artifact) }}
        </el-radio-button>
      </el-radio-group>
      <el-button v-if="activeArtifact" size="small" @click="emit('download', activeArtifact)">下载</el-button>
    </div>
    <pre v-if="activeArtifact" v-loading="loading" class="artifact-preview">{{ formatArtifactContent(activeArtifact) }}</pre>
  </div>
</template>

<script setup>
import { caseGenerationV2ArtifactLabel, formatCaseGenerationV2ArtifactContent } from '@/lib/caseGenerationV2'

const activeArtifactType = defineModel('activeArtifactType', { type: String, default: '' })

defineProps({
  artifacts: { type: Array, default: () => [] },
  activeArtifact: { type: Object, default: null },
  finalXmindArtifact: { type: Object, default: null },
  exportLogArtifact: { type: Object, default: null },
  jobStatus: { type: String, default: '' },
  trusted: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  showDelivery: { type: Boolean, default: true }
})

const emit = defineEmits(['download'])
const artifactLabel = caseGenerationV2ArtifactLabel
const formatArtifactContent = formatCaseGenerationV2ArtifactContent
</script>

<style scoped>
.xmind-download-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid rgba(22, 163, 74, 0.22);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(240, 253, 244, 0.96), rgba(236, 253, 245, 0.72));
}

.xmind-download-card__title {
  color: #166534;
  font-weight: 800;
}

.xmind-download-card__desc {
  margin-top: 6px;
  color: var(--color-text-secondary);
  word-break: break-all;
}

.export-log-alert {
  margin-top: 12px;
}

.artifact-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}

.artifact-toolbar :deep(.el-radio-group) {
  min-width: 0;
  overflow: auto;
  flex-wrap: nowrap;
}

.artifact-toolbar :deep(.el-radio-button__inner) {
  white-space: nowrap;
}

.artifact-preview {
  box-sizing: border-box;
  width: 100%;
  max-height: 420px;
  min-height: 240px;
  margin: 0;
  padding: 14px;
  overflow: auto;
  border-radius: 16px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 768px) {
  .xmind-download-card,
  .artifact-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
