<template>
  <div class="app-page">
    <PageHeader title="项目管理" subtitle="维护项目基础地址与描述信息">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增项目</el-button>
      </template>
    </PageHeader>

    <div class="project-hero section-gap">
      <el-card class="page-card project-hero__main" shadow="never">
        <div class="project-hero__kicker">Portfolio Layer</div>
        <div class="project-hero__title">项目是执行与环境的归属中心</div>
        <div class="project-hero__subtitle">统一管理基础地址、空间归属和说明信息，保证后续用例、环境和报告能自然串起来。</div>
      </el-card>
      <el-card class="page-card project-hero__stat" shadow="never">
        <el-statistic title="项目数量" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card project-hero__stat" shadow="never">
        <el-statistic title="工作空间数" :value="workspaceCount" />
      </el-card>
      <el-card class="page-card project-hero__stat" shadow="never">
        <el-statistic title="基础地址覆盖" :value="baseUrlCoverage">
          <template #suffix>%</template>
        </el-statistic>
      </el-card>
      <el-card class="page-card project-hero__stat" shadow="never">
        <el-statistic title="当前筛选" :value="filters.keyword ? '已筛选' : '全部'" />
      </el-card>
    </div>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="工作空间">
          <el-select v-model="filters.workspaceId" clearable placeholder="全部" style="width: 200px">
            <el-option v-for="item in workspaces" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="项目名称/说明" style="width: 260px" />
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
        <el-table-column label="工作空间" width="160" show-overflow-tooltip>
          <template #default="scope">
            {{ workspaceMap[scope.row.workspace_id] || scope.row.workspace_id }}
          </template>
        </el-table-column>
        <el-table-column label="项目名称" prop="name" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            <el-button type="primary" link @click="enterWorkspace(scope.row)">{{ scope.row.name }}</el-button>
          </template>
        </el-table-column>
        <el-table-column label="短码" prop="code" width="110" show-overflow-tooltip />
        <el-table-column label="基础地址" prop="base_url" min-width="200" show-overflow-tooltip />
        <el-table-column label="说明" prop="description" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" align="center" width="200">
          <template #default="scope">
            <el-button size="small" type="primary" @click="enterWorkspace(scope.row)">进入工作台</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">工作空间：{{ workspaceMap[item.workspace_id] || item.workspace_id }}</div>
          <div class="mobile-card-meta">基础地址：{{ item.base_url }}</div>
          <div class="mobile-card-desc">{{ item.description || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" type="primary" @click="enterWorkspace(item)">进入工作台</el-button>
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

    <el-dialog v-model="dialogVisible" title="新增项目" width="520px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="工作空间" prop="workspace_id">
          <el-select v-model="temp.workspace_id" placeholder="请选择工作空间" style="width: 100%">
            <el-option v-for="item in workspaces" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="temp.name" placeholder="例如：订单中心" />
        </el-form-item>
        <el-form-item label="基础地址" prop="base_url">
          <el-input v-model="temp.base_url" placeholder="http://backend:8000" />
        </el-form-item>
        <el-form-item label="项目说明" prop="description">
          <el-input v-model="temp.description" type="textarea" :rows="4" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createData">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const router = useRouter()

const list = ref([])
const workspaces = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
const { canAdmin, canTest } = usePermissions()

const filters = reactive({
  workspaceId: undefined,
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  workspace_id: undefined,
  name: '',
  base_url: 'http://backend:8000',
  description: ''
})

const rules = {
  workspace_id: [{ required: true, message: '请选择工作空间', trigger: 'change' }],
  name: [{ required: true, message: '项目名称必填', trigger: 'blur' }, { min: 2, message: '至少2个字符', trigger: 'blur' }],
  base_url: [{ required: true, message: '基础地址必填', trigger: 'blur' }, { min: 5, message: '至少5个字符', trigger: 'blur' }]
}

const getList = async () => {
  listLoading.value = true
  try {
    const [projectData, workspaceData] = await Promise.all([
      api.get('/projects'),
      api.get('/workspaces')
    ])
    list.value = projectData
    workspaces.value = workspaceData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((p) => {
    if (filters.workspaceId && p.workspace_id !== filters.workspaceId) return false
    if (!keyword) return true
    return (
      String(p.name || '').toLowerCase().includes(keyword) ||
      String(p.description || '').toLowerCase().includes(keyword)
    )
  })
})

const workspaceMap = computed(() => {
  const map = {}
  workspaces.value.forEach((w) => {
    map[w.id] = w.name
  })
  return map
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const workspaceCount = computed(() => new Set(list.value.map((item) => item.workspace_id)).size)
const baseUrlCoverage = computed(() => {
  if (!list.value.length) return 0
  const readyCount = list.value.filter((item) => String(item.base_url || '').trim()).length
  return Math.round((readyCount / list.value.length) * 100)
})

const handleCreate = () => {
  temp.workspace_id = workspaces.value.length > 0 ? workspaces.value[0].id : undefined
  temp.name = ''
  temp.base_url = 'http://backend:8000'
  temp.description = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleSearch = () => {
  page.value = 1
}

const enterWorkspace = (row) => {
  router.push(`/project/${row.id}/overview`)
}

const handleReset = () => {
  filters.workspaceId = undefined
  filters.keyword = ''
  page.value = 1
}

const createData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        await api.post('/projects', temp)
        dialogVisible.value = false
        ElMessage.success('创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除项目「${row.name}」？此操作会同时删除该项目下的用例、环境、计划与执行记录。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/projects/${row.id}`)
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
.project-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.project-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.26), transparent 35%);
  color: #f8fafc;
}

.project-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.project-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.project-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.project-hero__stat {
  border-radius: 18px;
}

.mobile-cards {
  display: none;
}

@media (max-width: 960px) {
  .project-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .project-hero__main {
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
