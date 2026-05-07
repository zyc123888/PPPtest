<template>
  <div class="app-page">
    <PageHeader title="工作空间" subtitle="管理工作空间、项目归属与资源隔离">
      <template #actions>
        <el-button v-if="canAdmin" type="primary" @click="handleCreate">新增空间</el-button>
      </template>
    </PageHeader>

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
  }

  .mobile-card-actions {
    margin-top: 10px;
  }
}

.member-panel {
  display: grid;
  gap: var(--space-16);
}
</style>
