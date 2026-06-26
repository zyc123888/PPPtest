<template>
  <div class="app-page">
    <PageHeader title="环境管理" subtitle="维护项目环境与变量配置">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增环境</el-button>
      </template>
    </PageHeader>

    <div class="environment-hero section-gap">
      <el-card class="page-card environment-hero__main" shadow="never">
        <div class="environment-hero__kicker">Runtime Layer</div>
        <div class="environment-hero__title">环境承载真实执行上下文</div>
        <div class="environment-hero__subtitle">变量、请求头和鉴权配置在这里统一收口，直接影响预检和执行链路。</div>
      </el-card>
      <el-card class="page-card environment-hero__stat" shadow="never">
        <el-statistic title="环境数量" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card environment-hero__stat" shadow="never">
        <el-statistic title="项目数" :value="projectCount" />
      </el-card>
      <el-card class="page-card environment-hero__stat" shadow="never">
        <el-statistic title="带变量环境" :value="variableCoverage">
          <template #suffix>%</template>
        </el-statistic>
      </el-card>
      <el-card class="page-card environment-hero__stat" shadow="never">
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
          <el-input v-model="filters.keyword" clearable placeholder="环境名称/地址" style="width: 260px" />
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
        <el-table-column label="环境名称" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="基础地址" prop="base_url" min-width="220" show-overflow-tooltip />
        <el-table-column label="创建时间" min-width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canTest || canAdmin" label="操作" align="center" width="220">
          <template #default="scope">
            <el-button v-if="canTest" size="small" @click="handleValidate(scope.row)">校验</el-button>
            <el-button v-if="canTest" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">项目：{{ projectMap[item.project_id] || item.project_id }}</div>
          <div class="mobile-card-meta">基础地址：{{ item.base_url }}</div>
          <div class="mobile-card-desc">创建时间：{{ formatTime(item.created_at) }}</div>
          <div v-if="canTest || canAdmin" class="mobile-card-actions">
            <el-button v-if="canTest" size="small" @click="handleValidate(item)">校验</el-button>
            <el-button v-if="canTest" size="small" @click="handleEdit(item)">编辑</el-button>
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

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑环境' : '新增环境'" width="640px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="环境名称" prop="name">
          <el-input v-model="temp.name" placeholder="例如：测试环境" />
        </el-form-item>
        <el-form-item label="基础地址" prop="base_url">
          <el-input v-model="temp.base_url" placeholder="http://backend:8000" />
        </el-form-item>
        <el-form-item label="请求头 JSON" prop="headers_text">
          <el-input v-model="temp.headers_text" type="textarea" :rows="4" placeholder='{"accept": "application/json"}' />
        </el-form-item>
        <el-form-item label="变量 JSON" prop="variables_text">
          <el-input v-model="temp.variables_text" type="textarea" :rows="4" placeholder='{"frontend_url": "http://frontend:3000"}' />
        </el-form-item>
        <div class="form-tip">模板变量使用 `{{variable_name}}`。执行时若缺失变量，系统会直接报出变量名和字段位置。</div>
        <el-form-item label="认证配置 JSON" prop="auth_config_text">
          <el-input v-model="temp.auth_config_text" type="textarea" :rows="4" placeholder='{"header_name": "Authorization", "token_prefix": "Bearer", "token": "{{token}}"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="handleValidateDraft">校验配置</el-button>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitData">{{ isEditing ? '保存' : '确认' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const projects = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const isEditing = ref(false)
const dataFormRef = ref(null)
const { canAdmin, canTest } = usePermissions()

const filters = reactive({
  projectId: undefined,
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  id: undefined,
  project_id: undefined,
  name: '',
  base_url: 'http://backend:8000',
  headers_text: '{\n  "accept": "application/json"\n}',
  variables_text: '{\n  "frontend_url": "http://frontend:3000"\n}',
  auth_config_text: ''
})

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '环境名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }],
  base_url: [{ required: true, message: '基础地址必填', trigger: 'blur' }],
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
  variables_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) JSON.parse(value)
        callback()
      } catch (e) {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }],
  auth_config_text: [{
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

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((p) => {
    map[p.id] = p.name
  })
  return map
})

const getList = async () => {
  listLoading.value = true
  try {
    const [envData, projectData] = await Promise.all([
      api.get('/environments'),
      api.get('/projects')
    ])
    list.value = envData
    projects.value = projectData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((env) => {
    if (filters.projectId && env.project_id !== filters.projectId) return false
    if (!keyword) return true
    return (
      String(env.name || '').toLowerCase().includes(keyword) ||
      String(env.base_url || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const projectCount = computed(() => new Set(list.value.map((item) => item.project_id)).size)
const variableCoverage = computed(() => {
  if (!list.value.length) return 0
  const readyCount = list.value.filter((item) => {
    try {
      return Object.keys(JSON.parse(item.variables_json || '{}')).length > 0
    } catch (error) {
      return false
    }
  }).length
  return Math.round((readyCount / list.value.length) * 100)
})

const handleCreate = () => {
  isEditing.value = false
  temp.id = undefined
  temp.project_id = projects.value.length > 0 ? projects.value[0].id : undefined
  temp.name = ''
  temp.base_url = 'http://backend:8000'
  temp.headers_text = '{\n  "accept": "application/json"\n}'
  temp.variables_text = '{\n  "frontend_url": "http://frontend:3000"\n}'
  temp.auth_config_text = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleEdit = (row) => {
  isEditing.value = true
  temp.id = row.id
  temp.project_id = row.project_id
  temp.name = row.name
  temp.base_url = row.base_url
  temp.headers_text = JSON.stringify(row.headers_json || {}, null, 2)
  temp.variables_text = JSON.stringify(row.variables_json || {}, null, 2)
  temp.auth_config_text = JSON.stringify(row.auth_config_json || {}, null, 2)
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

const buildPayload = () => ({
  project_id: temp.project_id,
  name: temp.name,
  base_url: temp.base_url,
  headers_json: temp.headers_text ? JSON.parse(temp.headers_text) : null,
  variables_json: temp.variables_text ? JSON.parse(temp.variables_text) : null,
  auth_config_json: temp.auth_config_text ? JSON.parse(temp.auth_config_text) : null
})

const showValidationResult = async (title, result) => {
  if (result.is_valid) {
    ElMessage.success(`${title}校验通过`)
    return
  }
  const lines = result.issues
    .slice(0, 8)
    .map((item) => `${item.scope} / ${item.field} / 缺失: ${item.missing_variables.join(', ')}`)
    .join('\n')
  await ElMessageBox.alert(lines, `${title}发现 ${result.issue_count} 个问题`, {
    confirmButtonText: '知道了'
  })
}

const handleValidateDraft = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      const payload = buildPayload()
      const result = await api.post('/environments/validate-draft', payload)
      await showValidationResult(`环境「${payload.name || '未命名'}」配置校验`, result)
    } catch (error) {
      ElMessage.error(error.message)
    }
  })
}

const submitData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        const payload = buildPayload()
        if (isEditing.value) {
          await api.put(`/environments/${temp.id}`, {
            name: payload.name,
            base_url: payload.base_url,
            headers_json: payload.headers_json,
            variables_json: payload.variables_json,
            auth_config_json: payload.auth_config_json
          })
        } else {
          await api.post('/environments', payload)
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

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除环境「${row.name}」？历史执行记录会保留，但环境引用会被置空。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/environments/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleValidate = async (row) => {
  try {
    const result = await api.get(`/environments/${row.id}/validate`)
    await showValidationResult(`环境「${row.name}」校验`, result)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  getList()
})
</script>

<style scoped>
.environment-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.environment-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(20, 184, 166, 0.26), transparent 35%);
  color: #f8fafc;
}

.environment-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.environment-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.environment-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.environment-hero__stat {
  border-radius: 18px;
}

.mobile-cards {
  display: none;
}

.form-tip {
  margin: -4px 0 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 960px) {
  .environment-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .environment-hero__main {
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
