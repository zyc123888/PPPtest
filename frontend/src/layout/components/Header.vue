<template>
  <div class="header-root">
    <div class="header-left">
      <el-button text @click="toggleSideBar">
        <el-icon size="18">
          <Fold v-if="sidebar.opened" />
          <Expand v-else />
        </el-icon>
      </el-button>

      <el-breadcrumb separator="/">
        <el-breadcrumb-item v-for="item in breadcrumbs" :key="item.path">
          {{ item.title }}
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div class="header-right">
      <el-tag size="small" type="info" class="version-tag">v{{ appVersion }}</el-tag>
      <el-tag size="small" type="success">前端在线</el-tag>
      <el-dropdown trigger="click">
        <el-button text>
          <el-icon><User /></el-icon>
          {{ displayName }}
          <el-icon><CaretBottom /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="openPasswordDialog">修改密码</el-dropdown-item>
            <el-dropdown-item @click="openTokenDialog">API Token</el-dropdown-item>
            <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <el-dialog v-model="passwordVisible" title="修改密码" width="420px">
      <el-form ref="passwordFormRef" :model="passwordForm" :rules="passwordRules" label-position="top">
        <el-form-item label="原密码" prop="old_password">
          <el-input v-model="passwordForm.old_password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="passwordForm.new_password" type="password" show-password placeholder="至少6位" autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_password">
          <el-input v-model="passwordForm.confirm_password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="passwordVisible = false">取消</el-button>
        <el-button type="primary" :loading="passwordSaving" @click="submitPassword">确认修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tokenVisible" title="API Token" width="720px">
      <el-alert
        v-if="createdToken"
        type="success"
        :closable="true"
        class="token-created-alert"
        @close="createdToken = ''"
      >
        <template #title>Token 创建成功，仅本次展示，请立即保存</template>
        <div class="token-created-row">
          <code class="token-created-value">{{ createdToken }}</code>
          <el-button size="small" type="primary" @click="copyToken">复制</el-button>
        </div>
        <div class="token-created-hint">CI 用法示例：curl -H "Authorization: Bearer {{ createdToken }}" {{ apiBaseHint }}/test-plans/&lt;计划ID&gt;/run -X POST -H "Content-Type: application/json" -d '{}'</div>
      </el-alert>

      <el-form :inline="true" class="token-create-form">
        <el-form-item label="名称">
          <el-input v-model="tokenForm.name" placeholder="例如：Jenkins CI" style="width: 200px" maxlength="60" />
        </el-form-item>
        <el-form-item label="有效期">
          <el-select v-model="tokenForm.expires_days" style="width: 140px">
            <el-option label="30 天" :value="30" />
            <el-option label="90 天" :value="90" />
            <el-option label="永久" :value="null" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="tokenCreating" :disabled="!tokenForm.name.trim()" @click="createToken">新建 Token</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="tokenLoading" :data="tokens" border size="small">
        <el-table-column label="名称" prop="name" min-width="140" show-overflow-tooltip />
        <el-table-column label="Token" prop="token_prefix" width="130" />
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTokenTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="最后使用" width="160">
          <template #default="{ row }">{{ formatTokenTime(row.last_used_at) }}</template>
        </el-table-column>
        <el-table-column label="过期时间" width="160">
          <template #default="{ row }">{{ row.expires_at ? formatTokenTime(row.expires_at) : '永久' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-popconfirm title="删除后使用该 Token 的 CI 将立即失效，确认删除？" @confirm="deleteToken(row)">
              <template #reference>
                <el-button size="small" text type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!tokenLoading && !tokens.length" description="暂无 Token" :image-size="60" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CaretBottom, Expand, Fold, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { version as appVersion } from '../../../package.json'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const sidebar = computed(() => appStore.sidebar)

const breadcrumbs = computed(() => {
  return route.matched
    .filter((r) => r.meta && r.meta.title)
    .map((r) => ({ path: r.path, title: r.meta.title }))
})

const displayName = computed(() => {
  return authStore.user?.display_name || authStore.user?.username || '用户'
})

const toggleSideBar = () => {
  appStore.toggleSideBar()
}

const handleLogout = async () => {
  await authStore.logout()
  router.replace('/login')
}

const passwordVisible = ref(false)
const passwordSaving = ref(false)
const passwordFormRef = ref(null)
const passwordForm = reactive({ old_password: '', new_password: '', confirm_password: '' })

const passwordRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '至少6位', trigger: 'blur' }
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== passwordForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur'
    }
  ]
}

const openPasswordDialog = () => {
  passwordForm.old_password = ''
  passwordForm.new_password = ''
  passwordForm.confirm_password = ''
  passwordVisible.value = true
}

const submitPassword = () => {
  passwordFormRef.value?.validate(async (valid) => {
    if (!valid) return
    passwordSaving.value = true
    try {
      await api.post('/auth/change-password', {
        old_password: passwordForm.old_password,
        new_password: passwordForm.new_password
      })
      passwordVisible.value = false
      ElMessage.success('密码已修改')
    } catch (error) {
      ElMessage.error(error.message)
    } finally {
      passwordSaving.value = false
    }
  })
}

const tokenVisible = ref(false)
const tokenLoading = ref(false)
const tokenCreating = ref(false)
const tokens = ref([])
const tokenForm = reactive({ name: '', expires_days: 30 })
const createdToken = ref('')
const apiBaseHint = `${window.location.origin}/api/v1`

function formatTokenTime(value) {
  if (!value) return '-'
  const normalized = /(Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`
  return new Date(normalized).toLocaleString('zh-CN', { hour12: false })
}

async function fetchTokens() {
  tokenLoading.value = true
  try {
    tokens.value = await api.get('/api-tokens')
  } catch (error) { ElMessage.error(error.message) } finally { tokenLoading.value = false }
}

const openTokenDialog = () => {
  createdToken.value = ''
  Object.assign(tokenForm, { name: '', expires_days: 30 })
  tokenVisible.value = true
  fetchTokens()
}

async function createToken() {
  tokenCreating.value = true
  try {
    const res = await api.post('/api-tokens', {
      name: tokenForm.name.trim(),
      expires_days: tokenForm.expires_days
    })
    createdToken.value = res.token
    tokenForm.name = ''
    ElMessage.success('Token 已创建，请立即复制保存')
    fetchTokens()
  } catch (error) { ElMessage.error(error.message) } finally { tokenCreating.value = false }
}

async function deleteToken(row) {
  try {
    await api.delete(`/api-tokens/${row.id}`)
    ElMessage.success('已删除')
    fetchTokens()
  } catch (error) { ElMessage.error(error.message) }
}

async function copyToken() {
  try {
    await navigator.clipboard.writeText(createdToken.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选中复制')
  }
}
</script>

<style scoped>
.header-root {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-16);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-16);
  overflow: hidden;
  min-width: 0;
}

.header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-8);
  flex-shrink: 0;
}

.header-root :deep(.el-button.is-text) {
  color: var(--color-text);
}

.header-root :deep(.el-button.is-text:hover) {
  color: var(--color-primary);
  background: rgba(99, 102, 241, 0.08);
}

.header-root :deep(.el-breadcrumb__inner),
.header-root :deep(.el-breadcrumb__separator) {
  color: var(--color-text-secondary);
}

.header-root :deep(.el-tag--success) {
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.16);
  color: #047857;
}

.header-root :deep(.el-dropdown .el-button) {
  border-radius: 999px;
  padding-inline: 10px;
}

.header-root :deep(.version-tag) {
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.3px;
}

.token-created-alert {
  margin-bottom: 12px;
}

.token-created-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
}

.token-created-value {
  word-break: break-all;
  background: rgba(16, 185, 129, 0.08);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.token-created-hint {
  font-size: 12px;
  color: var(--color-text-secondary);
  word-break: break-all;
}

.token-create-form {
  margin-bottom: 4px;
}
</style>
