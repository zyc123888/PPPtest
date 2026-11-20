<template>
  <div class="app-page plan-page">
    <PageHeader title="测试计划" subtitle="编排回归用例、定时调度与批量执行入口">
      <template #actions>
        <div class="plan-header-actions">
          <el-button :loading="listLoading" @click="getList">刷新</el-button>
          <el-button v-if="canTest" type="primary" @click="handleCreate">新增计划</el-button>
        </div>
      </template>
    </PageHeader>

    <section class="overview-strip section-gap" aria-label="测试计划概览">
      <div class="overview-grid">
        <div class="overview-cell">
          <span class="overview-cell__label">计划总数</span>
          <strong class="overview-cell__val">{{ filteredList.length }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">
            <span class="dot dot--emerald" />
            可执行计划
          </span>
          <strong class="overview-cell__val">{{ activePlanCount }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">
            <span class="dot dot--sky" />
            已启定时调度
          </span>
          <strong class="overview-cell__val">{{ scheduledPlanCount }}</strong>
        </div>
        <div class="overview-cell">
          <span class="overview-cell__label">覆盖项目数</span>
          <strong class="overview-cell__val">{{ projectCount }}</strong>
        </div>
      </div>
    </section>

    <section class="surface-card">
      <div class="filter-bar">
        <div class="filter-bar__controls">
          <el-select
            v-model="filters.projectId"
            clearable
            filterable
            placeholder="全部项目"
            class="filter-item filter-item--project"
            @change="handleSearch"
          >
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>

          <el-input
            v-model="filters.keyword"
            clearable
            placeholder="搜索计划名称或说明…"
            class="filter-item filter-item--search"
            @keyup.enter="handleSearch"
            @clear="handleSearch"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>

          <el-button v-if="filters.projectId || filters.keyword" text size="small" @click="handleReset">
            重置
          </el-button>
        </div>

        <span class="filter-bar__meta">共 {{ filteredList.length }} 个计划</span>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" class="clean-table" row-class-name="plan-row">
        <el-table-column label="计划" min-width="280" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="plan-primary">
              <span class="state-dot" :class="row.status === 'ACTIVE' ? 'state-dot--success' : 'state-dot--muted'" />
              <div class="plan-cell">
                <div class="plan-cell__name">{{ row.name }}</div>
                <div class="plan-cell__desc">
                  <span class="mono-id">#{{ row.id }}</span>
                  <span class="sep">·</span>
                  <span>{{ row.description || '暂无计划说明' }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="所属项目" width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="project-chip">{{ projectMap[row.project_id] || `#${row.project_id}` }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <span class="status-text" :class="row.status === 'ACTIVE' ? 'status-text--success' : 'status-text--muted'">
              {{ row.status === 'ACTIVE' ? '启用' : row.status }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="定时调度" min-width="190">
          <template #default="{ row }">
            <div v-if="row.schedule_enabled" class="schedule-cell">
              <code class="schedule-cron">{{ row.schedule_cron }}</code>
              <span class="schedule-next">下次 {{ formatDateTime(row.next_run_at) }}</span>
            </div>
            <span v-else class="text-muted">未启用</span>
          </template>
        </el-table-column>

        <el-table-column label="" align="right" width="188" fixed="right">
          <template #default="{ row }">
            <div class="row-ops">
              <button v-if="canTest" type="button" class="op-link op-link--primary" @click="openRunDialog(row)">执行</button>
              <button v-if="canTest" type="button" class="op-link" @click="openCaseDialog(row)">用例配置</button>
              <el-dropdown v-if="canTest" trigger="click" @command="(cmd) => handlePlanCommand(cmd, row)">
                <button type="button" class="op-icon" aria-label="更多操作">
                  <el-icon><MoreFilled /></el-icon>
                </button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="schedule">定时执行</el-dropdown-item>
                    <el-dropdown-item command="edit">编辑计划</el-dropdown-item>
                    <el-dropdown-item v-if="canAdmin" command="delete" divided>删除计划</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">
            {{ projectMap[item.project_id] || item.project_id }} · {{ item.status === 'ACTIVE' ? '启用' : item.status }}
          </div>
          <div class="mobile-card-desc">{{ item.description || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button v-if="canTest" size="small" text type="primary" @click="openRunDialog(item)">执行</el-button>
            <el-button v-if="canTest" size="small" text @click="openCaseDialog(item)">用例配置</el-button>
            <el-button v-if="canTest" size="small" text @click="openScheduleDialog(item)">定时</el-button>
            <el-button v-if="canTest" size="small" text @click="handleEdit(item)">编辑</el-button>
            <el-button v-if="canAdmin" size="small" text type="danger" @click="handlePlanCommand('delete', item)">删除</el-button>
          </div>
        </div>
      </div>

      <div class="surface-footer">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </section>

    <el-dialog v-model="dialogVisible" :title="editingPlanId ? '编辑测试计划' : '新增测试计划'" width="560px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" :disabled="!!editingPlanId" placeholder="请选择项目" style="width: 100%">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划名称" prop="name">
          <el-input v-model="temp.name" placeholder="例如：核心回归" />
        </el-form-item>
        <el-form-item label="计划说明" prop="description">
          <el-input v-model="temp.description" type="textarea" :rows="4" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveData">确认</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="caseDialogVisible" title="计划用例配置" size="920px">
      <div class="section-gap">
        <el-alert
          v-if="moveResult"
          :title="moveResult.title"
          :description="moveResult.description"
          type="success"
          :closable="true"
          class="section-gap"
          @close="moveResult = null"
        >
          <template #default>
            <div class="move-result-actions">
              <el-button size="small" type="primary" @click="openMovedPlanCaseDialog">打开新计划</el-button>
            </div>
          </template>
        </el-alert>

        <el-form :inline="true" class="query-form" label-position="top" :model="caseForm">
          <el-form-item label="用例类型">
            <el-select v-model="caseForm.case_type" placeholder="请选择" style="width: 130px">
              <el-option label="API" value="API" />
              <el-option label="UI" value="UI" />
              <el-option label="PERF" value="PERF" />
            </el-select>
          </el-form-item>
          <el-form-item label="选择用例">
            <el-select v-model="caseForm.case_id" filterable placeholder="请选择" style="width: 300px">
              <el-option
                v-for="item in selectableCases"
                :key="item.id"
                :label="`${item.name} · ${item.review_status || 'DRAFT'} · ${item.version_no || '1.0.0'}`"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="顺序">
            <el-input-number v-model="caseForm.order_index" :min="1" style="width: 110px" />
          </el-form-item>
          <el-form-item v-if="canAdmin" label="评审覆盖">
            <el-checkbox v-model="caseForm.allow_unapproved">允许未通过评审</el-checkbox>
          </el-form-item>
          <el-form-item label=" " class="query-actions">
            <el-button v-if="canTest" type="primary" @click="addPlanCase">加入计划</el-button>
          </el-form-item>
        </el-form>

        <div class="plan-case-toolbar">
          <el-tag type="danger" effect="light">风险用例 {{ riskPlanCaseCount }}</el-tag>
          <el-select v-model="caseFilter.riskMode" size="small" style="width: 160px">
            <el-option label="全部用例" value="ALL" />
            <el-option label="仅风险用例" value="RISK_ONLY" />
            <el-option label="仅已通过评审" value="APPROVED_ONLY" />
            <el-option label="仅看带风险加入" value="OVERRIDE_ONLY" />
          </el-select>
          <el-button v-if="filteredPlanCases.length" size="small" @click="exportRiskCases">导出当前清单</el-button>
          <el-button
            v-if="canAdmin && filteredPlanCases.length && caseFilter.riskMode !== 'APPROVED_ONLY'"
            size="small"
            type="warning"
            plain
            @click="moveFilteredPlanCases"
          >
            复制到待评审计划
          </el-button>
          <el-button
            v-if="canAdmin && filteredPlanCases.length && caseFilter.riskMode !== 'APPROVED_ONLY'"
            size="small"
            type="danger"
            plain
            @click="removeFilteredPlanCases"
          >
            批量移除
          </el-button>
        </div>

        <div class="plan-case-hint">
          默认仅允许加入评审状态为 APPROVED 的用例。
          <span v-if="canAdmin">管理员勾选后可带风险加入，并记录添加人。</span>
          <span>调整顺序请切换到“全部用例”视图。</span>
        </div>
      </div>

      <el-table v-loading="caseLoading" :data="filteredPlanCases" class="clean-table">
        <el-table-column label="顺序" prop="order_index" width="64" align="center" />
        <el-table-column label="类型" prop="case_type" width="76" align="center" />
        <el-table-column label="用例名称" prop="case_name" min-width="200" show-overflow-tooltip />
        <el-table-column label="版本" width="90" align="center">
          <template #default="scope">
            {{ scope.row.case_snapshot_json?.version_no || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="评审" width="110" align="center">
          <template #default="scope">
            <el-tag
              size="small"
              :type="scope.row.case_snapshot_json?.review_status === 'APPROVED' ? 'success' : 'warning'"
            >
              {{ scope.row.case_snapshot_json?.review_status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="风险备注" min-width="150" show-overflow-tooltip>
          <template #default="scope">
            {{ scope.row.case_snapshot_json?.review_status === 'APPROVED' ? '-' : (scope.row.case_snapshot_json?.review_note || '带风险加入计划') }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="right">
          <template #default="scope">
            <div class="row-ops">
              <el-button
                v-if="canTest"
                link
                size="small"
                :disabled="caseFilter.riskMode !== 'ALL'"
                @click="movePlanCase(scope.row, 'up')"
              >
                上移
              </el-button>
              <el-button
                v-if="canTest"
                link
                size="small"
                :disabled="caseFilter.riskMode !== 'ALL'"
                @click="movePlanCase(scope.row, 'down')"
              >
                下移
              </el-button>
              <el-button v-if="canTest" link size="small" type="danger" @click="removePlanCase(scope.row)">移除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <el-dialog v-model="runDialogVisible" title="执行测试计划" width="520px">
      <el-form label-position="top">
        <el-form-item label="选择环境">
          <el-select v-model="runForm.environment_id" clearable placeholder="默认项目基础地址" style="width: 100%">
            <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
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

    <el-dialog v-model="scheduleDialogVisible" title="定时执行配置" width="560px">
      <el-form label-position="top">
        <el-form-item label="启用定时执行">
          <el-switch v-model="scheduleForm.schedule_enabled" />
        </el-form-item>
        <template v-if="scheduleForm.schedule_enabled">
          <el-form-item label="cron 表达式（5 段，按北京时间）" required>
            <div class="schedule-cron-row">
              <el-input v-model="scheduleForm.schedule_cron" placeholder="例如 0 2 * * *" style="width: 240px" />
              <el-select placeholder="常用预设" style="width: 190px" @change="applyCronPreset">
                <el-option v-for="item in cronPresets" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </div>
          </el-form-item>
          <el-form-item label="默认执行环境">
            <el-select v-model="scheduleForm.schedule_environment_id" clearable placeholder="默认项目基础地址" style="width: 100%">
              <el-option v-for="item in environments" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="单用例超时（秒，可选）">
            <el-input-number v-model="scheduleForm.schedule_timeout_seconds" :min="1" :max="7200" placeholder="默认" />
          </el-form-item>
          <el-form-item label="失败重试次数">
            <el-input-number v-model="scheduleForm.schedule_max_retries" :min="0" :max="3" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="scheduleDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="scheduleSaving" @click="submitSchedule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { getSavedProjectId, saveActiveProjectId } from '@/lib/projectContext'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled, Search } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const projects = ref([])
const apiCases = ref([])
const uiCases = ref([])
const perfCases = ref([])
const environments = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const editingPlanId = ref(null)
const caseDialogVisible = ref(false)
const runDialogVisible = ref(false)
const caseLoading = ref(false)
const dataFormRef = ref(null)
const { canAdmin, canTest } = usePermissions()

const currentPlan = ref(null)

const filters = reactive({
  projectId: undefined,
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  project_id: undefined,
  name: '',
  description: ''
})

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '计划名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }]
}

const caseForm = reactive({
  case_type: 'API',
  case_id: undefined,
  order_index: 1,
  allow_unapproved: false
})

const caseFilter = reactive({
  riskMode: 'ALL'
})

const runForm = reactive({
  environment_id: undefined
})

const scheduleDialogVisible = ref(false)
const scheduleSaving = ref(false)
const scheduleForm = reactive({
  schedule_enabled: false,
  schedule_cron: '',
  schedule_environment_id: undefined,
  schedule_timeout_seconds: undefined,
  schedule_max_retries: 0
})

const cronPresets = [
  { label: '每天 02:00', value: '0 2 * * *' },
  { label: '每小时整点', value: '0 * * * *' },
  { label: '工作日 09:00', value: '0 9 * * 1-5' },
  { label: '每分钟（调试）', value: '* * * * *' }
]

const planCases = ref([])
const precheckResult = ref(null)
const moveResult = ref(null)

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((p) => {
    map[p.id] = p.name
  })
  return map
})

const activePlanCount = computed(() => list.value.filter((item) => item.status === 'ACTIVE').length)
const scheduledPlanCount = computed(() => list.value.filter((item) => item.schedule_enabled).length)

const riskPlanCaseCount = computed(() =>
  planCases.value.filter((item) => item.case_snapshot_json?.review_status !== 'APPROVED').length
)

const filteredPlanCases = computed(() => {
  if (caseFilter.riskMode === 'RISK_ONLY') {
    return planCases.value.filter((item) => item.case_snapshot_json?.review_status !== 'APPROVED')
  }
  if (caseFilter.riskMode === 'APPROVED_ONLY') {
    return planCases.value.filter((item) => item.case_snapshot_json?.review_status === 'APPROVED')
  }
  if (caseFilter.riskMode === 'OVERRIDE_ONLY') {
    return planCases.value.filter((item) => item.case_snapshot_json?.review_status !== 'APPROVED' && item.created_by)
  }
  return planCases.value
})

const selectableCases = computed(() => {
  const source = caseForm.case_type === 'UI' ? uiCases.value : (caseForm.case_type === 'PERF' ? perfCases.value : apiCases.value)
  if (canAdmin.value && caseForm.allow_unapproved) {
    return source
  }
  return source.filter((item) => item.review_status === 'APPROVED')
})

const getList = async () => {
  listLoading.value = true
  try {
    const [planData, projectData] = await Promise.all([
      api.get('/test-plans'),
      api.get('/projects')
    ])
    list.value = planData
    projects.value = projectData
    if (!filters.projectId) {
      const saved = getSavedProjectId(projectData)
      if (saved) filters.projectId = saved
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

watch(() => filters.projectId, (val) => {
  saveActiveProjectId(val)
})

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((plan) => {
    if (filters.projectId && plan.project_id !== filters.projectId) return false
    if (!keyword) return true
    return (
      String(plan.name || '').toLowerCase().includes(keyword) ||
      String(plan.description || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const projectCount = computed(() => new Set(list.value.map((item) => item.project_id)).size)

const handleCreate = () => {
  editingPlanId.value = null
  temp.project_id = projects.value.length > 0 ? projects.value[0].id : undefined
  temp.name = ''
  temp.description = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleEdit = (row) => {
  editingPlanId.value = row.id
  temp.project_id = row.project_id
  temp.name = row.name || ''
  temp.description = row.description || ''
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

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        if (editingPlanId.value) {
          await api.put(`/test-plans/${editingPlanId.value}`, {
            name: temp.name,
            description: temp.description
          })
          ElMessage.success('更新成功')
        } else {
          await api.post('/test-plans', temp)
          ElMessage.success('创建成功')
        }
        dialogVisible.value = false
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const loadPlanCases = async (planId) => {
  caseLoading.value = true
  try {
    planCases.value = await api.get(`/test-plans/${planId}/cases`)
    caseForm.order_index = planCases.value.length + 1
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    caseLoading.value = false
  }
}

const loadCaseAssets = async (projectId) => {
  const [apiData, uiData, perfData, envData] = await Promise.all([
    api.get(`/api-cases?project_id=${projectId}`),
    api.get(`/ui-cases?project_id=${projectId}`),
    api.get(`/performance-cases?project_id=${projectId}`),
    api.get(`/environments?project_id=${projectId}`)
  ])
  apiCases.value = Array.isArray(apiData) ? apiData : (apiData?.items || [])
  uiCases.value = Array.isArray(uiData) ? uiData : (uiData?.items || [])
  perfCases.value = Array.isArray(perfData) ? perfData : (perfData?.items || [])
  environments.value = envData
}

const openCaseDialog = async (plan) => {
  currentPlan.value = plan
  moveResult.value = null
  caseForm.case_type = 'API'
  caseForm.case_id = undefined
  caseForm.order_index = 1
  caseForm.allow_unapproved = false
  caseFilter.riskMode = 'ALL'
  await loadCaseAssets(plan.project_id)
  await loadPlanCases(plan.id)
  caseDialogVisible.value = true
}

const addPlanCase = async () => {
  if (!currentPlan.value) return
  if (!caseForm.case_id) {
    ElMessage.warning('请选择用例')
    return
  }
  try {
    await api.post(`/test-plans/${currentPlan.value.id}/cases`, {
      case_type: caseForm.case_type,
      case_id: caseForm.case_id,
      order_index: caseForm.order_index,
      allow_unapproved: canAdmin.value ? caseForm.allow_unapproved : false
    })
    ElMessage.success('已加入计划')
    caseForm.allow_unapproved = false
    loadPlanCases(currentPlan.value.id)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const removePlanCase = async (row) => {
  if (!currentPlan.value) return
  try {
    await api.delete(`/test-plans/${currentPlan.value.id}/cases/${row.id}`)
    ElMessage.success('已移除')
    loadPlanCases(currentPlan.value.id)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const persistPlanCaseOrder = async () => {
  if (!currentPlan.value) return
  await api.post(`/test-plans/${currentPlan.value.id}/cases/reorder`, {
    items: planCases.value.map((item, index) => ({
      id: item.id,
      order_index: index + 1
    }))
  })
}

const movePlanCase = async (row, direction) => {
  if (!currentPlan.value) return
  if (caseFilter.riskMode !== 'ALL') {
    ElMessage.warning('请切换到“全部用例”后再调整顺序')
    return
  }
  const index = planCases.value.findIndex((item) => item.id === row.id)
  if (index < 0) return
  const targetIndex = direction === 'up' ? index - 1 : index + 1
  if (targetIndex < 0 || targetIndex >= planCases.value.length) return
  const next = [...planCases.value]
  const [moved] = next.splice(index, 1)
  next.splice(targetIndex, 0, moved)
  planCases.value = next.map((item, idx) => ({ ...item, order_index: idx + 1 }))
  try {
    await persistPlanCaseOrder()
  } catch (error) {
    ElMessage.error(error.message)
    await loadPlanCases(currentPlan.value.id)
  }
}

const openRunDialog = async (plan) => {
  currentPlan.value = plan
  runForm.environment_id = undefined
  precheckResult.value = null
  await loadCaseAssets(plan.project_id)
  runDialogVisible.value = true
}

const submitRun = async () => {
  if (!currentPlan.value) return
  try {
    const passed = await precheckRun()
    if (!passed) return
    await api.post(`/test-plans/${currentPlan.value.id}/run`, {
      environment_id: runForm.environment_id || null
    })
    ElMessage.success('计划已投递')
    runDialogVisible.value = false
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
  if (!currentPlan.value) return false
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  const result = await api.get(`/test-plans/${currentPlan.value.id}/precheck${suffix}`)
  return showPrecheckResult(result)
}

const handlePrecheck = async () => {
  try {
    await precheckRun()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const exportRiskCases = () => {
  if (!currentPlan.value || !filteredPlanCases.value.length) {
    ElMessage.warning('当前没有可导出的计划用例')
    return
  }
  const projectName = projectMap.value[currentPlan.value.project_id] || String(currentPlan.value.project_id)
  const filterLabelMap = {
    ALL: '全部用例',
    RISK_ONLY: '仅风险用例',
    APPROVED_ONLY: '仅已通过评审',
    OVERRIDE_ONLY: '仅看带风险加入'
  }
  const exportedAt = new Date().toLocaleString('zh-CN', { hour12: false })
  const rows = filteredPlanCases.value.map((item) => ({
    execution_advice:
      item.case_snapshot_json?.review_status === 'APPROVED'
        ? '可执行'
        : item.created_by
          ? '高风险'
          : '待评审',
    order_index: item.order_index,
    case_type: item.case_type,
    case_name: item.case_name,
    version_no: item.case_snapshot_json?.version_no || '',
    review_status: item.case_snapshot_json?.review_status || '',
    review_note: item.case_snapshot_json?.review_note || '',
    created_by: item.created_by || ''
  }))
  const header = ['执行建议', '顺序', '类型', '用例名称', '快照版本', '快照评审', '风险备注', '加入人']
  const meta = [
    ['项目', projectName],
    ['计划', currentPlan.value.name || '-'],
    ['筛选模式', filterLabelMap[caseFilter.riskMode] || caseFilter.riskMode],
    ['导出时间', exportedAt],
    []
  ]
  const lines = [
    ...meta.map((items) => items.map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`).join(',')),
    header.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(','),
    ...rows.map((row) =>
      [
        row.execution_advice,
        row.order_index,
        row.case_type,
        row.case_name,
        row.version_no,
        row.review_status,
        row.review_note,
        row.created_by
      ]
        .map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`)
        .join(',')
    )
  ]
  const blob = new Blob([`\uFEFF${lines.join('\n')}`], { type: 'text/csv;charset=utf-8;' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${currentPlan.value.name || 'plan'}-risk-cases.csv`
  link.click()
  URL.revokeObjectURL(link.href)
  ElMessage.success(`已导出 ${rows.length} 条计划用例`)
}

const removeFilteredPlanCases = async () => {
  if (!currentPlan.value || !filteredPlanCases.value.length) {
    ElMessage.warning('当前没有可移除的计划用例')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认移除当前筛选结果中的 ${filteredPlanCases.value.length} 条计划用例？`,
      '批量移除确认',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    )
    const ids = filteredPlanCases.value.map((item) => item.id)
    await api.post(`/test-plans/${currentPlan.value.id}/cases/batch-delete`, {
      plan_case_ids: ids
    })
    ElMessage.success(`已移除 ${ids.length} 条计划用例`)
    await loadPlanCases(currentPlan.value.id)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const moveFilteredPlanCases = async () => {
  if (!currentPlan.value || !filteredPlanCases.value.length) {
    ElMessage.warning('当前没有可转移的计划用例')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将把当前筛选结果中的 ${filteredPlanCases.value.length} 条用例复制到新建的待评审计划，原计划中的用例会保留。继续吗？`,
      '复制确认',
      { type: 'warning', confirmButtonText: '复制', cancelButtonText: '取消' }
    )
    const createdPlan = await api.post(`/test-plans/${currentPlan.value.id}/cases/copy-to-review`, {
      item_ids: filteredPlanCases.value.map((item) => item.id)
    })
    moveResult.value = {
      title: `已复制到待评审计划：${createdPlan.name}`,
      description: `来源计划：${currentPlan.value.name}。原计划用例已保留；新计划中的条目使用当前用例版本快照。`,
      plan_id: createdPlan.id,
      plan_name: createdPlan.name
    }
    ElMessage.success(`已复制 ${filteredPlanCases.value.length} 条用例到计划「${createdPlan.name}」，原计划内容已保留`)
    await getList()
    await loadPlanCases(currentPlan.value.id)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const openMovedPlanCaseDialog = async () => {
  if (!moveResult.value?.plan_id) return
  try {
    let targetPlan = list.value.find((item) => item.id === moveResult.value.plan_id)
    if (!targetPlan) {
      await getList()
      targetPlan = list.value.find((item) => item.id === moveResult.value.plan_id)
    }
    if (!targetPlan) {
      ElMessage.warning('未找到目标计划，请在列表中手动打开')
      return
    }
    await openCaseDialog(targetPlan)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handlePlanCommand = async (command, row) => {
  if (command === 'schedule') {
    openScheduleDialog(row)
    return
  }
  if (command === 'edit') {
    handleEdit(row)
    return
  }
  if (command !== 'delete') return
  try {
    await ElMessageBox.confirm(
      `确认删除测试计划「${row.name}」？该计划的历史报告与执行记录将一并删除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/test-plans/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const formatDateTime = (value) => {
  if (!value) return '-'
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

const applyCronPreset = (value) => {
  scheduleForm.schedule_cron = value
}

const openScheduleDialog = async (plan) => {
  currentPlan.value = plan
  scheduleForm.schedule_enabled = !!plan.schedule_enabled
  scheduleForm.schedule_cron = plan.schedule_cron || ''
  scheduleForm.schedule_environment_id = plan.schedule_environment_id || undefined
  scheduleForm.schedule_timeout_seconds = plan.schedule_timeout_seconds || undefined
  scheduleForm.schedule_max_retries = plan.schedule_max_retries || 0
  await loadCaseAssets(plan.project_id)
  scheduleDialogVisible.value = true
}

const submitSchedule = async () => {
  if (!currentPlan.value) return
  if (scheduleForm.schedule_enabled && !scheduleForm.schedule_cron.trim()) {
    ElMessage.warning('请填写 cron 表达式')
    return
  }
  scheduleSaving.value = true
  try {
    await api.put(`/test-plans/${currentPlan.value.id}/schedule`, {
      schedule_enabled: scheduleForm.schedule_enabled,
      schedule_cron: scheduleForm.schedule_enabled ? scheduleForm.schedule_cron.trim() : null,
      schedule_environment_id: scheduleForm.schedule_enabled ? scheduleForm.schedule_environment_id || null : null,
      schedule_timeout_seconds: scheduleForm.schedule_enabled ? scheduleForm.schedule_timeout_seconds || null : null,
      schedule_max_retries: scheduleForm.schedule_enabled ? scheduleForm.schedule_max_retries : 0
    })
    ElMessage.success(scheduleForm.schedule_enabled ? '定时执行已启用' : '定时执行已停用')
    scheduleDialogVisible.value = false
    getList()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    scheduleSaving.value = false
  }
}

watch(() => caseForm.case_type, () => {
  caseForm.case_id = undefined
})

watch(() => caseForm.allow_unapproved, () => {
  caseForm.case_id = undefined
})

watch(() => runForm.environment_id, () => {
  precheckResult.value = null
})

onMounted(() => {
  getList()
})
</script>

<style scoped>
.plan-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.overview-strip {
  border-radius: 18px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(22px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.overview-cell {
  padding: 14px 18px;
  border-right: 1px solid var(--color-border);
}

.overview-cell:last-child {
  border-right: none;
}

.overview-cell__label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #71717a;
}

.overview-cell__val {
  display: block;
  margin-top: 6px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.1;
  color: #09090b;
  font-variant-numeric: tabular-nums;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.dot--emerald { background: #16a34a; }
.dot--sky { background: #0284c7; }

.surface-card {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.filter-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.055);
  background: rgba(255, 255, 255, 0.45);
}

.filter-bar__controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-item--project { width: 170px; }
.filter-item--search { width: 220px; }

.filter-bar__meta {
  font-size: 12px;
  color: #71717a;
  font-variant-numeric: tabular-nums;
}

.clean-table {
  --el-table-border-color: #f4f4f5;
  --el-table-header-bg-color: #ffffff;
  --el-table-row-hover-bg-color: #fafafa;
}

.clean-table :deep(th.el-table__cell) {
  font-size: 11.5px;
  font-weight: 500;
  color: #71717a;
  padding: 9px 0;
  border-bottom: 1px solid var(--color-border);
}

.clean-table :deep(td.el-table__cell) {
  padding: 11px 0;
}

.plan-primary {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  flex-shrink: 0;
}

.state-dot--success { background: #16a34a; }
.state-dot--muted { background: #a1a1aa; }

.mono-id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #71717a;
  font-variant-numeric: tabular-nums;
}

.sep {
  margin: 0 5px;
  color: #d4d4d8;
}

.plan-cell {
  min-width: 0;
  flex: 1;
}

.plan-cell__name {
  font-size: 13px;
  font-weight: 500;
  color: #09090b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.plan-cell__desc {
  margin-top: 2px;
  font-size: 12px;
  color: #71717a;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-chip {
  display: inline-block;
  max-width: 100%;
  padding: 2px 7px;
  border-radius: 5px;
  border: 1px solid #e4e4e7;
  background: #fafafa;
  color: #3f3f46;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-text {
  font-size: 12.5px;
  font-weight: 500;
}

.status-text--success { color: #15803d; }
.status-text--muted { color: #71717a; }

.schedule-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.schedule-cron {
  display: inline-block;
  width: fit-content;
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid #e4e4e7;
  background: #fafafa;
  color: #18181b;
  font-family: var(--font-mono);
  font-size: 11.5px;
}

.schedule-next {
  font-size: 11px;
  color: #71717a;
  font-variant-numeric: tabular-nums;
}

.text-muted {
  font-size: 12px;
  color: #a1a1aa;
}

.row-ops {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  white-space: nowrap;
  opacity: 0.4;
  transition: opacity 0.14s ease;
}

.clean-table :deep(.plan-row:hover) .row-ops {
  opacity: 1;
}

.op-link {
  border: none;
  background: transparent;
  padding: 3px 6px;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 500;
  color: #52525b;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}

.op-link:hover {
  background: #f4f4f5;
  color: #09090b;
}

.op-link--primary { color: #0071e3; }
.op-link--primary:hover { background: rgba(0, 113, 227, 0.1); color: #0071e3; }

.op-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #71717a;
  cursor: pointer;
}

.op-icon:hover {
  background: #f4f4f5;
  color: #09090b;
}

.surface-footer {
  display: flex;
  justify-content: flex-end;
  padding: 10px 14px;
  border-top: 1px solid var(--color-border);
  background: #fafafa;
}

.mobile-cards {
  display: none;
}

.plan-case-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}

.schedule-cron-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.precheck-panel {
  margin-top: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
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

.plan-case-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.move-result-actions {
  margin-top: 8px;
}

@media (max-width: 960px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .filter-item--project,
  .filter-item--search {
    width: 100%;
  }

  .clean-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: 10px;
    padding: 12px;
  }

  .mobile-card {
    background: #ffffff;
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 12px 14px;
  }

  .mobile-card-title {
    font-weight: 600;
    margin-bottom: 4px;
  }

  .mobile-card-meta {
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .mobile-card-desc {
    font-size: 13px;
    color: var(--color-text);
    margin-bottom: 8px;
  }

  .mobile-card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding-top: 8px;
    border-top: 1px solid #f1f5f9;
  }
}
</style>
