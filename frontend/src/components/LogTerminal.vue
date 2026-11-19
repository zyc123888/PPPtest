<template>
  <div class="log-terminal">
    <div class="log-terminal__bar">
      <div class="log-terminal__filters">
        <el-input
          v-model="keyword"
          size="small"
          clearable
          placeholder="搜索日志关键字..."
          style="width: 220px"
        />
        <el-switch
          v-model="errorsOnly"
          size="small"
          active-text="仅看错误/警告"
        />
        <span class="log-terminal__count">
          共 {{ visibleLines.length }} / {{ allLines.length }} 行
        </span>
      </div>
      <el-button size="small" @click="$emit('copy', content)">复制原文</el-button>
    </div>

    <div class="log-terminal__body">
      <div v-if="!visibleLines.length" class="log-terminal__empty">暂无匹配的日志输出</div>
      <div
        v-for="row in visibleLines"
        :key="row.lineNo"
        class="log-line"
        :class="row.levelClass"
      >
        <span class="log-line__no">{{ row.lineNo }}</span>
        <span class="log-line__text">{{ row.text }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  content: {
    type: String,
    default: ''
  }
})

defineEmits(['copy'])

const keyword = ref('')
const errorsOnly = ref(false)

const classifyLine = (line) => {
  const lower = line.toLowerCase()
  if (/(error|exception|traceback|failed|fatal|assert(ion)?error|❌|✗)/.test(lower)) return 'is-error'
  if (/(warn|warning|timeout|retry|⚠)/.test(lower)) return 'is-warn'
  if (/(success|passed|pass\b|✓|✅|200 ok)/.test(lower)) return 'is-success'
  return ''
}

const allLines = computed(() => {
  const raw = String(props.content || '')
  if (!raw) return []
  return raw.split(/\r?\n/).map((text, idx) => ({
    lineNo: idx + 1,
    text,
    levelClass: classifyLine(text)
  }))
})

const visibleLines = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return allLines.value.filter((row) => {
    if (errorsOnly.value && !['is-error', 'is-warn'].includes(row.levelClass)) return false
    if (kw && !row.text.toLowerCase().includes(kw)) return false
    return true
  })
})
</script>

<style scoped>
.log-terminal {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.log-terminal__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.log-terminal__filters {
  display: flex;
  align-items: center;
  gap: 12px;
}
.log-terminal__count {
  font-size: 12px;
  color: #64748b;
}
.log-terminal__body {
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 8px;
  padding: 10px 0;
  max-height: 420px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.55;
}
.log-terminal__empty {
  padding: 24px;
  text-align: center;
  color: #64748b;
}
.log-line {
  display: flex;
  padding: 1px 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.log-line:hover {
  background: rgba(148, 163, 184, 0.12);
}
.log-line__no {
  flex: 0 0 42px;
  color: #64748b;
  user-select: none;
  text-align: right;
  padding-right: 12px;
}
.log-line__text {
  flex: 1;
}
.log-line.is-error {
  background: rgba(239, 68, 68, 0.16);
  color: #fca5a5;
}
.log-line.is-warn {
  background: rgba(245, 158, 11, 0.14);
  color: #fcd34d;
}
.log-line.is-success {
  color: #86efac;
}
</style>
