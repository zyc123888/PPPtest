<template>
  <div class="apple-stage">
    <div class="apple-container">
      <header class="ap-header">
        <div>
          <h1 class="ap-title">工作空间</h1>
          <p class="ap-subtitle">管理团队工作空间、成员角色与项目资源边界</p>
        </div>
        <div class="ap-header__actions">
          <button type="button" class="ap-pill-btn ap-pill-btn--glass" :disabled="listLoading" @click="getList">
            刷新
          </button>
          <button v-if="canAdmin" type="button" class="ap-pill-btn ap-pill-btn--blue" @click="handleCreate">
            新增空间
          </button>
        </div>
      </header>

      <!-- Apple Bento Glass Summary Row -->
      <section class="ap-bento-row">
        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--blue">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="2" fill="currentColor" />
              <rect x="14" y="3" width="7" height="7" rx="2" fill="currentColor" opacity="0.55" />
              <rect x="3" y="14" width="7" height="7" rx="2" fill="currentColor" opacity="0.55" />
              <rect x="14" y="14" width="7" height="7" rx="2" fill="currentColor" opacity="0.3" />
            </svg>
          </div>
          <div class="ap-stat-tile__body">
            <span class="ap-stat-tile__label">空间总数</span>
            <strong class="ap-stat-tile__val">{{ filteredList.length }}</strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--green">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="9" cy="8" r="3.5" fill="currentColor" />
              <path d="M3 19c0-3 2.5-5 6-5s6 2 6 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              <circle cx="17" cy="9" r="2.5" fill="currentColor" opacity="0.55" />
              <path d="M16.5 14.5c2.2.4 4 1.8 4.5 4.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" opacity="0.55" />
            </svg>
          </div>
          <div class="ap-stat-tile__body">
            <span class="ap-stat-tile__label">已纳管成员空间</span>
            <strong class="ap-stat-tile__val">{{ memberWorkspaces }}</strong>
          </div>
        </div>

        <div class="ap-glass-card ap-stat-tile">
          <div class="ap-icon-box ap-icon-box--orange">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <path d="M12 3l7 3v5c0 4.5-3 8.2-7 9.8-4-1.6-7-5.3-7-9.8V6l7-3z" fill="currentColor" opacity="0.85" />
            </svg>
          </div>
          <div class="ap-stat-tile__body">
            <span class="ap-stat-tile__label">当前权限</span>
            <strong class="ap-stat-tile__val ap-stat-tile__val--text">{{ canAdmin ? '空间管理员' : '普通成员' }}</strong>
          </div>
        </div>
      </section>

      <!-- Apple Native Glass Search Bar -->
      <section class="ap-search-row">
        <div class="ap-search-box">
          <svg class="ap-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
            <path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
          </svg>
          <input
            v-model="filters.keyword"
            type="text"
            class="ap-search-input"
            placeholder="搜索工作空间名称或说明"
            @input="handleSearch"
          />
          <button v-if="filters.keyword || filters.workspaceId" type="button" class="ap-clear-btn" @click="handleReset">
            清除
          </button>
        </div>
        <span class="ap-count-label">{{ filteredList.length }} 个工作空间</span>
      </section>

      <!-- macOS System Settings Inset Grouped Glass List -->
      <section v-loading="listLoading" class="ap-glass-list">
        <div v-if="!pagedList.length" class="ap-empty">暂无匹配的工作空间</div>

        <div v-for="(item, idx) in pagedList" :key="item.id" class="ap-list-row">
          <div class="ap-list-row__left">
            <div class="ap-app-icon" :style="{ background: iconBg(idx) }">
              {{ (item.name || 'W').slice(0, 1).toUpperCase() }}
            </div>
            <div class="ap-list-row__info">
              <div class="ap-list-row__title-line">
                <span class="ap-list-row__name">{{ item.name }}</span>
                <span class="ap-id-badge">ID {{ item.id }}</span>
              </div>
              <p class="ap-list-row__desc">{{ item.description || '独立隔离的测试资产与成员协作空间' }}</p>
            </div>
          </div>

          <div class="ap-list-row__right">
            <span class="ap-time">{{ formatTime(item.created_at) }}</span>
            <div v-if="canAdmin" class="ap-row-actions">
              <button type="button" class="ap-action-btn ap-action-btn--blue" @click="openMemberDialog(item)">
                成员管理
              </button>
              <button type="button" class="ap-action-btn" @click="handleEdit(item)">编辑</button>
              <button type="button" class="ap-action-btn ap-action-btn--red" @click="handleDelete(item)">删除</button>
            </div>
          </div>
        </div>
      </section>

      <div class="ap-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑工作空间' : '新增工作空间'" width="520px">
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
        <el-button type="primary" @click="saveData">确认</el-button>
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
            <el-select v-model="memberForm.role" style="width: 160px">
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

        <el-table v-loading="memberLoading" :data="filteredMemberList">
          <el-table-column label="用户名" min-width="160" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.username || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="显示名" min-width="140" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.display_name || '-' }}
            </template>
          </el-table-column>
          <el-table-column label="空间角色" width="160" align="center">
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
          <el-table-column label="加入时间" min-width="160" align="center">
            <template #default="scope">
              {{ formatTime(scope.row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="center">
            <template #default="scope">
              <el-button
                size="small"
                type="danger"
                link
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
import { usePermissions } from '@/lib/permissions'
import { useAuthStore } from '@/stores/auth'
import { useRoute } from 'vue-router'
import { formatDateTime as formatTime } from '@/lib/formatTime'

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
const editingId = ref(null)

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

const APPLE_GRADIENTS = [
  'linear-gradient(180deg, #3b9eff 0%, #0071e3 100%)',
  'linear-gradient(180deg, #4cd964 0%, #28cd41 100%)',
  'linear-gradient(180deg, #ff9f0a 0%, #ff6b00 100%)',
  'linear-gradient(180deg, #5e5ce6 0%, #3634a3 100%)',
  'linear-gradient(180deg, #ff375f 0%, #d70040 100%)'
]
const iconBg = (idx) => APPLE_GRADIENTS[idx % APPLE_GRADIENTS.length]

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

const memberWorkspaces = computed(() => list.value.length)

const handleCreate = () => {
  editingId.value = null
  temp.name = ''
  temp.description = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleEdit = (row) => {
  editingId.value = row.id
  temp.name = row.name || ''
  temp.description = row.description || ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除工作空间「${row.name}」？仅当空间下无关联项目时可删除。`,
      '删除工作空间',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/workspaces/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.keyword = ''
  filters.workspaceId = ''
  page.value = 1
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        if (editingId.value) {
          await api.put(`/workspaces/${editingId.value}`, temp)
          ElMessage.success('更新成功')
        } else {
          await api.post('/workspaces', temp)
          ElMessage.success('创建成功')
        }
        dialogVisible.value = false
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
.apple-stage {
  min-height: calc(100vh - var(--app-header-height));
  background: transparent;
  padding: 24px 32px 36px;
}

.apple-container {
  max-width: 1120px;
  margin: 0 auto;
}

.ap-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.ap-kicker {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: #0071e3;
  margin-bottom: 4px;
}

.ap-title {
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #1d1d1f;
  line-height: 1.15;
}

.ap-subtitle {
  margin: 5px 0 0;
  font-size: 14px;
  color: #6e6e73;
}

.ap-header__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ap-pill-btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
  transition: transform 0.14s ease, background 0.14s ease, box-shadow 0.14s ease;
}

.ap-pill-btn--blue {
  border: none;
  background: #0071e3;
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(0, 113, 227, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.ap-pill-btn--blue:hover {
  background: #0077ed;
  transform: translateY(-0.5px);
}

.ap-pill-btn--glass {
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(18px) saturate(180%);
  color: #1d1d1f;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.ap-pill-btn--glass:hover {
  background: rgba(255, 255, 255, 0.92);
}

.ap-bento-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 20px;
}

.ap-glass-card {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.8);
  background: rgba(255, 255, 255, 0.76);
  backdrop-filter: blur(22px) saturate(180%);
  box-shadow:
    0 4px 20px rgba(0, 0, 0, 0.04),
    0 1px 2px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
}

.ap-stat-tile {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
}

.ap-icon-box {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.ap-icon-box--blue { background: rgba(0, 113, 227, 0.12); color: #0071e3; }
.ap-icon-box--green { background: rgba(52, 199, 89, 0.14); color: #248a3d; }
.ap-icon-box--orange { background: rgba(255, 159, 10, 0.14); color: #c96a00; }

.ap-stat-tile__label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: #6e6e73;
}

.ap-stat-tile__val {
  display: block;
  margin-top: 2px;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #1d1d1f;
  font-variant-numeric: tabular-nums;
}

.ap-stat-tile__val--text {
  font-size: 17px;
  margin-top: 4px;
}

.ap-search-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.ap-search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 340px;
  max-width: 100%;
  height: 38px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(18px);
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.03);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.ap-search-box:focus-within {
  border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.16);
}

.ap-search-icon {
  color: #86868b;
  flex-shrink: 0;
}

.ap-search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 13.5px;
  color: #1d1d1f;
}

.ap-search-input::placeholder {
  color: #86868b;
}

.ap-clear-btn {
  border: none;
  background: transparent;
  color: #0071e3;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.ap-count-label {
  font-size: 12.5px;
  color: #86868b;
}

.ap-glass-list {
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.85);
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow:
    0 8px 30px rgba(0, 0, 0, 0.045),
    0 1px 2px rgba(0, 0, 0, 0.03),
    inset 0 1px 0 rgba(255, 255, 255, 0.96);
  overflow: hidden;
}

.ap-empty {
  padding: 56px 16px;
  text-align: center;
  color: #86868b;
  font-size: 14px;
}

.ap-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 16px 22px;
  position: relative;
  transition: background 0.14s ease;
}

.ap-list-row:not(:last-child)::after {
  content: '';
  position: absolute;
  left: 74px;
  right: 22px;
  bottom: 0;
  height: 1px;
  background: rgba(0, 0, 0, 0.06);
}

.ap-list-row:hover {
  background: rgba(0, 113, 227, 0.035);
}

.ap-list-row__left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
  flex: 1;
}

.ap-app-icon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.ap-list-row__info {
  min-width: 0;
  flex: 1;
}

.ap-list-row__title-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ap-list-row__name {
  font-size: 15px;
  font-weight: 600;
  color: #1d1d1f;
  letter-spacing: -0.01em;
}

.ap-id-badge {
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.05);
  color: #6e6e73;
  font-size: 11px;
  font-weight: 500;
}

.ap-list-row__desc {
  margin: 3px 0 0;
  font-size: 13px;
  color: #6e6e73;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ap-list-row__right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.ap-time {
  font-size: 12px;
  color: #86868b;
  font-variant-numeric: tabular-nums;
}

.ap-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ap-action-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.85);
  color: #1d1d1f;
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}

.ap-action-btn:hover {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.16);
}

.ap-action-btn--blue {
  color: #0071e3;
  background: rgba(0, 113, 227, 0.08);
  border-color: transparent;
}

.ap-action-btn--blue:hover {
  background: rgba(0, 113, 227, 0.14);
}

.ap-action-btn--red {
  color: #d70015;
  background: rgba(255, 59, 48, 0.08);
  border-color: transparent;
}

.ap-action-btn--red:hover {
  background: rgba(255, 59, 48, 0.14);
}

.ap-pagination {
  margin-top: 18px;
  display: flex;
  justify-content: flex-end;
}

.member-panel {
  display: grid;
  gap: 14px;
}

@media (max-width: 860px) {
  .apple-stage { padding: 16px; }
  .ap-header { flex-direction: column; align-items: flex-start; }
  .ap-bento-row { grid-template-columns: 1fr; }
  .ap-list-row { flex-direction: column; align-items: flex-start; }
  .ap-list-row__right { width: 100%; justify-content: space-between; }
  .ap-search-box { width: 100%; }
}
</style>
