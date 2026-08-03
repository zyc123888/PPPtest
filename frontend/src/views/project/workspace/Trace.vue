<template>
  <div v-loading="loading">
    <div class="wb-toolbar page-card">
      <div class="wb-toolbar__left">
        <span class="wb-title">需求追溯矩阵</span>
        <span class="wb-sub">需求 ↔ 用例 ↔ 执行 ↔ 缺陷 全链路覆盖</span>
      </div>
      <el-button @click="fetchMatrix">刷新</el-button>
    </div>

    <el-card class="page-card" shadow="never">
      <el-table :data="rows" border stripe>
        <el-table-column label="需求" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="req-cell">
              <el-tag :type="statusType[row.requirement_status]" size="small" effect="plain">{{ statusLabels[row.requirement_status] || row.requirement_status }}</el-tag>
              <span>{{ row.requirement_title }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="90" align="center">
          <template #default="{ row }"><el-tag :type="priorityType[row.priority]" size="small" effect="plain">{{ row.priority }}</el-tag></template>
        </el-table-column>
        <el-table-column label="关联用例 (API/UI/PERF)" width="200" align="center">
          <template #default="{ row }">
            <span class="case-counts">
              <span class="cc api">{{ row.api_case_count }}</span>
              <span class="cc ui">{{ row.ui_case_count }}</span>
              <span class="cc perf">{{ row.perf_case_count }}</span>
              <span class="cc total">共 {{ row.total_case_count }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="最近执行" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.last_run_status" :type="runType(row.last_run_status)" size="small">{{ row.last_run_status }}</el-tag>
            <span v-else class="muted">未执行</span>
          </template>
        </el-table-column>
        <el-table-column label="缺陷 (开/关)" width="120" align="center">
          <template #default="{ row }">
            <span class="defect-counts">
              <span class="open" :class="{ warn: row.open_defect_count > 0 }">{{ row.open_defect_count }}</span>
              /
              <span class="closed">{{ row.closed_defect_count }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="覆盖状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="coverageType(row.coverage)" size="small">{{ coverageLabels[row.coverage] || row.coverage }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !rows.length" description="暂无需求，先在需求页创建" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import { REQUIREMENT_STATUS_LABELS, STATUS_TAG_TYPE, PRIORITY_TAG_TYPE } from './constants'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const statusLabels = REQUIREMENT_STATUS_LABELS
const statusType = STATUS_TAG_TYPE
const priorityType = PRIORITY_TAG_TYPE

const loading = ref(false)
const rows = ref([])

function runType(status) {
  const s = String(status).toUpperCase()
  if (['PASS', 'PASSED', 'SUCCESS'].includes(s)) return 'success'
  if (['FAIL', 'FAILED', 'ERROR'].includes(s)) return 'danger'
  return 'info'
}

const coverageLabels = { NONE: '未覆盖', COVERED: '已覆盖', UNTESTED: '待执行', FAILED: '执行失败' }
const coverageTypes = { NONE: 'info', COVERED: 'success', UNTESTED: 'warning', FAILED: 'danger' }
function coverageType(coverage) { return coverageTypes[coverage] || 'info' }

async function fetchMatrix() {
  loading.value = true
  try {
    const data = await api.get(`/projects/${props.project.id}/trace`)
    rows.value = data.rows || []
  } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
}

onMounted(fetchMatrix)
</script>

<style scoped>
.wb-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; margin-bottom: 12px; }
.wb-title { font-size: 15px; font-weight: 600; }
.wb-sub { color: #94a3b8; font-size: 12px; margin-left: 10px; }
.req-cell { display: flex; align-items: center; gap: 8px; }
.case-counts { display: inline-flex; align-items: center; gap: 6px; }
.cc { display: inline-block; min-width: 22px; padding: 1px 6px; border-radius: 6px; font-size: 12px; }
.cc.api { background: rgba(59,130,246,0.12); color: #2563eb; }
.cc.ui { background: rgba(168,85,247,0.12); color: #9333ea; }
.cc.perf { background: rgba(245,158,11,0.12); color: #d97706; }
.cc.total { background: rgba(148,163,184,0.14); color: #475569; }
.defect-counts .open { font-weight: 600; }
.defect-counts .open.warn { color: #ef4444; }
.defect-counts .closed { color: #94a3b8; }
.muted { color: #cbd5e1; font-size: 12px; }
</style>
