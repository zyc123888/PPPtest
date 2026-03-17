<template>
  <div class="app-page">
    <PageHeader title="执行中心" subtitle="查看执行记录、状态与请求/响应快照">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="类型">
          <el-select v-model="filters.caseType" clearable placeholder="全部" style="width: 160px">
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 160px">
            <el-option label="排队中" value="PENDING" />
            <el-option label="执行中" value="RUNNING" />
            <el-option label="成功" value="SUCCESS" />
            <el-option label="失败" value="FAILED" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="用例名称/摘要" style="width: 280px" />
        </el-form-item>
        <el-form-item label=" " class="query-actions">
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="page-card" shadow="never">
      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="类型" prop="case_type" width="90" align="center" />
        <el-table-column label="用例名称" prop="case_name" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" prop="status" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="240" show-overflow-tooltip />
        <el-table-column label="耗时" width="110" align="center">
          <template #default="scope">
            {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="110">
          <template #default="scope">
            <el-button size="small" @click="handleDetail(scope.row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.case_name }}</div>
          <div class="mobile-card-meta">类型：{{ item.case_type }} · 状态：{{ statusText(item.status) }}</div>
          <div class="mobile-card-meta">耗时：{{ item.duration_ms ? item.duration_ms + 'ms' : '-' }}</div>
          <div class="mobile-card-desc">{{ item.summary || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="handleDetail(item)">详情</el-button>
          </div>
        </div>
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="filteredList.length"
          :page-sizes="[10, 20, 30]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="执行详情" width="860px">
      <el-tabs>
        <el-tab-pane label="请求" name="req">
          <el-input :model-value="formatJson(currentRun.request_payload)" type="textarea" :rows="18" readonly />
        </el-tab-pane>
        <el-tab-pane label="响应" name="resp">
          <el-input :model-value="formatJson(currentRun.response_payload)" type="textarea" :rows="18" readonly />
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const list = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const currentRun = ref({})
let timer = null

const filters = reactive({
  status: '',
  caseType: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const statusText = (status) => {
  const map = {
    healthy: '正常',
    degraded: '降级',
    unhealthy: '异常',
    PENDING: '排队中',
    RUNNING: '执行中',
    SUCCESS: '成功',
    FAILED: '失败',
    loading: '加载中'
  }
  return map[status] || status
}

const statusType = (status) => {
  if (['healthy', 'SUCCESS'].includes(status)) return 'success'
  if (['RUNNING', 'PENDING', 'degraded', 'loading'].includes(status)) return 'warning'
  return 'danger'
}

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const formatJson = (val) => {
  if (!val) return '{}'
  try {
    return JSON.stringify(val, null, 2)
  } catch (e) {
    return val
  }
}

const getList = async () => {
  try {
    const data = await api.get('/executions/runs')
    list.value = data
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((r) => {
    if (filters.status && r.status !== filters.status) return false
    if (filters.caseType && r.case_type !== filters.caseType) return false
    if (!keyword) return true
    return (
      String(r.case_name || '').toLowerCase().includes(keyword) ||
      String(r.summary || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.status = ''
  filters.caseType = ''
  filters.keyword = ''
  page.value = 1
}

const handleDetail = async (row) => {
  try {
    const data = await api.get(`/executions/runs/${row.id}`)
    currentRun.value = data
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(() => {
  getList()
  timer = setInterval(getList, 5000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
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
