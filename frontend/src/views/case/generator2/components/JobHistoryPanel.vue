<template>
  <el-card class="page-card side-card job-history-panel" shadow="never">
    <div class="panel-head">
      <div class="panel-title">最近任务</div>
      <div class="job-filters">
        <el-select v-model="modeFilter" class="job-filter" size="small" clearable placeholder="全部模式" @change="emit('refresh')">
          <el-option label="轻量" value="lite" />
          <el-option label="可信" value="trusted" />
        </el-select>
        <el-select v-model="statusFilter" class="job-filter" size="small" clearable placeholder="全部状态" @change="emit('refresh')">
          <el-option label="进行中" value="RUNNING" />
          <el-option label="成功" value="SUCCESS" />
          <el-option label="有条件" value="CONDITIONAL" />
          <el-option label="失败" value="FAILED" />
          <el-option label="已取消" value="CANCELLED" />
        </el-select>
      </div>
    </div>

    <div class="job-list">
      <div v-if="pinnedRunningJob" class="job-pinned">
        <div class="job-pinned__label">进行中</div>
        <div
          class="job-item job-item--pinned"
          :class="{ active: currentJobId === pinnedRunningJob.id }"
          role="button"
          tabindex="0"
          @click="emit('select-job', pinnedRunningJob)"
          @keydown.enter.prevent="emit('select-job', pinnedRunningJob)"
          @keydown.space.prevent="emit('select-job', pinnedRunningJob)"
        >
          <div class="job-item__title">{{ pinnedRunningJob.name }}</div>
          <div class="job-item__meta">
            <span>#{{ pinnedRunningJob.id }}</span>
            <CaseGenerationModeBadge :mode="jobPipelineMode(pinnedRunningJob)" />
            <el-tag size="small" :type="statusTagType(pinnedRunningJob.status)">{{ pinnedRunningJob.status }}</el-tag>
          </div>
          <div class="job-item__desc">{{ formatJobListSummary(pinnedRunningJob) }}</div>
        </div>
      </div>

      <div
        v-for="item in jobs"
        :key="item.id"
        class="job-item"
        :class="{ active: currentJobId === item.id }"
        role="button"
        tabindex="0"
        @click="emit('select-job', item)"
        @keydown.enter.prevent="emit('select-job', item)"
        @keydown.space.prevent="emit('select-job', item)"
      >
        <div class="job-item__title">{{ item.name }}</div>
        <div class="job-item__meta">
          <span>#{{ item.id }}</span>
          <CaseGenerationModeBadge :mode="jobPipelineMode(item)" />
          <el-tag size="small" :type="statusTagType(item.status)">{{ item.status }}</el-tag>
        </div>
        <div class="job-item__desc">{{ formatJobListSummary(item) }}</div>
      </div>
      <el-empty v-if="!totalJobs" description="暂无生成任务" />
      <el-button v-if="hasMore" class="load-more-button" :loading="loadingMore" @click="emit('load-more')">加载更多</el-button>
    </div>
  </el-card>
</template>

<script setup>
import CaseGenerationModeBadge from '@/components/CaseGenerationModeBadge.vue'
import { caseGenerationV2StatusTagType } from '@/lib/caseGenerationV2'
import { formatJobListSummary, jobPipelineMode } from '../presentation'

const modeFilter = defineModel('modeFilter', { type: String, default: '' })
const statusFilter = defineModel('statusFilter', { type: String, default: '' })

defineProps({
  jobs: { type: Array, default: () => [] },
  totalJobs: { type: Number, default: 0 },
  pinnedRunningJob: { type: Object, default: null },
  currentJobId: { type: Number, default: null },
  hasMore: { type: Boolean, default: false },
  loadingMore: { type: Boolean, default: false }
})

const emit = defineEmits(['refresh', 'select-job', 'load-more'])
const statusTagType = caseGenerationV2StatusTagType
</script>

<style scoped>
.side-card {
  border-radius: 20px;
  height: 100%;
  min-height: 0;
}

.side-card :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.panel-title {
  min-width: 0;
  font-size: 18px;
  font-weight: 700;
}

.job-filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 72px));
  gap: 4px;
  flex: 0 0 auto;
}

.job-filter {
  width: 72px;
}

.job-list {
  display: grid;
  gap: 12px;
  overflow: auto;
  min-height: 0;
}

.job-item {
  display: grid;
  align-content: start;
  grid-auto-rows: min-content;
  width: 100%;
  min-height: 98px;
  box-sizing: border-box;
  padding: 12px 14px;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 248, 255, 0.96));
  color: inherit;
  cursor: pointer;
  outline: none;
  text-align: left;
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.job-item--pinned {
  border-color: rgba(79, 70, 229, 0.26);
  background: rgba(246, 248, 255, 0.92);
}

.job-pinned__label {
  color: rgba(79, 70, 229, 0.72);
  font-size: 12px;
  font-weight: 700;
}

.job-item.active {
  position: relative;
  overflow: hidden;
  border-color: rgba(79, 70, 229, 0.32);
  background: linear-gradient(180deg, rgba(244, 246, 255, 0.92), rgba(248, 250, 255, 0.98));
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.08);
}

.job-item.active::before {
  content: '';
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.job-item__title {
  font-weight: 700;
}

.job-item__meta {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  color: var(--color-text-secondary);
}

.job-item__desc {
  display: -webkit-box;
  margin-top: 8px;
  overflow: hidden;
  color: var(--color-text-secondary);
  line-height: 1.5;
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.load-more-button {
  width: 100%;
  flex: 0 0 auto;
}

@media (max-width: 1100px) {
  .side-card {
    height: min(680px, calc(100vh - 150px));
    min-height: 560px;
  }
}

@media (max-width: 768px) {
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }

  .job-filters {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .job-filter {
    width: 100%;
  }
}
</style>
