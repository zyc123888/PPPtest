<template>
  <div ref="containerRef" class="trend-chart" :style="{ height: `${height}px` }">
    <svg
      v-if="width > 0 && points.length"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      :aria-label="ariaLabel"
      class="trend-chart__svg"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(20, 184, 166, 0.26)" />
          <stop offset="100%" stop-color="rgba(20, 184, 166, 0)" />
        </linearGradient>
      </defs>
      <g class="trend-chart__grid">
        <line v-for="tick in yTicks" :key="tick.value" :x1="plot.left" :y1="tick.y" :x2="plot.right" :y2="tick.y" />
      </g>
      <text
        v-for="tick in yTicks"
        :key="`y-${tick.value}`"
        class="trend-chart__tick"
        :x="plot.left - 8"
        :y="tick.y + 4"
        text-anchor="end"
      >
        {{ tick.value }}
      </text>
      <path class="trend-chart__area" :d="areaPath" :fill="`url(#${gradientId})`" />
      <polyline class="trend-chart__line" :points="linePoints" />
      <circle
        v-for="point in points"
        :key="point.key"
        class="trend-chart__point"
        :cx="point.x"
        :cy="point.y"
        r="4"
      >
        <title>{{ point.title }}</title>
      </circle>
      <text
        v-for="point in xLabels"
        :key="`x-${point.key}`"
        class="trend-chart__tick"
        :x="point.x"
        :y="height - 8"
        text-anchor="middle"
      >
        {{ point.label }}
      </text>
    </svg>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  },
  height: {
    type: Number,
    default: 240
  },
  ariaLabel: {
    type: String,
    default: '趋势图'
  }
})

let instanceSeed = 0
const gradientId = `trend-fill-${++instanceSeed}-${Math.random().toString(36).slice(2, 8)}`

const containerRef = ref(null)
const width = ref(0)
let observer = null

onMounted(() => {
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        width.value = Math.round(entry.contentRect.width)
      }
    })
    observer.observe(containerRef.value)
  } else if (containerRef.value) {
    width.value = containerRef.value.clientWidth
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

const plot = computed(() => ({
  left: 40,
  right: Math.max(width.value - 16, 56),
  top: 16,
  bottom: props.height - 32
}))

const yTicks = computed(() => {
  const { top, bottom } = plot.value
  return [100, 50, 0].map((value) => ({
    value,
    y: bottom - (value / 100) * (bottom - top)
  }))
})

const points = computed(() => {
  const series = props.data || []
  if (!series.length || width.value <= 0) return []
  const { left, right, top, bottom } = plot.value
  const span = right - left
  return series.map((item, index) => {
    const x = series.length === 1
      ? left + span / 2
      : left + (span / (series.length - 1)) * index
    const value = Math.max(0, Math.min(Number(item.value) || 0, 100))
    const y = bottom - (value / 100) * (bottom - top)
    return {
      key: item.key ?? index,
      x: Math.round(x * 10) / 10,
      y: Math.round(y * 10) / 10,
      value,
      label: item.label ?? String(item.key ?? index),
      title: item.title ?? `${item.label ?? ''} ${value}%`.trim()
    }
  })
})

const linePoints = computed(() => points.value.map((point) => `${point.x},${point.y}`).join(' '))

const areaPath = computed(() => {
  if (!points.value.length) return ''
  const { bottom } = plot.value
  const first = points.value[0]
  const last = points.value[points.value.length - 1]
  const line = points.value.map((point) => `L${point.x},${point.y}`).join(' ')
  return `M${first.x},${bottom} ${line} L${last.x},${bottom} Z`
})

const xLabels = computed(() => {
  const all = points.value
  if (!all.length) return []
  const minSpacing = 56
  const stride = Math.max(1, Math.ceil((all.length * minSpacing) / Math.max(plot.value.right - plot.value.left, 1)))
  return all.filter((_, index) => index % stride === 0 || index === all.length - 1)
})
</script>

<style scoped>
.trend-chart {
  position: relative;
  width: 100%;
  min-width: 0;
  overflow: hidden;
}

.trend-chart__svg {
  position: absolute;
  top: 0;
  left: 0;
  display: block;
}

.trend-chart__grid line {
  stroke: rgba(148, 163, 184, 0.35);
  stroke-width: 1;
  stroke-dasharray: 4 4;
}

.trend-chart__tick {
  font-size: 11px;
  fill: var(--color-text-secondary, #64748b);
}

.trend-chart__area {
  stroke: none;
}

.trend-chart__line {
  fill: none;
  stroke: #0f766e;
  stroke-width: 2.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.trend-chart__point {
  fill: #ffffff;
  stroke: #0f766e;
  stroke-width: 2;
  cursor: pointer;
}

.trend-chart__point:hover {
  fill: #0f766e;
}
</style>
