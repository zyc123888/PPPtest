<template>
  <div class="case-table-wrap">
    <div v-if="selection.length" class="batch-bar">
      <span class="batch-bar__count">已选 {{ selection.length }} 条</span>
      <el-button v-if="canTest" type="primary" size="small" :icon="VideoPlay" @click="$emit('batch-run')">批量执行</el-button>
      <el-button v-if="canTest" size="small" :icon="EditPen" @click="$emit('batch-edit')">批量修改</el-button>
      <el-button v-if="canAdmin" type="danger" plain size="small" :icon="Delete" @click="$emit('batch-delete')">批量删除</el-button>
      <el-button text size="small" @click="clearSelection">取消选择</el-button>
    </div>

    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="rows"
      class="case-table"
      row-key="id"
      @row-dblclick="(row) => $emit('detail', row)"
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="42" :reserve-selection="true" />
      <el-table-column label="序号" width="60" align="center">
        <template #default="scope">{{ caseSequence(scope.$index) }}</template>
      </el-table-column>
      <el-table-column label="用例" min-width="235">
        <template #default="scope">
          <button class="case-name" type="button" @click="$emit('detail', scope.row)">{{ scope.row.name }}</button>
          <div class="case-meta">
            <span>{{ scope.row.folder_path || '未分组' }}</span>
            <span>v{{ scope.row.version_no }}</span>
            <span>{{ (scope.row.steps_json || []).length }} 步</span>
            <el-tag v-if="scope.row.generation_mode === 'ai_skill'" size="small" effect="plain">AI</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="项目" width="120" show-overflow-tooltip>
        <template #default="scope">{{ projectMap[scope.row.project_id] || scope.row.project_id }}</template>
      </el-table-column>
      <el-table-column label="优先级" width="70" align="center">
        <template #default="scope"><el-tag size="small" :type="priorityTag(scope.row.priority)">{{ scope.row.priority }}</el-tag></template>
      </el-table-column>
      <el-table-column label="状态" width="74" align="center">
        <template #default="scope"><el-tag size="small" :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(scope.row.status) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="评审" width="86" align="center">
        <template #default="scope">
          <el-tooltip :disabled="!scope.row.reviewed_by" placement="top" :content="reviewTooltip(scope.row)">
            <el-tag size="small" effect="plain" :type="reviewTag(scope.row.review_status)">{{ reviewText(scope.row.review_status) }}</el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="目标地址" prop="target_url" min-width="160" show-overflow-tooltip />
      <el-table-column label="最近执行" width="126">
        <template #default="scope">
          <div v-if="latestRunMap[scope.row.id]" class="last-run">
            <el-tag size="small" :type="executionStatusTag(latestRunMap[scope.row.id].status)">{{ executionStatusText(latestRunMap[scope.row.id].status) }}</el-tag>
            <span>{{ formatShortTime(latestRunMap[scope.row.id].created_at) }}</span>
          </div>
          <span v-else class="muted">未执行</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" align="right" width="164" fixed="right">
        <template #default="scope">
          <div class="row-actions">
            <el-tooltip content="查看详情" placement="top"><el-button circle size="small" :icon="View" aria-label="查看 UI 用例" @click="$emit('detail', scope.row)" /></el-tooltip>
            <el-tooltip v-if="canTest" content="编辑" placement="top"><el-button circle size="small" :icon="Edit" aria-label="编辑 UI 用例" @click="$emit('edit', scope.row)" /></el-tooltip>
            <el-tooltip v-if="canTest" content="立即执行" placement="top"><el-button circle size="small" type="primary" :icon="VideoPlay" aria-label="执行 UI 用例" @click="$emit('run', scope.row)" /></el-tooltip>
            <el-tooltip v-if="canAdmin" content="删除" placement="top"><el-button circle size="small" type="danger" plain :icon="Delete" aria-label="删除 UI 用例" @click="$emit('delete', scope.row)" /></el-tooltip>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <div class="mobile-cards">
      <article v-for="(item, index) in rows" :key="item.id" class="mobile-case">
        <div class="mobile-case__title">
          <span class="case-sequence">#{{ caseSequence(index) }}</span>
          <button class="case-name" type="button" @click="$emit('detail', item)">{{ item.name }}</button>
        </div>
        <div class="mobile-case__tags">
          <el-tag size="small" :type="priorityTag(item.priority)">{{ item.priority }}</el-tag>
          <el-tag size="small" :type="item.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(item.status) }}</el-tag>
          <el-tag size="small" effect="plain" :type="reviewTag(item.review_status)">{{ reviewText(item.review_status) }}</el-tag>
          <el-tag v-if="item.generation_mode === 'ai_skill'" size="small" effect="plain">AI</el-tag>
        </div>
        <div class="mobile-case__url">{{ item.target_url }}</div>
        <div class="row-actions">
          <el-button size="small" :icon="View" @click="$emit('detail', item)">详情</el-button>
          <el-button v-if="canTest" size="small" type="primary" :icon="VideoPlay" @click="$emit('run', item)">执行</el-button>
        </div>
      </article>
    </div>

    <div class="table-pagination">
      <el-pagination
        :current-page="page"
        :page-size="pageSize"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[10, 20, 50]"
        @update:current-page="$emit('update:page', $event)"
        @update:page-size="$emit('update:pageSize', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Delete, Edit, EditPen, VideoPlay, View } from '@element-plus/icons-vue'
import { executionStatusTag, executionStatusText } from '@/lib/execution'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  projectMap: { type: Object, default: () => ({}) },
  latestRunMap: { type: Object, default: () => ({}) },
  canTest: { type: Boolean, default: false },
  canAdmin: { type: Boolean, default: false }
})
const emit = defineEmits(['update:page', 'update:pageSize', 'selection-change', 'detail', 'edit', 'run', 'delete', 'batch-run', 'batch-edit', 'batch-delete'])

const tableRef = ref(null)
const selection = ref([])

const handleSelectionChange = (rows) => {
  selection.value = rows
  emit('selection-change', rows)
}
const clearSelection = () => tableRef.value?.clearSelection()
defineExpose({ clearSelection })

const caseSequence = (pageIndex) => props.total - ((props.page - 1) * props.pageSize + pageIndex)
const priorityTag = (priority) => ({ P0: 'danger', P1: 'warning', P2: '', P3: 'info' }[priority] || 'info')
const caseStatusText = (status) => ({ ACTIVE: '启用', INACTIVE: '停用' }[status] || status)
const reviewText = (status) => ({ DRAFT: '草稿', IN_REVIEW: '评审中', APPROVED: '已通过', REJECTED: '已拒绝' }[status] || status)
const reviewTag = (status) => ({ APPROVED: 'success', IN_REVIEW: 'warning', REJECTED: 'danger', DRAFT: 'info' }[status] || 'info')
const formatShortTime = (value) => (value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-')
const reviewTooltip = (row) => `评审人：用户 #${row.reviewed_by} · ${row.reviewed_at ? new Date(row.reviewed_at).toLocaleString('zh-CN') : '-'}`
</script>

<style scoped>
.case-table-wrap { min-width: 0; }
.batch-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-color-primary-light-9); }
.batch-bar__count { color: var(--el-color-primary); font-size: 13px; font-weight: 600; }
.case-table { width: 100%; }
.case-name { border: 0; padding: 0; background: none; color: var(--el-color-primary); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.case-name:hover { text-decoration: underline; }
.case-meta { margin-top: 5px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.4; }
.last-run { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }
.muted { color: var(--color-text-secondary); }
.row-actions { display: flex; justify-content: flex-end; gap: 6px; }
.mobile-cards { display: none; }
.table-pagination { display: flex; justify-content: flex-end; padding: 12px 16px; }
:deep(.case-table .el-table__header th) { height: 44px; background: #f8fafc; color: #667085; font-weight: 600; }
:deep(.case-table .el-table__row td) { padding: 12px 0; }
:deep(.case-table .el-table__row:hover > td) { background: #f8faff !important; }

@media (max-width: 900px) {
  .case-table { display: none; }
  .mobile-cards { display: grid; gap: 10px; padding: 12px; }
  .mobile-case { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 6px; }
  .mobile-case__title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .case-sequence { flex: 0 0 auto; color: var(--color-text-secondary); font-size: 12px; }
  .mobile-case__tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
  .mobile-case__url { margin-bottom: 10px; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
}
</style>
