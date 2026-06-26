<template>
  <div class="app-page">
    <PageHeader title="工作空间" subtitle="管理工作空间、项目归属与资源隔离">
      <template #actions>
        <el-button v-if="canAdmin" type="primary" @click="handleCreate">新增空间</el-button>
      </template>
    </PageHeader>

    <div class="workspace-hero section-gap">
      <el-card class="page-card workspace-hero__main" shadow="never">
        <div class="workspace-hero__kicker">Isolation Layer</div>
        <div class="workspace-hero__title">工作空间是权限与资源隔离边界</div>
        <div class="workspace-hero__subtitle">成员、项目和执行数据围绕空间组织，先把边界定清，后面所有流程才不会互相污染。</div>
      </el-card>
      <el-card class="page-card workspace-hero__stat" shadow="never">
        <el-statistic title="空间数量" :value="filteredList.length" />
      </el-card>
      <el-card class="page-card workspace-hero__stat" shadow="never">
        <el-statistic title="成员管理" :value="memberWorkspaces" />
      </el-card>
      <el-card class="page-card workspace-hero__stat" shadow="never">
        <el-statistic title="当前筛选" :value="filters.keyword ? '已筛选' : '全部'" />
      </el-card>
      <el-card class="page-card workspace-hero__stat" shadow="never">
        <el-statistic title="可管理" :value="canAdmin ? 'Yes' : 'No'" />
      </el-card>
    </div>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="空间名称/说明" style="width: 260px" />
        </el-form-item>
        <el-form-item label=" " class="query-actions">
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="page-card" shadow="never">
      <div class="toolbar section-gap">
        <div />
        <div class="toolbar-right">
          <el-button @click="getList">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="空间名称" prop="name" min-width="200" show-overflow-tooltip />
        <el-table-column label="说明" prop="description" min-width="260" show-overflow-tooltip />
        <el-table-column label="创建时间" min-width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column v-if="canAdmin" label="操作" width="140" align="center">
          <template #default="scope">
            <el-button size="small" @click="openMemberDialog(scope.row)">成员管理</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">创建时间：{{ formatTime(item.created_at) }}</div>
          <div class="mobile-card-desc">{{ item.description || '-' }}</div>
          <div v-if="canAdmin" class="mobile-card-actions">
            <el-button size="small" @click="openMemberDialog(item)">成员管理</el-button>
          </div>
        </div>
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增工作空间" width="520px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="空间名称" prop="name">
          <el-input v-model="temp.name" placeholder="例如：核心业务" />
        </el-form-item>
        <el-form-item label="空间说明" prop="description">
          <el-input v-model="temp.description" type="textarea" :rows="4" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="createData">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberDialogVisible" :title="memberDialogTitle" width="760px">
      <div class="member-panel">
        <el-form :inline="true" label-position="top" class="query-form member-form">
          <el-form-item label="选择用户">
            <el-select v-model="memberForm.user_id" filterable placeholder="请选择用户" style="width: 260px">
              <el-option
                v-for="item in availableUsers"
                :key="item.id"
                :label="`${item.username}${item.display_name ? ` (${item.display_name})` : ''}`"
                :value="item.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="成员角色">
            <el-select v-model="memberForm.role" style="width: 180px">
              <el-option label="Owner" value="owner" />
              <el-option label="Member" value="member" />
            </el-select>
          </el-form-item>
          <el-form-item label=" " class="query-actions">
            <el-button type="primary" :loading="memberSubmitting" @click="handleAddMember">添加成员</el-button>
          </el-form-item>
        </el-form>

        <el-form :inline="true" label-position="top" class="query-form member-search">
          <el-form-item label="成员搜索">
            <el-input v-model="memberFilters.keyword" clearable placeholder="用户名/显示名/角色" style="width: 260px" />
          </el-form-item>
        </el-form>

        <el-table v-loading="memberLoading" :data="filteredMemberList" border>
          <el-table-column label="用户名" min-width="180" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.username || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="显示名" min-width="160" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.display_name || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="空间角色" width="180" align="center">
            <template #default="scope">
              <el-select
                :model-value="scope.row.role"
                style="width: 120px"
                @change="(value) => handleUpdateMemberRole(scope.row, value)"
              >
                <el-option label="Owner" value="owner" />
                <el-option label="Member" value="member" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="加入时间" min-width="180" align="center">
            <template #default="scope">
              {{ formatTime(scope.row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template #default="scope">
              <el-button
                size="small"
                type="danger"
                :disabled="scope.row.user_id === currentUserId"
                @click="handleRemoveMember(scope.row)"
              >
                移除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="memberDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'
import { useAuthStore } from '@/stores/auth'
import { useRoute } from 'vue-router'

const list = ref([])
const users = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const memberDialogVisible = ref(false)
const dataFormRef = ref(null)
const memberLoading = ref(false)
const memberSubmitting = ref(false)
const memberList = ref([])
const currentWorkspace = ref(null)
const { canAdmin } = usePermissions()
const authStore = useAuthStore()
const route = useRoute()

const filters = reactive({
  keyword: '',
  workspaceId: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  name: '',
  description: ''
})

const memberForm = reactive({
  user_id: undefined,
  role: 'member'
})
const memberFilters = reactive({
  keyword: ''
})

const rules = {
  name: [{ required: true, message: '空间名称必填', trigger: 'blur' }, { min: 2, message: '至少2个字符', trigger: 'blur' }]
}

const currentUserId = computed(() => authStore.user?.id || null)
const memberDialogTitle = computed(() => {
  return currentWorkspace.value ? `成员管理 · ${currentWorkspace.value.name}` : '成员管理'
})
const availableUsers = computed(() => {
  const memberIds = new Set(memberList.value.map((item) => item.user_id))
  return users.value.filter((user) => !memberIds.has(user.id))
})
const filteredMemberList = computed(() => {
  const keyword = memberFilters.keyword.trim().toLowerCase()
  if (!keyword) return memberList.value
  return memberList.value.filter((item) => {
    return (
      String(item.username || '').toLowerCase().includes(keyword) ||
      String(item.display_name || '').toLowerCase().includes(keyword) ||
      String(item.role || '').toLowerCase().includes(keyword)
    )
  })
})

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const getList = async () => {
  listLoading.value = true
  try {
    const [workspaceData, userData] = await Promise.all([
      api.get('/workspaces'),
      canAdmin.value ? api.get('/users') : Promise.resolve([])
    ])
    list.value = workspaceData
    users.value = userData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((item) => {
    if (filters.workspaceId && String(item.id) !== String(filters.workspaceId)) {
      return false
    }
    if (!keyword) return true
    return (
      String(item.name || '').toLowerCase().includes(keyword) ||
      String(item.description || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const memberWorkspaces = computed(() => list.value.filter((item) => (item.member_count || 0) > 0).length)

const handleCreate = () => {
  temp.name = ''
  temp.description = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.keyword = ''
  filters.workspaceId = ''
  page.value = 1
}

const createData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        await api.post('/workspaces', temp)
        dialogVisible.value = false
        ElMessage.success('创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const loadMembers = async (workspaceId) => {
  memberLoading.value = true
  try {
    memberList.value = await api.get(`/workspaces/${workspaceId}/members`)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    memberLoading.value = false
  }
}

const openMemberDialog = async (row) => {
  currentWorkspace.value = row
  memberForm.user_id = undefined
  memberForm.role = 'member'
  memberFilters.keyword = ''
  memberDialogVisible.value = true
  await loadMembers(row.id)
}

const handleAddMember = async () => {
  if (!currentWorkspace.value) return
  if (!memberForm.user_id) {
    ElMessage.warning('请选择用户')
    return
  }
  memberSubmitting.value = true
  try {
    await api.post(`/workspaces/${currentWorkspace.value.id}/members`, {
      user_id: memberForm.user_id,
      role: memberForm.role
    })
    memberForm.user_id = undefined
    memberForm.role = 'member'
    ElMessage.success('成员已添加')
    await loadMembers(currentWorkspace.value.id)
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    memberSubmitting.value = false
  }
}

const handleRemoveMember = async (row) => {
  if (!currentWorkspace.value) return
  try {
    await ElMessageBox.confirm(
      `确认将用户「${row.username || row.user_id}」移出工作空间「${currentWorkspace.value.name}」？`,
      '移除成员',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    )
    await api.delete(`/workspaces/${currentWorkspace.value.id}/members/${row.id}`)
    ElMessage.success('成员已移除')
    await loadMembers(currentWorkspace.value.id)
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleUpdateMemberRole = async (row, role) => {
  if (!currentWorkspace.value) return
  try {
    await api.put(`/workspaces/${currentWorkspace.value.id}/members/${row.id}`, { role })
    ElMessage.success('成员角色已更新')
    await loadMembers(currentWorkspace.value.id)
  } catch (error) {
    ElMessage.error(error.message)
    await loadMembers(currentWorkspace.value.id)
  }
}

watch(
  () => [route.query.keyword, route.query.workspace_id],
  ([keyword, workspaceId]) => {
    filters.keyword = typeof keyword === 'string' ? keyword : ''
    filters.workspaceId = typeof workspaceId === 'string' ? workspaceId : ''
    page.value = 1
  },
  { immediate: true }
)

onMounted(() => {
  getList()
})
</script>

<style scoped>
/* ========== PageHeader 主按钮 ========== */
:deep(.page-header-actions .el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.18);
  border-radius: 12px;
  font-weight: 600;
  padding: 10px 24px;
  font-size: 14px;
  transition: all 0.2s ease;
}

:deep(.page-header-actions .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 10px 26px rgba(99, 102, 241, 0.26);
  transform: translateY(-1px);
}

:deep(.page-header-actions .el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
  transform: translateY(0);
}

/* ========== Hero 卡片 ========== */
.workspace-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.workspace-hero__main {
  border-radius: 20px;
  background:
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.16), transparent 34%),
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.10), transparent 32%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.96));
  color: var(--color-text);
}

.workspace-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--color-primary-strong);
  margin-bottom: 10px;
}

.workspace-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
  color: var(--color-text);
}

.workspace-hero__subtitle {
  max-width: 760px;
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.workspace-hero__stat {
  border-radius: 18px;
}

/* ========== 查询表单 ========== */
.query-form {
  margin-bottom: 0;
}

.query-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.query-form :deep(.el-form-item__label) {
  font-weight: 600;
  color: #312e81;
  font-size: 13px;
}

.query-form :deep(.el-input__wrapper),
.query-form :deep(.el-select .el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.15) inset;
  transition: all 0.2s ease;
}

.query-form :deep(.el-input__wrapper:hover),
.query-form :deep(.el-select .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.2) inset, 0 0 0 3px rgba(99, 102, 241, 0.06);
}

.query-form :deep(.el-input__wrapper.is-focus),
.query-form :deep(.el-select .el-input__wrapper.is-focus) {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.3) inset, 0 0 0 4px rgba(99, 102, 241, 0.1);
}

.query-actions {
  margin-bottom: 0;
}

.query-actions :deep(.el-form-item__content) {
  display: flex;
  gap: 8px;
}

.query-actions :deep(.el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.16);
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.query-actions :deep(.el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.22);
}

.query-actions :deep(.el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
}

.query-actions :deep(.el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.query-actions :deep(.el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

/* ========== 工具栏 ========== */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.04);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  font-size: 13px;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

.toolbar :deep(.el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
}

.toolbar :deep(.el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

/* ========== 表格 ========== */
:deep(.el-table) {
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.06);
}

:deep(.el-table::before) {
  height: 0;
}

:deep(.el-table th.el-table__cell) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.98), rgba(250, 245, 255, 0.98));
  border-bottom: 1px solid rgba(129, 140, 248, 0.15);
  color: #312e81;
  font-weight: 600;
  font-size: 13px;
  padding: 14px 0;
}

:deep(.el-table td.el-table__cell) {
  padding: 12px 0;
  color: #475569;
  font-size: 13px;
}

:deep(.el-table .el-table__row:hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.7), rgba(250, 245, 255, 0.7));
}

:deep(.el-table .el-table__row) {
  transition: background 0.15s ease;
}

:deep(.el-table .el-button) {
  border-radius: 8px;
  font-weight: 500;
  font-size: 12px;
  padding: 6px 12px;
  transition: all 0.15s ease;
}

:deep(.el-table .el-button--primary) {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.15);
}

:deep(.el-table .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.22);
}

:deep(.el-table .el-button--danger) {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.12), rgba(239, 68, 68, 0.08));
  border-color: rgba(239, 68, 68, 0.2);
  color: #dc2626;
}

:deep(.el-table .el-button--danger:hover) {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.2), rgba(239, 68, 68, 0.15));
  border-color: rgba(239, 68, 68, 0.35);
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.1);
}

:deep(.el-table .el-button:not(.el-button--primary):not(.el-button--danger)) {
  background: rgba(99, 102, 241, 0.06);
  border-color: rgba(129, 140, 248, 0.15);
  color: #4f46e5;
}

:deep(.el-table .el-button:not(.el-button--primary):not(.el-button--danger):hover) {
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.25);
}

/* ========== 分页 ========== */
.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0 0;
}

.table-pagination :deep(.el-pagination) {
  padding: 12px 18px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.04);
}

.table-pagination :deep(.el-pager li) {
  border-radius: 8px;
  font-weight: 500;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
}

.table-pagination :deep(.el-pager li.is-active) {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  color: #fff;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.2);
}

.table-pagination :deep(.el-pager li:not(.is-active):hover) {
  background: rgba(99, 102, 241, 0.08);
  color: #4f46e5;
}

.table-pagination :deep(.btn-prev),
.table-pagination :deep(.btn-next) {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(129, 140, 248, 0.15);
}

.table-pagination :deep(.btn-prev:hover),
.table-pagination :deep(.btn-next:hover) {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.3);
}

/* ========== 弹窗 ========== */
:deep(.el-dialog) {
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(129, 140, 248, 0.15);
  box-shadow: 0 24px 64px rgba(99, 102, 241, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}

:deep(.el-dialog__header) {
  padding: 20px 24px 16px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.98), rgba(250, 245, 255, 0.98));
  border-bottom: 1px solid rgba(129, 140, 248, 0.1);
}

:deep(.el-dialog__title) {
  font-weight: 700;
  color: #312e81;
  font-size: 16px;
}

:deep(.el-dialog__body) {
  padding: 20px 24px;
  background: linear-gradient(180deg, #ffffff, rgba(248, 250, 255, 0.5));
}

:deep(.el-dialog__footer) {
  padding: 16px 24px 20px;
  border-top: 1px solid rgba(129, 140, 248, 0.08);
  background: rgba(248, 250, 255, 0.5);
}

:deep(.el-dialog .el-form-item__label) {
  font-weight: 600;
  color: #312e81;
  font-size: 13px;
}

:deep(.el-dialog .el-input__wrapper),
:deep(.el-dialog .el-select .el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.15) inset;
}

:deep(.el-dialog .el-input__wrapper:hover),
:deep(.el-dialog .el-select .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.3);
}

:deep(.el-dialog .el-input__wrapper.is-focus),
:deep(.el-dialog .el-select .el-input__wrapper.is-focus) {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.3) inset, 0 0 0 4px rgba(99, 102, 241, 0.1);
}

:deep(.el-dialog .el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.16);
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

:deep(.el-dialog .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.22);
}

:deep(.el-dialog .el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
}

:deep(.el-dialog .el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

:deep(.el-dialog .el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

/* ========== 成员面板 ========== */
.member-panel {
  display: grid;
  gap: var(--space-16);
}

.member-panel :deep(.el-form-item__label) {
  font-weight: 600;
  color: #312e81;
  font-size: 13px;
}

.member-panel :deep(.el-input__wrapper),
.member-panel :deep(.el-select .el-input__wrapper) {
  border-radius: 10px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.15) inset;
}

.member-panel :deep(.el-input__wrapper:hover),
.member-panel :deep(.el-select .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.3);
}

.member-panel :deep(.el-input__wrapper.is-focus),
.member-panel :deep(.el-select .el-input__wrapper.is-focus) {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.3) inset, 0 0 0 4px rgba(99, 102, 241, 0.1);
}

.member-panel :deep(.el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.16);
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.member-panel :deep(.el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.22);
}

.member-panel :deep(.el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
}

.member-panel :deep(.el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.member-panel :deep(.el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

/* ========== 移动端卡片 ========== */
.mobile-cards {
  display: none;
}

/* ========== 响应式 ========== */
@media (max-width: 960px) {
  .workspace-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workspace-hero__main {
    grid-column: 1 / -1;
  }

  .el-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: var(--space-12);
  }

  .mobile-card {
    background: #ffffff;
    border: 1px solid rgba(129, 140, 248, 0.12);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 8px 20px rgba(99, 102, 241, 0.06);
  }

  .mobile-card-title {
    font-weight: 600;
    margin-bottom: 6px;
    color: #312e81;
  }

  .mobile-card-meta {
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .mobile-card-desc {
    font-size: 13px;
    color: var(--color-text);
  }

  .mobile-card-actions {
    margin-top: 10px;
  }
}
</style>
