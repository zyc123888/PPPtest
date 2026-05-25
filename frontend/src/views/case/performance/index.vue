<template>
  <div class="app-page">
    <PageHeader title="性能用例" subtitle="维护 HTTP 压测用例并投递性能执行任务">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增性能用例</el-button>
      </template>
    </PageHeader>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="所属项目">
          <el-select v-model="filters.projectId" clearable placeholder="全部" style="width: 200px">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="请求方法">
          <el-select v-model="filters.method" clearable placeholder="全部" style="width: 160px">
            <el-option label="GET" value="GET" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
            <el-option label="DELETE" value="DELETE" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="名称/路径" style="width: 260px" />
        </el-form-item>
        <el-form-item label=" " class="query-actions">
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="page-card" shadow="never">
      <div class="toolbar section-gap">
        <div />
        <div class="toolbar-right">
          <el-button @click="getList">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="项目" width="160" show-overflow-tooltip>
          <template #default="scope">{{ projectMap[scope.row.project_id] || scope.row.project_id }}</template>
        </el-table-column>
        <el-table-column label="名称" prop="name" min-width="180" show-overflow-tooltip />
        <el-table-column label="版本" prop="version_no" width="100" align="center" />
        <el-table-column label="评审" prop="review_status" width="110" align="center" />
        <el-table-column label="方法" prop="method" width="100" align="center" />
        <el-table-column label="路径" prop="path" min-width="220" show-overflow-tooltip />
        <el-table-column label="并发" prop="concurrency" width="90" align="center" />
        <el-table-column label="总请求数" prop="total_requests" width="110" align="center" />
        <el-table-column label="阈值" min-width="220" show-overflow-tooltip>
          <template #default="scope">{{ thresholdSummary(scope.row) }}</template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="280">
          <template #default="scope">
            <el-button v-if="canTest" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="handleRun(scope.row)">立即执行</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">项目：{{ projectMap[item.project_id] || item.project_id }}</div>
          <div class="mobile-card-meta">方法：{{ item.method }} · 并发：{{ item.concurrency }}</div>
          <div class="mobile-card-desc">{{ item.path }}</div>
          <div class="mobile-card-meta">阈值：{{ thresholdSummary(item) }}</div>
          <div class="mobile-card-actions">
            <el-button v-if="canTest" size="small" type="primary" @click="handleRun(item)">立即执行</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(item)">删除</el-button>
          </div>
        </div>
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑性能用例' : '新增性能用例'" width="700px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称" prop="name">
          <el-input v-model="temp.name" />
        </el-form-item>
        <el-form-item label="目录/分组">
          <el-input v-model="temp.folder_path" placeholder="例如：压测基线/系统接口" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="请求方法" prop="method">
              <el-select v-model="temp.method" style="width: 100%">
                <el-option label="GET" value="GET" />
                <el-option label="POST" value="POST" />
                <el-option label="PUT" value="PUT" />
                <el-option label="DELETE" value="DELETE" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="预期状态码" prop="expected_status">
              <el-input-number v-model="temp.expected_status" :min="100" :max="599" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="优先级" prop="priority">
              <el-select v-model="temp.priority" style="width: 100%">
                <el-option label="P0" value="P0" />
                <el-option label="P1" value="P1" />
                <el-option label="P2" value="P2" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="状态" prop="status">
              <el-select v-model="temp.status" style="width: 100%">
                <el-option label="ACTIVE" value="ACTIVE" />
                <el-option label="DISABLED" value="DISABLED" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="请求路径" prop="path">
          <el-input v-model="temp.path" placeholder="/api/v1/system/health" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：baseline、perf-smoke">
            <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="评审状态">
              <el-select v-model="temp.review_status" style="width: 100%">
                <el-option label="DRAFT" value="DRAFT" />
                <el-option label="IN_REVIEW" value="IN_REVIEW" />
                <el-option label="APPROVED" value="APPROVED" />
                <el-option label="REJECTED" value="REJECTED" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="当前版本">
              <el-input v-model="temp.version_no" disabled />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="评审备注">
          <el-input v-model="temp.review_note" type="textarea" :rows="3" placeholder="例如：压测基线已确认；或填写拒绝原因" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="并发数" prop="concurrency">
              <el-input-number v-model="temp.concurrency" :min="1" :max="50" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="总请求数" prop="total_requests">
              <el-input-number v-model="temp.total_requests" :min="1" :max="1000" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="平均响应阈值(ms)">
              <el-input-number v-model="temp.max_avg_response_ms" :min="1" :max="60000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="P95 阈值(ms)">
              <el-input-number v-model="temp.max_p95_response_ms" :min="1" :max="60000" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="错误率阈值">
              <el-input-number v-model="temp.max_error_rate" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="请求头 JSON" prop="headers_text">
          <el-input v-model="temp.headers_text" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="请求体 JSON" prop="body_text">
          <el-input v-model="temp.body_text" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveData">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="执行性能用例" width="520px">
      <el-form label-position="top" :model="runForm">
        <el-form-item label="执行环境">
          <el-select v-model="runForm.environment_id" clearable placeholder="不指定环境，使用项目基础地址" style="width: 100%">
            <el-option v-for="item in runEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="runForm.timeout_seconds" :min="1" :max="600" style="width: 100%" />
        </el-form-item>
      </el-form>
      <div v-if="precheckResult" class="precheck-panel">
        <div class="precheck-summary" :class="{ invalid: !precheckResult.is_valid }">{{ precheckResult.summary }}</div>
        <div v-if="precheckResult.missing_variables?.length" class="precheck-tags">
          <el-tag v-for="item in precheckResult.missing_variables" :key="item" size="small" type="danger">{{ item }}</el-tag>
        </div>
      </div>
      <template #footer>
        <el-button @click="handlePrecheck">执行前校验</el-button>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRun">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const projects = ref([])
const environments = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const runDialogVisible = ref(false)
const isEditing = ref(false)
const editingCaseId = ref(undefined)
const dataFormRef = ref(null)
const precheckResult = ref(null)
const { canAdmin, canTest } = usePermissions()

const filters = reactive({
  projectId: undefined,
  method: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  project_id: undefined,
  name: '',
  folder_path: '',
  method: 'GET',
  path: '',
  priority: 'P2',
  status: 'ACTIVE',
  review_status: 'DRAFT',
  version_no: '1.0.0',
  review_note: '',
  tags_json: [],
  headers_text: '{\n  "accept": "application/json"\n}',
  body_text: '',
  expected_status: 200,
  concurrency: 5,
  total_requests: 20,
  max_avg_response_ms: 1500,
  max_p95_response_ms: 2500,
  max_error_rate: 0.1
})

const runForm = reactive({
  case_id: undefined,
  project_id: undefined,
  environment_id: undefined,
  timeout_seconds: 120
})

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }],
  path: [{ required: true, message: '路径必填', trigger: 'blur' }],
  headers_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) JSON.parse(value)
        callback()
      } catch (e) {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }],
  body_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) JSON.parse(value)
        callback()
      } catch (e) {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }]
}

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((item) => {
    map[item.id] = item.name
  })
  return map
})

const tagOptions = computed(() => {
  const tags = new Set()
  list.value.forEach((item) => (item.tags_json || []).forEach((tag) => tags.add(tag)))
  return Array.from(tags).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))

const thresholdSummary = (item) => {
  return [
    item.max_avg_response_ms ? `AVG<=${item.max_avg_response_ms}ms` : null,
    item.max_p95_response_ms ? `P95<=${item.max_p95_response_ms}ms` : null,
    item.max_error_rate !== null && item.max_error_rate !== undefined ? `ERR<=${Math.round(item.max_error_rate * 100)}%` : null
  ].filter(Boolean).join('，') || '-'
}

const getList = async () => {
  listLoading.value = true
  try {
    const [caseData, projectData] = await Promise.all([
      api.get('/performance-cases'),
      api.get('/projects')
    ])
    list.value = caseData
    projects.value = projectData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((item) => {
    if (filters.projectId && item.project_id !== filters.projectId) return false
    if (filters.method && item.method !== filters.method) return false
    if (!keyword) return true
    return String(item.name || '').toLowerCase().includes(keyword) || String(item.path || '').toLowerCase().includes(keyword)
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const handleCreate = () => {
  temp.project_id = projects.value.length ? projects.value[0].id : undefined
  temp.name = ''
  temp.folder_path = ''
  temp.method = 'GET'
  temp.path = ''
  temp.priority = 'P2'
  temp.status = 'ACTIVE'
  temp.review_status = 'DRAFT'
  temp.version_no = '1.0.0'
  temp.review_note = ''
  temp.tags_json = []
  temp.headers_text = '{\n  "accept": "application/json"\n}'
  temp.body_text = ''
  temp.expected_status = 200
  temp.concurrency = 5
  temp.total_requests = 20
  temp.max_avg_response_ms = 1500
  temp.max_p95_response_ms = 2500
  temp.max_error_rate = 0.1
  isEditing.value = false
  editingCaseId.value = undefined
  dialogVisible.value = true
  nextTick(() => dataFormRef.value?.clearValidate())
}

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.projectId = undefined
  filters.method = ''
  filters.keyword = ''
  page.value = 1
}

const handleEdit = (row) => {
  temp.project_id = row.project_id
  temp.name = row.name
  temp.folder_path = row.folder_path || ''
  temp.method = row.method
  temp.path = row.path
  temp.priority = row.priority || 'P2'
  temp.status = row.status
  temp.review_status = row.review_status || 'DRAFT'
  temp.version_no = row.version_no || '1.0.0'
  temp.review_note = row.review_note || ''
  temp.tags_json = [...(row.tags_json || [])]
  temp.headers_text = row.headers_json ? JSON.stringify(row.headers_json, null, 2) : ''
  temp.body_text = row.body_json ? JSON.stringify(row.body_json, null, 2) : ''
  temp.expected_status = row.expected_status
  temp.concurrency = row.concurrency
  temp.total_requests = row.total_requests
  temp.max_avg_response_ms = row.max_avg_response_ms
  temp.max_p95_response_ms = row.max_p95_response_ms
  temp.max_error_rate = row.max_error_rate
  isEditing.value = true
  editingCaseId.value = row.id
  dialogVisible.value = true
  nextTick(() => dataFormRef.value?.clearValidate())
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      const payload = {
        project_id: temp.project_id,
        name: temp.name,
        folder_path: temp.folder_path || null,
        method: temp.method,
        path: temp.path,
        priority: temp.priority,
        status: temp.status,
        review_status: temp.review_status,
        version_no: temp.version_no,
        review_note: temp.review_note || null,
        tags_json: temp.tags_json.length ? temp.tags_json : null,
        headers_json: temp.headers_text ? JSON.parse(temp.headers_text) : null,
        body_json: temp.body_text ? JSON.parse(temp.body_text) : null,
        expected_status: temp.expected_status,
        concurrency: temp.concurrency,
        total_requests: temp.total_requests,
        max_avg_response_ms: temp.max_avg_response_ms,
        max_p95_response_ms: temp.max_p95_response_ms,
        max_error_rate: temp.max_error_rate
      }
      if (isEditing.value && editingCaseId.value) {
        await api.put(`/performance-cases/${editingCaseId.value}`, payload)
      } else {
        await api.post('/performance-cases', payload)
      }
      dialogVisible.value = false
      ElMessage.success(isEditing.value ? '更新成功' : '创建成功')
      getList()
    } catch (error) {
      ElMessage.error(error.message)
    }
  })
}

const handleRun = async (row) => {
  runForm.case_id = row.id
  runForm.project_id = row.project_id
  runForm.environment_id = undefined
  runForm.timeout_seconds = 120
  precheckResult.value = null
  try {
    environments.value = await api.get(`/environments?project_id=${row.project_id}`)
    runDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const precheckRun = async () => {
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  const result = await api.get(`/executions/perf/${runForm.case_id}/precheck${suffix}`)
  precheckResult.value = result
  if (result.is_valid) {
    ElMessage.success('执行预检通过')
    return true
  }
  return false
}

const handlePrecheck = async () => {
  try {
    await precheckRun()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitRun = async () => {
  try {
    const passed = await precheckRun()
    if (!passed) return
    await api.post(`/executions/perf/${runForm.case_id}/run`, {
      environment_id: runForm.environment_id,
      timeout_seconds: runForm.timeout_seconds,
      max_retries: 0
    })
    runDialogVisible.value = false
    ElMessage.success('性能任务已投递')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除性能用例「${row.name}」？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await api.delete(`/performance-cases/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  getList()
})
</script>

<style scoped>
.mobile-cards {
  display: none;
}

.precheck-panel {
  margin-top: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 12px;
  background: #f8fafc;
}

.precheck-summary {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.precheck-summary.invalid {
  color: var(--el-color-danger);
}

.precheck-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

@media (max-width: 960px) {
  .el-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: var(--space-12);
  }

  .mobile-card {
    background: #ffffff;
    border: 1px solid var(--el-border-color);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  }

  .mobile-card-title {
    font-weight: 600;
    margin-bottom: 6px;
  }

  .mobile-card-meta {
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .mobile-card-desc {
    font-size: 13px;
    color: var(--color-text);
    margin-bottom: 10px;
  }

  .mobile-card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-8);
  }
}
</style>
