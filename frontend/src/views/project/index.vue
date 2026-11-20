<template>
  <div class="apple-page">
    <div class="apple-container">
      <header class="ap-header">
        <div>
          <h1 class="ap-title">项目管理</h1>
          <p class="ap-subtitle">维护项目基础地址、短码与工作空间归属，支持卡片与列表双视图切换</p>
        </div>
        <div class="ap-header__actions">
          <button type="button" class="ap-pill-btn ap-pill-btn--glass" @click="exportProjectsJson">导出配置</button>
          <button type="button" class="ap-pill-btn ap-pill-btn--glass" :disabled="listLoading" @click="getList">刷新</button>
          <button v-if="canTest" type="button" class="ap-pill-btn ap-pill-btn--blue" @click="handleCreate">新增项目</button>
        </div>
      </header>

      <section class="ap-bento-row">
        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--blue">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" fill="currentColor" opacity="0.88" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">项目总数</span>
            <strong class="ap-stat-tile__val">{{ filteredList.length }}</strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--purple">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="2" fill="currentColor" />
              <rect x="14" y="3" width="7" height="7" rx="2" fill="currentColor" opacity="0.55" />
              <rect x="3" y="14" width="7" height="7" rx="2" fill="currentColor" opacity="0.55" />
              <rect x="14" y="14" width="7" height="7" rx="2" fill="currentColor" opacity="0.3" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">覆盖工作空间</span>
            <strong class="ap-stat-tile__val">{{ workspaceCount }}</strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--green">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M5 13l4 4L19 7" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </div>
          <div>
            <span class="ap-stat-tile__label">基础地址就绪率</span>
            <strong class="ap-stat-tile__val">{{ baseUrlCoverage }}<small>%</small></strong>
          </div>
        </div>
      </section>

      <section class="ap-toolbar">
        <div class="ws-pills">
          <button
            type="button"
            class="ws-pill"
            :class="{ 'is-active': !filters.workspaceId }"
            @click="selectWorkspace(undefined)"
          >
            全部空间
          </button>
          <button
            v-for="ws in workspaces"
            :key="ws.id"
            type="button"
            class="ws-pill"
            :class="{ 'is-active': filters.workspaceId === ws.id }"
            @click="selectWorkspace(ws.id)"
          >
            {{ ws.name }}
          </button>
        </div>

        <div class="ap-toolbar__right">
          <div class="ap-search-box">
            <svg class="ap-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
              <path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
            <input
              v-model="filters.keyword"
              type="text"
              class="ap-search-input"
              placeholder="搜索项目名称或说明"
              @input="handleSearch"
            />
          </div>

          <div class="ap-seg" role="group" aria-label="视图切换">
            <button type="button" class="ap-seg__btn" :class="{ 'is-active': viewMode === 'grid' }" @click="viewMode = 'grid'">
              卡片
            </button>
            <button type="button" class="ap-seg__btn" :class="{ 'is-active': viewMode === 'table' }" @click="viewMode = 'table'">
              列表
            </button>
          </div>
        </div>
      </section>

      <!-- Apple Liquid Glass Card Grid -->
      <section v-if="viewMode === 'grid'" v-loading="listLoading">
        <el-empty v-if="!pagedList.length" description="暂无匹配项目" />
        <div v-else class="project-grid">
          <article
            v-for="(item, idx) in pagedList"
            :key="item.id"
            class="ap-glass-card project-card"
            @click="enterWorkspace(item)"
          >
            <div class="project-card__body">
              <div class="project-card__top">
                <div class="ap-app-icon" :style="{ background: iconBg(idx) }">
                  {{ (item.code || item.name || 'P').slice(0, 2).toUpperCase() }}
                </div>
                <div class="project-card__title-wrap">
                  <h3 class="project-card__name">{{ item.name }}</h3>
                  <span class="project-card__ws">{{ workspaceMap[item.workspace_id] || `空间 #${item.workspace_id}` }}</span>
                </div>
                <span class="project-card__id">#{{ item.id }}</span>
              </div>

              <p class="project-card__desc">{{ item.description || '点击进入项目工作台管理需求、用例与缺陷。' }}</p>

              <div class="project-card__url" @click.stop="copyBaseUrl(item.base_url)" title="点击复制基础地址">
                <code>{{ item.base_url || '未配置基础地址' }}</code>
                <span class="copy-hint">复制</span>
              </div>
            </div>

            <footer class="project-card__foot" @click.stop>
              <button type="button" class="card-enter-btn" @click="enterWorkspace(item)">进入工作台 →</button>
              <div class="ap-row-actions">
                <button v-if="canTest" type="button" class="ap-action-btn" @click="handleEdit(item)">编辑</button>
                <button v-if="canAdmin" type="button" class="ap-action-btn ap-action-btn--red" @click="handleDelete(item)">删除</button>
              </div>
            </footer>
          </article>
        </div>
      </section>

      <!-- Apple Glass Inset List View -->
      <section v-else v-loading="listLoading" class="ap-glass-list">
        <div v-if="!pagedList.length" class="ap-empty">暂无匹配项目</div>
        <div v-for="(row, idx) in pagedList" :key="row.id" class="ap-list-row" @click="enterWorkspace(row)">
          <div class="ap-list-row__left">
            <div class="ap-app-icon" :style="{ background: iconBg(idx) }">
              {{ (row.code || row.name || 'P').slice(0, 2).toUpperCase() }}
            </div>
            <div class="ap-list-row__info">
              <div class="ap-list-row__title-line">
                <span class="ap-list-row__name">{{ row.name }}</span>
                <span class="ap-chip">{{ workspaceMap[row.workspace_id] || row.workspace_id }}</span>
              </div>
              <div class="ap-list-row__meta">
                <code>{{ row.base_url }}</code>
                <span>·</span>
                <span>{{ row.description || '—' }}</span>
              </div>
            </div>
          </div>
          <div class="ap-row-actions" @click.stop>
            <button type="button" class="ap-action-btn ap-action-btn--blue" @click="enterWorkspace(row)">进入工作台</button>
            <button v-if="canTest" type="button" class="ap-action-btn" @click="handleEdit(row)">编辑</button>
            <button v-if="canAdmin" type="button" class="ap-action-btn ap-action-btn--red" @click="handleDelete(row)">删除</button>
          </div>
        </div>
      </section>

      <div class="ap-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[9, 18, 36]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑项目' : '新增项目'" width="520px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="工作空间" prop="workspace_id">
          <el-select v-model="temp.workspace_id" placeholder="请选择工作空间" style="width: 100%">
            <el-option v-for="item in workspaces" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目名称" prop="name">
          <el-input v-model="temp.name" placeholder="例如：订单中心" />
        </el-form-item>
        <el-form-item label="项目短码" prop="code">
          <el-input v-model="temp.code" placeholder="可选，例如：ORD" />
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
        <el-button type="primary" @click="saveData">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePermissions } from '@/lib/permissions'

const router = useRouter()

const list = ref([])
const workspaces = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
const viewMode = ref('grid')
const { canAdmin, canTest } = usePermissions()

const filters = reactive({
  workspaceId: undefined,
  keyword: ''
})

const page = ref(1)
const pageSize = ref(9)
const editingId = ref(null)

const temp = reactive({
  workspace_id: undefined,
  name: '',
  code: '',
  base_url: 'http://backend:8000',
  description: ''
})

const rules = {
  workspace_id: [{ required: true, message: '请选择工作空间', trigger: 'change' }],
  name: [{ required: true, message: '项目名称必填', trigger: 'blur' }, { min: 2, message: '至少2个字符', trigger: 'blur' }],
  base_url: [{ required: true, message: '基础地址必填', trigger: 'blur' }, { min: 5, message: '至少5个字符', trigger: 'blur' }]
}

const APPLE_GRADIENTS = [
  'linear-gradient(180deg, #3b9eff 0%, #0071e3 100%)',
  'linear-gradient(180deg, #4cd964 0%, #28cd41 100%)',
  'linear-gradient(180deg, #5e5ce6 0%, #3634a3 100%)',
  'linear-gradient(180deg, #ff9f0a 0%, #ff6b00 100%)',
  'linear-gradient(180deg, #ff375f 0%, #d70040 100%)'
]
const iconBg = (idx) => APPLE_GRADIENTS[idx % APPLE_GRADIENTS.length]

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

const selectWorkspace = (id) => {
  filters.workspaceId = id
  page.value = 1
}

const copyBaseUrl = async (url) => {
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('已复制基础地址')
  } catch {
    ElMessage.warning('复制失败')
  }
}

const handleCreate = () => {
  editingId.value = null
  temp.workspace_id = workspaces.value.length > 0 ? workspaces.value[0].id : undefined
  temp.name = ''
  temp.code = ''
  temp.base_url = 'http://backend:8000'
  temp.description = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleEdit = (row) => {
  editingId.value = row.id
  temp.workspace_id = row.workspace_id
  temp.name = row.name || ''
  temp.code = row.code || ''
  temp.base_url = row.base_url || 'http://backend:8000'
  temp.description = row.description || ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const exportProjectsJson = () => {
  const blob = new Blob([JSON.stringify(filteredList.value, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `omnitest-projects-${new Date().toISOString().slice(0, 10)}.json`
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success(`已导出 ${filteredList.value.length} 个项目配置`)
}

const handleSearch = () => {
  page.value = 1
}

const enterWorkspace = (row) => {
  router.push(`/project/${row.id}/overview`)
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        if (editingId.value) {
          await api.put(`/projects/${editingId.value}`, temp)
          ElMessage.success('更新成功')
        } else {
          await api.post('/projects', temp)
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
.apple-page {
  min-height: calc(100vh - var(--app-header-height));
  padding: 24px 32px 36px;
}

.apple-container {
  max-width: 1280px;
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
.ap-icon-box--purple { background: rgba(94, 92, 230, 0.12); color: #5e5ce6; }
.ap-icon-box--green { background: rgba(52, 199, 89, 0.14); color: #248a3d; }

.ap-stat-tile__label { display: block; font-size: 12px; color: #6e6e73; }

.ap-stat-tile__val {
  display: block;
  margin-top: 2px;
  font-size: 24px;
  font-weight: 700;
  color: #1d1d1f;
  font-variant-numeric: tabular-nums;
}

.ap-stat-tile__val small { font-size: 13px; color: #86868b; margin-left: 2px; }

.ap-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.ws-pills { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.ws-pill {
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.07);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(14px);
  color: #424245;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.14s ease;
}

.ws-pill:hover { background: #ffffff; color: #1d1d1f; }

.ws-pill.is-active {
  border-color: transparent;
  background: #0071e3;
  color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 113, 227, 0.25);
}

.ap-toolbar__right { display: flex; align-items: center; gap: 10px; }

.ap-search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 240px;
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(16px);
}

.ap-search-box:focus-within {
  border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.16);
}

.ap-search-icon { color: #86868b; flex-shrink: 0; }
.ap-search-input { flex: 1; border: none; background: transparent; outline: none; font-size: 13px; color: #1d1d1f; }

.ap-seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.055);
}

.ap-seg__btn {
  height: 28px;
  padding: 0 13px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #6e6e73;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
}

.ap-seg__btn.is-active {
  background: #ffffff;
  color: #1d1d1f;
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.project-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}

.project-card:hover {
  transform: translateY(-2px);
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.98);
}

.project-card__body {
  padding: 18px 20px 14px;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.project-card__top { display: flex; align-items: center; gap: 12px; }

.ap-app-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.project-card__title-wrap { flex: 1; min-width: 0; }

.project-card__name {
  margin: 0;
  font-size: 15.5px;
  font-weight: 600;
  color: #1d1d1f;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-card__ws { display: block; margin-top: 2px; font-size: 12px; color: #6e6e73; }
.project-card__id { font-family: var(--font-mono); font-size: 11.5px; color: #86868b; }

.project-card__desc {
  margin: 12px 0;
  font-size: 13px;
  line-height: 1.55;
  color: #6e6e73;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex: 1;
}

.project-card__url {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 11px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.035);
}

.project-card__url code {
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: #424245;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.copy-hint { font-size: 11px; font-weight: 600; color: #0071e3; opacity: 0; transition: opacity 0.14s ease; }
.project-card__url:hover .copy-hint { opacity: 1; }

.project-card__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 20px;
  border-top: 1px solid rgba(0, 0, 0, 0.05);
  background: rgba(255, 255, 255, 0.45);
}

.card-enter-btn {
  border: none;
  background: transparent;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  color: #0071e3;
  cursor: pointer;
}

.ap-row-actions { display: flex; align-items: center; gap: 6px; }

.ap-action-btn {
  height: 28px;
  padding: 0 11px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.85);
  color: #1d1d1f;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.ap-action-btn:hover { background: #ffffff; }
.ap-action-btn--blue { color: #0071e3; background: rgba(0, 113, 227, 0.08); border-color: transparent; }
.ap-action-btn--blue:hover { background: rgba(0, 113, 227, 0.14); }
.ap-action-btn--red { color: #d70015; background: rgba(255, 59, 48, 0.08); border-color: transparent; }
.ap-action-btn--red:hover { background: rgba(255, 59, 48, 0.14); }

.ap-glass-list {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.ap-empty { padding: 56px 16px; text-align: center; color: #86868b; }

.ap-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 22px;
  position: relative;
  cursor: pointer;
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
.ap-list-row__left { display: flex; align-items: center; gap: 14px; min-width: 0; flex: 1; }
.ap-list-row__info { min-width: 0; flex: 1; }
.ap-list-row__title-line { display: flex; align-items: center; gap: 8px; }
.ap-list-row__name { font-size: 15px; font-weight: 600; color: #1d1d1f; }
.ap-chip { padding: 2px 8px; border-radius: 999px; background: rgba(0, 0, 0, 0.05); color: #6e6e73; font-size: 11.5px; }
.ap-list-row__meta { margin-top: 3px; display: flex; gap: 8px; font-size: 12px; color: #86868b; }
.ap-list-row__meta code { font-family: var(--font-mono); color: #424245; }

.ap-pagination { margin-top: 18px; display: flex; justify-content: flex-end; }

@media (max-width: 1100px) { .project-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) {
  .apple-page { padding: 16px; }
  .ap-header { flex-direction: column; align-items: flex-start; }
  .ap-bento-row, .project-grid { grid-template-columns: 1fr; }
}
</style>
