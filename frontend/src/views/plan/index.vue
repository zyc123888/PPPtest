<template>
  <div class="app-page">
    <PageHeader title="测试计划" subtitle="编排回归计划并统一执行">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增计划</el-button>
      </template>
    </PageHeader>

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

    <el-dialog v-model="caseDialogVisible" title="计划用例配置" width="860px">
      <template #default>
        <div class="section-gap">
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
                  :label="item.name"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="顺序">
              <el-input-number v-model="caseForm.order_index" :min="1" />
            </el-form-item>
            <el-form-item label=" " class="query-actions">
              <el-button v-if="canTest" type="primary" @click="addPlanCase">加入计划</el-button>
            </el-form-item>
          </el-form>
        </div>

        <el-table v-loading="caseLoading" :data="planCases" border>
          <el-table-column label="顺序" prop="order_index" width="80" align="center" />
          <el-table-column label="类型" prop="case_type" width="90" align="center" />
          <el-table-column label="用例名称" prop="case_name" min-width="220" show-overflow-tooltip />
          <el-table-column label="操作" width="120" align="center">
            <template #default="scope">
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
      <template #footer>
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
  order_index: 1
})

const runForm = reactive({
  environment_id: undefined
})

const planCases = ref([])

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((p) => {
    map[p.id] = p.name
  })
  return map
})

const selectableCases = computed(() => {
  return caseForm.case_type === 'UI' ? uiCases.value : apiCases.value
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
  caseForm.case_type = 'API'
  caseForm.case_id = undefined
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
      order_index: caseForm.order_index
    })
    ElMessage.success('已加入计划')
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

const openRunDialog = async (plan) => {
  currentPlan.value = plan
  runForm.environment_id = undefined
  await loadCaseAssets(plan.project_id)
  runDialogVisible.value = true
}

const submitRun = async () => {
  if (!currentPlan.value) return
  try {
    await api.post(`/test-plans/${currentPlan.value.id}/run`, {
      environment_id: runForm.environment_id || null
    })
    ElMessage.success('计划已投递')
    runDialogVisible.value = false
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

onMounted(() => {
  getList()
})
</script>

<style scoped>
.mobile-cards {
  display: none;
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
