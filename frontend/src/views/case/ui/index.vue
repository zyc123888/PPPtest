<template>
  <div class="app-page">
    <PageHeader title="UI 用例" subtitle="维护 Web UI 巡检用例并投递执行任务">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增 UI 用例</el-button>
      </template>
    </PageHeader>

    <div class="ui-hero section-gap">
      <el-card class="page-card ui-hero__main" shadow="never">
        <div class="ui-hero__kicker">Visual Checks</div>
        <div class="ui-hero__title">UI 巡检用例</div>
        <div class="ui-hero__subtitle">聚焦目标地址、期望文本和步骤定义，让页面巡检与执行预检保持同一套产品化体验。</div>
      </el-card>
      <el-card class="page-card ui-hero__stat" shadow="never">
        <el-statistic title="UI 用例" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card ui-hero__stat" shadow="never">
        <el-statistic title="项目数" :value="projectCount" />
      </el-card>
      <el-card class="page-card ui-hero__stat" shadow="never">
        <el-statistic title="标签数" :value="tagOptions.length" />
      </el-card>
      <el-card class="page-card ui-hero__stat" shadow="never">
        <el-statistic title="当前筛选" :value="filters.keyword ? '已筛选' : '全部'" />
      </el-card>
    </div>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="所属项目">
          <el-select v-model="filters.projectId" clearable placeholder="全部" style="width: 200px">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="名称/目标地址" style="width: 280px" />
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
          <el-dropdown>
            <el-button>
              更多
              <el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>导入</el-dropdown-item>
                <el-dropdown-item disabled>导出</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button @click="getList">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="项目" width="160" show-overflow-tooltip>
          <template #default="scope">
            {{ projectMap[scope.row.project_id] || scope.row.project_id }}
          </template>
        </el-table-column>
        <el-table-column label="名称" prop="name" min-width="180" show-overflow-tooltip />
        <el-table-column label="版本" prop="version_no" width="100" align="center" />
        <el-table-column label="评审" prop="review_status" width="110" align="center" />
        <el-table-column label="目标地址" prop="target_url" min-width="240" show-overflow-tooltip />
        <el-table-column label="期望文本" prop="expect_text" min-width="200" show-overflow-tooltip />
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
          <div class="mobile-card-meta">目标：{{ item.target_url }}</div>
          <div class="mobile-card-desc">期望：{{ item.expect_text }}</div>
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

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑 UI 用例' : '新增 UI 用例'" width="640px">
      <el-form
        ref="dataFormRef"
        :model="temp"
        :rules="rules"
        label-position="top"
      >
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option
              v-for="item in projects"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称" prop="name">
          <el-input v-model="temp.name" placeholder="请输入用例名称" />
        </el-form-item>
        <el-form-item label="目录/分组">
          <el-input v-model="temp.folder_path" placeholder="例如：首页巡检/登录流程" />
        </el-form-item>
        <el-form-item label="目标地址" prop="target_url">
          <el-input v-model="temp.target_url" placeholder="http://frontend:3000" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：smoke、ui-core">
            <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-row>
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
          <el-input v-model="temp.review_note" type="textarea" :rows="3" placeholder="例如：页面巡检通过，可进入回归；或填写拒绝原因" />
        </el-form-item>
        <el-form-item label="期望文本" prop="expect_text">
          <el-input v-model="temp.expect_text" placeholder="期望出现的文本" />
        </el-form-item>
        <el-form-item label="步骤 JSON" prop="steps_text">
          <el-input
            v-model="temp.steps_text"
            type="textarea"
            :rows="6"
            placeholder='[{"action": "goto", "value": "..."}]'
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveData">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="执行 UI 用例" width="520px">
      <el-form label-position="top" :model="runForm">
        <el-form-item label="执行环境">
          <el-select v-model="runForm.environment_id" clearable placeholder="不指定环境，直接使用用例目标地址" style="width: 100%">
            <el-option v-for="item in runEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="runForm.timeout_seconds" :min="1" :max="600" style="width: 100%" />
        </el-form-item>
        <el-form-item label="失败后自动重试">
          <el-input-number v-model="runForm.max_retries" :min="0" :max="3" style="width: 100%" />
        </el-form-item>
      </el-form>
      <div v-if="precheckResult" class="precheck-panel">
        <div class="precheck-summary" :class="{ invalid: !precheckResult.is_valid }">{{ precheckResult.summary }}</div>
        <div v-if="precheckResult.missing_variables?.length" class="precheck-tags">
          <el-tag v-for="item in precheckResult.missing_variables" :key="item" size="small" type="danger">{{ item }}</el-tag>
        </div>
        <el-table
          v-if="precheckResult.issues?.length"
          :data="precheckResult.issues.slice(0, 20)"
          size="small"
          border
          class="precheck-table"
        >
          <el-table-column label="范围" prop="scope" min-width="140" show-overflow-tooltip />
          <el-table-column label="字段" prop="field" min-width="140" show-overflow-tooltip />
          <el-table-column label="缺失变量" min-width="160" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.missing_variables.join(', ') }}
            </template>
          </el-table-column>
        </el-table>
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
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
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
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  project_id: undefined,
  name: '',
  folder_path: '',
  target_url: '',
  review_status: 'DRAFT',
  version_no: '1.0.0',
  review_note: '',
  expect_text: '',
  tags_json: [],
  steps_text: ''
})

const runForm = reactive({
  case_id: undefined,
  project_id: undefined,
  environment_id: undefined,
  timeout_seconds: 60,
  max_retries: 0
})

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }],
  target_url: [{ required: true, message: '目标地址必填', trigger: 'blur' }],
  expect_text: [{ required: true, message: '期望文本必填', trigger: 'blur' }],
  steps_text: [{
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
  projects.value.forEach(p => {
    map[p.id] = p.name
  })
  return map
})

const tagOptions = computed(() => {
  const tags = new Set()
  list.value.forEach((item) => (item.tags_json || []).forEach((tag) => tags.add(tag)))
  return Array.from(tags).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((c) => {
    if (filters.projectId && c.project_id !== filters.projectId) return false
    if (!keyword) return true
    return (
      String(c.name || '').toLowerCase().includes(keyword) ||
      String(c.target_url || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const projectCount = computed(() => new Set(list.value.map((item) => item.project_id)).size)

const getList = async () => {
  listLoading.value = true
  try {
    const [caseData, projectData] = await Promise.all([
      api.get('/ui-cases'),
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

const handleCreate = () => {
  temp.project_id = projects.value.length > 0 ? projects.value[0].id : undefined
  temp.name = ''
  temp.folder_path = ''
  temp.target_url = 'http://frontend:3000'
  temp.review_status = 'DRAFT'
  temp.version_no = '1.0.0'
  temp.review_note = ''
  temp.expect_text = ''
  temp.tags_json = []
  temp.steps_text = '[\n  {\n    "action": "goto",\n    "value": "http://frontend:3000"\n  }\n]'
  isEditing.value = false
  editingCaseId.value = undefined
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.projectId = undefined
  filters.keyword = ''
  page.value = 1
}

const handleEdit = (row) => {
  temp.project_id = row.project_id
  temp.name = row.name
  temp.folder_path = row.folder_path || ''
  temp.target_url = row.target_url
  temp.review_status = row.review_status || 'DRAFT'
  temp.version_no = row.version_no || '1.0.0'
  temp.review_note = row.review_note || ''
  temp.expect_text = row.expect_text
  temp.tags_json = [...(row.tags_json || [])]
  temp.steps_text = row.steps_json ? JSON.stringify(row.steps_json, null, 2) : '[]'
  isEditing.value = true
  editingCaseId.value = row.id
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        const payload = {
          project_id: temp.project_id,
          name: temp.name,
          folder_path: temp.folder_path || null,
          target_url: temp.target_url,
          review_status: temp.review_status,
          version_no: temp.version_no,
          review_note: temp.review_note || null,
          expect_text: temp.expect_text,
          tags_json: temp.tags_json.length ? temp.tags_json : null,
          steps_json: temp.steps_text ? JSON.parse(temp.steps_text) : []
        }
        if (isEditing.value && editingCaseId.value) {
          await api.put(`/ui-cases/${editingCaseId.value}`, payload)
        } else {
          await api.post('/ui-cases', payload)
        }
        dialogVisible.value = false
        ElMessage.success(isEditing.value ? '更新成功' : '创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const handleRun = async (row) => {
  runForm.case_id = row.id
  runForm.project_id = row.project_id
  runForm.environment_id = undefined
  runForm.timeout_seconds = 60
  runForm.max_retries = 0
  precheckResult.value = null
  try {
    environments.value = await api.get(`/environments?project_id=${row.project_id}`)
    runDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitRun = async () => {
  try {
    const passed = await precheckRun()
    if (!passed) return
    await api.post(`/executions/ui/${runForm.case_id}/run`, {
      environment_id: runForm.environment_id,
      timeout_seconds: runForm.timeout_seconds,
      max_retries: runForm.max_retries
    })
    runDialogVisible.value = false
    ElMessage.success('任务已投递')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const showPrecheckResult = async (result) => {
  precheckResult.value = result
  if (result.is_valid) {
    ElMessage.success('执行预检通过')
    return true
  }
  return false
}

const precheckRun = async () => {
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  const result = await api.get(`/executions/ui/${runForm.case_id}/precheck${suffix}`)
  return showPrecheckResult(result)
}

const handlePrecheck = async () => {
  try {
    await precheckRun()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除 UI 用例「${row.name}」？该用例将从测试计划中自动移除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/ui-cases/${row.id}`)
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
.ui-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.ui-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.26), transparent 35%);
  color: #f8fafc;
}

.ui-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.ui-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.ui-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.ui-hero__stat {
  border-radius: 18px;
}

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

.precheck-table {
  margin-top: 12px;
}

@media (max-width: 960px) {
  .ui-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ui-hero__main {
    grid-column: 1 / -1;
  }

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
    gap: var(--space-8);
  }
}
</style>
