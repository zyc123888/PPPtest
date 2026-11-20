<template>
  <div class="apple-page">
    <div class="apple-container">
      <header class="ap-header">
        <div>
          <h1 class="ap-title">环境管理</h1>
          <p class="ap-subtitle">维护项目运行地址、模板变量与鉴权配置，支持一键在线校验</p>
        </div>
        <div class="ap-header__actions">
          <button type="button" class="ap-pill-btn ap-pill-btn--glass" :disabled="listLoading" @click="getList">
            刷新
          </button>
          <button v-if="canTest" type="button" class="ap-pill-btn ap-pill-btn--blue" @click="handleCreate">
            新增环境
          </button>
        </div>
      </header>

      <section class="ap-bento-row">
        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--blue">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2" />
              <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" stroke="currentColor" stroke-width="1.6" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">环境总数</span>
            <strong class="ap-stat-tile__val">{{ filteredList.length }}</strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--green">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">带变量环境占比</span>
            <strong class="ap-stat-tile__val">{{ variableCoverage }}<small>%</small></strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--orange">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="4" width="18" height="6" rx="2" fill="currentColor" opacity="0.85" />
              <rect x="3" y="14" width="18" height="6" rx="2" fill="currentColor" opacity="0.4" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">覆盖项目</span>
            <strong class="ap-stat-tile__val">{{ projectCount }}</strong>
          </div>
        </div>
      </section>

      <section class="ap-search-row">
        <div class="ap-filter-left">
          <el-select
            v-model="filters.projectId"
            clearable
            filterable
            placeholder="全部项目"
            style="width: 190px"
            @change="handleSearch"
          >
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>

          <div class="ap-search-box">
            <svg class="ap-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
              <path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
            <input
              v-model="filters.keyword"
              type="text"
              class="ap-search-input"
              placeholder="搜索环境名称或基础地址"
              @input="handleSearch"
            />
            <button v-if="filters.keyword || filters.projectId" type="button" class="ap-clear-btn" @click="handleReset">
              清除
            </button>
          </div>
        </div>
        <span class="ap-count-label">共 {{ filteredList.length }} 个环境</span>
      </section>

      <section v-loading="listLoading" class="ap-glass-list">
        <div v-if="!pagedList.length" class="ap-empty">暂无匹配的环境配置</div>

        <div v-for="(row, idx) in pagedList" :key="row.id" class="ap-list-row">
          <div class="ap-list-row__left">
            <div class="ap-app-icon" :style="{ background: iconBg(idx) }">
              {{ (row.name || 'E').slice(0, 1).toUpperCase() }}
            </div>
            <div class="ap-list-row__info">
              <div class="ap-list-row__title-line">
                <span class="ap-list-row__name">{{ row.name }}</span>
                <span class="ap-chip">{{ projectMap[row.project_id] || `#${row.project_id}` }}</span>
                <span class="ap-chip ap-chip--blue">{{ varCount(row) }} 个变量</span>
                <span v-if="hasAuth(row)" class="ap-chip ap-chip--green">已配鉴权</span>
              </div>
              <div class="ap-list-row__meta">
                <code class="ap-url">{{ row.base_url }}</code>
                <span class="ap-sep">·</span>
                <span class="ap-time">{{ formatTime(row.created_at) }}</span>
              </div>
            </div>
          </div>

          <div v-if="canTest || canAdmin" class="ap-row-actions">
            <button v-if="canTest" type="button" class="ap-action-btn ap-action-btn--blue" @click="handleValidate(row)">
              校验
            </button>
            <button v-if="canTest" type="button" class="ap-action-btn" @click="handleEdit(row)">编辑</button>
            <button v-if="canAdmin" type="button" class="ap-action-btn ap-action-btn--red" @click="handleDelete(row)">
              删除
            </button>
          </div>
        </div>
      </section>

      <div class="ap-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </div>

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
import { computed, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { getSavedProjectId, saveActiveProjectId } from '@/lib/projectContext'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePermissions } from '@/lib/permissions'
import { formatDateTime as formatTime } from '@/lib/formatTime'

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
      } catch {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }],
  variables_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) JSON.parse(value)
        callback()
      } catch {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }],
  auth_config_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) JSON.parse(value)
        callback()
      } catch {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }]
}

const APPLE_GRADIENTS = [
  'linear-gradient(180deg, #4cd964 0%, #28cd41 100%)',
  'linear-gradient(180deg, #3b9eff 0%, #0071e3 100%)',
  'linear-gradient(180deg, #ff9f0a 0%, #ff6b00 100%)',
  'linear-gradient(180deg, #5e5ce6 0%, #3634a3 100%)'
]
const iconBg = (idx) => APPLE_GRADIENTS[idx % APPLE_GRADIENTS.length]

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((p) => {
    map[p.id] = p.name
  })
  return map
})

const varCount = (row) => {
  const v = row?.variables_json
  if (!v) return 0
  if (typeof v === 'object') return Object.keys(v).length
  try {
    return Object.keys(JSON.parse(v)).length
  } catch {
    return 0
  }
}

const hasAuth = (row) => {
  const a = row?.auth_config_json
  if (!a) return false
  if (typeof a === 'object') return Object.keys(a).length > 0
  try {
    return Object.keys(JSON.parse(a)).length > 0
  } catch {
    return false
  }
}

const getList = async () => {
  listLoading.value = true
  try {
    const [envData, projectData] = await Promise.all([
      api.get('/environments'),
      api.get('/projects')
    ])
    list.value = envData
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
  const readyCount = list.value.filter((item) => varCount(item) > 0).length
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
.apple-page {
  min-height: calc(100vh - var(--app-header-height));
  padding: 24px 32px 36px;
}

.apple-container {
  max-width: 1180px;
  margin: 0 auto;
}

.ap-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.ap-title {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #1d1d1f;
}

.ap-subtitle {
  margin: 4px 0 0;
  font-size: 13.5px;
  color: #6e6e73;
}

.ap-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ap-pill-btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.12s ease, background 0.14s ease;
}

.ap-pill-btn--blue {
  border: none;
  background: #0071e3;
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(0, 113, 227, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.ap-pill-btn--blue:hover { background: #0077ed; transform: translateY(-0.5px); }

.ap-pill-btn--glass {
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.76);
  backdrop-filter: blur(18px);
  color: #1d1d1f;
}

.ap-pill-btn--glass:hover { background: #ffffff; }

.ap-bento-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.ap-glass-card {
  border-radius: 18px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(22px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
}

.ap-stat-tile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
}

.ap-icon-box {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ap-icon-box--blue { background: rgba(0, 113, 227, 0.12); color: #0071e3; }
.ap-icon-box--green { background: rgba(52, 199, 89, 0.14); color: #248a3d; }
.ap-icon-box--orange { background: rgba(255, 159, 10, 0.14); color: #c96a00; }

.ap-stat-tile__label {
  display: block;
  font-size: 12px;
  color: #6e6e73;
}

.ap-stat-tile__val {
  display: block;
  margin-top: 2px;
  font-size: 24px;
  font-weight: 700;
  color: #1d1d1f;
  font-variant-numeric: tabular-nums;
}

.ap-stat-tile__val small {
  font-size: 13px;
  color: #86868b;
  margin-left: 2px;
}

.ap-search-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.ap-filter-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ap-search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 300px;
  height: 36px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(18px);
}

.ap-search-box:focus-within {
  border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.16);
}

.ap-search-icon { color: #86868b; flex-shrink: 0; }

.ap-search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13.5px;
  color: #1d1d1f;
}

.ap-clear-btn {
  border: none;
  background: transparent;
  color: #0071e3;
  font-size: 12px;
  cursor: pointer;
}

.ap-count-label { font-size: 12.5px; color: #86868b; }

.ap-glass-list {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.ap-empty {
  padding: 56px 16px;
  text-align: center;
  color: #86868b;
  font-size: 14px;
}

.ap-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 22px;
  position: relative;
  transition: background 0.14s ease;
}

.ap-list-row:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 74px;
  right: 22px;
  bottom: 0;
  height: 1px;
  background: rgba(0, 0, 0, 0.06);
}

.ap-list-row:hover { background: rgba(0, 113, 227, 0.035); }

.ap-list-row__left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}

.ap-app-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.ap-list-row__info { min-width: 0; flex: 1; }

.ap-list-row__title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ap-list-row__name {
  font-size: 15px;
  font-weight: 600;
  color: #1d1d1f;
}

.ap-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.05);
  color: #6e6e73;
  font-size: 11.5px;
  font-weight: 500;
}

.ap-chip--blue { background: rgba(0, 113, 227, 0.1); color: #0071e3; }
.ap-chip--green { background: rgba(52, 199, 89, 0.14); color: #248a3d; }

.ap-list-row__meta {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ap-url {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #424245;
}

.ap-sep { color: #d2d2d7; }

.ap-time {
  font-size: 12px;
  color: #86868b;
  font-variant-numeric: tabular-nums;
}

.ap-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.ap-action-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.85);
  color: #1d1d1f;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
}

.ap-action-btn:hover { background: #ffffff; border-color: rgba(0, 0, 0, 0.16); }
.ap-action-btn--blue { color: #0071e3; background: rgba(0, 113, 227, 0.08); border-color: transparent; }
.ap-action-btn--blue:hover { background: rgba(0, 113, 227, 0.14); }
.ap-action-btn--red { color: #d70015; background: rgba(255, 59, 48, 0.08); border-color: transparent; }
.ap-action-btn--red:hover { background: rgba(255, 59, 48, 0.14); }

.ap-pagination {
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
}

.form-tip {
  margin: -4px 0 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 860px) {
  .apple-page { padding: 16px; }
  .ap-header { flex-direction: column; align-items: flex-start; }
  .ap-bento-row { grid-template-columns: 1fr; }
  .ap-list-row { flex-direction: column; align-items: flex-start; }
  .ap-search-box { width: 100%; }
}
</style>
