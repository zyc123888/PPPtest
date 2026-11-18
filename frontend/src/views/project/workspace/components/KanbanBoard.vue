<template>
  <div class="kanban-board">
    <div
      v-for="col in displayColumns"
      :key="col.key"
      class="kanban-col"
      :class="{
        'is-drop-target': dragOverKey === col.key && isColumnAllowedDrop(col),
        'is-drop-disabled': dragging && dragging.fromKey !== col.key && !isColumnAllowedDrop(col)
      }"
      @dragover.prevent="onDragOver(col.key)"
      @dragleave="onDragLeave(col.key)"
      @drop="onDrop(col.key)"
    >
      <div class="kanban-col__head">
        <button v-if="col.collapsible" class="kanban-col__toggle" type="button" :aria-expanded="!collapsedKeys.has(col.key)" @click="toggleColumn(col.key)">{{ col.label }} {{ collapsedKeys.has(col.key) ? '▸' : '▾' }}</button>
        <span v-else class="kanban-col__title">{{ col.label }}</span>
        <el-tag size="small" round type="info">{{ grouped[col.key]?.length || 0 }}</el-tag>
      </div>
      <div v-show="!collapsedKeys.has(col.key)" class="kanban-col__body">
        <div
          v-for="card in grouped[col.key] || []"
          :key="card.id"
          class="kanban-card"
          :draggable="draggable && !col.unclassified"
          tabindex="0"
          @dragstart="onDragStart(card, col.key)"
          @dragend="onDragEnd"
          @dragover.prevent.stop="onDragOver(col.key, card)"
          @drop.stop="onDrop(col.key, card)"
          @keydown.enter.prevent="$emit('open', card)"
          @keydown.space.prevent="$emit('open', card)"
          @click="$emit('open', card)"
        >
          <slot name="card" :card="card">
            <div class="kanban-card__title">{{ card.title }}</div>
          </slot>
          <select
            v-if="canKeyboardMove(col, card)"
            class="kanban-card__move"
            :aria-label="`更改「${card.title}」的状态`"
            @click.stop
            @keydown.stop
            @change="onKeyboardMove(card, $event)"
          >
            <option value="" disabled selected>移动状态…</option>
            <option v-for="target in moveTargets(col, card)" :key="target.key" :value="target.key">{{ target.label }}</option>
          </select>
        </div>
        <div v-if="!(grouped[col.key] || []).length" class="kanban-empty">暂无</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  columns: { type: Array, required: true },
  items: { type: Array, default: () => [] },
  statusKey: { type: String, default: 'status' },
  draggable: { type: Boolean, default: true },
  transitions: { type: Object, default: null }
})

const emit = defineEmits(['open', 'move'])

const dragging = ref(null)
const dragOverKey = ref(null)
const collapsedKeys = ref(new Set(props.columns.filter((column) => column.defaultCollapsed).map((column) => column.key)))

function toggleColumn(key) {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
}

const displayColumns = computed(() => {
  const knownStatuses = new Set(props.columns.flatMap((column) => column.statuses || [column.key]))
  const hasUnknown = props.items.some((item) => !knownStatuses.has(item[props.statusKey]))
  return hasUnknown
    ? [...props.columns, { key: '__unclassified__', label: '待归类', unclassified: true }]
    : props.columns
})

const grouped = computed(() => {
  const map = {}
  displayColumns.value.forEach((c) => { map[c.key] = [] })
  props.items.forEach((item) => {
    const status = item[props.statusKey]
    const column = props.columns.find((candidate) => (candidate.statuses || [candidate.key]).includes(status))
    const key = column?.key || '__unclassified__'
    if (!map[key]) map[key] = []
    map[key].push(item)
  })
  if (map.__unclassified__?.length) map.__unclassified__.sort((a, b) => (a.order_index || 0) - (b.order_index || 0))
  Object.keys(map).forEach((key) => {
    map[key].sort((a, b) => (a.order_index || 0) - (b.order_index || 0))
  })
  return map
})

function onDragStart(card, fromKey) {
  dragging.value = { card, fromKey }
}

function onDragEnd() {
  dragging.value = null
  dragOverKey.value = null
}

function onDragOver(key) {
  dragOverKey.value = key
}

function onDragLeave(key) {
  if (dragOverKey.value === key) dragOverKey.value = null
}

function onDrop(toKey, targetCard = null) {
  dragOverKey.value = null
  if (!dragging.value) return
  const { card, fromKey } = dragging.value
  const targets = grouped.value[toKey] || []
  const target = displayColumns.value.find((column) => column.key === toKey)
  if (!target || target.unclassified) return

  if (fromKey === toKey) {
    if (!targetCard || targetCard.id === card.id) {
      const maxOrder = targets.reduce((m, c) => Math.max(m, c.order_index || 0), 0)
      emit('move', { card, fromStatus: card[props.statusKey], toStatus: card[props.statusKey], orderIndex: maxOrder + 1000 })
    } else {
      const idx = targets.findIndex((c) => c.id === targetCard.id)
      const prevOrder = idx > 0 ? (targets[idx - 1].order_index || 0) : 0
      const currOrder = targetCard.order_index || 1000
      const nextOrder = idx > 0 ? Math.floor((prevOrder + currOrder) / 2) : Math.max(1, Math.floor(currOrder / 2))
      emit('move', { card, fromStatus: card[props.statusKey], toStatus: card[props.statusKey], orderIndex: nextOrder })
    }
    dragging.value = null
    return
  }

  const maxOrder = targets.reduce((m, c) => Math.max(m, c.order_index || 0), 0)
  const toStatus = target.dropStatus || target.key
  if (card[props.statusKey] === toStatus) return
  emit('move', { card, fromStatus: card[props.statusKey], toStatus, orderIndex: maxOrder + 1000 })
  dragging.value = null
}

function isTransitionAllowed(fromStatus, toStatus) {
  if (!props.transitions || !fromStatus || fromStatus === toStatus) return true
  const allowed = props.transitions[fromStatus]
  if (!Array.isArray(allowed)) return true
  return allowed.includes(toStatus)
}

function isColumnAllowedDrop(col) {
  if (!dragging.value || !col || col.unclassified) return false
  const fromStatus = dragging.value.card?.[props.statusKey]
  const toStatus = col.dropStatus || col.key
  return isTransitionAllowed(fromStatus, toStatus)
}

function moveTargets(col, card) {
  const fromStatus = card?.[props.statusKey]
  return displayColumns.value.filter((column) => {
    if (column.key === col.key || column.unclassified) return false
    const toStatus = column.dropStatus || column.key
    return isTransitionAllowed(fromStatus, toStatus)
  })
}

function canKeyboardMove(col, card) {
  return props.draggable && !col.unclassified && moveTargets(col, card).length > 0
}

function moveCard(card, toKey) {
  const target = displayColumns.value.find((column) => column.key === toKey)
  if (!target || target.unclassified) return
  const toStatus = target.dropStatus || target.key
  if (card[props.statusKey] === toStatus) return
  const targets = grouped.value[toKey] || []
  const maxOrder = targets.reduce((m, c) => Math.max(m, c.order_index || 0), 0)
  emit('move', { card, fromStatus: card[props.statusKey], toStatus, orderIndex: maxOrder + 1000 })
}

function onKeyboardMove(card, event) {
  const toKey = event.target.value
  event.target.value = ''
  moveCard(card, toKey)
}
</script>

<style scoped>
.kanban-board {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 8px;
  align-items: flex-start;
}
.kanban-col {
  flex: 0 0 260px;
  min-width: 260px;
  background: rgba(148, 163, 184, 0.08);
  border-radius: 12px;
  padding: 10px;
  transition: background 0.15s ease;
}
.kanban-col.is-drop-target {
  background: rgba(99, 102, 241, 0.12);
  outline: 1px dashed rgba(99, 102, 241, 0.5);
}
.kanban-col.is-drop-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.kanban-col__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
}
.kanban-col__toggle { border: 0; padding: 0; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.kanban-col__body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 60px;
}
.kanban-card {
  background: #fff;
  border: 1px solid var(--el-border-color, #e4e7ed);
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
}
.kanban-card:hover {
  border-color: rgba(99, 102, 241, 0.5);
}
.kanban-card:focus-visible {
  outline: 2px solid rgba(99, 102, 241, 0.6);
  outline-offset: 1px;
}
.kanban-card__move {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-text-secondary, #64748b);
  border: 1px solid var(--el-border-color, #e4e7ed);
  border-radius: 6px;
  background: transparent;
  padding: 2px 4px;
  cursor: pointer;
  max-width: 100%;
}
.kanban-card__title {
  font-size: 13px;
  font-weight: 600;
}
.kanban-empty {
  color: var(--color-text-secondary, #94a3b8);
  font-size: 12px;
  text-align: center;
  padding: 12px 0;
}
</style>
