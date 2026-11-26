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
        <el-button v-if="canEdit" :disabled="!selectedRows.length" @click="openBatchIteration">规划到迭代</el-button>
      </div>
      <el-button v-if="canEdit" type="primary" @click="openCreate">新增需求</el-button>
    </div>

    <el-card v-if="viewMode === 'list'" class="page-card" shadow="never">
      <el-table :data="items" border @row-click="openDrawer" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="42" :selectable="() => canEdit" />
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
      <div class="board-scope">当前页已加载 {{ items.length }} 条需求，共 {{ total }} 条（仅允许按状态机合法流转的列高亮投递）</div>
      <KanbanBoard :columns="columns" :items="items" :draggable="canEdit" :transitions="requirementTransitions" @open="openDrawer" @move="handleMove">
        <template #card="{ card }">
          <div class="kc-title">{{ card.title }}</div>
          <div class="kc-meta">
            <el-tag :type="priorityType[card.priority]" size="small" effect="plain">{{ card.priority }}</el-tag>
            <span v-if="card.story_points" class="kc-pts">{{ card.story_points }} pts</span>
          </div>
        </template>
      </KanbanBoard>
      <div class="table-pagination">
        <el-pagination layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="fetchList" />
      </div>
    </el-card>

    <!-- batch iteration dialog -->
    <el-dialog v-model="batchIterationVisible" title="批量规划到迭代" width="420px">
      <el-form label-position="top">
        <el-form-item label="已选需求">
          <span>共 {{ selectedRows.length }} 条</span>
        </el-form-item>
        <el-form-item label="目标迭代">
          <el-select v-model="batchIterationId" clearable placeholder="选择迭代（清空并确认表示移出迭代）" style="width: 100%">
            <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchIterationVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchSubmitting" @click="submitBatchIteration">确认</el-button>
      </template>
    </el-dialog>

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
        <div class="form-row2">
          <el-form-item label="负责人">
            <el-select v-model="form.owner_id" clearable filterable style="width: 100%" placeholder="选择负责人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="协作人（多选）">
            <el-select v-model="form.assignees_json" multiple filterable collapse-tags style="width: 100%" placeholder="选择协作人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row2">
          <el-form-item label="截止时间">
            <el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" placeholder="选择日期" />
          </el-form-item>
          <el-form-item label="标签">
            <el-select v-model="form.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="回车添加标签" />
          </el-form-item>
        </div>
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
          <div v-if="canDelete" class="ds-row" style="justify-content: flex-end">
            <el-popconfirm title="确认删除该需求？关联用例关系将一并解除" @confirm="removeRequirement">
              <template #reference>
                <el-button size="small" type="danger" plain>删除需求</el-button>
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
                :disabled="c.key !== current.status && !(requirementTransitions[current.status] || []).includes(c.key)"
              />
            </el-select>
          </div>
          <div class="ds-row">
            <span class="ds-label">优先级</span>
            <el-select v-model="current.priority" :disabled="!canEdit" size="small" style="width: 120px" @change="(val) => updateField('priority', val)">
              <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
            </el-select>
          </div>
          <div class="ds-row">
            <span class="ds-label">故事点</span>
            <el-input-number v-model="current.story_points" :disabled="!canEdit" :min="0" :step="1" size="small" @change="(val) => updateField('story_points', val)" />
          </div>
          <div class="ds-row"><span class="ds-label">迭代</span>
            <el-select v-model="current.iteration_id" :disabled="!canEdit" clearable size="small" style="width: 200px" placeholder="未规划" @change="(val) => updateField('iteration_id', val)">
              <el-option v-for="it in iterations" :key="it.id" :label="it.name" :value="it.id" />
            </el-select>
          </div>
          <div class="ds-row">
            <span class="ds-label">负责人</span>
            <el-select v-model="current.owner_id" :disabled="!canEdit" clearable filterable size="small" style="width: 200px" placeholder="选择负责人" @change="(val) => updateField('owner_id', val)">
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
          <div class="ds-row"><span class="ds-label">创建人</span><span>{{ memberLabel(current.reporter_id) }}</span></div>
          <div class="ds-row">
            <span class="ds-label">标签</span>
            <div class="ds-tags">
              <el-tag v-for="t in (current.tags_json || [])" :key="t" size="small" effect="plain">{{ t }}</el-tag>
              <span v-if="!current.tags_json?.length">-</span>
            </div>
          </div>
          <div class="ds-row">
            <span class="ds-label">描述</span>
            <el-input v-model="current.description" :disabled="!canEdit" type="textarea" :rows="3" @change="(val) => updateField('description', val)" />
          </div>
        </div>

        <el-divider content-position="left">关联用例（追溯）</el-divider>
        <el-alert v-if="linkedCasesError" :title="linkedCasesError" type="error" :closable="false" show-icon>
          <template #default><el-button link type="primary" @click="loadLinkedCases(current.id)">重试</el-button></template>
        </el-alert>
        <div class="link-add">
          <el-select v-model="linkForm.case_key" filterable remote reserve-keyword clearable :remote-method="searchCases" :loading="caseSearchLoading" size="small" style="width: 300px" placeholder="搜索当前项目用例">
            <el-option v-for="item in caseOptions" :key="`${item.case_type}:${item.case_id}`" :label="`${item.case_type} · ${item.name} · v${item.version_no}`" :value="`${item.case_type}:${item.case_id}`">
              <span>{{ item.case_type }} · {{ item.name }} · v{{ item.version_no }}</span>
            </el-option>
          </el-select>
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
        <el-alert v-if="commentsError" :title="commentsError" type="error" :closable="false" show-icon>
          <template #default><el-button link type="primary" @click="loadComments(current.id)">重试</el-button></template>
        </el-alert>
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
import { formatDateTime as formatTime } from '@/lib/formatTime'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const columns = REQUIREMENT_COLUMNS
const statusLabels = REQUIREMENT_STATUS_LABELS
const statusType = STATUS_TAG_TYPE
const priorityOptions = PRIORITY_OPTIONS
const priorityType = PRIORITY_TAG_TYPE
const typeOptions = REQUIREMENT_TYPE_OPTIONS
const requirementTransitions = {
  PENDING: ['PLANNING', 'REJECTED', 'CLOSED'],
  PLANNING: ['IN_PROGRESS', 'PENDING', 'REJECTED'],
  IN_PROGRESS: ['TESTING', 'PLANNING'],
  TESTING: ['DONE', 'IN_PROGRESS'],
  DONE: ['CLOSED', 'TESTING'],
  CLOSED: ['PENDING'],
  REJECTED: ['PENDING']
}

async function removeRequirement() {
  if (!current.value) return
  try {
    await api.delete(`/requirements/${current.value.id}`)
    drawerVisible.value = false
    ElMessage.success('需求已删除')
    fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const canEdit = computed(() => ['owner', 'manager', 'member'].includes(props.myRole))
const canDelete = computed(() => ['owner', 'manager'].includes(props.myRole))

const members = ref([])
const memberMap = computed(() => {
  const m = {}
  members.value.forEach((it) => { m[it.user_id] = it.display_name || it.username || ('#' + it.user_id) })
  return m
})
function memberLabel(id) { return id ? (memberMap.value[id] || ('#' + id)) : '-' }

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
const form = reactive({ title: '', description: '', priority: 'P2', type: 'FEATURE', iteration_id: null, story_points: 0, owner_id: null, assignees_json: [], due_date: null, tags_json: [] })
const rules = { title: [{ required: true, message: '标题必填', trigger: 'blur' }] }

const drawerVisible = ref(false)
const current = ref(null)
const currentSnapshot = ref(null)
const linkedCases = ref([])
const comments = ref([])
const linkForm = reactive({ case_key: null })
const caseOptions = ref([])
const caseSearchLoading = ref(false)
const commentText = ref('')
const linkedCasesError = ref('')
const commentsError = ref('')
let drawerRequestToken = 0
let caseSearchToken = 0

const iterationMap = computed(() => {
  const m = {}
  iterations.value.forEach((it) => { m[it.id] = it.name })
  return m
})

function cloneValue(value) { return value == null ? value : JSON.parse(JSON.stringify(value)) }

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

async function loadMembers() {
  try { members.value = await api.get(`/projects/${props.project.id}/members`) } catch { /* noop */ }
}

function reload() { page.value = 1; fetchList() }

const selectedRows = ref([])
const batchIterationVisible = ref(false)
const batchIterationId = ref(null)
const batchSubmitting = ref(false)

function onSelectionChange(rows) { selectedRows.value = rows }

function openBatchIteration() {
  if (!selectedRows.value.length) return
  batchIterationId.value = null
  batchIterationVisible.value = true
}

async function submitBatchIteration() {
  batchSubmitting.value = true
  try {
    await api.put('/requirements/batch-iteration', {
      requirement_ids: selectedRows.value.map((row) => row.id),
      iteration_id: batchIterationId.value || null
    })
    batchIterationVisible.value = false
    ElMessage.success('已更新所选需求的迭代归属')
    fetchList()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    batchSubmitting.value = false
  }
}

function openCreate() {
  Object.assign(form, { title: '', description: '', priority: 'P2', type: 'FEATURE', iteration_id: null, story_points: 0, owner_id: null, assignees_json: [], due_date: null, tags_json: [] })
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
  const token = ++drawerRequestToken
  current.value = cloneValue(row)
  currentSnapshot.value = cloneValue(row)
  commentText.value = ''
  linkedCases.value = []
  comments.value = []
  linkedCasesError.value = ''
  commentsError.value = ''
  linkForm.case_key = null
  caseOptions.value = []
  caseSearchToken += 1
  drawerVisible.value = true
  await Promise.all([loadLinkedCases(row.id, token), loadComments(row.id, token)])
}

async function loadLinkedCases(requirementId, token = drawerRequestToken) {
  linkedCasesError.value = ''
  try {
    const rows = await api.get(`/requirements/${requirementId}/cases`)
    if (token === drawerRequestToken && current.value?.id === requirementId) linkedCases.value = rows
  } catch (error) {
    if (token === drawerRequestToken) linkedCasesError.value = `关联用例加载失败：${error.message}`
  }
}

async function loadComments(requirementId, token = drawerRequestToken) {
  commentsError.value = ''
  try {
    const rows = await api.get(`/requirement/${requirementId}/comments`)
    if (token === drawerRequestToken && current.value?.id === requirementId) comments.value = rows
  } catch (error) {
    if (token === drawerRequestToken) commentsError.value = `评论加载失败：${error.message}`
  }
}

async function changeStatus(status) {
  try {
    await api.put(`/requirements/${current.value.id}/status`, { status })
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
    await api.put(`/requirements/${current.value.id}`, { [field]: value })
    currentSnapshot.value[field] = cloneValue(value)
    ElMessage.success('已更新')
    fetchList()
  } catch (error) {
    current.value[field] = cloneValue(currentSnapshot.value[field])
    ElMessage.error(error.message)
  }
}

async function handleMove({ card, toStatus, orderIndex }) {
  const prevStatus = card.status
  const prevOrder = card.order_index
  const targetItem = items.value.find((it) => it.id === card.id)
  if (targetItem) {
    targetItem.status = toStatus
    targetItem.order_index = orderIndex
  }
  try {
    await api.put(`/requirements/${card.id}/rank`, { status: toStatus, order_index: orderIndex })
  } catch (error) {
    if (targetItem) {
      targetItem.status = prevStatus
      targetItem.order_index = prevOrder
    }
    ElMessage.error(error.message)
    fetchList()
  }
}

async function linkCase() {
  const selected = caseOptions.value.find((item) => `${item.case_type}:${item.case_id}` === linkForm.case_key)
  if (!selected) { ElMessage.warning('请先搜索并选择一个用例'); return }
  const requirementId = current.value.id
  const token = drawerRequestToken
  try {
    await api.post(`/requirements/${requirementId}/cases`, { case_type: selected.case_type, case_id: selected.case_id })
    if (token === drawerRequestToken && current.value?.id === requirementId) {
      linkForm.case_key = null
      await loadLinkedCases(requirementId, token)
    }
    ElMessage.success('已关联')
  } catch (error) { ElMessage.error(error.message) }
}

async function searchCases(keyword) {
  const token = ++caseSearchToken
  const query = String(keyword || '').trim()
  if (query.length < 2) { caseOptions.value = []; caseSearchLoading.value = false; return }
  caseSearchLoading.value = true
  try {
    const results = await api.get(`/cases?project_id=${props.project.id}&keyword=${encodeURIComponent(query)}`)
    if (token === caseSearchToken) caseOptions.value = results
  } catch (error) {
    if (token === caseSearchToken) ElMessage.error(`用例搜索失败：${error.message}`)
  } finally { if (token === caseSearchToken) caseSearchLoading.value = false }
}

async function unlinkCase(linkId) {
  const requirementId = current.value.id
  const token = drawerRequestToken
  try {
    await api.delete(`/requirements/${requirementId}/cases/${linkId}`)
    if (token === drawerRequestToken && current.value?.id === requirementId) await loadLinkedCases(requirementId, token)
  } catch (error) { ElMessage.error(error.message) }
}

async function addComment() {
  if (!commentText.value.trim()) return
  const requirementId = current.value.id
  const token = drawerRequestToken
  const content = commentText.value
  try {
    await api.post(`/requirement/${requirementId}/comments`, { content })
    if (token === drawerRequestToken && current.value?.id === requirementId) {
      if (commentText.value === content) commentText.value = ''
      await loadComments(requirementId, token)
    }
  } catch (error) { ElMessage.error(error.message) }
}

onMounted(() => { loadIterations(); loadMembers(); fetchList() })
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
.form-row2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.ds-tags { display: flex; flex-wrap: wrap; gap: 4px; }
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
.board-scope { margin-bottom: 10px; color: var(--el-text-color-secondary); font-size: 13px; }
</style>
