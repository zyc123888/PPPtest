<template>
  <div class="shared-report">
    <div class="shared-report__inner" v-loading="loading">
      <header class="shared-report__head">
        <h1>测试报告分享</h1>
        <p class="shared-report__sub">只读视图 · 无需登录即可查看</p>
      </header>

      <el-result
        v-if="error"
        icon="warning"
        title="无法访问该报告"
        :sub-title="error"
      />

      <template v-else-if="loaded">
        <el-descriptions :column="3" border class="shared-report__section">
          <el-descriptions-item label="计划">{{ report.plan_name || report.plan_run.plan_id }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusType(report.plan_run.status)">{{ statusText(report.plan_run.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="错误类型">{{ errorTypeText(report.plan_run.error_type) }}</el-descriptions-item>
          <el-descriptions-item label="总数">{{ report.plan_run.total_count }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ report.plan_run.pass_count }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ report.plan_run.fail_count }}</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatTime(report.plan_run.started_at) }}</el-descriptions-item>
          <el-descriptions-item label="结束时间">{{ formatTime(report.plan_run.finished_at) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ formatDuration(report.plan_run.duration_ms) }}</el-descriptions-item>
        </el-descriptions>

        <el-table :data="report.test_runs" border class="shared-report__section">
          <el-table-column label="类型" prop="case_type" width="90" align="center" />
          <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="110" align="center">
            <template #default="scope">
              <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="摘要" prop="summary" min-width="220" show-overflow-tooltip />
          <el-table-column label="错误类型" width="120" align="center">
            <template #default="scope">
              <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
                {{ errorTypeText(scope.row.error_type) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="110" align="center">
            <template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template>
          </el-table-column>
        </el-table>
      </template>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/lib/api'
import {
  executionErrorTypeTag as errorTypeTag,
  executionErrorTypeText as errorTypeText,
  executionStatusTag as statusType,
  executionStatusText as statusText
} from '@/lib/execution'

const route = useRoute()
const loading = ref(false)
const loaded = ref(false)
const error = ref('')
const report = reactive({
  plan_name: '',
  plan_run: {},
  test_runs: [],
  recent_history: [],
  defects: []
})

function formatTime(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '-' }
function formatDuration(ms) {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

onMounted(async () => {
  const token = route.params.token
  if (!token) { error.value = '分享链接无效'; return }
  loading.value = true
  try {
    const data = await api.get(`/public/reports/${token}`)
    report.plan_name = data.plan_name || ''
    report.plan_run = data.plan_run
    report.test_runs = data.test_runs || []
    report.recent_history = data.recent_history || []
    report.defects = data.defects || []
    loaded.value = true
  } catch (e) {
    error.value = e.message || '该分享链接不存在或已被关闭'
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.shared-report { min-height: 100vh; background: var(--el-bg-color-page, #f5f7fa); padding: 24px 16px; }
.shared-report__inner { max-width: 1080px; margin: 0 auto; background: var(--el-bg-color, #fff); border-radius: 8px; padding: 24px; box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06); }
.shared-report__head { margin-bottom: 20px; }
.shared-report__head h1 { margin: 0; font-size: 20px; }
.shared-report__sub { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 13px; }
.shared-report__section { margin-bottom: 20px; }
</style>
