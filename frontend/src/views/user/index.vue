<template>
  <div class="app-page">
    <PageHeader title="用户权限" subtitle="管理平台用户与角色">
      <template #actions>
        <el-button type="primary" @click="handleCreate">新增用户</el-button>
      </template>
    </PageHeader>

    <div class="user-hero section-gap">
      <el-card class="page-card user-hero__main" shadow="never">
        <div class="user-hero__kicker">Access Layer</div>
        <div class="user-hero__title">用户与角色</div>
        <div class="user-hero__subtitle">把账号状态、角色和空间归属放在一起看，管理权限边界更直接。</div>
      </el-card>
      <el-card class="page-card user-hero__stat" shadow="never">
        <el-statistic title="用户数量" :value="list.length" />
      </el-card>
      <el-card class="page-card user-hero__stat" shadow="never">
        <el-statistic title="管理员" :value="adminCount" />
      </el-card>
      <el-card class="page-card user-hero__stat" shadow="never">
        <el-statistic title="已绑定空间" :value="workspaceBoundCount" />
      </el-card>
      <el-card class="page-card user-hero__stat" shadow="never">
        <el-statistic title="最近登录" :value="list.some((item) => item.last_login_at) ? '有' : '无'" />
      </el-card>
    </div>

    <el-card class="page-card" shadow="never">
      <div class="filter-bar">
        <el-input v-model="filters.keyword" placeholder="搜索用户名 / 显示名" clearable style="width: 220px" />
        <el-select v-model="filters.role" placeholder="角色" clearable style="width: 140px">
          <el-option v-for="(label, value) in roleLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <el-select v-model="filters.status" placeholder="状态" clearable style="width: 140px">
          <el-option v-for="(label, value) in statusLabels" :key="value" :label="label" :value="value" />
        </el-select>
        <span class="filter-count">共 {{ filteredList.length }} 人</span>
      </div>
      <el-table v-loading="listLoading" :data="filteredList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="用户名" prop="username" min-width="160" />
        <el-table-column label="显示名" prop="display_name" min-width="160" />
        <el-table-column label="角色" width="120" align="center">
          <template #default="scope">
            <el-tag :type="roleTagTypes[scope.row.role] || 'info'" effect="light">{{ roleLabels[scope.row.role] || scope.row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="scope">
            <el-tag :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'" effect="light">{{ statusLabels[scope.row.status] || scope.row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所属工作空间" min-width="260">
          <template #default="scope">
            <div class="workspace-tags">
              <el-tag
                v-for="membership in getWorkspaceMemberships(scope.row)"
                :key="`${membership.workspace_id}-${membership.role}`"
                class="workspace-tag"
                effect="plain"
                @click="handleWorkspaceJump(membership)"
              >
                {{ membership.workspace_name }}
                <span class="workspace-role">· {{ membership.role }}</span>
              </el-tag>
              <span v-if="!getWorkspaceMemberships(scope.row).length">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.last_login_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center">
          <template #default="scope">
            <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="scope.row.id === currentUserId"
              @click="handleDelete(scope.row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in filteredList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.username }}</div>
          <div class="mobile-card-meta">角色：{{ roleLabels[item.role] || item.role }} · 状态：{{ statusLabels[item.status] || item.status }}</div>
          <div class="mobile-card-meta">显示名：{{ item.display_name || '-' }}</div>
          <div class="mobile-card-meta">
            空间：
            <template v-if="getWorkspaceMemberships(item).length">
              <el-tag
                v-for="membership in getWorkspaceMemberships(item)"
                :key="`${membership.workspace_id}-${membership.role}`"
                class="workspace-tag"
                effect="plain"
                @click="handleWorkspaceJump(membership)"
              >
                {{ membership.workspace_name }}
                <span class="workspace-role">· {{ membership.role }}</span>
              </el-tag>
            </template>
            <template v-else>-</template>
          </div>
          <div class="mobile-card-desc">最近登录：{{ formatTime(item.last_login_at) }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="handleEdit(item)">编辑</el-button>
            <el-button size="small" type="danger" plain :disabled="item.id === currentUserId" @click="handleDelete(item)">删除</el-button>
          </div>
        </div>
      </div>
    </el-card>

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
import PageHeader from '@/components/PageHeader.vue'
import { useAuthStore } from '@/stores/auth'

const list = ref([])
const listLoading = ref(false)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
const isEdit = ref(false)
const router = useRouter()
const authStore = useAuthStore()

const currentUserId = computed(() => authStore.user?.id ?? null)

const roleLabels = { admin: '管理员', tester: '测试工程师', viewer: '访客' }
const statusLabels = { ACTIVE: '启用', DISABLED: '停用' }
const roleTagTypes = { admin: 'danger', tester: 'primary', viewer: 'info' }

const filters = reactive({ keyword: '', role: '', status: '' })

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

const dialogTitle = computed(() => (isEdit.value ? '编辑用户' : '新增用户'))
const passwordLabel = computed(() => (isEdit.value ? '重置密码（可选）' : '密码'))
const adminCount = computed(() => list.value.filter((item) => item.role === 'admin').length)
const workspaceBoundCount = computed(() => list.value.filter((item) => getWorkspaceMemberships(item).length > 0).length)

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

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
    allWorkspaces.value = await api.get('/workspaces')
  } catch (error) {
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
.user-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.user-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.26), transparent 35%);
  color: #f8fafc;
}

.user-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.user-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.user-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.user-hero__stat {
  border-radius: 18px;
}

@media (max-width: 960px) {
  .user-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .user-hero__main {
    grid-column: 1 / -1;
  }
}
</style>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
  margin-bottom: var(--space-12);
}

.filter-count {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.workspace-manage {
  width: 100%;
}

.workspace-add {
  display: flex;
  align-items: center;
  gap: var(--space-8);
  margin-top: 10px;
}

.workspace-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.workspace-tag {
  cursor: pointer;
}

.workspace-role {
  margin-left: 4px;
  color: var(--color-text-secondary);
}

.dialog-workspaces {
  min-height: 32px;
  align-items: center;
}

.mobile-cards {
  display: none;
}

@media (max-width: 960px) {
  .el-table {
    display: none;
  }

  .mobile-cards {
    display: grid;
    gap: var(--space-12);
  }

  .mobile-card {
    background: #ffffff;
    border: 1px solid var(--el-border-color);
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  }

  .mobile-card-title {
    font-weight: 600;
    margin-bottom: 6px;
  }

  .mobile-card-meta {
    font-size: 12px;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .mobile-card-desc {
    font-size: 13px;
    color: var(--color-text);
    margin-bottom: 10px;
  }

  .mobile-card-actions {
    display: flex;
    gap: var(--space-8);
  }
}
</style>
