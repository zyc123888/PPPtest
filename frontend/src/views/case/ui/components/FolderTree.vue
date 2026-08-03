<template>
  <aside class="folder-tree">
    <div class="folder-tree__head">
      <strong>用例目录</strong>
      <el-tooltip content="刷新目录" placement="top">
        <el-button text size="small" :icon="Refresh" aria-label="刷新目录" @click="$emit('refresh')" />
      </el-tooltip>
    </div>
    <button
      type="button"
      class="folder-tree__item"
      :class="{ 'is-active': modelValue === '' }"
      @click="$emit('update:modelValue', '')"
    >
      <el-icon><Files /></el-icon>
      <span>全部用例</span>
      <em>{{ total }}</em>
    </button>
    <button
      type="button"
      class="folder-tree__item"
      :class="{ 'is-active': modelValue === '__ungrouped__' }"
      @click="$emit('update:modelValue', '__ungrouped__')"
    >
      <el-icon><FolderOpened /></el-icon>
      <span>未分组</span>
      <em>{{ ungrouped }}</em>
    </button>
    <el-tree
      class="folder-tree__tree"
      :data="folders"
      node-key="path"
      :props="{ label: 'name', children: 'children' }"
      :expand-on-click-node="false"
      default-expand-all
      highlight-current
      :current-node-key="modelValue"
      @node-click="(node) => $emit('update:modelValue', node.path)"
    >
      <template #default="{ data }">
        <div class="folder-node">
          <el-icon><Folder /></el-icon>
          <span class="folder-node__name" :title="data.path">{{ data.name }}</span>
          <em>{{ data.case_count }}</em>
          <el-tooltip v-if="canRename" content="重命名" placement="top">
            <el-button
              text
              size="small"
              class="folder-node__rename"
              :icon="EditPen"
              aria-label="重命名目录"
              @click.stop="promptRename(data)"
            />
          </el-tooltip>
        </div>
      </template>
    </el-tree>
    <el-empty v-if="!folders.length" description="暂无目录" :image-size="52" />
  </aside>
</template>

<script setup>
import { ElMessageBox } from 'element-plus'
import { EditPen, Files, Folder, FolderOpened, Refresh } from '@element-plus/icons-vue'

defineProps({
  folders: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  ungrouped: { type: Number, default: 0 },
  modelValue: { type: String, default: '' },
  canRename: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'rename', 'refresh'])

const promptRename = async (node) => {
  try {
    const { value } = await ElMessageBox.prompt('输入新的目录路径（用 / 分隔层级）', `重命名「${node.path}」`, {
      inputValue: node.path,
      confirmButtonText: '重命名',
      cancelButtonText: '取消',
      inputValidator: (input) => (input && input.trim().replace(/^\/+|\/+$/g, '') ? true : '目录路径不能为空')
    })
    const newPath = value.trim().replace(/^\/+|\/+$/g, '')
    if (newPath && newPath !== node.path) emit('rename', { oldPath: node.path, newPath })
  } catch {
    /* 用户取消 */
  }
}
</script>

<style scoped>
.folder-tree { display: flex; flex-direction: column; min-width: 0; }
.folder-tree__head { display: flex; align-items: center; justify-content: space-between; padding: 4px 6px 10px; }
.folder-tree__head strong { font-size: 13px; color: var(--color-text); }
.folder-tree__item { width: 100%; display: flex; align-items: center; gap: 8px; padding: 8px 10px; margin-bottom: 2px; border: 0; border-radius: 6px; background: none; cursor: pointer; color: var(--color-text); font-size: 13px; text-align: left; }
.folder-tree__item:hover { background: #f3f5f9; }
.folder-tree__item.is-active { background: var(--el-color-primary-light-9); color: var(--el-color-primary); font-weight: 600; }
.folder-tree__item em, .folder-node em { margin-left: auto; color: var(--color-text-secondary); font-size: 12px; font-style: normal; }
.folder-tree__tree { margin-top: 4px; background: none; }
.folder-node { flex: 1; min-width: 0; display: flex; align-items: center; gap: 6px; padding-right: 4px; font-size: 13px; }
.folder-node__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.folder-node__rename { display: none; margin-left: 2px; }
.folder-node:hover .folder-node__rename { display: inline-flex; }
</style>
