<template>
  <div class="header-root">
    <div class="header-left">
      <el-button text :aria-label="sidebar.opened ? '折叠侧边栏' : '展开侧边栏'" @click="toggleSideBar">
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
      <button
        type="button"
        class="glass-toggle-pill"
        :class="{ 'is-liquid': isLiquidGlass }"
        :title="isLiquidGlass ? '当前：液态玻璃（点击切回经典毛玻璃）' : '当前：经典毛玻璃（点击开启液态玻璃）'"
        @click="toggleGlassMode"
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M12 2.5C12 2.5 5.5 9.8 5.5 14.5a6.5 6.5 0 0 0 13 0C18.5 9.8 12 2.5 12 2.5z"
            stroke="currentColor"
            stroke-width="2"
            stroke-linejoin="round"
          />
          <path d="M9.5 14.5a2.5 2.5 0 0 0 2.5 2.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <span>{{ isLiquidGlass ? '液态玻璃' : '经典毛玻璃' }}</span>
      </button>

      <button type="button" class="cmd-pill" @click="openCommandPalette">
        <span class="cmd-pill__text">搜索或跳转…</span>
        <kbd class="cmd-pill__kbd">⌘K</kbd>
      </button>

      <div class="status-indicator" :class="backendOnline ? 'is-online' : 'is-offline'" :title="`v${appVersion}`">
        <span class="status-indicator__dot" />
        <span>{{ backendOnline ? '在线' : '离线' }}</span>
      </div>

      <el-dropdown trigger="click">
        <button type="button" class="user-trigger">
          <span class="user-avatar">{{ displayName.slice(0, 1).toUpperCase() }}</span>
          <span class="user-name">{{ displayName }}</span>
          <el-icon class="user-caret"><CaretBottom /></el-icon>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item disabled>版本 v{{ appVersion }}</el-dropdown-item>
            <el-dropdown-item divided @click="openPasswordDialog">修改密码</el-dropdown-item>
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
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CaretBottom, Expand, Fold, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { api } from '@/lib/api'
import { formatDateTime as formatTokenTime } from '@/lib/formatTime'
import { version as appVersion } from '../../../package.json'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()
const sidebar = computed(() => appStore.sidebar)
const isLiquidGlass = computed(() => appStore.glassMode === 'liquid')
const toggleGlassMode = () => appStore.toggleGlassMode()
const backendOnline = ref(true)

const checkBackendAlive = async () => {
  try {
    await api.get('/system/health/live')
    backendOnline.value = true
  } catch {
    backendOnline.value = false
  }
}

onMounted(() => {
  checkBackendAlive()
})

const breadcrumbs = computed(() => {
  return route.matched
    .filter((r) => r.meta && r.meta.title)
    .map((r) => ({ path: r.path, title: r.meta.title }))
})

const displayName = computed(() => {
  return authStore.user?.display_name || authStore.user?.username || '用户'
})

const openCommandPalette = () => {
  window.dispatchEvent(new CustomEvent('tp-open-command-palette'))
}

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
  gap: 10px;
  flex-shrink: 0;
}

.glass-toggle-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.72);
  color: #424245;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: all 0.16s ease;
}

.glass-toggle-pill:hover {
  background: #ffffff;
  color: #1d1d1f;
  border-color: rgba(0, 113, 227, 0.3);
}

.glass-toggle-pill.is-liquid {
  border-color: rgba(0, 113, 227, 0.28);
  background: linear-gradient(135deg, rgba(0, 113, 227, 0.14), rgba(94, 92, 230, 0.12));
  color: #0071e3;
  box-shadow:
    0 2px 10px rgba(0, 113, 227, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.85);
}

.cmd-pill {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  height: 32px;
  padding: 0 8px 0 14px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.08);
  background: rgba(255, 255, 255, 0.72);
  color: #6e6e73;
  font-size: 12.5px;
  cursor: pointer;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
  transition: border-color 0.14s ease, background 0.14s ease, color 0.14s ease;
}

.cmd-pill:hover {
  border-color: rgba(0, 113, 227, 0.3);
  background: #ffffff;
  color: #1d1d1f;
}

.cmd-pill__kbd {
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.07);
  background: rgba(0, 0, 0, 0.03);
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: #6e6e73;
}

.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 28px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  color: #248a3d;
  background: rgba(52, 199, 89, 0.12);
}

.status-indicator__dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
}

.status-indicator.is-online .status-indicator__dot {
  background: #28cd41;
}

.status-indicator.is-offline {
  background: rgba(255, 59, 48, 0.12);
  color: #d70015;
}

.status-indicator.is-offline .status-indicator__dot {
  background: #ff3b30;
}

.user-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 2px 10px 2px 3px;
  border-radius: 999px;
  border: 1px solid rgba(0, 0, 0, 0.06);
  background: rgba(255, 255, 255, 0.72);
  color: #1d1d1f;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease;
}

.user-trigger:hover {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.14);
}

.user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: linear-gradient(180deg, #3b9eff 0%, #0071e3 100%);
  color: #ffffff;
  font-size: 11px;
  font-weight: 600;
}

.user-name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-caret {
  font-size: 12px;
  color: #71717a;
}

.header-root :deep(.el-button.is-text) {
  color: #52525b;
}

.header-root :deep(.el-button.is-text:hover) {
  color: #09090b;
  background: #f4f4f5;
}

.header-root :deep(.el-breadcrumb__inner),
.header-root :deep(.el-breadcrumb__separator) {
  color: #71717a;
  font-size: 13px;
}

.header-root :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: #09090b;
  font-weight: 600;
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
