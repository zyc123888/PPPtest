<template>
  <div v-loading="loading">
    <div class="wb-toolbar page-card">
      <div class="wb-toolbar__left">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="board">看板</el-radio-button>
          <el-radio-button value="list">列表</el-radio-button>
        </el-radio-group>
        <el-input v-model="filters.keyword" clearable placeholder="标题关键字" style="width: 200px" @keyup.enter="reload" />
        <el-select v-model="filters.iteration_id" clearable placeholder="迭代" style="width: 150px" @change="reload">
          <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
        </el-select>
        <el-button @click="reload">查询</el-button>
      </div>
      <el-button v-if="canEdit" type="primary" @click="openCreate">新增任务</el-button>
    </div>

    <el-card v-if="viewMode === 'board'" class="page-card" shadow="never">
      <KanbanBoard :columns="columns" :items="items" :draggable="canEdit" :transitions="taskTransitions" @open="openDrawer" @move="handleMove">
        <template #card="{ card }">
          <div class="kc-title">{{ card.title }}</div>
          <div class="kc-meta">
            <el-tag :type="priorityType[card.priority]" size="small" effect="plain">{{ card.priority }}</el-tag>
            <span v-if="card.estimate_hours" class="kc-h">{{ card.estimate_hours }}h</span>
          </div>
        </template>
      </KanbanBoard>
      <div v-if="total > pageSize" class="table-pagination">
        <el-pagination layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="fetchList" />
      </div>
    </el-card>

    <el-card v-else class="page-card" shadow="never">
      <el-table :data="items" border @row-click="openDrawer">
        <el-table-column label="ID" prop="id" width="70" align="center" />
        <el-table-column label="标题" prop="title" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType[row.status]" size="small">{{ statusLabels[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{ row }"><el-tag :type="priorityType[row.priority]" size="small" effect="plain">{{ row.priority }}</el-tag></template>
        </el-table-column>
        <el-table-column label="预估(h)" prop="estimate_hours" width="90" align="center" />
        <el-table-column label="实际(h)" prop="spent_hours" width="90" align="center" />
      </el-table>
      <div class="table-pagination">
        <el-pagination layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="fetchList" />
      </div>
    </el-card>

    <el-dialog v-model="createVisible" title="新增任务" width="520px">
      <el-form ref="createFormRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <div class="form-row">
          <el-form-item label="优先级">
            <el-select v-model="form.priority" style="width: 100%">
              <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
          <el-form-item label="迭代">
            <el-select v-model="form.iteration_id" clearable style="width: 100%">
              <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="预估工时">
            <el-input-number v-model="form.estimate_hours" :min="0" :step="1" />
          </el-form-item>
        </div>
        <div class="form-row2">
          <el-form-item label="处理人">
            <el-select v-model="form.assignee_id" clearable filterable style="width: 100%" placeholder="选择处理人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="协作人（多选）">
            <el-select v-model="form.assignees_json" multiple filterable collapse-tags style="width: 100%" placeholder="选择协作人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="截止时间">
          <el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" placeholder="选择日期" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="drawerVisible" :title="current?.title || '任务详情'" size="480px">
      <div v-if="current" class="drawer-body">
        <div v-if="canEdit" class="ds-row" style="justify-content: flex-end">
          <el-popconfirm title="确认删除该任务？" @confirm="removeTask">
            <template #reference>
              <el-button size="small" type="danger" plain>删除任务</el-button>
            </template>
          </el-popconfirm>
        </div>
        <div class="ds-row">
          <span class="ds-label">标题</span>
          <el-input v-model="current.title" :disabled="!canEdit" size="small" @change="(val) => updateField('title', val)" />
        </div>
        <div class="ds-row">
          <span class="ds-label">状态流转</span>
          <el-select v-model="current.status" :disabled="!canEdit" size="small" style="width: 160px" @change="changeStatus">
            <el-option
              v-for="c in columns"
              :key="c.key"
              :label="c.label"
              :value="c.key"
              :disabled="c.key !== current.status && !(taskTransitions[current.status] || []).includes(c.key)"
            />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">优先级</span>
          <el-select v-model="current.priority" :disabled="!canEdit" size="small" style="width: 120px" @change="(val) => updateField('priority', val)">
            <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </div>
        <div class="ds-row"><span class="ds-label">迭代</span>
          <el-select v-model="current.iteration_id" :disabled="!canEdit" clearable size="small" style="width: 200px" placeholder="未规划" @change="(val) => updateField('iteration_id', val)">
            <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">处理人</span>
          <el-select v-model="current.assignee_id" :disabled="!canEdit" clearable filterable size="small" style="width: 200px" placeholder="选择处理人" @change="(val) => updateField('assignee_id', val)">
            <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">协作人</span>
          <el-select v-model="current.assignees_json" :disabled="!canEdit" multiple filterable collapse-tags size="small" style="width: 260px" placeholder="选择协作人" @change="(val) => updateField('assignees_json', val)">
            <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">截止时间</span>
          <el-date-picker v-model="current.due_date" :disabled="!canEdit" type="date" value-format="YYYY-MM-DD" size="small" style="width: 200px" placeholder="选择日期" @change="(val) => updateField('due_date', val)" />
        </div>
        <div class="ds-row"><span class="ds-label">预估工时</span><el-input-number v-model="current.estimate_hours" :disabled="!canEdit" :min="0" :precision="1" size="small" @change="(val) => updateField('estimate_hours', val)" /></div>
        <div class="ds-row"><span class="ds-label">实际工时</span><el-input-number v-model="current.spent_hours" :disabled="!canEdit" :min="0" :precision="1" size="small" @change="(val) => updateField('spent_hours', val)" /></div>
        <div class="ds-row"><span class="ds-label">创建人</span><span>{{ memberLabel(current.reporter_id) }}</span></div>
        <div class="ds-row">
          <span class="ds-label">描述</span>
          <el-input v-model="current.description" :disabled="!canEdit" type="textarea" :rows="3" @change="(val) => updateField('description', val)" />
        </div>
        <el-divider content-position="left">评论</el-divider>
        <el-alert v-if="commentsError" :title="commentsError" type="error" :closable="false" show-icon>
          <template #default><el-button link type="primary" @click="loadComments(current.id)">重试</el-button></template>
        </el-alert>
        <div class="comment-add">
          <el-input v-model="commentText" type="textarea" :rows="2" placeholder="写下评论..." />
          <el-button size="small" type="primary" style="margin-top: 6px" @click="addComment">发表</el-button>
        </div>
        <div v-for="c in comments" :key="c.id" class="comment-item">
          <strong>{{ c.author_name || '用户' }}</strong><span class="comment-time">{{ formatTime(c.created_at) }}</span>
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
import { TASK_COLUMNS, TASK_STATUS_LABELS, STATUS_TAG_TYPE, PRIORITY_OPTIONS, PRIORITY_TAG_TYPE } from './constants'
import { formatDateTime as formatTime } from '@/lib/formatTime'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const columns = TASK_COLUMNS
const statusLabels = TASK_STATUS_LABELS
const statusType = STATUS_TAG_TYPE
const priorityOptions = PRIORITY_OPTIONS
const priorityType = PRIORITY_TAG_TYPE
const canEdit = computed(() => ['owner', 'manager', 'member'].includes(props.myRole))
const taskTransitions = {
  TODO: ['DOING'],
  DOING: ['REVIEW', 'TODO'],
  REVIEW: ['DONE', 'DOING'],
  DONE: ['REVIEW']
}

async function removeTask() {
  if (!current.value) return
  try {
    await api.delete(`/tasks/${current.value.id}`)
    drawerVisible.value = false
    ElMessage.success('任务已删除')
    fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const loading = ref(false)
const viewMode = ref('board')
const items = ref([])
const iterations = ref([])
const members = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({ keyword: '', iteration_id: null })

const createVisible = ref(false)
const createFormRef = ref(null)
const form = reactive({ title: '', description: '', priority: 'P2', iteration_id: null, estimate_hours: 0, assignee_id: null, assignees_json: [], due_date: null })
const rules = { title: [{ required: true, message: '标题必填', trigger: 'blur' }] }

const drawerVisible = ref(false)
const current = ref(null)
const currentSnapshot = ref(null)
const comments = ref([])
const commentText = ref('')
const commentsError = ref('')
let drawerRequestToken = 0

const iterationMap = computed(() => {
  const m = {}
  iterations.value.forEach((it) => { m[it.id] = it.name })
  return m
})

const memberMap = computed(() => {
  const m = {}
  members.value.forEach((x) => { m[x.user_id] = x.display_name || x.username || ('#' + x.user_id) })
  return m
})

function memberLabel(id) { return id ? (memberMap.value[id] || ('#' + id)) : '未指派' }

function cloneValue(value) { return value == null ? value : JSON.parse(JSON.stringify(value)) }

async function fetchList() {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: page.value, page_size: pageSize.value })
    if (filters.keyword) params.append('keyword', filters.keyword)
    if (filters.iteration_id) params.append('iteration_id', filters.iteration_id)
    const data = await api.get(`/projects/${props.project.id}/tasks?${params}`)
    items.value = data.items
    total.value = data.total
  } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
}

async function loadIterations() {
  try { iterations.value = await api.get(`/projects/${props.project.id}/iterations`) } catch { /* noop */ }
}

async function loadMembers() {
  try { members.value = await api.get(`/projects/${props.project.id}/members`) } catch { /* noop */ }
}

function reload() { page.value = 1; fetchList() }

function openCreate() {
  Object.assign(form, { title: '', description: '', priority: 'P2', iteration_id: null, estimate_hours: 0, assignee_id: null, assignees_json: [], due_date: null })
  createVisible.value = true
}

function submitCreate() {
  createFormRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      await api.post(`/projects/${props.project.id}/tasks`, { ...form })
      createVisible.value = false
      ElMessage.success('创建成功')
      fetchList()
    } catch (error) { ElMessage.error(error.message) }
  })
}

async function openDrawer(row) {
  const token = ++drawerRequestToken
  current.value = cloneValue(row)
  currentSnapshot.value = cloneValue(row)
  commentText.value = ''
  comments.value = []
  commentsError.value = ''
  drawerVisible.value = true
  await loadComments(row.id, token)
}

async function loadComments(taskId, token = drawerRequestToken) {
  commentsError.value = ''
  try {
    const rows = await api.get(`/task/${taskId}/comments`)
    if (token === drawerRequestToken && current.value?.id === taskId) comments.value = rows
  } catch (error) {
    if (token === drawerRequestToken) commentsError.value = `评论加载失败：${error.message}`
  }
}

async function changeStatus(status) {
  try {
    await api.put(`/tasks/${current.value.id}/status`, { status })
    currentSnapshot.value.status = status
    ElMessage.success('状态已更新')
    fetchList()
  } catch (error) {
    current.value.status = currentSnapshot.value.status
    ElMessage.error(error.message)
  }
}

async function updateField(field, value) {
  try {
    await api.put(`/tasks/${current.value.id}`, { [field]: value })
    currentSnapshot.value[field] = cloneValue(value)
    ElMessage.success('已更新')
    fetchList()
  } catch (error) {
    current.value[field] = cloneValue(currentSnapshot.value[field])
    ElMessage.error(error.message)
  }
}

async function handleMove({ card, toStatus, orderIndex }) {
  try {
    await api.put(`/tasks/${card.id}/rank`, { status: toStatus, order_index: orderIndex })
    fetchList()
  } catch (error) { ElMessage.error(error.message); fetchList() }
}

async function addComment() {
  if (!commentText.value.trim()) return
  const taskId = current.value.id
  const token = drawerRequestToken
  const content = commentText.value
  try {
    await api.post(`/task/${taskId}/comments`, { content })
    if (token === drawerRequestToken && current.value?.id === taskId) {
      if (commentText.value === content) commentText.value = ''
      await loadComments(taskId, token)
    }
  } catch (error) { ElMessage.error(error.message) }
}

onMounted(() => { loadIterations(); loadMembers(); fetchList() })
</script>

<style scoped>
.wb-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; margin-bottom: 12px; gap: 10px; }
.wb-toolbar__left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.form-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.form-row2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.kc-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.kc-meta { display: flex; align-items: center; gap: 6px; }
.kc-h { font-size: 12px; color: #64748b; }
.ds-row { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.ds-label { width: 72px; color: #64748b; font-size: 13px; flex-shrink: 0; }
.comment-add { margin-bottom: 12px; }
.comment-item { padding: 8px 0; border-bottom: 1px solid rgba(148,163,184,0.15); font-size: 13px; }
.comment-time { color: #94a3b8; font-size: 12px; margin-left: 8px; }
.table-pagination { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
