<template>
  <section class="review-panel">
    <div class="review-panel__head">
      <h3>评审</h3>
      <el-tag effect="plain" :type="reviewTag(caseData.review_status)">{{ reviewText(caseData.review_status) }}</el-tag>
    </div>
    <el-descriptions :column="2" size="small" border>
      <el-descriptions-item label="提交评审时间">{{ formatTime(caseData.submitted_review_at) }}</el-descriptions-item>
      <el-descriptions-item label="评审人">{{ caseData.reviewed_by ? `用户 #${caseData.reviewed_by}` : '-' }}</el-descriptions-item>
      <el-descriptions-item label="评审时间">{{ formatTime(caseData.reviewed_at) }}</el-descriptions-item>
      <el-descriptions-item label="评审意见">{{ caseData.review_note || '-' }}</el-descriptions-item>
    </el-descriptions>

    <div class="review-panel__actions">
      <el-button
        v-if="canSubmit"
        type="primary"
        plain
        :loading="submitting"
        @click="submitReview"
      >提交评审</el-button>
      <template v-if="canDecide">
        <el-input v-model="decideNote" class="review-panel__note" placeholder="评审意见（拒绝时建议填写）" clearable />
        <el-button type="success" :loading="deciding" @click="decide('APPROVED')">通过</el-button>
        <el-button type="danger" plain :loading="deciding" @click="decide('REJECTED')">拒绝</el-button>
      </template>
      <span v-else-if="isAuthor && caseData.review_status === 'IN_REVIEW'" class="review-panel__hint">
        评审中：不能评审自己创建的用例，请等待其他成员处理
      </span>
    </div>

    <div class="review-panel__history">
      <div class="review-panel__history-head">
        <h4>评审历史</h4>
        <el-button text size="small" :icon="Refresh" :loading="historyLoading" aria-label="刷新评审历史" @click="loadHistory" />
      </div>
      <el-empty v-if="!historyRows.length" description="暂无评审记录" :image-size="48" />
      <div v-for="row in historyRows" :key="row.id" class="review-history-item">
        <el-tag size="small" effect="plain" :type="reviewTag(row.review_status)">{{ reviewText(row.review_status) }}</el-tag>
        <div class="review-history-item__body">
          <strong>{{ row.summary || row.action }}</strong>
          <span>{{ row.changed_by ? `用户 #${row.changed_by}` : '-' }} · {{ formatTime(row.created_at) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { api } from '@/lib/api'

const props = defineProps({
  caseData: { type: Object, required: true },
  canTest: { type: Boolean, default: false },
  currentUserId: { type: Number, default: null },
  caseType: { type: String, default: 'UI', validator: (value) => ['UI', 'API', 'PERF'].includes(value) }
})
const emit = defineEmits(['changed'])

const CASE_PREFIX_MAP = { API: 'api-cases', UI: 'ui-cases', PERF: 'performance-cases' }
const casePrefix = computed(() => CASE_PREFIX_MAP[props.caseType] || 'ui-cases')

const submitting = ref(false)
const deciding = ref(false)
const decideNote = ref('')
const historyRows = ref([])
const historyLoading = ref(false)

const isAuthor = computed(() => props.caseData.created_by != null && props.caseData.created_by === props.currentUserId)
const canSubmit = computed(() => props.canTest && ['DRAFT', 'REJECTED'].includes(props.caseData.review_status))
const canDecide = computed(() => props.canTest && props.caseData.review_status === 'IN_REVIEW' && !isAuthor.value)

const reviewText = (status) => ({ DRAFT: '草稿', IN_REVIEW: '评审中', APPROVED: '已通过', REJECTED: '已拒绝' }[status] || status || '-')
const reviewTag = (status) => ({ APPROVED: 'success', IN_REVIEW: 'warning', REJECTED: 'danger', DRAFT: 'info' }[status] || 'info')
const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN') : '-')

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const rows = await api.get(`/cases/${props.caseType}/${props.caseData.id}/history`)
    historyRows.value = (rows || []).filter((row) => row.action === 'REVIEW' || /评审/.test(row.summary || ''))
  } catch {
    historyRows.value = []
  } finally {
    historyLoading.value = false
  }
}

const submitReview = async () => {
  submitting.value = true
  try {
    await api.post(`/${casePrefix.value}/${props.caseData.id}/review/submit`)
    ElMessage.success('已提交评审')
    emit('changed')
    await loadHistory()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    submitting.value = false
  }
}

const decide = async (result) => {
  deciding.value = true
  try {
    await api.post(`/${casePrefix.value}/${props.caseData.id}/review/decide`, {
      result,
      note: decideNote.value.trim() || null
    })
    ElMessage.success(result === 'APPROVED' ? '评审已通过' : '评审已拒绝')
    decideNote.value = ''
    emit('changed')
    await loadHistory()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    deciding.value = false
  }
}

watch(() => props.caseData.id, loadHistory, { immediate: true })
</script>

<style scoped>
.review-panel { margin-top: 22px; }
.review-panel__head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.review-panel__head h3 { margin: 0; font-size: 14px; }
.review-panel__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.review-panel__note { flex: 1; min-width: 200px; }
.review-panel__hint { color: var(--color-text-secondary); font-size: 12px; }
.review-panel__history { margin-top: 16px; }
.review-panel__history-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.review-panel__history-head h4 { margin: 0; font-size: 13px; }
.review-history-item { display: flex; align-items: flex-start; gap: 10px; padding: 8px 2px; border-bottom: 1px solid var(--el-border-color-lighter); }
.review-history-item__body { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.review-history-item__body strong { font-size: 12px; }
.review-history-item__body span { color: var(--color-text-secondary); font-size: 11px; }
</style>
