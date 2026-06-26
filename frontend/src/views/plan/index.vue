<template>
  <div class="app-page">
    <PageHeader title="测试计划" subtitle="编排回归计划并统一执行">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增计划</el-button>
      </template>
    </PageHeader>

    <div class="plan-hero section-gap">
      <el-card class="page-card plan-hero__main" shadow="never">
        <div class="plan-hero__kicker">Execution Orchestration</div>
        <div class="plan-hero__title">测试计划是执行的编排入口</div>
        <div class="plan-hero__subtitle">把计划、用例配置和执行动作放在同一层级，减少切换成本，保证回归闭环清晰可见。</div>
      </el-card>
      <el-card class="page-card plan-hero__stat" shadow="never">
        <el-statistic title="计划数量" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card plan-hero__stat" shadow="never">
        <el-statistic title="项目数" :value="projectCount" />
      </el-card>
      <el-card class="page-card plan-hero__stat" shadow="never">
        <el-statistic title="可执行计划" :value="list.filter((item) => item.status === 'ACTIVE').length" />
      </el-card>
      <el-card class="page-card plan-hero__stat" shadow="never">
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
          <el-input v-model="filters.keyword" clearable placeholder="计划名称/说明" style="width: 260px" />
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
        <el-table-column label="项目" width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ projectMap[scope.row.project_id] || scope.row.project_id }}
          </template>
        </el-table-column>
        <el-table-column label="计划名称" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="说明" prop="description" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" prop="status" width="120" align="center" />
        <el-table-column label="操作" align="center" width="300">
          <template #default="scope">
            <el-button v-if="canTest" size="small" @click="openCaseDialog(scope.row)">用例配置</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="openRunDialog(scope.row)">执行计划</el-button>
            <el-dropdown v-if="canAdmin" @command="(cmd) => handlePlanCommand(cmd, scope.row)">
              <el-button size="small">
                更多
                <el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">项目：{{ projectMap[item.project_id] || item.project_id }}</div>
          <div class="mobile-card-meta">状态：{{ item.status }}</div>
          <div class="mobile-card-desc">{{ item.description || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button v-if="canTest" size="small" @click="openCaseDialog(item)">用例配置</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="openRunDialog(item)">执行计划</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handlePlanCommand('delete', item)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" title="新增测试计划" width="620px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
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
        <el-button type="primary" @click="createData">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="caseDialogVisible" title="计划用例配置" width="980px">
      <template #default>
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
              <el-select v-model="caseForm.case_type" placeholder="请选择" style="width: 160px">
                <el-option label="API" value="API" />
                <el-option label="UI" value="UI" />
              </el-select>
            </el-form-item>
            <el-form-item label="选择用例">
              <el-select v-model="caseForm.case_id" placeholder="请选择" style="width: 320px">
                <el-option
                  v-for="item in selectableCases"
                  :key="item.id"
                  :label="`${item.name} · ${item.review_status || 'DRAFT'} · ${item.version_no || '1.0.0'}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="顺序">
              <el-input-number v-model="caseForm.order_index" :min="1" />
            </el-form-item>
            <el-form-item v-if="canAdmin" label="评审覆盖">
              <el-checkbox v-model="caseForm.allow_unapproved">允许加入未通过评审用例</el-checkbox>
            </el-form-item>
            <el-form-item label=" " class="query-actions">
              <el-button v-if="canTest" type="primary" @click="addPlanCase">加入计划</el-button>
            </el-form-item>
          </el-form>
          <div class="plan-case-toolbar">
            <el-tag type="danger" effect="light">风险用例 {{ riskPlanCaseCount }}</el-tag>
            <el-select v-model="caseFilter.riskMode" style="width: 180px">
              <el-option label="全部用例" value="ALL" />
              <el-option label="仅风险用例" value="RISK_ONLY" />
              <el-option label="仅已通过评审" value="APPROVED_ONLY" />
              <el-option label="仅看带风险加入" value="OVERRIDE_ONLY" />
            </el-select>
            <el-button
              v-if="filteredPlanCases.length"
              size="small"
              @click="exportRiskCases"
            >
              导出当前清单
            </el-button>
            <el-button
              v-if="canAdmin && filteredPlanCases.length && caseFilter.riskMode !== 'APPROVED_ONLY'"
              size="small"
              type="warning"
              @click="moveFilteredPlanCases"
            >
              转移到待评审计划
            </el-button>
            <el-button
              v-if="canAdmin && filteredPlanCases.length && caseFilter.riskMode !== 'APPROVED_ONLY'"
              size="small"
              type="danger"
              @click="removeFilteredPlanCases"
            >
              批量移除当前结果
            </el-button>
          </div>
          <div class="plan-case-hint">
            默认仅允许加入评审状态为 `APPROVED` 的用例。
            <span v-if="canAdmin">管理员勾选后可带风险加入，并记录添加人。</span>
            <span>调整顺序请切换到“全部用例”视图。</span>
          </div>
        </div>

        <el-table v-loading="caseLoading" :data="filteredPlanCases" border>
          <el-table-column label="顺序" prop="order_index" width="80" align="center" />
          <el-table-column label="类型" prop="case_type" width="90" align="center" />
          <el-table-column label="用例名称" prop="case_name" min-width="220" show-overflow-tooltip />
          <el-table-column label="快照版本" min-width="120" align="center">
            <template #default="scope">
              {{ scope.row.case_snapshot_json?.version_no || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="快照评审" min-width="140" align="center">
            <template #default="scope">
              <el-tag
                size="small"
                :type="scope.row.case_snapshot_json?.review_status === 'APPROVED' ? 'success' : 'warning'"
              >
                {{ scope.row.case_snapshot_json?.review_status || '-' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="加入人" prop="created_by" width="100" align="center" />
          <el-table-column label="风险备注" min-width="180" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.case_snapshot_json?.review_status === 'APPROVED' ? '-' : (scope.row.case_snapshot_json?.review_note || '带风险加入计划') }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center">
            <template #default="scope">
              <el-button
                v-if="canTest"
                size="small"
                :disabled="caseFilter.riskMode !== 'ALL'"
                @click="movePlanCase(scope.row, 'up')"
              >
                上移
              </el-button>
              <el-button
                v-if="canTest"
                size="small"
                :disabled="caseFilter.riskMode !== 'ALL'"
                @click="movePlanCase(scope.row, 'down')"
              >
                下移
              </el-button>
              <el-button v-if="canAdmin" size="small" type="danger" @click="removePlanCase(scope.row)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>

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
import { computed, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const projects = ref([])
const apiCases = ref([])
const uiCases = ref([])
const environments = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
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
  const source = caseForm.case_type === 'UI' ? uiCases.value : apiCases.value
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
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

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
  temp.project_id = projects.value.length > 0 ? projects.value[0].id : undefined
  temp.name = ''
  temp.description = ''
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

const createData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        await api.post('/test-plans', temp)
        dialogVisible.value = false
        ElMessage.success('创建成功')
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
  const [apiData, uiData, envData] = await Promise.all([
    api.get(`/api-cases?project_id=${projectId}`),
    api.get(`/ui-cases?project_id=${projectId}`),
    api.get(`/environments?project_id=${projectId}`)
  ])
  apiCases.value = apiData
  uiCases.value = uiData
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
      order_index: index + 1,
    })),
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
    return
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
    OVERRIDE_ONLY: '仅看带风险加入',
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
    created_by: item.created_by || '',
  }))
  const header = ['执行建议', '顺序', '类型', '用例名称', '快照版本', '快照评审', '风险备注', '加入人']
  const meta = [
    ['项目', projectName],
    ['计划', currentPlan.value.name || '-'],
    ['筛选模式', filterLabelMap[caseFilter.riskMode] || caseFilter.riskMode],
    ['导出时间', exportedAt],
    [],
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
        row.created_by,
      ]
        .map((value) => `"${String(value ?? '').replace(/"/g, '""')}"`)
        .join(',')
    ),
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
    for (const item of filteredPlanCases.value) {
      await api.delete(`/test-plans/${currentPlan.value.id}/cases/${item.id}`)
    }
    ElMessage.success(`已移除 ${filteredPlanCases.value.length} 条计划用例`)
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
      `确认把当前筛选结果中的 ${filteredPlanCases.value.length} 条用例转移到新建的待评审计划？`,
      '转移确认',
      { type: 'warning', confirmButtonText: '转移', cancelButtonText: '取消' }
    )
    const createdPlan = await api.post('/test-plans', {
      project_id: currentPlan.value.project_id,
      name: `${currentPlan.value.name}-待评审-${new Date().toISOString().slice(0, 10)}`,
      description: `由计划「${currentPlan.value.name}」转移出的待评审风险用例`,
    })
    await api.post(`/test-plans/${createdPlan.id}/cases/batch`, {
      items: filteredPlanCases.value.map((item) => ({
        case_type: item.case_type,
        case_id: item.case_id,
      })),
      order_start: 1,
      allow_unapproved: true,
    })
    for (const item of filteredPlanCases.value) {
      await api.delete(`/test-plans/${currentPlan.value.id}/cases/${item.id}`)
    }
    moveResult.value = {
      title: `已转移到待评审计划：${createdPlan.name}`,
      description: `来源计划：${currentPlan.value.name}。新计划说明已写入来源信息，可在计划列表中继续跟踪。`,
      plan_id: createdPlan.id,
      plan_name: createdPlan.name,
    }
    ElMessage.success(`已转移 ${filteredPlanCases.value.length} 条用例到计划「${createdPlan.name}」`)
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
.plan-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.plan-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.26), transparent 35%);
  color: #f8fafc;
}

.plan-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.plan-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.plan-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.plan-hero__stat {
  border-radius: 18px;
}

.mobile-cards {
  display: none;
}

.plan-case-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
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

.plan-case-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.move-result-actions {
  margin-top: 8px;
}

@media (max-width: 960px) {
  .plan-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .plan-hero__main {
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
    flex-wrap: wrap;
    gap: var(--space-8);
  }
}
</style>
