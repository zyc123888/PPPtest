<template>
  <div class="app-page">
    <PageHeader title="用户权限" subtitle="管理平台用户与角色">
      <template #actions>
        <el-button type="primary" @click="handleCreate">新增用户</el-button>
      </template>
    </PageHeader>

    <el-card class="page-card" shadow="never">
      <el-table v-loading="listLoading" :data="list" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="用户名" prop="username" min-width="160" />
        <el-table-column label="显示名" prop="display_name" min-width="160" />
        <el-table-column label="角色" prop="role" width="120" align="center" />
        <el-table-column label="状态" prop="status" width="120" align="center" />
        <el-table-column label="所属工作空间" min-width="240" show-overflow-tooltip>
          <template #default="scope">
            {{ formatWorkspaces(scope.row.workspaces) }}
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
        <el-table-column label="操作" width="140" align="center">
          <template #default="scope">
            <el-button size="small" @click="handleEdit(scope.row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in list" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.username }}</div>
          <div class="mobile-card-meta">角色：{{ item.role }} · 状态：{{ item.status }}</div>
          <div class="mobile-card-meta">显示名：{{ item.display_name || '-' }}</div>
          <div class="mobile-card-meta">空间：{{ formatWorkspaces(item.workspaces) }}</div>
          <div class="mobile-card-desc">最近登录：{{ formatTime(item.last_login_at) }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="handleEdit(item)">编辑</el-button>
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
          <el-input :model-value="formatWorkspaces(temp.workspaces)" disabled />
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
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const list = ref([])
const listLoading = ref(false)
const dialogVisible = ref(false)
const dataFormRef = ref(null)
const isEdit = ref(false)

const temp = reactive({
  id: null,
  username: '',
  display_name: '',
  role: 'tester',
  status: 'ACTIVE',
  workspaces: [],
  password: ''
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

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const formatWorkspaces = (workspaces) => {
  if (!Array.isArray(workspaces) || workspaces.length === 0) return '-'
  return workspaces.join(' / ')
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

const handleCreate = () => {
  isEdit.value = false
  temp.id = null
  temp.username = ''
  temp.display_name = ''
  temp.role = 'tester'
  temp.status = 'ACTIVE'
  temp.workspaces = []
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
    margin-bottom: 10px;
  }

  .mobile-card-actions {
    display: flex;
    gap: var(--space-8);
  }
}
</style>
