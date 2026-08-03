<template>
  <div class="app-page">
    <PageHeader title="常用工具" subtitle="格式化、编解码、造数、调度预览等测试辅助能力" />

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

        <el-tab-pane label="URL 编解码" name="url">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="urlTool.input" type="textarea" :rows="12" placeholder="请输入待编码 / 解码的文本" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="urlTool.output" type="textarea" :rows="12" readonly placeholder="转换结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button type="primary" @click="handleUrlEncode">URL 编码</el-button>
              <el-button @click="handleUrlDecode">URL 解码</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="哈希计算" name="hash">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="hashTool.input" type="textarea" :rows="12" placeholder="请输入待计算哈希的文本" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="hashTool.output" type="textarea" :rows="12" readonly placeholder="MD5 / SHA1 / SHA256 结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button type="primary" @click="handleHashDigest">计算哈希</el-button>
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

        <el-tab-pane label="Cron 预览" name="cron">
          <el-alert
            class="tool-hint"
            type="info"
            :closable="false"
            title="与测试计划定时调度口径一致：5 段（分 时 日 月 周），按北京时间解释"
          />
          <div class="ts-line section-gap">
            <el-input v-model="cronTool.expression" class="ts-line__grow" placeholder="如 0 2 * * *" />
            <el-select v-model="cronTool.preset" class="ts-line__dir" placeholder="常用预设" @change="applyCronPreset">
              <el-option v-for="item in cronPresets" :key="item.value" :label="`${item.label}（${item.value}）`" :value="item.value" />
            </el-select>
            <el-button type="primary" class="ts-line__btn" @click="handleCronPreview">预览触发时间</el-button>
          </div>
          <div v-if="cronTool.runs.length" class="cron-runs">
            <div v-for="(run, idx) in cronTool.runs" :key="run + idx" class="cron-runs__item">
              <span class="cron-runs__index">第 {{ idx + 1 }} 次</span>
              <span class="cron-runs__time">{{ run }}</span>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="JWT 解析" name="jwt">
          <el-input v-model="jwtTool.input" type="textarea" :rows="5" placeholder="粘贴 JWT（header.payload.signature）" />
          <div class="toolbar">
            <div class="jwt-status">
              <template v-if="jwtTool.expText">
                <el-tag :type="jwtTool.expired ? 'danger' : 'success'" effect="light">
                  {{ jwtTool.expired ? '已过期' : '未过期' }}
                </el-tag>
                <span class="jwt-status__text">过期时间：{{ jwtTool.expText }}</span>
              </template>
            </div>
            <div class="toolbar-right">
              <el-button type="primary" @click="handleJwtDecode">解析 Token</el-button>
            </div>
          </div>
          <el-row v-if="jwtTool.header" :gutter="16">
            <el-col :xs="24" :lg="8">
              <div class="tool-block__title">Header</div>
              <el-input v-model="jwtTool.header" type="textarea" :rows="12" readonly />
            </el-col>
            <el-col :xs="24" :lg="16">
              <div class="tool-block__title">Payload</div>
              <el-input v-model="jwtTool.payload" type="textarea" :rows="12" readonly />
            </el-col>
          </el-row>
        </el-tab-pane>

        <el-tab-pane label="数据生成" name="datagen">
          <div class="ts-line">
            <el-select v-model="genTool.type" class="ts-line__dir">
              <el-option label="手机号" value="phone" />
              <el-option label="身份证号" value="idcard" />
              <el-option label="邮箱" value="email" />
              <el-option label="UUID" value="uuid" />
              <el-option label="随机字符串" value="string" />
            </el-select>
            <div class="gen-count">
              <span class="gen-count__label">数量</span>
              <el-input-number v-model="genTool.count" :min="1" :max="100" />
            </div>
            <div v-if="genTool.type === 'string'" class="gen-count">
              <span class="gen-count__label">长度</span>
              <el-input-number v-model="genTool.length" :min="4" :max="128" />
            </div>
            <el-button type="primary" class="ts-line__btn" @click="handleGenerate">生成</el-button>
            <el-button :disabled="!genTool.output" @click="copyText(genTool.output, '已复制生成结果')">复制结果</el-button>
          </div>
          <el-input v-model="genTool.output" class="section-gap" type="textarea" :rows="12" readonly placeholder="生成结果，每行一条" />
        </el-tab-pane>

        <el-tab-pane label="正则测试" name="regex">
          <div class="ts-line">
            <el-input v-model="regexTool.pattern" class="ts-line__grow" placeholder="正则表达式，如 \d+" />
            <el-checkbox-group v-model="regexTool.flags" class="regex-flags">
              <el-checkbox label="g">g 全局</el-checkbox>
              <el-checkbox label="i">i 忽略大小写</el-checkbox>
              <el-checkbox label="m">m 多行</el-checkbox>
              <el-checkbox label="s">s 单行</el-checkbox>
            </el-checkbox-group>
          </div>
          <el-input v-model="regexTool.text" class="section-gap" type="textarea" :rows="6" placeholder="待匹配文本，结果实时更新" />
          <el-alert v-if="regexResult.error" class="tool-hint" type="error" :closable="false" :title="`表达式错误：${regexResult.error}`" />
          <template v-else>
            <div class="tool-block__title">匹配结果（{{ regexResult.matches.length }} 处{{ regexResult.truncated ? '，仅展示前 200 条' : '' }}）</div>
            <el-table v-if="regexResult.matches.length" :data="regexResult.matches" size="small" border max-height="320">
              <el-table-column type="index" label="#" width="56" />
              <el-table-column prop="match" label="匹配内容" min-width="200" show-overflow-tooltip />
              <el-table-column prop="index" label="起始位置" width="100" />
              <el-table-column label="捕获分组" min-width="200" show-overflow-tooltip>
                <template #default="scope">{{ scope.row.groups.length ? scope.row.groups.join(' | ') : '-' }}</template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="暂无匹配" :image-size="64" />
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

const copyText = async (text, tip = '已复制') => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(tip)
  } catch (error) {
    ElMessage.error('复制失败，请手动复制')
  }
}

/* ---------------- URL 编解码 ---------------- */
const urlTool = reactive({
  input: 'https://example.com/search?q=测试 平台&lang=zh',
  output: ''
})

const handleUrlEncode = () => {
  urlTool.output = encodeURIComponent(urlTool.input)
}

const handleUrlDecode = () => {
  try {
    urlTool.output = decodeURIComponent(urlTool.input)
  } catch (error) {
    ElMessage.error('解码失败：不是合法的 URL 编码内容')
  }
}

/* ---------------- 哈希计算 ---------------- */
const hashTool = reactive({ input: 'platform-demo', output: '' })

const handleHashDigest = async () => {
  try {
    const res = await api.post('/tools/hash/digest', { payload: hashTool.input })
    hashTool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

/* ---------------- Cron 预览 ---------------- */
const cronPresets = [
  { label: '每天 02:00', value: '0 2 * * *' },
  { label: '每小时整点', value: '0 * * * *' },
  { label: '每 30 分钟', value: '*/30 * * * *' },
  { label: '工作日 09:00', value: '0 9 * * 1-5' },
  { label: '每周一 08:30', value: '30 8 * * 1' }
]

const cronTool = reactive({ expression: '0 2 * * *', preset: '', runs: [] })

const applyCronPreset = (value) => {
  if (value) cronTool.expression = value
}

const handleCronPreview = async () => {
  try {
    const res = await api.post('/tools/cron/preview', { payload: cronTool.expression })
    cronTool.runs = res.result.split('\n').filter(Boolean)
  } catch (error) {
    cronTool.runs = []
    ElMessage.error(error.message)
  }
}

/* ---------------- JWT 解析 ---------------- */
const jwtTool = reactive({ input: '', header: '', payload: '', expired: false, expText: '' })

const decodeJwtSegment = (segment) => {
  const normalized = segment.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized + '='.repeat((4 - (normalized.length % 4)) % 4)
  const bytes = Uint8Array.from(atob(padded), (char) => char.charCodeAt(0))
  return JSON.parse(new TextDecoder().decode(bytes))
}

const handleJwtDecode = () => {
  const parts = jwtTool.input.trim().split('.')
  if (parts.length !== 3) {
    ElMessage.error('JWT 需为三段式（header.payload.signature）')
    return
  }
  try {
    const header = decodeJwtSegment(parts[0])
    const payload = decodeJwtSegment(parts[1])
    jwtTool.header = JSON.stringify(header, null, 2)
    jwtTool.payload = JSON.stringify(payload, null, 2)
    if (payload.exp) {
      jwtTool.expired = payload.exp * 1000 < Date.now()
      jwtTool.expText = new Date(payload.exp * 1000).toLocaleString()
    } else {
      jwtTool.expired = false
      jwtTool.expText = ''
    }
  } catch (error) {
    jwtTool.header = ''
    jwtTool.payload = ''
    jwtTool.expText = ''
    ElMessage.error('解析失败：不是合法的 JWT')
  }
}

/* ---------------- 数据生成 ---------------- */
const genTool = reactive({ type: 'phone', count: 5, length: 16, output: '' })

const randomInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min
const randomPick = (list) => list[randomInt(0, list.length - 1)]

const PHONE_PREFIXES = ['133', '135', '137', '138', '139', '150', '152', '157', '158', '159', '176', '177', '180', '182', '185', '186', '188', '189', '198', '199']
const ID_AREA_CODES = ['110101', '310104', '440305', '510107', '330106', '420111', '320102', '500103']
const EMAIL_DOMAINS = ['example.com', 'test.com', 'qq.com', '163.com', 'outlook.com']
const STRING_CHARSET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

const randomString = (length) =>
  Array.from({ length }, () => STRING_CHARSET[randomInt(0, STRING_CHARSET.length - 1)]).join('')

const generatePhone = () =>
  randomPick(PHONE_PREFIXES) + Array.from({ length: 8 }, () => randomInt(0, 9)).join('')

const generateIdCard = () => {
  const area = randomPick(ID_AREA_CODES)
  const year = randomInt(1960, 2005)
  const month = String(randomInt(1, 12)).padStart(2, '0')
  const day = String(randomInt(1, 28)).padStart(2, '0')
  const sequence = String(randomInt(1, 999)).padStart(3, '0')
  const base = `${area}${year}${month}${day}${sequence}`
  const weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
  const checkCodes = '10X98765432'
  const sum = base.split('').reduce((acc, char, idx) => acc + Number(char) * weights[idx], 0)
  return base + checkCodes[sum % 11]
}

const generateEmail = () => `${randomString(randomInt(6, 10)).toLowerCase()}@${randomPick(EMAIL_DOMAINS)}`

const generateUuid = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const rand = randomInt(0, 15)
    return (char === 'x' ? rand : (rand & 0x3) | 0x8).toString(16)
  })
}

const handleGenerate = () => {
  const generators = {
    phone: generatePhone,
    idcard: generateIdCard,
    email: generateEmail,
    uuid: generateUuid,
    string: () => randomString(genTool.length)
  }
  const generator = generators[genTool.type]
  genTool.output = Array.from({ length: genTool.count }, () => generator()).join('\n')
}

/* ---------------- 正则测试 ---------------- */
const regexTool = reactive({
  pattern: '\\d+',
  flags: ['g'],
  text: '订单 20260731-042 已发货，运单号 SF1391234567890'
})

const regexResult = computed(() => {
  const out = { error: '', matches: [], truncated: false }
  if (!regexTool.pattern) return out
  let re
  try {
    re = new RegExp(regexTool.pattern, regexTool.flags.join(''))
  } catch (error) {
    out.error = error.message
    return out
  }
  if (re.global) {
    for (const match of regexTool.text.matchAll(re)) {
      if (out.matches.length >= 200) {
        out.truncated = true
        break
      }
      out.matches.push({ index: match.index, match: match[0], groups: match.slice(1).map((g) => g ?? '') })
    }
  } else {
    const match = re.exec(regexTool.text)
    if (match) {
      out.matches.push({ index: match.index, match: match[0], groups: match.slice(1).map((g) => g ?? '') })
    }
  }
  return out
})

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
.tool-hint {
  margin-bottom: 14px;
}

.tool-block__title {
  font-size: 14px;
  font-weight: 600;
  margin: 12px 0 8px;
}

.cron-runs {
  display: grid;
  gap: 8px;
  max-width: 560px;
}

.cron-runs__item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  border: 1px solid var(--el-border-color-light, #e4e7ed);
  border-radius: 10px;
  background: var(--el-fill-color-lighter, #fafafa);
}

.cron-runs__index {
  flex: 0 0 auto;
  font-size: 12px;
  color: var(--color-text-secondary, #909399);
}

.cron-runs__time {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.jwt-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.jwt-status__text {
  font-size: 13px;
  color: var(--color-text-secondary, #909399);
}

.gen-count {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}

.gen-count__label {
  font-size: 13px;
  color: var(--color-text-secondary, #909399);
}

.regex-flags {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
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
