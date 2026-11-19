<template>
  <div v-loading="loading">
    <div class="wb-toolbar page-card">
      <div class="wb-toolbar__left">
        <span class="wb-title">迭代规划</span>
      </div>
      <el-button v-if="canEdit" type="primary" @click="openCreate">新建迭代</el-button>
    </div>

    <el-empty v-if="!iterations.length" description="暂无迭代，点击右上角创建" />

    <div class="iter-grid">
      <el-card v-for="it in iterations" :key="it.id" class="iter-card" shadow="hover">
        <div class="iter-head">
          <div class="iter-name">{{ it.name }}</div>
          <el-tag :type="statusType[it.status]" size="small">{{ statusLabels[it.status] || it.status }}</el-tag>
        </div>
        <div class="iter-goal">{{ it.goal || '暂无迭代目标' }}</div>
        <div class="iter-dates">
          <el-icon><Calendar /></el-icon>
          <span>{{ formatDate(it.start_date) }} ~ {{ formatDate(it.end_date) }}</span>
        </div>
        <div class="burndown">
          <div class="burndown-row">
            <span>故事点进度（剩余 / 总计）</span>
            <strong>{{ burndowns[it.id]?.remaining_points ?? '-' }} / {{ burndowns[it.id]?.total_points ?? '-' }}</strong>
          </div>
          <el-progress
            :percentage="donePercent(it.id)"
            :stroke-width="10"
            :status="donePercent(it.id) === 100 ? 'success' : ''"
          />
          <div v-if="burndownChart(it.id)" class="burndown-chart">
            <div class="burndown-legend">
              <span class="legend-item"><i class="legend-dot ideal" />理想燃尽</span>
              <span class="legend-item"><i class="legend-dot actual" />实际剩余</span>
            </div>
            <svg viewBox="0 0 260 86" class="burndown-svg" role="img" aria-label="迭代燃尽趋势图">
              <line x1="24" y1="10" x2="248" y2="10" stroke="#e2e8f0" stroke-dasharray="2 2" />
              <line x1="24" y1="38" x2="248" y2="38" stroke="#e2e8f0" stroke-dasharray="2 2" />
              <line x1="24" y1="66" x2="248" y2="66" stroke="#cbd5e1" />
              <polyline :points="burndownChart(it.id).idealPoints" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="4 3" />
              <polyline :points="burndownChart(it.id).actualPoints" fill="none" stroke="#6366f1" stroke-width="2" />
              <circle
                v-for="(pt, idx) in burndownChart(it.id).dots"
                :key="idx"
                :cx="pt.x"
                :cy="pt.y"
                r="2.5"
                fill="#6366f1"
              />
              <text
                v-for="(pt, idx) in burndownChart(it.id).labels"
                :key="'lbl-' + idx"
                :x="pt.x"
                y="80"
                text-anchor="middle"
                font-size="9"
                fill="#64748b"
              >{{ pt.text }}</text>
            </svg>
          </div>
          <div class="burndown-row sub">
            <span>需求完成：{{ burndowns[it.id]?.requirement_done ?? 0 }} / {{ burndowns[it.id]?.requirement_total ?? 0 }}</span>
            <span>周期时间消耗：{{ timeElapsedPercent(it) }}%</span>
          </div>
          <div v-if="burndowns[it.id]?.series?.length > 1" class="burndown-chart">
            <div class="burndown-chart__legend">
              <span class="legend-item"><i class="dot ideal" />理想燃尽线</span>
              <span class="legend-item"><i class="dot actual" />实际剩余线</span>
            </div>
            <svg viewBox="0 0 260 72" class="burndown-svg" preserveAspectRatio="none">
              <polyline
                fill="none"
                stroke="#94a3b8"
                stroke-width="1.5"
                stroke-dasharray="4 3"
                :points="burndownPolyline(burndowns[it.id], 'ideal_remaining')"
              />
              <polyline
                fill="none"
                stroke="#2563eb"
                stroke-width="2"
                :points="burndownPolyline(burndowns[it.id], 'actual_remaining')"
              />
            </svg>
          </div>
        </div>
        <div v-if="canEdit" class="iter-actions">
          <el-button size="small" text @click="openEdit(it)">编辑</el-button>
          <el-popconfirm title="确认删除该迭代？关联项将回退需求池" @confirm="removeIteration(it)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="editVisible" :title="editing ? '编辑迭代' : '新建迭代'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="迭代目标"><el-input v-model="form.goal" type="textarea" :rows="2" /></el-form-item>
        <div class="form-row">
          <el-form-item label="状态">
            <el-select v-model="form.status" style="width: 100%">
              <el-option v-for="s in statusOptions" :key="s" :label="statusLabels[s]" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="容量(故事点)">
            <el-input-number v-model="form.capacity_points" :min="0" :step="1" style="width: 100%" />
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="开始日期">
            <el-date-picker v-model="form.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="form.end_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import { Calendar } from '@element-plus/icons-vue'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const statusOptions = ['PLANNING', 'ACTIVE', 'CLOSED']
const statusLabels = { PLANNING: '规划中', ACTIVE: '进行中', CLOSED: '已关闭' }
const statusType = { PLANNING: 'info', ACTIVE: 'warning', CLOSED: 'success' }
const canEdit = computed(() => ['owner', 'manager'].includes(props.myRole))

const loading = ref(false)
const iterations = ref([])
const burndowns = reactive({})

const editVisible = ref(false)
const editing = ref(null)
const formRef = ref(null)
const form = reactive({ name: '', goal: '', status: 'PLANNING', capacity_points: 0, start_date: null, end_date: null })
const rules = { name: [{ required: true, message: '名称必填', trigger: 'blur' }] }

function formatDate(t) { return t ? String(t).slice(0, 10) : '未设置' }

function burndownPolyline(b, field) {
  const series = b?.series || []
  if (series.length < 2) return ''
  const maxVal = Math.max(b?.total_points || 1, ...series.map((p) => Math.max(p.ideal_remaining || 0, p.actual_remaining || 0)), 1)
  return series
    .map((pt, idx) => {
      const x = Math.round((idx / (series.length - 1)) * 248) + 6
      const val = Number(pt[field] ?? 0)
      const y = Math.round(64 - (val / maxVal) * 54)
      return `${x},${y}`
    })
    .join(' ')
}

function donePercent(id) {
  const b = burndowns[id]
  if (!b || !b.total_points) return 0
  return Math.round((b.done_points / b.total_points) * 100)
}

function timeElapsedPercent(it) {
  if (!it?.start_date || !it?.end_date) return 0
  const start = new Date(it.start_date).getTime()
  const end = new Date(it.end_date).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start) return 0
  const now = Date.now()
  if (now <= start) return 0
  if (now >= end) return 100
  return Math.round(((now - start) / (end - start)) * 100)
}

function burndownChart(id) {
  const b = burndowns[id]
  const series = b?.series
  if (!Array.isArray(series) || series.length < 2) return null
  const maxVal = Math.max(b.total_points || 0, ...series.map((s) => Math.max(s.ideal || 0, s.actual || 0)), 1)
  const left = 24
  const right = 248
  const top = 10
  const bottom = 66
  const width = right - left
  const height = bottom - top
  const toCoord = (idx, val) => {
    const x = Math.round(left + (idx / Math.max(series.length - 1, 1)) * width)
    const y = Math.round(bottom - (Math.max(val, 0) / maxVal) * height)
    return { x, y }
  }
  const idealPts = series.map((s, idx) => toCoord(idx, s.ideal ?? 0))
  const actualPts = series.map((s, idx) => toCoord(idx, s.actual ?? 0))
  return {
    idealPoints: idealPts.map((p) => `${p.x},${p.y}`).join(' '),
    actualPoints: actualPts.map((p) => `${p.x},${p.y}`).join(' '),
    dots: actualPts,
    labels: [
      { x: idealPts[0].x, text: series[0].label },
      { x: idealPts[Math.floor(series.length / 2)].x, text: series[Math.floor(series.length / 2)].label },
      { x: idealPts[series.length - 1].x, text: series[series.length - 1].label }
    ]
  }
}

async function fetchList() {
  loading.value = true
  try {
    iterations.value = await api.get(`/projects/${props.project.id}/iterations?include_burndown=true`)
    iterations.value.forEach((it) => {
      if (it.burndown) burndowns[it.id] = it.burndown
    })
  } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', goal: '', status: 'PLANNING', capacity_points: 0, start_date: null, end_date: null })
  editVisible.value = true
}

function openEdit(it) {
  editing.value = it
  Object.assign(form, {
    name: it.name, goal: it.goal || '', status: it.status,
    capacity_points: it.capacity_points || 0,
    start_date: it.start_date ? String(it.start_date).slice(0, 10) : null,
    end_date: it.end_date ? String(it.end_date).slice(0, 10) : null
  })
  editVisible.value = true
}

function submit() {
  formRef.value?.validate(async (valid) => {
    if (!valid) return
    try {
      if (editing.value) {
        await api.put(`/iterations/${editing.value.id}`, { ...form })
      } else {
        await api.post(`/projects/${props.project.id}/iterations`, { ...form })
      }
      editVisible.value = false
      ElMessage.success('保存成功')
      fetchList()
    } catch (error) { ElMessage.error(error.message) }
  })
}

async function removeIteration(it) {
  try {
    await api.delete(`/iterations/${it.id}`)
    ElMessage.success('已删除')
    fetchList()
  } catch (error) { ElMessage.error(error.message) }
}

onMounted(fetchList)
</script>

<style scoped>
.wb-toolbar { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; margin-bottom: 12px; }
.wb-title { font-size: 15px; font-weight: 600; }
.iter-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.iter-card { border-radius: 12px; }
.iter-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.iter-name { font-size: 15px; font-weight: 600; }
.iter-goal { color: #64748b; font-size: 13px; min-height: 20px; margin-bottom: 10px; }
.iter-dates { display: flex; align-items: center; gap: 6px; color: #94a3b8; font-size: 12px; margin-bottom: 12px; }
.burndown-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }
.burndown-chart { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #e2e8f0; }
.burndown-chart__legend { display: flex; gap: 12px; font-size: 11px; color: #64748b; margin-bottom: 4px; }
.legend-item { display: inline-flex; align-items: center; gap: 4px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.dot.ideal { background: #94a3b8; }
.dot.actual { background: #2563eb; }
.burndown-svg { width: 100%; height: 68px; background: #f8fafc; border-radius: 6px; }
.burndown-row.sub { color: #94a3b8; font-size: 12px; margin-top: 6px; }
.burndown-chart { margin-top: 8px; padding: 6px 8px; background: #f8fafc; border-radius: 8px; border: 1px solid #eef2f6; }
.burndown-legend { display: flex; justify-content: flex-end; gap: 12px; font-size: 11px; color: #64748b; margin-bottom: 2px; }
.legend-item { display: inline-flex; align-items: center; gap: 4px; }
.legend-dot { width: 8px; height: 2px; display: inline-block; }
.legend-dot.ideal { background: #94a3b8; }
.legend-dot.actual { background: #6366f1; }
.burndown-svg { width: 100%; height: 76px; display: block; }
.iter-actions { display: flex; justify-content: flex-end; gap: 4px; margin-top: 10px; }
.form-row { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
</style>
