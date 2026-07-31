<template>
  <div class="kanban-board">
    <div
      v-for="col in columns"
      :key="col.key"
      class="kanban-col"
      :class="{ 'is-drop-target': dragOverKey === col.key }"
      @dragover.prevent="onDragOver(col.key)"
      @dragleave="onDragLeave(col.key)"
      @drop="onDrop(col.key)"
    >
      <div class="kanban-col__head">
        <span class="kanban-col__title">{{ col.label }}</span>
        <el-tag size="small" round type="info">{{ grouped[col.key]?.length || 0 }}</el-tag>
      </div>
      <div class="kanban-col__body">
        <div
          v-for="card in grouped[col.key] || []"
          :key="card.id"
          class="kanban-card"
          :draggable="draggable"
          @dragstart="onDragStart(card, col.key)"
          @dragend="onDragEnd"
          @click="$emit('open', card)"
        >
          <slot name="card" :card="card">
            <div class="kanban-card__title">{{ card.title }}</div>
          </slot>
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
  draggable: { type: Boolean, default: true }
})

const emit = defineEmits(['open', 'move'])

const dragging = ref(null)
const dragOverKey = ref(null)

const grouped = computed(() => {
  const map = {}
  props.columns.forEach((c) => { map[c.key] = [] })
  props.items.forEach((item) => {
    const key = item[props.statusKey]
    if (!map[key]) map[key] = []
    map[key].push(item)
  })
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

function onDrop(toKey) {
  dragOverKey.value = null
  if (!dragging.value) return
  const { card, fromKey } = dragging.value
  if (fromKey === toKey) return
  const targets = grouped.value[toKey] || []
  const maxOrder = targets.reduce((m, c) => Math.max(m, c.order_index || 0), 0)
  emit('move', { card, fromStatus: fromKey, toStatus: toKey, orderIndex: maxOrder + 1000 })
  dragging.value = null
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
.kanban-col__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 600;
}
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
