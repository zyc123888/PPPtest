<template>
  <div v-loading="loading">
    <div class="ov-metrics">
      <el-card class="page-card ov-metric" shadow="never">
        <div class="ov-metric__label">需求总数</div>
        <div class="ov-metric__value">{{ overview.requirement_total || 0 }}</div>
        <div class="ov-metric__sub">用例覆盖率 {{ overview.case_coverage_rate || 0 }}%</div>
      </el-card>
      <el-card class="page-card ov-metric" shadow="never">
        <div class="ov-metric__label">任务总数</div>
        <div class="ov-metric__value">{{ overview.task_total || 0 }}</div>
        <div class="ov-metric__sub">我的待办 {{ overview.my_open_tasks || 0 }}</div>
      </el-card>
      <el-card class="page-card ov-metric" shadow="never">
        <div class="ov-metric__label">缺陷总数</div>
        <div class="ov-metric__value">{{ overview.defect_total || 0 }}</div>
        <div class="ov-metric__sub">未关闭 {{ overview.open_defect_total || 0 }}</div>
      </el-card>
      <el-card class="page-card ov-metric" shadow="never">
        <div class="ov-metric__label">迭代 / 成员</div>
        <div class="ov-metric__value">{{ overview.iteration_total || 0 }} / {{ overview.member_total || 0 }}</div>
        <div class="ov-metric__sub">{{ overview.active_iteration ? '进行中：' + overview.active_iteration.name : '无进行中迭代' }}</div>
      </el-card>
    </div>

    <div class="ov-grid">
      <el-card class="page-card" shadow="never">
        <template #header><span>需求状态分布</span></template>
        <StatusBars :counts="overview.requirement_counts" :labels="reqLabels" />
      </el-card>
      <el-card class="page-card" shadow="never">
        <template #header><span>任务状态分布</span></template>
        <StatusBars :counts="overview.task_counts" :labels="taskLabels" />
      </el-card>
      <el-card class="page-card" shadow="never">
        <template #header><span>缺陷状态分布</span></template>
        <StatusBars :counts="overview.defect_counts" :labels="defectLabels" />
      </el-card>
    </div>

    <div class="ov-grid-2">
      <el-card class="page-card" shadow="never">
        <template #header><span>我的待办</span></template>
        <ul class="ov-todo">
          <li>未完成需求：<strong>{{ overview.my_open_requirements || 0 }}</strong></li>
          <li>未完成任务：<strong>{{ overview.my_open_tasks || 0 }}</strong></li>
          <li>待处理缺陷：<strong>{{ overview.my_open_defects || 0 }}</strong></li>
        </ul>
      </el-card>
      <el-card class="page-card" shadow="never">
        <template #header><span>最近活动</span></template>
        <el-timeline v-if="overview.recent_activities?.length">
          <el-timeline-item
            v-for="act in overview.recent_activities"
            :key="act.id"
            :timestamp="formatTime(act.created_at)"
          >
            <span>{{ act.actor_name || '系统' }}</span>
            {{ actionLabel(act.action) }}了{{ entityLabel(act.entity_type) }} #{{ act.entity_id }}
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无活动" :image-size="60" />
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { h, onMounted, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import { REQUIREMENT_STATUS_LABELS, TASK_STATUS_LABELS, DEFECT_STATUS_LABELS } from './constants'

const props = defineProps({ project: { type: Object, required: true } })

const loading = ref(false)
const overview = ref({})
const reqLabels = REQUIREMENT_STATUS_LABELS
const taskLabels = TASK_STATUS_LABELS
const defectLabels = DEFECT_STATUS_LABELS

const ACTIONS = { create: '创建', update: '更新', status_change: '流转', link: '关联', comment: '评论' }
const ENTITIES = { requirement: '需求', task: '任务', defect: '缺陷', iteration: '迭代' }

function actionLabel(a) { return ACTIONS[a] || a }
function entityLabel(e) { return ENTITIES[e] || e }
function formatTime(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '' }

// StatusBars: simple inline functional component (CSS bar chart, no chart lib)
const StatusBars = {
  props: { counts: { type: Object, default: () => ({}) }, labels: { type: Object, default: () => ({}) } },
  setup(p) {
    const palette = ['#6366f1', '#8b5cf6', '#f59e0b', '#10b981', '#ef4444', '#0ea5e9', '#64748b']
    return () => {
      const entries = Object.entries(p.counts || {})
      const total = entries.reduce((s, [, v]) => s + v, 0)
      if (!total) return h('div', { class: 'ov-empty' }, '暂无数据')
      return h('div', { class: 'sb-wrap' }, entries.map(([k, v], i) => h('div', { class: 'sb-row', key: k }, [
        h('span', { class: 'sb-label' }, p.labels[k] || k),
        h('div', { class: 'sb-track' }, [h('div', { class: 'sb-fill', style: { width: (v / total * 100) + '%', background: palette[i % palette.length] } })]),
        h('span', { class: 'sb-val' }, String(v))
      ])))
    }
  }
}

async function load() {
  loading.value = true
  try {
    overview.value = await api.get(`/projects/${props.project.id}/overview`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ov-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.ov-metric__label { color: var(--color-text-secondary, #64748b); font-size: 13px; }
.ov-metric__value { font-size: 30px; font-weight: 700; margin: 6px 0; }
.ov-metric__sub { font-size: 12px; color: var(--color-text-secondary, #94a3b8); }
.ov-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.ov-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.ov-todo { list-style: none; padding: 0; margin: 0; line-height: 2.2; }
.ov-todo strong { color: #6366f1; }
:deep(.sb-wrap) { display: flex; flex-direction: column; gap: 10px; }
:deep(.sb-row) { display: flex; align-items: center; gap: 8px; }
:deep(.sb-label) { width: 64px; font-size: 12px; color: #64748b; }
:deep(.sb-track) { flex: 1; height: 10px; background: rgba(148,163,184,0.15); border-radius: 6px; overflow: hidden; }
:deep(.sb-fill) { height: 100%; border-radius: 6px; }
:deep(.sb-val) { width: 28px; text-align: right; font-size: 12px; font-weight: 600; }
:deep(.ov-empty) { color: #94a3b8; font-size: 13px; text-align: center; padding: 16px 0; }
@media (max-width: 960px) {
  .ov-metrics, .ov-grid, .ov-grid-2 { grid-template-columns: 1fr; }
}
</style>
