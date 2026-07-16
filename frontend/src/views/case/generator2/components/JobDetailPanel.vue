<template>
  <el-card class="page-card side-card job-detail-panel" shadow="never">
    <div class="panel-head">
      <div class="panel-title">结果详情</div>
      <div class="detail-actions">
        <div class="detail-actions__primary">
          <el-button v-if="canRerun" size="small" :loading="rerunning" :disabled="rerunDisabled" @click="emit('rerun-job')">重跑</el-button>
          <el-button
            v-if="canCancel"
            size="small"
            type="danger"
            plain
            :loading="cancelling"
            :disabled="cancelling"
            @click="emit('cancel-job')"
          >
            停止任务
          </el-button>
        </div>
        <el-button v-if="job" size="small" class="detail-actions__secondary" @click="emit('refresh')">刷新详情</el-button>
      </div>
    </div>

    <div class="detail-body">
      <el-empty v-if="!job" description="请选择一个任务查看详情" />

      <template v-else>
        <div class="detail-summary">
          <div class="summary-line"><span>状态</span><el-tag :type="statusTagType(job.status)">{{ job.status }}</el-tag></div>
          <div class="summary-line"><span>生成模式</span><strong>{{ pipelineModeLabel(pipelineMode) }}</strong></div>
          <div v-if="trusted" class="summary-line">
            <span>生成策略</span>
            <strong>{{ trustedGenerationStrategyLabel(job.input_payload_json?.trusted_generation_strategy) }}</strong>
          </div>
          <div v-if="trusted" class="summary-line">
            <span>生成密度</span>
            <strong>{{ generationDensityLabel(job.input_payload_json?.generation_density) }}</strong>
          </div>
          <div v-if="trusted && scopeIndexStrategyText" class="summary-line">
            <span>索引策略</span>
            <strong>{{ scopeIndexStrategyText }}</strong>
          </div>
          <div v-if="trusted && finalDeliveryGatePassed !== null" class="summary-line">
            <span>交付门禁</span>
            <el-tag :type="finalDeliveryGatePassed ? 'success' : 'danger'">{{ finalDeliveryGatePassed ? '通过' : '未通过' }}</el-tag>
          </div>
          <div class="summary-line"><span>摘要</span><strong>{{ job.summary || '-' }}</strong></div>
          <div class="summary-line"><span>来源</span><span>{{ job.source_document_name || '-' }}</span></div>
          <div v-if="job.error_message" class="summary-line"><span>错误</span><span class="error-text">{{ job.error_message }}</span></div>
        </div>

        <MetricsPanel
          :generation-metrics="generationMetrics"
          :metrics-comparison="metricsComparison"
          :trusted-metrics="trustedMetrics"
          :trusted="trusted"
        />

        <GateIssuesPanel
          v-if="trusted"
          :gates="gateIssues"
          :job-status="job.status"
          :rerunning-shard="rerunningShard"
          :rerunning="rerunning"
          :rerun-disabled="rerunDisabled"
          @rerun-source="emit('rerun-source', $event)"
          @rerun-job="emit('rerun-job')"
        />

        <SourceDetailTable
          v-if="trusted"
          :sources="sources"
          :job="job"
          :trusted="trusted"
          :rerunning-shard="rerunningShard"
          @rerun-source="emit('rerun-source', $event)"
        />

        <div class="progress-card">
          <div class="progress-card__head">
            <div>
              <div class="progress-card__title">执行进度</div>
              <div class="progress-card__subtitle">{{ progressStatusText }}</div>
            </div>
            <div class="progress-percent">{{ progressPercent }}%</div>
          </div>
          <div class="progress-track" aria-hidden="true">
            <div class="progress-track__fill" :style="{ width: `${progressPercent}%` }"></div>
          </div>
          <div v-if="activeExecutionProof" class="progress-live-proof">{{ activeExecutionProof }}</div>
          <div class="progress-stage-rail">
            <div
              v-for="stage in progressStages"
              :key="stage.key"
              class="progress-stage-node"
              :class="`is-${stage.status}`"
              :title="stage.childLabels || stage.label"
            >
              <div class="progress-stage-node__dot">{{ stage.index }}</div>
              <div class="progress-stage-node__label">{{ stage.label }}</div>
              <div v-if="stage.durationText" class="progress-stage-node__duration">{{ stage.durationText }}</div>
            </div>
          </div>
          <div class="stage-summary-list">
            <div
              v-for="stage in stageSummaries"
              :key="stage.key"
              class="stage-summary-item"
              :class="`is-${stage.status || 'pending'}`"
            >
              <button
                type="button"
                class="stage-summary-item__trigger"
                :class="{ 'is-expandable': artifactsForStage(stage.key).length }"
                :aria-expanded="expandedStageKey === stage.key"
                :disabled="!artifactsForStage(stage.key).length"
                @click="toggleStageArtifacts(stage.key)"
              >
                <span class="stage-summary-item__title-wrap">
                  <span class="stage-summary-item__title">{{ stage.title }}</span>
                  <span v-if="formatStageDuration(stage)" class="stage-summary-item__duration">{{ formatStageDuration(stage) }}</span>
                </span>
                <span class="stage-summary-item__meta">
                  <span v-if="artifactsForStage(stage.key).length" class="stage-summary-item__artifact-count">
                    中间产物 {{ artifactsForStage(stage.key).length }}
                  </span>
                  <el-tag size="small" :type="stageTagType(stage.status)">{{ stage.status }}</el-tag>
                  <el-icon
                    v-if="artifactsForStage(stage.key).length"
                    class="stage-summary-item__chevron"
                    :class="{ 'is-expanded': expandedStageKey === stage.key }"
                  >
                    <ArrowDown />
                  </el-icon>
                </span>
                <span class="stage-summary-item__desc">{{ stage.summary || '-' }}</span>
              </button>
              <ArtifactViewer
                v-if="expandedStageKey === stage.key"
                class="stage-artifact-viewer"
                v-model:active-artifact-type="activeArtifactType"
                :artifacts="artifactsForStage(stage.key)"
                :active-artifact="activeArtifact"
                :job-status="job.status"
                :trusted="trusted"
                :loading="artifactLoading"
                :show-delivery="false"
                @download="emit('download-artifact', $event)"
              />
            </div>
          </div>
        </div>

        <ArtifactViewer
          v-model:active-artifact-type="activeArtifactType"
          :artifacts="[]"
          :active-artifact="activeArtifact"
          :final-xmind-artifact="finalXmindArtifact"
          :export-log-artifact="exportLogArtifact"
          :job-status="job.status"
          :trusted="trusted"
          :loading="artifactLoading"
          @download="emit('download-artifact', $event)"
        />
      </template>
    </div>
  </el-card>
</template>

<script setup>
import { ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { caseGenerationV2StatusTagType } from '@/lib/caseGenerationV2'
import { pipelineModeLabel } from '@/lib/caseGenerationUi'
import {
  formatDurationMs,
  filterStageArtifacts,
  generationDensityLabel,
  trustedGenerationStrategyLabel
} from '../presentation'
import ArtifactViewer from './ArtifactViewer.vue'
import GateIssuesPanel from './GateIssuesPanel.vue'
import MetricsPanel from './MetricsPanel.vue'
import SourceDetailTable from './SourceDetailTable.vue'

const activeArtifactType = defineModel('activeArtifactType', { type: String, default: '' })
const expandedStageKey = ref('')

const props = defineProps({
  job: { type: Object, default: null },
  pipelineMode: { type: String, default: 'lite' },
  trusted: { type: Boolean, default: false },
  canRerun: { type: Boolean, default: false },
  canCancel: { type: Boolean, default: false },
  rerunning: { type: Boolean, default: false },
  rerunDisabled: { type: Boolean, default: false },
  cancelling: { type: Boolean, default: false },
  rerunningShard: { type: String, default: '' },
  scopeIndexStrategyText: { type: String, default: '' },
  finalDeliveryGatePassed: { type: Boolean, default: null },
  generationMetrics: { type: Object, default: null },
  metricsComparison: { type: Object, default: null },
  trustedMetrics: { type: Object, default: null },
  gateIssues: { type: Array, default: () => [] },
  sources: { type: Array, default: () => [] },
  progressStatusText: { type: String, default: '' },
  progressPercent: { type: Number, default: 0 },
  activeExecutionProof: { type: String, default: '' },
  progressStages: { type: Array, default: () => [] },
  stageSummaries: { type: Array, default: () => [] },
  artifacts: { type: Array, default: () => [] },
  activeArtifact: { type: Object, default: null },
  finalXmindArtifact: { type: Object, default: null },
  exportLogArtifact: { type: Object, default: null },
  artifactLoading: { type: Boolean, default: false }
})

const emit = defineEmits([
  'rerun-job',
  'cancel-job',
  'refresh',
  'rerun-source',
  'download-artifact'
])

const statusTagType = caseGenerationV2StatusTagType

function stageTagType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function formatStageDuration(stage) {
  return formatDurationMs(stage?.duration_ms)
}

function artifactsForStage(stageKey) {
  return filterStageArtifacts(props.artifacts, stageKey, props.trusted)
}

function toggleStageArtifacts(stageKey) {
  const stageArtifacts = artifactsForStage(stageKey)
  if (!stageArtifacts.length) return
  if (expandedStageKey.value === stageKey) {
    expandedStageKey.value = ''
    return
  }
  expandedStageKey.value = stageKey
  activeArtifactType.value = stageArtifacts[0].artifact_type
}

watch(
  () => props.job?.id,
  () => {
    expandedStageKey.value = ''
  }
)
</script>

<style scoped>
.side-card {
  height: 100%;
  min-height: 0;
  border-radius: 20px;
}

.side-card :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-head,
.detail-actions,
.detail-actions__primary,
.progress-card__head {
  display: flex;
  align-items: center;
}

.panel-head {
  position: sticky;
  top: 0;
  z-index: 2;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  background: var(--color-surface, #fff);
}

.panel-title {
  font-size: 18px;
  font-weight: 700;
}

.detail-actions {
  gap: 4px;
  max-width: 100%;
  margin-left: auto;
  flex-shrink: 0;
}

.detail-actions__primary {
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: nowrap;
}

.detail-actions :deep(.el-button) {
  flex: 0 0 auto;
  padding-inline: 10px;
  white-space: nowrap;
}

.detail-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.detail-summary {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 16px;
  background: rgba(248, 250, 255, 0.88);
}

.summary-line {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.summary-line span:first-child {
  padding-top: 2px;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.summary-line strong,
.summary-line > span:last-child {
  min-width: 0;
  line-height: 1.5;
  word-break: break-word;
}

.summary-line :deep(.el-tag) {
  min-width: 96px;
  justify-self: start;
  padding-inline: 12px;
  border-radius: 999px;
  font-weight: 600;
}

.error-text {
  color: #dc2626;
}

.progress-card {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid rgba(99, 102, 241, 0.14);
  border-radius: 18px;
  background: radial-gradient(circle at 8% 0%, rgba(79, 70, 229, 0.1), transparent 32%), linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(246, 248, 255, 0.9));
  box-shadow: 0 18px 44px rgba(79, 70, 229, 0.08);
}

.progress-card__head {
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.progress-card__title {
  color: var(--color-text-primary);
  font-size: 15px;
  font-weight: 700;
}

.progress-card__subtitle {
  margin-top: 5px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.progress-percent {
  min-width: 58px;
  padding: 6px 10px;
  border: 1px solid rgba(99, 102, 241, 0.16);
  border-radius: 999px;
  background: rgba(238, 242, 255, 0.96);
  color: #3730a3;
  font-weight: 800;
  text-align: center;
}

.progress-track {
  position: relative;
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.9);
}

.progress-track__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #4f46e5 52%, #14b8a6);
  box-shadow: 0 0 18px rgba(79, 70, 229, 0.28);
  transition: width 360ms ease;
}

.progress-live-proof {
  padding: 8px 10px;
  border: 1px solid rgba(79, 70, 229, 0.14);
  border-radius: 10px;
  background: rgba(238, 242, 255, 0.72);
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.progress-stage-rail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(46px, 1fr));
  gap: 8px;
}

.progress-stage-node {
  display: grid;
  justify-items: center;
  gap: 7px;
  min-width: 0;
  color: var(--color-text-secondary);
}

.progress-stage-node__dot {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  font-size: 12px;
  font-weight: 800;
}

.progress-stage-node__label {
  max-width: 100%;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-stage-node__duration {
  color: var(--color-text-secondary);
  font-size: 11px;
  line-height: 1;
}

.progress-stage-node.is-success .progress-stage-node__dot {
  border-color: rgba(20, 184, 166, 0.22);
  background: linear-gradient(135deg, rgba(204, 251, 241, 0.96), rgba(240, 253, 250, 0.96));
  color: #0f766e;
}

.progress-stage-node.is-running .progress-stage-node__dot {
  border-color: rgba(79, 70, 229, 0.34);
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  box-shadow: 0 10px 22px rgba(79, 70, 229, 0.28);
  color: #fff;
}

.progress-stage-node.is-failed .progress-stage-node__dot {
  border-color: rgba(220, 38, 38, 0.22);
  background: rgba(254, 226, 226, 0.94);
  color: #b91c1c;
}

.stage-summary-list {
  display: grid;
  gap: 10px;
}

.stage-summary-item {
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.78);
}

.stage-summary-item__trigger {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 12px;
  align-items: start;
  width: 100%;
  padding: 12px 14px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
}

.stage-summary-item__trigger.is-expandable {
  cursor: pointer;
}

.stage-summary-item__trigger.is-expandable:hover {
  background: rgba(238, 242, 255, 0.66);
}

.stage-summary-item__trigger:disabled {
  cursor: default;
  opacity: 1;
}

.stage-summary-item.is-running {
  border-color: rgba(79, 70, 229, 0.24);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.92), rgba(255, 255, 255, 0.82));
}

.stage-summary-item.is-success {
  border-color: rgba(20, 184, 166, 0.2);
}

.stage-summary-item__title-wrap {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.stage-summary-item__title {
  font-weight: 600;
}

.stage-summary-item__duration {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.stage-summary-item__meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.stage-summary-item__artifact-count {
  color: #4f46e5;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.stage-summary-item__chevron {
  color: var(--color-text-secondary);
  transition: transform 180ms ease;
}

.stage-summary-item__chevron.is-expanded {
  transform: rotate(180deg);
}

.stage-summary-item :deep(.el-tag) {
  min-width: 0;
  align-self: start;
  justify-self: end;
  padding-inline: 10px;
  border-radius: 999px;
  font-weight: 600;
  text-transform: lowercase;
}

.stage-summary-item__desc {
  grid-column: 1 / -1;
  margin-top: 2px;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.stage-artifact-viewer {
  padding: 0 14px 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

.stage-artifact-viewer :deep(.artifact-toolbar) {
  padding-top: 12px;
}

@media (max-width: 1100px) {
  .side-card {
    height: min(860px, calc(100vh - 120px));
    min-height: 680px;
  }
}

@media (max-width: 768px) {
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }

  .detail-actions {
    justify-content: flex-start;
    margin-left: 0;
  }

  .detail-actions__primary {
    justify-content: flex-start;
    flex-wrap: wrap;
  }

  .progress-stage-rail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
