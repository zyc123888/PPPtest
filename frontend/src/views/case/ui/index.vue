<template>
  <div class="app-page">
    <PageHeader title="UI 用例" subtitle="维护 Web UI 巡检用例并投递执行任务">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增 UI 用例</el-button>
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
        <el-table-column label="目标地址" prop="target_url" min-width="240" show-overflow-tooltip />
        <el-table-column label="期望文本" prop="expect_text" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" align="center" width="220">
          <template #default="scope">
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

    <el-dialog v-model="dialogVisible" title="新增 UI 用例" width="640px">
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
        <el-form-item label="目标地址" prop="target_url">
          <el-input v-model="temp.target_url" placeholder="http://frontend:3000" />
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
        <el-button type="primary" @click="createData">确认</el-button>
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
const listLoading = ref(true)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
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
  target_url: '',
  expect_text: '',
  steps_text: ''
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
  temp.target_url = 'http://frontend:3000'
  temp.expect_text = ''
  temp.steps_text = '[\n  {\n    "action": "goto",\n    "value": "http://frontend:3000"\n  }\n]'
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
        await api.post('/ui-cases', {
          project_id: temp.project_id,
          name: temp.name,
          target_url: temp.target_url,
          expect_text: temp.expect_text,
          steps_json: temp.steps_text ? JSON.parse(temp.steps_text) : []
        })
        dialogVisible.value = false
        ElMessage.success('创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const handleRun = async (row) => {
  try {
    await api.post(`/executions/ui/${row.id}/run`)
    ElMessage.success('任务已投递')
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
    gap: var(--space-8);
  }
}
</style>
