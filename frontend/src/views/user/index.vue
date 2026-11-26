<template>
  <div class="apple-page">
    <div class="apple-container">
      <header class="ap-header">
        <div>
          <h1 class="ap-title">用户与权限</h1>
          <p class="ap-subtitle">管理团队成员账号、角色权限与所属工作空间</p>
        </div>
        <button type="button" class="ap-pill-btn ap-pill-btn--blue" @click="handleCreate">邀请成员</button>
      </header>

      <section class="ap-controls">
        <div class="ap-seg" role="tablist">
          <button type="button" class="ap-seg__btn" :class="{ 'is-active': !filters.role }" @click="filters.role = ''">
            全部成员 <span>{{ list.length }}</span>
          </button>
          <button type="button" class="ap-seg__btn" :class="{ 'is-active': filters.role === 'admin' }" @click="filters.role = 'admin'">
            管理员 <span>{{ adminCount }}</span>
          </button>
          <button type="button" class="ap-seg__btn" :class="{ 'is-active': filters.role === 'tester' }" @click="filters.role = 'tester'">
            测试工程师 <span>{{ testerCount }}</span>
          </button>
          <button type="button" class="ap-seg__btn" :class="{ 'is-active': filters.role === 'viewer' }" @click="filters.role = 'viewer'">
            访客 <span>{{ viewerCount }}</span>
          </button>
        </div>

        <div class="ap-controls__right">
          <el-select v-model="filters.status" placeholder="状态" clearable style="width: 116px">
            <el-option v-for="(label, value) in statusLabels" :key="value" :label="label" :value="value" />
          </el-select>
          <div class="ap-search-box">
            <svg class="ap-search-icon" width="15" height="15" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="7" stroke="currentColor" stroke-width="2" />
              <path d="M16.5 16.5L21 21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
            </svg>
            <input v-model="filters.keyword" type="text" class="ap-search-input" placeholder="搜索成员姓名或账号" />
          </div>
        </div>
      </section>

      <section v-loading="listLoading" class="ap-glass-list">
        <div v-if="!filteredList.length" class="ap-empty">没有符合条件的成员</div>

        <div v-for="(row, idx) in filteredList" :key="row.id" class="ap-list-row">
          <div class="ap-member__id">
            <div class="ap-app-icon" :style="{ background: avatarGradient(idx) }">
              {{ (row.display_name || row.username || 'U').slice(0, 1).toUpperCase() }}
            </div>
            <div class="ap-member__text">
              <div class="ap-member__name-line">
                <span class="ap-member__name">{{ row.display_name || row.username }}</span>
                <span class="ap-member__handle">@{{ row.username }}</span>
                <span class="ap-role-pill" :class="`ap-role-pill--${row.role}`">
                  {{ roleLabels[row.role] || row.role }}
                </span>
                <span v-if="row.status !== 'ACTIVE'" class="ap-disabled-pill">已停用</span>
              </div>
              <div class="ap-member__meta">
                <span>最近登录：{{ formatTime(row.last_login_at) }}</span>
                <span class="ap-dot-sep">·</span>
                <span>加入于 {{ formatTime(row.created_at) }}</span>
              </div>
            </div>
          </div>

          <div class="ap-member__spaces">
            <button
              v-for="membership in getWorkspaceMemberships(row)"
              :key="`${membership.workspace_id}-${membership.role}`"
              type="button"
              class="ap-space-chip"
              @click="handleWorkspaceJump(membership)"
            >
              {{ membership.workspace_name }}
              <small>{{ membership.role }}</small>
            </button>
            <span v-if="!getWorkspaceMemberships(row).length" class="ap-no-space">未绑定空间</span>
          </div>

          <div class="ap-row-actions">
            <button type="button" class="ap-action-btn ap-action-btn--blue" @click="handleEdit(row)">编辑</button>
            <button
              type="button"
              class="ap-action-btn ap-action-btn--red"
              :disabled="row.id === currentUserId"
              @click="handleDelete(row)"
            >
              移除
            </button>
          </div>
        </div>
      </section>
    </div>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="520px">
      <el-form ref="dataFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="temp.username" :disabled="isEdit" placeholder="例如：tester1" />
        </el-form-item>
        <el-form-item label="显示名" prop="display_name">
          <el-input v-model="temp.display_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="temp.role" style="width: 100%">
            <el-option label="管理员" value="admin" />
            <el-option label="测试工程师" value="tester" />
            <el-option label="访客" value="viewer" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态" prop="status">
          <el-select v-model="temp.status" style="width: 100%">
            <el-option label="启用" value="ACTIVE" />
            <el-option label="停用" value="DISABLED" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isEdit" label="所属工作空间">
          <div class="workspace-manage">
            <div class="workspace-tags dialog-workspaces">
              <el-tag
                v-for="membership in temp.workspace_memberships"
                :key="`${membership.workspace_id}-${membership.role}`"
                class="workspace-tag"
                effect="plain"
                closable
                @close="removeMembership(membership)"
              >
                {{ membership.workspace_name }}
                <span class="workspace-role">· {{ membership.role }}</span>
              </el-tag>
              <span v-if="!temp.workspace_memberships?.length">-</span>
            </div>
            <div class="workspace-add">
              <el-select v-model="joinForm.workspace_id" placeholder="选择工作空间" size="small" style="width: 200px">
                <el-option v-for="ws in joinableWorkspaces" :key="ws.id" :label="ws.name" :value="ws.id" />
              </el-select>
              <el-select v-model="joinForm.role" size="small" style="width: 110px">
                <el-option label="member" value="member" />
                <el-option label="owner" value="owner" />
              </el-select>
              <el-button size="small" type="primary" plain :disabled="!joinForm.workspace_id" :loading="joining" @click="joinWorkspace">加入</el-button>
            </div>
          </div>
        </el-form-item>
        <el-form-item :label="passwordLabel" prop="password">
          <el-input v-model="temp.password" type="password" show-password placeholder="至少6位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitData">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useContextStore } from '@/stores/context'
import { formatDateTime as formatTime } from '@/lib/formatTime'

const list = ref([])
const listLoading = ref(false)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
const isEdit = ref(false)
const router = useRouter()
const authStore = useAuthStore()
const contextStore = useContextStore()

const currentUserId = computed(() => authStore.user?.id ?? null)

const roleLabels = { admin: '管理员', tester: '测试工程师', viewer: '访客' }
const statusLabels = { ACTIVE: '启用', DISABLED: '停用' }

const filters = reactive({ keyword: '', role: '', status: '' })

const AVATARS = [
  'linear-gradient(180deg, #3b9eff 0%, #0071e3 100%)',
  'linear-gradient(180deg, #4cd964 0%, #28cd41 100%)',
  'linear-gradient(180deg, #ff9f0a 0%, #ff6b00 100%)',
  'linear-gradient(180deg, #5e5ce6 0%, #3634a3 100%)',
  'linear-gradient(180deg, #ff375f 0%, #d70040 100%)'
]
const avatarGradient = (idx) => AVATARS[idx % AVATARS.length]

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((item) => {
    if (keyword) {
      const username = (item.username || '').toLowerCase()
      const displayName = (item.display_name || '').toLowerCase()
      if (!username.includes(keyword) && !displayName.includes(keyword)) return false
    }
    if (filters.role && item.role !== filters.role) return false
    if (filters.status && item.status !== filters.status) return false
    return true
  })
})

const temp = reactive({
  id: null,
  username: '',
  display_name: '',
  role: 'tester',
  status: 'ACTIVE',
  workspaces: [],
  workspace_memberships: [],
  password: ''
})

const allWorkspaces = ref([])
const joinForm = reactive({ workspace_id: null, role: 'member' })
const joining = ref(false)

const joinableWorkspaces = computed(() => {
  const joinedIds = new Set((temp.workspace_memberships || []).map((item) => item.workspace_id))
  return allWorkspaces.value.filter((ws) => !joinedIds.has(ws.id))
})

const rules = computed(() => {
  const passwordRules = isEdit.value
    ? [{ min: 6, message: '至少6位', trigger: 'blur' }]
    : [{ required: true, message: '密码必填', trigger: 'blur' }, { min: 6, message: '至少6位', trigger: 'blur' }]

  return {
    username: [
      { required: true, message: '用户名必填', trigger: 'blur' },
      { min: 2, message: '至少2字符', trigger: 'blur' }
    ],
    role: [{ required: true, message: '请选择角色', trigger: 'change' }],
    status: [{ required: true, message: '请选择状态', trigger: 'change' }],
    password: passwordRules
  }
})

const dialogTitle = computed(() => (isEdit.value ? '编辑成员' : '邀请成员'))
const passwordLabel = computed(() => (isEdit.value ? '重置密码（可选）' : '初始密码'))
const adminCount = computed(() => list.value.filter((item) => item.role === 'admin').length)
const testerCount = computed(() => list.value.filter((item) => item.role === 'tester').length)
const viewerCount = computed(() => list.value.filter((item) => item.role === 'viewer').length)

const getWorkspaceMemberships = (user) => {
  if (Array.isArray(user?.workspace_memberships) && user.workspace_memberships.length > 0) {
    return user.workspace_memberships
  }
  if (Array.isArray(user?.workspaces)) {
    return user.workspaces.map((workspaceName) => ({
      workspace_id: 0,
      workspace_name: workspaceName,
      role: 'member'
    }))
  }
  return []
}

const handleWorkspaceJump = (membership) => {
  if (!membership?.workspace_name) return
  router.push({
    path: '/workspace/index',
    query: membership.workspace_id ? { workspace_id: String(membership.workspace_id) } : { keyword: membership.workspace_name }
  })
}

const getList = async () => {
  listLoading.value = true
  try {
    list.value = await api.get('/users')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const loadWorkspaces = async () => {
  try {
    allWorkspaces.value = await contextStore.fetchWorkspaces()
  } catch {
    allWorkspaces.value = []
  }
}

const refreshTempMemberships = async () => {
  await getList()
  const fresh = list.value.find((item) => item.id === temp.id)
  if (fresh) {
    temp.workspaces = Array.isArray(fresh.workspaces) ? [...fresh.workspaces] : []
    temp.workspace_memberships = getWorkspaceMemberships(fresh).map((item) => ({ ...item }))
  }
}

const joinWorkspace = async () => {
  if (!joinForm.workspace_id || !temp.id) return
  joining.value = true
  try {
    await api.post(`/workspaces/${joinForm.workspace_id}/members`, {
      user_id: temp.id,
      role: joinForm.role
    })
    ElMessage.success('已加入工作空间')
    joinForm.workspace_id = null
    joinForm.role = 'member'
    await refreshTempMemberships()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    joining.value = false
  }
}

const removeMembership = async (membership) => {
  if (!membership?.member_id) {
    ElMessage.warning('该成员记录暂不支持移除')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认将该用户移出「${membership.workspace_name}」？`,
      '移除成员',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.delete(`/workspaces/${membership.workspace_id}/members/${membership.member_id}`)
    ElMessage.success('已移出工作空间')
    await refreshTempMemberships()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.username}」？删除后不可恢复。`,
      '删除用户',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await api.delete(`/users/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleCreate = () => {
  isEdit.value = false
  temp.id = null
  temp.username = ''
  temp.display_name = ''
  temp.role = 'tester'
  temp.status = 'ACTIVE'
  temp.workspaces = []
  temp.workspace_memberships = []
  temp.password = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleEdit = (row) => {
  isEdit.value = true
  temp.id = row.id
  temp.username = row.username
  temp.display_name = row.display_name || ''
  temp.role = row.role
  temp.status = row.status
  temp.workspaces = Array.isArray(row.workspaces) ? [...row.workspaces] : []
  temp.workspace_memberships = getWorkspaceMemberships(row).map((item) => ({ ...item }))
  temp.password = ''
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const submitData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        if (isEdit.value) {
          const payload = {
            display_name: temp.display_name,
            role: temp.role,
            status: temp.status
          }
          if (temp.password) {
            payload.password = temp.password
          }
          await api.put(`/users/${temp.id}`, payload)
        } else {
          await api.post('/users', {
            username: temp.username,
            display_name: temp.display_name,
            role: temp.role,
            status: temp.status,
            password: temp.password
          })
        }
        dialogVisible.value = false
        ElMessage.success(isEdit.value ? '更新成功' : '创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

onMounted(() => {
  getList()
  loadWorkspaces()
})
</script>

<style scoped>
.apple-page {
  min-height: calc(100vh - var(--app-header-height));
  padding: 24px 32px 36px;
}

.apple-container {
  max-width: 1180px;
  margin: 0 auto;
}

.ap-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.ap-title {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #1d1d1f;
}

.ap-subtitle {
  margin: 4px 0 0;
  font-size: 13.5px;
  color: #6e6e73;
}

.ap-pill-btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 999px;
  font-size: 13.5px;
  font-weight: 500;
  cursor: pointer;
}

.ap-pill-btn--blue {
  border: none;
  background: #0071e3;
  color: #ffffff;
  box-shadow: 0 2px 10px rgba(0, 113, 227, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.ap-pill-btn--blue:hover { background: #0077ed; }

.ap-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.ap-seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.055);
}

.ap-seg__btn {
  height: 30px;
  padding: 0 14px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #6e6e73;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.14s ease;
}

.ap-seg__btn span {
  margin-left: 4px;
  font-size: 11.5px;
  opacity: 0.7;
  font-variant-numeric: tabular-nums;
}

.ap-seg__btn.is-active {
  background: #ffffff;
  color: #1d1d1f;
  font-weight: 600;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.ap-controls__right { display: flex; align-items: center; gap: 10px; }

.ap-search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 230px;
  height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(16px);
}

.ap-search-box:focus-within {
  border-color: #0071e3;
  box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.16);
}

.ap-search-icon { color: #86868b; flex-shrink: 0; }
.ap-search-input { flex: 1; border: none; background: transparent; outline: none; font-size: 13px; color: #1d1d1f; }

.ap-glass-list {
  border-radius: 20px;
  border: var(--apple-glass-border);
  background: var(--apple-glass-bg);
  backdrop-filter: blur(24px) saturate(180%);
  box-shadow: var(--apple-glass-shadow);
  overflow: hidden;
}

.ap-empty { padding: 56px 16px; text-align: center; color: #86868b; }

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
  left: 76px;
  right: 22px;
  bottom: 0;
  height: 1px;
  background: rgba(0, 0, 0, 0.06);
}

.ap-list-row:hover { background: rgba(0, 113, 227, 0.035); }

.ap-member__id { display: flex; align-items: center; gap: 14px; min-width: 0; flex: 1.2; }

.ap-app-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 700;
  flex-shrink: 0;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.35);
}

.ap-member__text { min-width: 0; }
.ap-member__name-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ap-member__name { font-size: 15px; font-weight: 600; color: #1d1d1f; }
.ap-member__handle { font-family: var(--font-mono); font-size: 12px; color: #86868b; }

.ap-role-pill { padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.ap-role-pill--admin { background: rgba(255, 59, 48, 0.12); color: #d70015; }
.ap-role-pill--tester { background: rgba(0, 113, 227, 0.1); color: #0071e3; }
.ap-role-pill--viewer { background: rgba(0, 0, 0, 0.055); color: #6e6e73; }

.ap-disabled-pill { padding: 2px 7px; border-radius: 999px; background: rgba(0, 0, 0, 0.05); color: #86868b; font-size: 11px; }
.ap-member__meta { margin-top: 3px; font-size: 12px; color: #86868b; }
.ap-dot-sep { margin: 0 6px; color: #d2d2d7; }

.ap-member__spaces { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; flex: 1; }

.ap-space-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.07);
  background: rgba(255, 255, 255, 0.72);
  color: #424245;
  font-size: 12px;
  cursor: pointer;
}

.ap-space-chip:hover { background: #ffffff; border-color: rgba(0, 113, 227, 0.3); color: #0071e3; }
.ap-space-chip small { color: #86868b; font-size: 11px; }
.ap-no-space { font-size: 12px; color: #86868b; }

.ap-row-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

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
}

.ap-action-btn--blue { color: #0071e3; background: rgba(0, 113, 227, 0.08); border-color: transparent; }
.ap-action-btn--blue:hover { background: rgba(0, 113, 227, 0.14); }
.ap-action-btn--red { color: #d70015; background: rgba(255, 59, 48, 0.08); border-color: transparent; }
.ap-action-btn--red:hover:not(:disabled) { background: rgba(255, 59, 48, 0.14); }
.ap-action-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.workspace-manage { width: 100%; }
.workspace-add { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.workspace-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.workspace-tag { cursor: pointer; }
.workspace-role { margin-left: 4px; color: var(--color-text-secondary); }
.dialog-workspaces { min-height: 32px; align-items: center; }

@media (max-width: 900px) {
  .apple-page { padding: 16px; }
  .ap-header { flex-direction: column; align-items: flex-start; }
  .ap-list-row { flex-direction: column; align-items: flex-start; }
}
</style>
