<template>
  <div class="app-page">
    <PageHeader title="常用工具" subtitle="提供常用的测试数据辅助能力" />

    <div class="tools-hero section-gap">
      <el-card class="page-card tools-hero__main" shadow="never">
        <div class="tools-hero__kicker">Utility Layer</div>
        <div class="tools-hero__title">常用工具</div>
        <div class="tools-hero__subtitle">把格式化、编码、时间转换这类辅助能力统一收口，保持平台内部工具的一致视觉。</div>
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="工具页签" :value="3" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="JSON 默认内容" :value="jsonTool.input ? 1 : 0" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="Base64 示例" :value="base64Tool.input ? 1 : 0" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="时区选项" :value="timezones.length" />
      </el-card>
    </div>

    <el-card class="page-card" shadow="never">
      <el-tabs v-model="activeTab" type="card">
        <el-tab-pane label="JSON 格式化" name="json">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="jsonTool.input" data-testid="json-input" type="textarea" :rows="18" placeholder="请输入 JSON" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="jsonTool.output" data-testid="json-output" type="textarea" :rows="18" readonly placeholder="格式化结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button data-testid="json-format-btn" type="primary" @click="handleJsonFormat">格式化 JSON</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Base64 编解码" name="base64">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="base64Tool.input" type="textarea" :rows="12" placeholder="请输入内容" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="base64Tool.output" type="textarea" :rows="12" readonly placeholder="结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button type="primary" @click="handleBase64Encode">编码</el-button>
              <el-button @click="handleBase64Decode">解码</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="时间戳转换" name="timestamp">
          <div class="ts-now">
            <div class="ts-now__label">当前时间戳</div>
            <div class="ts-now__value">
              <span class="ts-now__number">{{ displayNow }}</span>
              <span class="ts-now__unit">{{ nowUnit === 's' ? '秒' : '毫秒' }}</span>
            </div>
            <div class="ts-now__actions">
              <el-button @click="toggleNowUnit">
                <el-icon><Refresh /></el-icon>&nbsp;切换单位
              </el-button>
              <el-button @click="copyNow">
                <el-icon><CopyDocument /></el-icon>&nbsp;复制
              </el-button>
              <el-button :type="running ? 'danger' : 'success'" @click="toggleRunning">
                <el-icon><VideoPause v-if="running" /><VideoPlay v-else /></el-icon>
                &nbsp;{{ running ? '停止' : '开始' }}
              </el-button>
            </div>
          </div>

          <el-radio-group v-model="tsMode" class="ts-mode section-gap">
            <el-radio-button label="single">单个转换</el-radio-button>
            <el-radio-button label="batch">批量转换</el-radio-button>
          </el-radio-group>

          <template v-if="tsMode === 'single'">
            <div class="ts-block">
              <div class="ts-block__title">
                <el-icon><Clock /></el-icon>&nbsp;时间戳转日期时间
              </div>
              <div class="ts-line">
                <el-input v-model="ts2dt.value" class="ts-line__grow" placeholder="请输入时间戳" />
                <el-select v-model="ts2dt.unit" class="ts-line__unit">
                  <el-option label="秒(s)" value="s" />
                  <el-option label="毫秒(ms)" value="ms" />
                </el-select>
                <el-button type="primary" class="ts-line__btn" @click="convertTs2Dt">转换</el-button>
                <el-input v-model="ts2dt.result" class="ts-line__grow" readonly placeholder="转换结果" />
                <el-select v-model="ts2dt.tz" class="ts-line__tz" filterable>
                  <el-option v-for="tz in timezones" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </div>
            </div>

            <div class="ts-block">
              <div class="ts-block__title">
                <el-icon><Calendar /></el-icon>&nbsp;日期时间转时间戳
              </div>
              <div class="ts-line">
                <el-input v-model="dt2ts.value" class="ts-line__grow" placeholder="如 2026-07-16 17:10:42" />
                <el-select v-model="dt2ts.tz" class="ts-line__tz" filterable>
                  <el-option v-for="tz in timezones" :key="tz" :label="tz" :value="tz" />
                </el-select>
                <el-button type="primary" class="ts-line__btn" @click="convertDt2Ts">转换</el-button>
                <el-input v-model="dt2ts.result" class="ts-line__grow" readonly placeholder="转换结果" />
                <el-select v-model="dt2ts.unit" class="ts-line__unit">
                  <el-option label="秒(s)" value="s" />
                  <el-option label="毫秒(ms)" value="ms" />
                </el-select>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="ts-block">
              <div class="ts-batch-controls">
                <el-select v-model="batch.direction" class="ts-line__dir">
                  <el-option label="时间戳 → 日期时间" value="ts2dt" />
                  <el-option label="日期时间 → 时间戳" value="dt2ts" />
                </el-select>
                <el-select v-model="batch.unit" class="ts-line__unit">
                  <el-option label="秒(s)" value="s" />
                  <el-option label="毫秒(ms)" value="ms" />
                </el-select>
                <el-select v-model="batch.tz" class="ts-line__tz" filterable>
                  <el-option v-for="tz in timezones" :key="tz" :label="tz" :value="tz" />
                </el-select>
              </div>
              <el-row :gutter="16" class="section-gap">
                <el-col :xs="24" :lg="12">
                  <el-input v-model="batch.input" type="textarea" :rows="10" placeholder="每行一个，支持批量转换" />
                </el-col>
                <el-col :xs="24" :lg="12">
                  <el-input v-model="batch.output" type="textarea" :rows="10" readonly placeholder="转换结果" />
                </el-col>
              </el-row>
              <div class="toolbar">
                <div />
                <div class="toolbar-right">
                  <el-button type="primary" @click="convertBatch">转换</el-button>
                </div>
              </div>
            </div>
          </template>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import {
  Refresh, CopyDocument, VideoPause, VideoPlay, Clock, Calendar
} from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'

const activeTab = ref('json')

const jsonTool = reactive({
  input: '{\n  "name": "OmniTest",\n  "module": "接口测试"\n}',
  output: ''
})

const base64Tool = reactive({
  input: 'platform-demo',
  output: ''
})

const handleJsonFormat = async () => {
  try {
    const res = await api.post('/tools/json/format', { payload: jsonTool.input })
    jsonTool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleBase64Encode = async () => {
  try {
    const res = await api.post('/tools/base64/encode', { payload: base64Tool.input })
    base64Tool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleBase64Decode = async () => {
  try {
    const res = await api.post('/tools/base64/decode', { payload: base64Tool.input })
    base64Tool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

/* ---------------- 时间戳转换 ---------------- */
const timezones = [
  'Asia/Shanghai', 'UTC', 'Asia/Tokyo', 'Asia/Hong_Kong', 'Asia/Singapore',
  'Asia/Kolkata', 'Europe/London', 'Europe/Paris', 'Europe/Moscow',
  'America/New_York', 'America/Los_Angeles', 'Australia/Sydney'
]

// 当前时间戳（实时）
const nowMs = ref(Date.now())
const nowUnit = ref('s')
const running = ref(true)
let nowTimer = null

const displayNow = computed(() =>
  nowUnit.value === 's' ? Math.floor(nowMs.value / 1000) : nowMs.value
)

const toggleNowUnit = () => {
  nowUnit.value = nowUnit.value === 's' ? 'ms' : 's'
}

const toggleRunning = () => {
  running.value = !running.value
}

const copyNow = async () => {
  try {
    await navigator.clipboard.writeText(String(displayNow.value))
    ElMessage.success('已复制当前时间戳')
  } catch (error) {
    ElMessage.error('复制失败，请手动复制')
  }
}

onMounted(() => {
  nowTimer = setInterval(() => {
    if (running.value) nowMs.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (nowTimer) clearInterval(nowTimer)
})

// 将某时刻在指定时区下格式化为 YYYY-MM-DD HH:mm:ss
const formatInTimeZone = (ms, timeZone) => {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false
  }).formatToParts(new Date(ms))
  const map = {}
  parts.forEach((p) => { map[p.type] = p.value })
  const hour = map.hour === '24' ? '00' : map.hour
  return `${map.year}-${map.month}-${map.day} ${hour}:${map.minute}:${map.second}`
}

// 指定时区在某 UTC 时刻的偏移（毫秒）
const tzOffsetMs = (utcMs, timeZone) => {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone, hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).formatToParts(new Date(utcMs))
  const map = {}
  parts.forEach((p) => { map[p.type] = p.value })
  const hour = map.hour === '24' ? 0 : Number(map.hour)
  const asUtc = Date.UTC(Number(map.year), Number(map.month) - 1, Number(map.day), hour, Number(map.minute), Number(map.second))
  return asUtc - utcMs
}

// 单个：时间戳 -> 日期时间
const ts2dt = reactive({ value: String(Math.floor(Date.now() / 1000)), unit: 's', tz: 'Asia/Shanghai', result: '' })
// 单个：日期时间 -> 时间戳
const dt2ts = reactive({ value: formatInTimeZone(Date.now(), 'Asia/Shanghai'), tz: 'Asia/Shanghai', unit: 's', result: '' })
// 批量
const batch = reactive({ input: '', direction: 'ts2dt', unit: 's', tz: 'Asia/Shanghai', output: '' })

const tsMode = ref('single')

const timestampToDatetime = (raw, unit, tz) => {
  const text = String(raw).trim()
  if (!/^-?\d+$/.test(text)) throw new Error(`无效时间戳: ${raw}`)
  const ms = unit === 's' ? Number(text) * 1000 : Number(text)
  if (!Number.isFinite(ms)) throw new Error(`无效时间戳: ${raw}`)
  return formatInTimeZone(ms, tz)
}

const datetimeToTimestamp = (raw, tz, unit) => {
  const text = String(raw).trim()
  const m = text.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/)
  if (!m) throw new Error(`无效日期时间: ${raw}`)
  const [, y, mo, d, h = '0', mi = '0', s = '0'] = m
  const naiveUtc = Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s))
  // 迭代校正时区偏移（应对 DST 边界）
  let offset = tzOffsetMs(naiveUtc, tz)
  offset = tzOffsetMs(naiveUtc - offset, tz)
  const realMs = naiveUtc - offset
  return unit === 's' ? Math.floor(realMs / 1000) : realMs
}

const convertTs2Dt = () => {
  try {
    ts2dt.result = timestampToDatetime(ts2dt.value, ts2dt.unit, ts2dt.tz)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const convertDt2Ts = () => {
  try {
    dt2ts.result = String(datetimeToTimestamp(dt2ts.value, dt2ts.tz, dt2ts.unit))
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const convertBatch = () => {
  const lines = batch.input.split('\n')
  const out = []
  for (const line of lines) {
    const text = line.trim()
    if (!text) { out.push(''); continue }
    try {
      out.push(batch.direction === 'ts2dt'
        ? timestampToDatetime(text, batch.unit, batch.tz)
        : String(datetimeToTimestamp(text, batch.tz, batch.unit)))
    } catch (error) {
      out.push(`错误: ${error.message}`)
    }
  }
  batch.output = out.join('\n')
}
</script>

<style scoped>
.tools-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.tools-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.26), transparent 35%);
  color: #f8fafc;
}

.tools-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.tools-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.tools-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.tools-hero__stat {
  border-radius: 18px;
}

@media (max-width: 960px) {
  .tools-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .tools-hero__main {
    grid-column: 1 / -1;
  }
}

/* 时间戳转换 */
.ts-now {
  padding: 20px 24px;
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 14px;
  background: var(--el-fill-color-lighter, #fafafa);
  margin-bottom: 18px;
}

.ts-now__label {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 8px;
}

.ts-now__value {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
}

.ts-now__number {
  font-size: 34px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.5px;
}

.ts-now__unit {
  font-size: 14px;
  color: var(--color-text-secondary, #909399);
}

.ts-now__actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.ts-mode {
  display: block;
}

.ts-block {
  margin-bottom: 20px;
}

.ts-block__title {
  display: flex;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.ts-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.ts-line__grow {
  flex: 1 1 200px;
  min-width: 160px;
}

.ts-line__unit {
  width: 120px;
  flex: 0 0 auto;
}

.ts-line__tz {
  width: 170px;
  flex: 0 0 auto;
}

.ts-line__dir {
  width: 200px;
}

.ts-line__btn {
  flex: 0 0 auto;
}

.ts-batch-controls {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}

@media (max-width: 768px) {
  .ts-line__grow,
  .ts-line__unit,
  .ts-line__tz,
  .ts-line__dir {
    width: 100%;
    flex: 1 1 100%;
  }
}
</style>
