<template>
  <div v-loading="loading">
    <el-card class="page-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span>项目成员与角色</span>
          <el-button v-if="canManage" type="primary" size="small" @click="openAdd">添加成员</el-button>
        </div>
      </template>
      <el-table :data="members" border>
        <el-table-column label="用户" min-width="180">
          <template #default="{ row }">{{ row.display_name || row.username || ('#' + row.user_id) }}</template>
        </el-table-column>
        <el-table-column label="账号" prop="username" width="160" />
        <el-table-column label="角色" width="180">
          <template #default="{ row }">
            <el-select
              v-if="canManage"
              v-model="row.role"
              size="small"
              style="width: 130px"
              @change="(val) => changeRole(row, val)"
            >
              <el-option v-for="r in roleOptions" :key="r" :label="roleLabels[r]" :value="r" />
            </el-select>
            <el-tag v-else size="small">{{ roleLabels[row.role] || row.role }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="加入时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="90" align="center">
          <template #default="{ row }">
            <el-popconfirm title="确认移除该成员？" @confirm="removeMember(row)">
              <template #reference>
                <el-button size="small" text type="danger">移除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && !members.length" description="暂无项目成员" :image-size="80" />
    </el-card>

    <el-card class="page-card" shadow="never">
      <template #header><span>项目信息</span></template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="项目名称">{{ project.name }}</el-descriptions-item>
        <el-descriptions-item label="项目短码">{{ project.code || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ project.status || 'ACTIVE' }}</el-descriptions-item>
        <el-descriptions-item label="Base URL">{{ project.base_url || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="page-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span>消息通知</span>
          <div v-if="canManage">
            <el-button size="small" :loading="notifyTesting" @click="sendTestMessage">发送测试消息</el-button>
            <el-button size="small" type="primary" :loading="notifySaving" @click="saveNotifySetting">保存</el-button>
          </div>
        </div>
      </template>
      <el-form label-position="top" :disabled="!canManage" class="notify-form">
        <el-form-item label="启用通知">
          <el-switch v-model="notifyForm.enabled" />
        </el-form-item>
        <el-form-item label="通知渠道">
          <el-select v-model="notifyForm.channel_type" style="width: 220px">
            <el-option label="飞书机器人" value="FEISHU" />
            <el-option label="钉钉机器人" value="DINGTALK" />
            <el-option label="企业微信机器人" value="WECOM" />
            <el-option label="自定义 Webhook" value="CUSTOM" />
          </el-select>
        </el-form-item>
        <el-form-item label="Webhook 地址">
          <el-input v-model="notifyForm.webhook_url" placeholder="https://..." clearable />
        </el-form-item>
        <el-form-item v-if="notifyForm.channel_type === 'DINGTALK'" label="加签密钥（可选）">
          <el-input v-model="notifyForm.secret" placeholder="钉钉机器人安全设置中的加签密钥" show-password clearable />
        </el-form-item>
        <el-form-item label="通知时机">
          <el-radio-group v-model="notifyForm.notify_on">
            <el-radio value="ALL">全部执行结果</el-radio>
            <el-radio value="FAIL_ONLY">仅失败时通知</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div class="notify-hint">测试计划执行完成后，将按以上配置向对应渠道推送结果摘要与报告链接。</div>
    </el-card>

    <el-dialog v-model="addVisible" title="添加成员" width="460px">
      <el-form label-position="top">
        <el-form-item label="用户">
          <el-select v-model="addForm.user_id" filterable placeholder="选择用户" style="width: 100%">
            <el-option v-for="u in candidateUsers" :key="u.id" :label="u.display_name ? `${u.display_name} (${u.username})` : u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="addForm.role" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r" :label="roleLabels[r]" :value="r" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!addForm.user_id" @click="submitAdd">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import { PROJECT_ROLE_LABELS } from './constants'

const props = defineProps({ project: { type: Object, required: true }, myRole: { type: String, default: '' } })

const roleOptions = ['viewer', 'member', 'manager', 'owner']
const roleLabels = PROJECT_ROLE_LABELS
const canManage = computed(() => ['owner', 'manager'].includes(props.myRole))

const loading = ref(false)
const members = ref([])
const allUsers = ref([])

const addVisible = ref(false)
const addForm = reactive({ user_id: null, role: 'member' })

const notifyForm = reactive({ enabled: false, channel_type: 'FEISHU', webhook_url: '', secret: '', notify_on: 'ALL' })
const notifySaving = ref(false)
const notifyTesting = ref(false)

const candidateUsers = computed(() => {
  const joined = new Set(members.value.map((m) => m.user_id))
  return allUsers.value.filter((u) => !joined.has(u.id))
})

function formatTime(t) { return t ? String(t).replace('T', ' ').slice(0, 19) : '-' }

async function fetchMembers() {
  loading.value = true
  try {
    members.value = await api.get(`/projects/${props.project.id}/members`)
  } catch (error) { ElMessage.error(error.message) } finally { loading.value = false }
}

async function loadUsers() {
  try { allUsers.value = await api.get('/users') } catch { allUsers.value = [] }
}

function openAdd() {
  Object.assign(addForm, { user_id: null, role: 'member' })
  addVisible.value = true
}

async function submitAdd() {
  try {
    await api.post(`/projects/${props.project.id}/members`, { user_id: addForm.user_id, role: addForm.role })
    addVisible.value = false
    ElMessage.success('已添加成员')
    fetchMembers()
  } catch (error) { ElMessage.error(error.message) }
}

async function changeRole(row, role) {
  try {
    await api.put(`/projects/${props.project.id}/members/${row.id}`, { role })
    ElMessage.success('角色已更新')
  } catch (error) { ElMessage.error(error.message); fetchMembers() }
}

async function removeMember(row) {
  try {
    await api.delete(`/projects/${props.project.id}/members/${row.id}`)
    ElMessage.success('已移除')
    fetchMembers()
  } catch (error) { ElMessage.error(error.message) }
}

async function fetchNotifySetting() {
  try {
    const data = await api.get(`/projects/${props.project.id}/notification-setting`)
    Object.assign(notifyForm, {
      enabled: !!data.enabled,
      channel_type: data.channel_type || 'FEISHU',
      webhook_url: data.webhook_url || '',
      secret: data.secret || '',
      notify_on: data.notify_on || 'ALL',
    })
  } catch { /* 保持默认值 */ }
}

function buildNotifyPayload() {
  return {
    enabled: notifyForm.enabled,
    channel_type: notifyForm.channel_type,
    webhook_url: notifyForm.webhook_url || null,
    secret: notifyForm.secret || null,
    notify_on: notifyForm.notify_on,
  }
}

async function saveNotifySetting() {
  notifySaving.value = true
  try {
    await api.put(`/projects/${props.project.id}/notification-setting`, buildNotifyPayload())
    ElMessage.success('通知设置已保存')
  } catch (error) { ElMessage.error(error.message) } finally { notifySaving.value = false }
}

async function sendTestMessage() {
  if (!notifyForm.webhook_url) {
    ElMessage.warning('请先填写 Webhook 地址')
    return
  }
  notifyTesting.value = true
  try {
    const res = await api.post(`/projects/${props.project.id}/notification-setting/test`, buildNotifyPayload())
    if (res.success) { ElMessage.success(res.message || '发送成功') } else { ElMessage.error(res.message || '发送失败') }
  } catch (error) { ElMessage.error(error.message) } finally { notifyTesting.value = false }
}

onMounted(() => { fetchMembers(); loadUsers(); fetchNotifySetting() })
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
.page-card { margin-bottom: 12px; }
.notify-form { max-width: 560px; }
.notify-hint { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
</style>
