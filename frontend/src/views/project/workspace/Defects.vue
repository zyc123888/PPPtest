<template>
  <div v-loading="loading">
    <div class="wb-toolbar page-card">
      <div class="wb-toolbar__left">
        <el-radio-group v-model="viewMode" size="small">
          <el-radio-button value="list">列表</el-radio-button>
          <el-radio-button value="board">看板</el-radio-button>
        </el-radio-group>
        <el-input v-model="filters.keyword" clearable placeholder="标题关键字" style="width: 200px" @keyup.enter="reload" />
        <el-select v-model="filters.severity" clearable placeholder="严重度" style="width: 130px" @change="reload">
          <el-option v-for="s in severityOptions" :key="s" :label="severityLabels[s]" :value="s" />
        </el-select>
        <el-button @click="reload">查询</el-button>
      </div>
      <el-button v-if="canEdit" type="primary" @click="openCreate">新建缺陷</el-button>
    </div>

    <el-card v-if="viewMode === 'list'" class="page-card" shadow="never">
      <el-table :data="items" border @row-click="openDrawer">
        <el-table-column label="ID" prop="id" width="70" align="center" />
        <el-table-column label="标题" prop="title" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><el-tag :type="statusType[row.status]" size="small">{{ statusLabels[row.status] || row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="严重度" width="90">
          <template #default="{ row }"><el-tag :type="severityType[row.severity]" size="small">{{ severityLabels[row.severity] || row.severity }}</el-tag></template>
        </el-table-column>
        <el-table-column label="优先级" width="90">
          <template #default="{ row }"><el-tag :type="priorityType[row.priority]" size="small" effect="plain">{{ row.priority }}</el-tag></template>
        </el-table-column>
        <el-table-column label="处理人" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ namesOf(row.assignees_json) }}</template>
        </el-table-column>
        <el-table-column label="创建人" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ memberLabel(row.reporter_id) }}</template>
        </el-table-column>
      </el-table>
      <div class="table-pagination">
        <el-pagination layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="fetchList" />
      </div>
    </el-card>

    <el-card v-else class="page-card" shadow="never">
      <KanbanBoard :columns="columns" :items="items" :draggable="canEdit" @open="openDrawer" @move="handleMove">
        <template #card="{ card }">
          <div class="kc-title">{{ card.title }}</div>
          <div class="kc-meta">
            <el-tag :type="severityType[card.severity]" size="small">{{ severityLabels[card.severity] }}</el-tag>
            <el-tag :type="priorityType[card.priority]" size="small" effect="plain">{{ card.priority }}</el-tag>
          </div>
        </template>
      </KanbanBoard>
    </el-card>

    <el-dialog v-model="createVisible" title="新建缺陷" width="640px">
      <el-form ref="createFormRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="标题" prop="title"><el-input v-model="form.title" /></el-form-item>
        <el-form-item label="描述"><RichTextEditor v-model="form.description" placeholder="描述缺陷现象，可直接粘贴 / 拖拽截图" /></el-form-item>
        <el-form-item label="重现步骤"><RichTextEditor v-model="form.reproduce_steps" placeholder="分步描述重现路径，可粘贴截图" /></el-form-item>
        <div class="form-row">
          <el-form-item label="缺陷类型">
            <el-select v-model="form.defect_type" style="width: 100%">
              <el-option v-for="t in defectTypeOptions" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="复现概率">
            <el-select v-model="form.reproducibility" style="width: 100%">
              <el-option v-for="r in reproducibilityOptions" :key="r.value" :label="r.label" :value="r.value" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="严重度">
            <el-select v-model="form.severity" style="width: 100%">
              <el-option v-for="s in severityOptions" :key="s" :label="severityLabels[s]" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="优先级">
            <el-select v-model="form.priority" style="width: 100%">
              <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="处理人（多选）">
            <el-select v-model="form.assignees_json" multiple filterable collapse-tags style="width: 100%" placeholder="选择处理人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
          <el-form-item label="抄送人（多选）">
            <el-select v-model="form.cc_json" multiple filterable collapse-tags style="width: 100%" placeholder="选择抄送人">
              <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="发现版本"><el-input v-model="form.found_version" placeholder="如 v1.2.0" /></el-form-item>
          <el-form-item label="所属模块"><el-input v-model="form.module" placeholder="如 登录/支付" /></el-form-item>
        </div>
        <div class="form-row">
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

    <el-drawer v-model="drawerVisible" :title="current?.title || '缺陷详情'" size="520px">
      <div v-if="current" class="drawer-body">
        <div v-if="canEdit" class="ds-actions">
          <template v-if="!editing">
            <el-button size="small" type="primary" plain :icon="Edit" @click="startEdit">编辑缺陷</el-button>
          </template>
          <template v-else>
            <el-button size="small" @click="cancelEdit">取消</el-button>
            <el-button size="small" type="primary" :loading="saving" @click="saveEdit">保存</el-button>
          </template>
        </div>
        <div class="ds-row">
          <span class="ds-label">状态流转</span>
          <el-select v-model="nextStatus" :disabled="!canEdit || editing" size="small" style="width: 160px" placeholder="选择目标状态" @change="changeStatus">
            <el-option v-for="s in allStatuses" :key="s" :label="statusLabels[s]" :value="s" />
          </el-select>
        </div>
        <div class="ds-row"><span class="ds-label">当前状态</span><el-tag :type="statusType[current.status]">{{ statusLabels[current.status] }}</el-tag></div>
        <div v-if="editing" class="ds-block">
          <div class="ds-block-label">标题</div>
          <el-input v-model="editForm.title" placeholder="缺陷标题" />
        </div>
        <div class="ds-row">
          <span class="ds-label">严重度</span>
          <el-tag v-if="!editing" :type="severityType[current.severity]">{{ severityLabels[current.severity] }}</el-tag>
          <el-select v-else v-model="editForm.severity" size="small" style="width: 160px">
            <el-option v-for="s in severityOptions" :key="s" :label="severityLabels[s]" :value="s" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">优先级</span>
          <el-tag v-if="!editing" :type="priorityType[current.priority]" effect="plain">{{ current.priority }}</el-tag>
          <el-select v-else v-model="editForm.priority" size="small" style="width: 160px">
            <el-option v-for="p in priorityOptions" :key="p" :label="p" :value="p" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">缺陷类型</span>
          <span v-if="!editing">{{ defectTypeLabels[current.defect_type] || current.defect_type || '-' }}</span>
          <el-select v-else v-model="editForm.defect_type" size="small" style="width: 160px">
            <el-option v-for="t in defectTypeOptions" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">复现概率</span>
          <span v-if="!editing">{{ reproducibilityLabels[current.reproducibility] || current.reproducibility || '-' }}</span>
          <el-select v-else v-model="editForm.reproducibility" size="small" style="width: 160px">
            <el-option v-for="r in reproducibilityOptions" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">处理人</span>
          <span v-if="!editing">{{ namesOf(current.assignees_json) }}</span>
          <el-select v-else v-model="editForm.assignees_json" multiple filterable collapse-tags size="small" style="width: 260px" placeholder="选择处理人">
            <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
          </el-select>
        </div>
        <div class="ds-row">
          <span class="ds-label">抄送人</span>
          <span v-if="!editing">{{ namesOf(current.cc_json) }}</span>
          <el-select v-else v-model="editForm.cc_json" multiple filterable collapse-tags size="small" style="width: 260px" placeholder="选择抄送人">
            <el-option v-for="m in members" :key="m.user_id" :label="memberLabel(m.user_id)" :value="m.user_id" />
          </el-select>
        </div>
        <div class="ds-row"><span class="ds-label">创建人</span><span>{{ memberLabel(current.reporter_id) }}</span></div>
        <div class="ds-row">
          <span class="ds-label">所属模块</span>
          <span v-if="!editing">{{ current.module || '-' }}</span>
          <el-input v-else v-model="editForm.module" size="small" style="width: 200px" placeholder="如 登录/支付" />
        </div>
        <div class="ds-row">
          <span class="ds-label">发现版本</span>
          <span v-if="!editing">{{ current.found_version || '-' }}</span>
          <el-input v-else v-model="editForm.found_version" size="small" style="width: 200px" placeholder="如 v1.2.0" />
        </div>
        <div class="ds-row">
          <span class="ds-label">解决版本</span>
          <span v-if="!editing">{{ current.fixed_version || '-' }}</span>
          <el-input v-else v-model="editForm.fixed_version" size="small" style="width: 200px" placeholder="如 v1.3.0" />
        </div>
        <div class="ds-row">
          <span class="ds-label">截止时间</span>
          <span v-if="!editing">{{ formatDate(current.due_date) }}</span>
          <el-date-picker v-else v-model="editForm.due_date" type="date" value-format="YYYY-MM-DD" size="small" style="width: 200px" placeholder="选择日期" />
        </div>
        <div class="ds-row">
          <span class="ds-label">标签</span>
          <div v-if="!editing" class="ds-tags">
            <el-tag v-for="t in (current.tags_json || [])" :key="t" size="small" effect="plain">{{ t }}</el-tag>
            <span v-if="!current.tags_json?.length" class="ds-empty">-</span>
          </div>
          <el-select v-else v-model="editForm.tags_json" multiple filterable allow-create default-first-option size="small" style="width: 260px" placeholder="回车添加标签" />
        </div>
        <div class="ds-block">
          <div class="ds-block-label">描述</div>
          <RichTextEditor v-if="editing" v-model="editForm.description" placeholder="描述缺陷现象，可直接粘贴 / 拖拽截图" />
          <div v-else-if="current.description" class="rich-content" v-html="current.description" />
          <span v-else class="ds-empty">-</span>
        </div>
        <div class="ds-block">
          <div class="ds-block-label">重现步骤</div>
          <RichTextEditor v-if="editing" v-model="editForm.reproduce_steps" placeholder="分步描述重现路径，可粘贴截图" />
          <div v-else-if="current.reproduce_steps" class="rich-content" v-html="current.reproduce_steps" />
          <span v-else class="ds-empty">-</span>
        </div>
        <div class="ds-block">
          <div class="ds-block-label">解决方案</div>
          <RichTextEditor v-if="editing" v-model="editForm.resolution" placeholder="记录根因与解决方案" />
          <div v-else-if="current.resolution" class="rich-content" v-html="current.resolution" />
          <span v-else class="ds-empty">-</span>
        </div>
        <el-divider content-position="left">关联执行 / 用例</el-divider>
        <div v-if="links.runs?.length" class="link-block">
          <div class="link-head">触发执行</div>
          <div v-for="r in links.runs" :key="r.link_id" class="link-item">#{{ r.test_run_id }} {{ r.case_name }} · {{ r.status }}</div>
        </div>
        <div v-if="links.cases?.length" class="link-block">
          <div class="link-head">关联用例</div>
          <div v-for="c in links.cases" :key="c.link_id" class="link-item">{{ c.case_type }} {{ c.case_name || ('#' + c.case_id) }}</div>
        </div>
        <el-empty v-if="!links.runs?.length && !links.cases?.length" description="暂无关联" :image-size="60" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import KanbanBoard from './components/KanbanBoard.vue'
import RichTextEditor from './components/RichTextEditor.vue'
import { Edit } from '@element-plus/icons-vue'
import {
  DEFECT_COLUMNS, DEFECT_STATUS_LABELS, STATUS_TAG_TYPE, PRIORITY_OPTIONS, PRIORITY_TAG_TYPE,
  SEVERITY_OPTIONS, SEVERITY_LABELS, SEVERITY_TAG_TYPE,
  DEFECT_TYPE_OPTIONS, DEFECT_TYPE_LABELS, REPRODUCIBILITY_OPTIONS, REPRODUCIBILITY_LABELS
} from './constants'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const columns = DEFECT_COLUMNS
const statusLabels = DEFECT_STATUS_LABELS
const statusType = STATUS_TAG_TYPE
const priorityOptions = PRIORITY_OPTIONS
const priorityType = PRIORITY_TAG_TYPE
const severityOptions = SEVERITY_OPTIONS
const severityLabels = SEVERITY_LABELS
const severityType = SEVERITY_TAG_TYPE
const defectTypeOptions = DEFECT_TYPE_OPTIONS
const defectTypeLabels = DEFECT_TYPE_LABELS
const reproducibilityOptions = REPRODUCIBILITY_OPTIONS
const reproducibilityLabels = REPRODUCIBILITY_LABELS
const allStatuses = Object.keys(DEFECT_STATUS_LABELS)
const canEdit = computed(() => ['owner', 'manager', 'member'].includes(props.myRole))

const members = ref([])
const memberMap = computed(() => {
  const m = {}
  members.value.forEach((it) => { m[it.user_id] = it.display_name || it.username || ('#' + it.user_id) })
  return m
})
function memberLabel(id) { return id ? (memberMap.value[id] || ('#' + id)) : '-' }
function namesOf(ids) {
  if (!Array.isArray(ids) || !ids.length) return '-'
  return ids.map((id) => memberLabel(id)).join('、')
}
function formatDate(t) { return t ? String(t).slice(0, 10) : '-' }

const DEFECT_FORM_DEFAULT = {
  title: '', description: '', reproduce_steps: '', severity: 'MAJOR', priority: 'P2',
  defect_type: 'FUNCTION', reproducibility: 'ALWAYS', assignees_json: [], cc_json: [],
  found_version: '', module: '', due_date: null, tags_json: []
}

const loading = ref(false)
const viewMode = ref('list')
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filters = reactive({ keyword: '', severity: '' })

const createVisible = ref(false)
const createFormRef = ref(null)
const form = reactive({ ...DEFECT_FORM_DEFAULT })
const rules = { title: [{ required: true, message: '标题必填', trigger: 'blur' }] }

const drawerVisible = ref(false)
const current = ref(null)
const nextStatus = ref('')
const links = ref({ runs: [], cases: [] })
const editing = ref(false)
const saving = ref(false)
const editForm = reactive({
  title: '', description: '', reproduce_steps: '', resolution: '', severity: 'MAJOR', priority: 'P2',
  defect_type: 'FUNCTION', reproducibility: 'ALWAYS', assignees_json: [], cc_json: [],
  found_version: '', fixed_version: '', module: '', due_date: null, tags_json: []
})

async function fetchList() {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: page.value, page_size: pageSize.value })
    if (filters.keyword) params.append('keyword', filters.keyword)
    if (filters.severity) params.append('severity', filters.severity)
    const data = await api.get(`/projects/${props.project.id}/defects?${params}`)
    items.value = data.items
    total.value = data.total
  } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
}

function reload() { page.value = 1; fetchList() }

async function loadMembers() {
  try { members.value = await api.get(`/projects/${props.project.id}/members`) } catch { /* noop */ }
}

function openCreate() {
  Object.assign(form, { ...DEFECT_FORM_DEFAULT, assignees_json: [], cc_json: [], tags_json: [] })
  createVisible.value = true
}

function submitCreate() {
  createFormRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      await api.post(`/projects/${props.project.id}/defects`, { ...form })
      createVisible.value = false
      ElMessage.success('创建成功')
      fetchList()
    } catch (error) { ElMessage.error(error.message) }
  })
}

async function openDrawer(row) {
  current.value = { ...row }
  nextStatus.value = ''
  editing.value = false
  drawerVisible.value = true
  try { links.value = await api.get(`/project-defects/${row.id}/links`) } catch { links.value = { runs: [], cases: [] } }
}

function startEdit() {
  Object.assign(editForm, {
    title: current.value.title || '',
    description: current.value.description || '',
    reproduce_steps: current.value.reproduce_steps || '',
    resolution: current.value.resolution || '',
    severity: current.value.severity || 'MAJOR',
    priority: current.value.priority || 'P2',
    defect_type: current.value.defect_type || 'FUNCTION',
    reproducibility: current.value.reproducibility || 'ALWAYS',
    assignees_json: Array.isArray(current.value.assignees_json) ? [...current.value.assignees_json] : [],
    cc_json: Array.isArray(current.value.cc_json) ? [...current.value.cc_json] : [],
    found_version: current.value.found_version || '',
    fixed_version: current.value.fixed_version || '',
    module: current.value.module || '',
    due_date: current.value.due_date ? String(current.value.due_date).slice(0, 10) : null,
    tags_json: Array.isArray(current.value.tags_json) ? [...current.value.tags_json] : [],
  })
  editing.value = true
}

function cancelEdit() { editing.value = false }

async function saveEdit() {
  if (!editForm.title?.trim()) { ElMessage.warning('标题不能为空'); return }
  saving.value = true
  try {
    const updated = await api.put(`/project-defects/${current.value.id}`, { ...editForm })
    current.value = { ...current.value, ...updated }
    editing.value = false
    ElMessage.success('已保存')
    fetchList()
  } catch (error) { ElMessage.error(error.message) } finally { saving.value = false }
}

async function changeStatus(status) {
  if (!status) return
  try {
    await api.put(`/project-defects/${current.value.id}/status`, { status })
    current.value.status = status
    nextStatus.value = ''
    ElMessage.success('状态已更新')
    fetchList()
  } catch (error) { ElMessage.error(error.message) }
}

async function handleMove({ card, toStatus, orderIndex }) {
  try {
    await api.put(`/project-defects/${card.id}/rank`, { status: toStatus, order_index: orderIndex })
    fetchList()
  } catch (error) { ElMessage.error(error.message); fetchList() }
}

onMounted(() => { loadMembers(); fetchList() })
</script>

<style scoped>
.wb-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; margin-bottom: 12px; gap: 10px; }
.wb-toolbar__left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.form-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.kc-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
.kc-meta { display: flex; align-items: center; gap: 6px; }
.ds-row { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
.ds-actions { display: flex; justify-content: flex-end; gap: 8px; margin-bottom: 12px; }
.ds-label { width: 72px; color: #64748b; font-size: 13px; flex-shrink: 0; }
.ds-block { margin-bottom: 12px; }
.ds-block-label { color: #64748b; font-size: 13px; margin-bottom: 6px; }
.ds-empty { color: #94a3b8; font-size: 13px; }
.ds-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.rich-content { font-size: 14px; line-height: 1.6; color: var(--el-text-color-primary); word-break: break-word; }
.rich-content :deep(img) { max-width: 100%; border-radius: 4px; display: block; margin: 6px 0; }
.rich-content :deep(p) { margin: 4px 0; }
.rich-content :deep(pre) { background: var(--el-fill-color-light); border-radius: 4px; padding: 8px 10px; overflow-x: auto; }
.link-block { margin-bottom: 12px; }
.link-head { font-size: 12px; color: #64748b; margin-bottom: 4px; }
.link-item { font-size: 13px; padding: 4px 0; }
.table-pagination { margin-top: 12px; display: flex; justify-content: flex-end; }
</style>
