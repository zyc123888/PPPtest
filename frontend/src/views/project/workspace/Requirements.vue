<template>
  <div v-loading="loading">
    <div class="wb-toolbar page-card">
      <div class="wb-toolbar__left">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="list">列表</el-radio-button>
          <el-radio-button value="board">看板</el-radio-button>
        </el-radio-group>
        <el-input v-model="filters.keyword" clearable placeholder="标题关键字" style="width: 200px" @keyup.enter="reload" />
        <el-select v-model="filters.priority" clearable placeholder="优先级" style="width: 120px" @change="reload">
          <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
        </el-select>
        <el-select v-model="filters.iteration_id" clearable placeholder="迭代" style="width: 150px" @change="reload">
          <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
        </el-select>
        <el-button @click="reload">查询</el-button>
      </div>
      <el-button v-if="canEdit" type="primary" @click="openCreate">新增需求</el-button>
    </div>

    <el-card v-if="viewMode === 'list'" class="page-card" shadow="never">
      <el-table :data="items" border @row-click="openDrawer">
        <el-table-column label="ID" prop="id" width="70" align="center" />
        <el-table-column label="标题" prop="title" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType[row.status]" size="small">{{ statusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{ row }">
            <el-tag :type="priorityType[row.priority]" size="small" effect="plain">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="故事点" prop="story_points" width="80" align="center" />
        <el-table-column label="迭代" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ iterationMap[row.iteration_id] || '-' }}</template>
        </el-table-column>
      </el-table>
      <div class="table-pagination">
        <el-pagination
          layout="total, prev, pager, next"
          :total="total"
          :page-size="pageSize"
          v-model:current-page="page"
          @current-change="fetchList"
        />
      </div>
    </el-card>

    <el-card v-else class="page-card" shadow="never">
      <KanbanBoard :columns="columns" :items="items" :draggable="canEdit" @open="openDrawer" @move="handleMove">
        <template #card="{ card }">
          <div class="kc-title">{{ card.title }}</div>
          <div class="kc-meta">
            <el-tag :type="priorityType[card.priority]" size="small" effect="plain">{{ card.priority }}</el-tag>
            <span v-if="card.story_points" class="kc-pts">{{ card.story_points }} pts</span>
          </div>
        </template>
      </KanbanBoard>
    </el-card>

    <!-- create dialog -->
    <el-dialog v-model="createVisible" title="新增需求" width="560px">
      <el-form ref="createFormRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <div class="form-row">
          <el-form-item label="优先级">
            <el-select v-model="form.priority" style="width: 100%">
              <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
          <el-form-item label="类型">
            <el-select v-model="form.type" style="width: 100%">
              <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="迭代">
            <el-select v-model="form.iteration_id" clearable style="width: 100%">
              <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="故事点"><el-input-number v-model="form.story_points" :min="0" :step="1" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- detail drawer -->
    <el-drawer v-model="drawerVisible" :title="current?.title || '需求详情'" size="560px">
      <div v-if="current" class="drawer-body">
        <div class="drawer-section">
          <div class="ds-row">
            <span class="ds-label">状态流转</span>
            <el-select v-model="current.status" :disabled="!canEdit" size="small" style="width: 160px" @change="changeStatus">
              <el-option v-for="c in columns" :key="c.key" :label="c.label" :value="c.key" />
            </el-select>
          </div>
          <div class="ds-row"><span class="ds-label">优先级</span><el-tag :type="priorityType[current.priority]" effect="plain">{{ current.priority }}</el-tag></div>
          <div class="ds-row"><span class="ds-label">迭代</span><span>{{ iterationMap[current.iteration_id] || '未规划' }}</span></div>
          <div class="ds-row"><span class="ds-label">描述</span><span>{{ current.description || '-' }}</span></div>
        </div>

        <el-divider content-position="left">关联用例（追溯）</el-divider>
        <div class="link-add">
          <el-select v-model="linkForm.case_type" size="small" style="width: 100px">
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
            <el-option label="PERF" value="PERF" />
          </el-select>
          <el-input-number v-model="linkForm.case_id" :min="1" size="small" controls-position="right" style="width: 130px" />
          <el-button size="small" type="primary" :disabled="!canEdit" @click="linkCase">关联</el-button>
        </div>
        <el-table :data="linkedCases" size="small" border style="margin-top: 8px">
          <el-table-column label="类型" prop="case_type" width="70" />
          <el-table-column label="用例" min-width="160">
            <template #default="{ row }">{{ row.case_name || ('#' + row.case_id) }}</template>
          </el-table-column>
          <el-table-column width="70">
            <template #default="{ row }">
              <el-button size="small" text type="danger" :disabled="!canEdit" @click="unlinkCase(row.id)">移除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-divider content-position="left">评论</el-divider>
        <div class="comment-add">
          <el-input v-model="commentText" type="textarea" :rows="2" placeholder="写下评论..." />
          <el-button size="small" type="primary" style="margin-top: 6px" @click="addComment">发表</el-button>
        </div>
        <div v-for="c in comments" :key="c.id" class="comment-item">
          <strong>{{ c.author_name || '用户' }}</strong>
          <span class="comment-time">{{ formatTime(c.created_at) }}</span>
          <div>{{ c.content }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import KanbanBoard from './components/KanbanBoard.vue'
import {
  REQUIREMENT_COLUMNS, REQUIREMENT_STATUS_LABELS, STATUS_TAG_TYPE,
  PRIORITY_OPTIONS, PRIORITY_TAG_TYPE, REQUIREMENT_TYPE_OPTIONS
} from './constants'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const columns = REQUIREMENT_COLUMNS
const statusLabels = REQUIREMENT_STATUS_LABELS
const statusType = STATUS_TAG_TYPE
const priorityOptions = PRIORITY_OPTIONS
const priorityType = PRIORITY_TAG_TYPE
const typeOptions = REQUIREMENT_TYPE_OPTIONS

const canEdit = computed(() => ['owner', 'manager', 'member'].includes(props.myRole))

const loading = ref(false)
const viewMode = ref('board')
const items = ref([])
const iterations = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({ keyword: '', priority: '', iteration_id: null })

const createVisible = ref(false)
const createFormRef = ref(null)
const form = reactive({ title: '', description: '', priority: 'P2', type: 'FEATURE', iteration_id: null, story_points: 0 })
const rules = { title: [{ required: true, message: '标题必填', trigger: 'blur' }] }

const drawerVisible = ref(false)
const current = ref(null)
const linkedCases = ref([])
const comments = ref([])
const linkForm = reactive({ case_type: 'API', case_id: 1 })
const commentText = ref('')

const iterationMap = computed(() => {
  const m = {}
  iterations.value.forEach((it) => { m[it.id] = it.name })
  return m
})

function formatTime(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '' }

async function fetchList() {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: page.value, page_size: pageSize.value })
    if (filters.keyword) params.append('keyword', filters.keyword)
    if (filters.priority) params.append('priority', filters.priority)
    if (filters.iteration_id) params.append('iteration_id', filters.iteration_id)
    const data = await api.get(`/projects/${props.project.id}/requirements?${params}`)
    items.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadIterations() {
  try { iterations.value = await api.get(`/projects/${props.project.id}/iterations`) } catch { /* noop */ }
}

function reload() { page.value = 1; fetchList() }

function openCreate() {
  Object.assign(form, { title: '', description: '', priority: 'P2', type: 'FEATURE', iteration_id: null, story_points: 0 })
  createVisible.value = true
}

function submitCreate() {
  createFormRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      await api.post(`/projects/${props.project.id}/requirements`, { ...form })
      createVisible.value = false
      ElMessage.success('创建成功')
      fetchList()
    } catch (error) { ElMessage.error(error.message) }
  })
}

async function openDrawer(row) {
  current.value = { ...row }
  drawerVisible.value = true
  try {
    linkedCases.value = await api.get(`/requirements/${row.id}/cases`)
    comments.value = await api.get(`/requirement/${row.id}/comments`)
  } catch { /* noop */ }
}

async function changeStatus(status) {
  try {
    await api.put(`/requirements/${current.value.id}/status`, { status })
    ElMessage.success('状态已更新')
    fetchList()
  } catch (error) { ElMessage.error(error.message); await openDrawer(current.value) }
}

async function handleMove({ card, toStatus, orderIndex }) {
  try {
    await api.put(`/requirements/${card.id}/rank`, { status: toStatus, order_index: orderIndex })
    fetchList()
  } catch (error) { ElMessage.error(error.message); fetchList() }
}

async function linkCase() {
  try {
    await api.post(`/requirements/${current.value.id}/cases`, { case_type: linkForm.case_type, case_id: linkForm.case_id })
    linkedCases.value = await api.get(`/requirements/${current.value.id}/cases`)
    ElMessage.success('已关联')
  } catch (error) { ElMessage.error(error.message) }
}

async function unlinkCase(linkId) {
  try {
    await api.delete(`/requirements/${current.value.id}/cases/${linkId}`)
    linkedCases.value = await api.get(`/requirements/${current.value.id}/cases`)
  } catch (error) { ElMessage.error(error.message) }
}

async function addComment() {
  if (!commentText.value.trim()) return
  try {
    await api.post(`/requirement/${current.value.id}/comments`, { content: commentText.value })
    commentText.value = ''
    comments.value = await api.get(`/requirement/${current.value.id}/comments`)
  } catch (error) { ElMessage.error(error.message) }
}

onMounted(() => { loadIterations(); fetchList() })
</script>

<style scoped>
.wb-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  margin-bottom: 12px;
  gap: 10px;
}
.wb-toolbar__left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.form-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.kc-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.kc-meta { display: flex; align-items: center; gap: 6px; }
.kc-pts { font-size: 12px; color: #64748b; }
.drawer-section { display: flex; flex-direction: column; gap: 10px; }
.ds-row { display: flex; align-items: flex-start; gap: 10px; }
.ds-label { width: 72px; color: #64748b; font-size: 13px; flex-shrink: 0; }
.link-add { display: flex; gap: 8px; align-items: center; }
.comment-add { margin-bottom: 12px; }
.comment-item { padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,0.15); font-size: 13px; }
.comment-time { color: #94a3b8; font-size: 12px; margin-left: 8px; }
.table-pagination { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
