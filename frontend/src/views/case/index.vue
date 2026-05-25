<template>
  <div class="app-page">
    <PageHeader title="用例中心" subtitle="统一查看 API、UI 和性能用例，按项目、类型、目录、优先级、评审状态、标签快速检索">
      <template #actions>
        <div class="header-actions">
          <el-button v-if="canTest" @click="goCreate('API')">新增接口用例</el-button>
          <el-button v-if="canTest" @click="goCreate('UI')">新增 UI 用例</el-button>
          <el-button v-if="canTest" type="primary" @click="goCreate('PERF')">新增性能用例</el-button>
        </div>
      </template>
    </PageHeader>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top">
        <el-form-item label="所属项目">
          <el-select v-model="filters.projectId" clearable placeholder="全部" style="width: 200px">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例类型">
          <el-select v-model="filters.caseType" clearable placeholder="全部" style="width: 140px">
            <el-option label="API" value="API" />
            <el-option label="UI" value="UI" />
            <el-option label="PERF" value="PERF" />
          </el-select>
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="filters.priority" clearable placeholder="全部" style="width: 140px">
            <el-option label="P0" value="P0" />
            <el-option label="P1" value="P1" />
            <el-option label="P2" value="P2" />
          </el-select>
        </el-form-item>
        <el-form-item label="目录">
          <el-select v-model="filters.folderPath" clearable filterable placeholder="全部" style="width: 220px">
            <el-option v-for="item in allFolders" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 140px">
            <el-option label="ACTIVE" value="ACTIVE" />
            <el-option label="DISABLED" value="DISABLED" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审状态">
          <el-select v-model="filters.reviewStatus" clearable placeholder="全部" style="width: 160px">
            <el-option label="DRAFT" value="DRAFT" />
            <el-option label="IN_REVIEW" value="IN_REVIEW" />
            <el-option label="APPROVED" value="APPROVED" />
            <el-option label="REJECTED" value="REJECTED" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="filters.tag" clearable filterable placeholder="全部" style="width: 180px">
            <el-option v-for="item in allTags" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="名称/路径/目标地址" style="width: 260px" />
        </el-form-item>
        <el-form-item label=" " class="query-actions">
          <el-button type="primary" @click="getList">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="page-card" shadow="never">
      <div class="summary-bar section-gap">
        <el-tag size="large">总数 {{ list.length }}</el-tag>
        <el-tag size="large" type="success">API {{ typeCounts.API || 0 }}</el-tag>
        <el-tag size="large" type="warning">UI {{ typeCounts.UI || 0 }}</el-tag>
        <el-tag size="large" type="danger">PERF {{ typeCounts.PERF || 0 }}</el-tag>
        <el-tag size="large">待评审 {{ reviewCounts.DRAFT || 0 }}</el-tag>
        <el-tag size="large" type="warning">评审中 {{ reviewCounts.IN_REVIEW || 0 }}</el-tag>
        <el-tag size="large" type="success">已通过 {{ reviewCounts.APPROVED || 0 }}</el-tag>
        <el-tag size="large" type="danger">已拒绝 {{ reviewCounts.REJECTED || 0 }}</el-tag>
        <div class="summary-actions">
          <el-button :type="quickFilter === 'PENDING_REVIEW' ? 'primary' : 'default'" @click="applyQuickFilter('PENDING_REVIEW')">待评审</el-button>
          <el-button :type="quickFilter === 'RECENT_CHANGED' ? 'primary' : 'default'" @click="applyQuickFilter('RECENT_CHANGED')">最近变更</el-button>
          <el-button v-if="quickFilter" @click="applyQuickFilter('')">取消快捷视图</el-button>
          <el-button :disabled="!selectedRows.length" @click="openBatchUpdate">批量改状态/标签</el-button>
          <el-button :disabled="!selectedRows.length" @click="openBatchReview">批量评审</el-button>
          <el-button
            v-if="quickFilter === 'PENDING_REVIEW'"
            type="warning"
            :disabled="!quickReviewRows.length"
            @click="openQuickReview"
          >
            评审当前视图
          </el-button>
          <el-button type="primary" :disabled="!selectedRows.length" @click="openBatchPlan">批量加入计划</el-button>
        </div>
      </div>
      <div v-if="quickFilter === 'PENDING_REVIEW'" class="pending-review-board section-gap">
        <el-card shadow="never" class="pending-card">
          <template #header>按项目</template>
          <div class="pending-stats">
            <el-tag
              v-for="item in pendingReviewProjectStats"
              :key="item.label"
              size="large"
              class="clickable-tag"
              @click="applyPendingProjectFilter(item)"
            >
              {{ item.label }} {{ item.count }}
            </el-tag>
          </div>
        </el-card>
        <el-card shadow="never" class="pending-card">
          <template #header>按类型</template>
          <div class="pending-stats">
            <el-tag
              v-for="item in pendingReviewTypeStats"
              :key="item.label"
              size="large"
              :type="typeTag(item.label)"
              class="clickable-tag"
              @click="applyPendingTypeFilter(item)"
            >
              {{ item.label }} {{ item.count }}
            </el-tag>
          </div>
        </el-card>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" border @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="48" align="center" />
        <el-table-column label="类型" width="90" align="center">
          <template #default="scope">
            <el-tag size="small" :type="typeTag(scope.row.case_type)">{{ scope.row.case_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="项目" width="160" show-overflow-tooltip>
          <template #default="scope">
            {{ projectMap[scope.row.project_id] || scope.row.project_id }}
          </template>
        </el-table-column>
        <el-table-column label="名称" prop="name" min-width="180" show-overflow-tooltip />
        <el-table-column label="目录" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ scope.row.folder_path || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="入口" min-width="240" show-overflow-tooltip>
          <template #default="scope">
            {{ caseEntry(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column label="优先级" prop="priority" width="100" align="center" />
        <el-table-column label="版本" prop="version_no" width="100" align="center" />
        <el-table-column label="状态" prop="status" width="100" align="center" />
        <el-table-column label="评审" prop="review_status" width="120" align="center" />
        <el-table-column label="评审备注" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ scope.row.review_note || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="标签" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            <div v-if="scope.row.tags_json?.length" class="tag-cell">
              <el-tag v-for="item in scope.row.tags_json" :key="item" size="small">{{ item }}</el-tag>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="补充信息" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ extraSummary(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="scope">
            <div class="row-actions">
              <el-button size="small" @click="openHistory(scope.row)">查看历史</el-button>
              <el-button size="small" @click="openDetail(scope.row)">进入类型页</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="`${item.case_type}-${item.case_id}`" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">类型：{{ item.case_type }} · 项目：{{ projectMap[item.project_id] || item.project_id }}</div>
          <div class="mobile-card-meta">目录：{{ item.folder_path || '-' }}</div>
          <div class="mobile-card-meta">优先级：{{ item.priority }} · 版本：{{ item.version_no }}</div>
          <div class="mobile-card-meta">状态：{{ item.status }} · 评审：{{ item.review_status }}</div>
          <div class="mobile-card-meta">评审备注：{{ item.review_note || '-' }}</div>
          <div class="mobile-card-desc">{{ caseEntry(item) }}</div>
          <div class="mobile-card-meta">补充：{{ extraSummary(item) }}</div>
          <div v-if="item.tags_json?.length" class="tag-cell">
            <el-tag v-for="tag in item.tags_json" :key="tag" size="small">{{ tag }}</el-tag>
          </div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="openHistory(item)">查看历史</el-button>
            <el-button size="small" @click="openDetail(item)">进入类型页</el-button>
          </div>
        </div>
      </div>

      <div class="table-pagination">
        <el-pagination
          layout="total, sizes, prev, pager, next"
          :total="quickFilteredList.length"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="pageSize"
          v-model:current-page="page"
        />
      </div>
    </el-card>

    <el-dialog v-model="batchUpdateVisible" title="批量更新用例" width="520px">
      <el-form label-position="top">
        <el-form-item label="批量状态">
          <el-select v-model="batchUpdateForm.status" clearable placeholder="不修改" style="width: 100%">
            <el-option label="ACTIVE" value="ACTIVE" />
            <el-option label="DISABLED" value="DISABLED" />
          </el-select>
        </el-form-item>
        <el-form-item label="追加标签">
          <el-select v-model="batchUpdateForm.add_tags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：core、regression">
            <el-option v-for="item in allTags" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchUpdateVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchUpdate">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchPlanVisible" title="批量加入计划" width="520px">
      <el-form label-position="top">
        <el-form-item label="测试计划">
          <el-select v-model="batchPlanForm.plan_id" placeholder="请选择计划" style="width: 100%">
            <el-option v-for="item in planOptions" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="起始顺序">
          <el-input-number v-model="batchPlanForm.order_start" :min="1" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="canAdmin" label="评审覆盖">
          <el-checkbox v-model="batchPlanForm.allow_unapproved">允许加入未通过评审用例</el-checkbox>
        </el-form-item>
      </el-form>
      <div class="batch-plan-hint">
        默认仅允许加入评审状态为 `APPROVED` 的用例。
        <span v-if="canAdmin">管理员勾选后可带风险加入。</span>
      </div>
      <template #footer>
        <el-button @click="batchPlanVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchPlan">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="batchReviewVisible" title="批量评审用例" width="520px">
      <el-form label-position="top">
        <el-form-item label="评审状态">
          <el-select v-model="batchReviewForm.review_status" style="width: 100%">
            <el-option label="DRAFT" value="DRAFT" />
            <el-option label="IN_REVIEW" value="IN_REVIEW" />
            <el-option label="APPROVED" value="APPROVED" />
            <el-option label="REJECTED" value="REJECTED" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审备注">
          <el-input v-model="batchReviewForm.review_note" type="textarea" :rows="3" placeholder="例如：已通过自检，可进入计划回归；或填写拒绝原因" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchReviewVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchReview">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="用例变更历史" width="820px">
      <div v-if="historyTarget" class="history-title">
        {{ historyTarget.name }} · {{ historyTarget.case_type }} · {{ historyTarget.version_no || '-' }}
      </div>
      <div class="history-toolbar">
        <el-select v-model="historyFilter.mode" style="width: 180px">
          <el-option label="全部变化" value="ALL" />
          <el-option label="仅版本变化" value="VERSION_ONLY" />
          <el-option label="仅评审变化" value="REVIEW_ONLY" />
        </el-select>
      </div>
      <el-table :data="filteredHistoryList" border max-height="420">
        <el-table-column label="时间" min-width="160">
          <template #default="scope">
            {{ formatDate(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="动作" prop="action" width="120" align="center" />
        <el-table-column label="版本" width="120" align="center">
          <template #default="scope">
            <el-tag :type="historyVersionChanged(scope.$index) ? 'primary' : 'info'" size="small">
              {{ scope.row.version_no || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="评审" width="140" align="center">
          <template #default="scope">
            <el-tag :type="historyReviewChanged(scope.$index) ? 'warning' : 'info'" size="small">
              {{ scope.row.review_status || '-' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="评审备注" prop="review_note" min-width="180" show-overflow-tooltip />
        <el-table-column label="摘要" prop="summary" min-width="180" show-overflow-tooltip />
        <el-table-column label="变化" min-width="160">
          <template #default="scope">
            <div class="history-flags">
              <el-tag v-if="historyVersionChanged(scope.$index)" size="small" type="primary">版本变化</el-tag>
              <el-tag v-if="historyReviewChanged(scope.$index)" size="small" type="warning">评审变化</el-tag>
              <span v-if="!historyVersionChanged(scope.$index) && !historyReviewChanged(scope.$index)">-</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="差异摘要" min-width="260" show-overflow-tooltip>
          <template #default="scope">
            {{ historyDiffSummary(scope.$index) }}
          </template>
        </el-table-column>
        <el-table-column label="变更人" prop="changed_by" width="100" align="center" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '@/lib/api'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const router = useRouter()
const { canAdmin, canTest } = usePermissions()
const list = ref([])
const projects = ref([])
const plans = ref([])
const listLoading = ref(false)
const page = ref(1)
const pageSize = ref(10)
const selectedRows = ref([])
const batchUpdateVisible = ref(false)
const batchPlanVisible = ref(false)
const batchReviewVisible = ref(false)
const historyVisible = ref(false)
const historyList = ref([])
const historyTarget = ref(null)
const historyFilter = reactive({
  mode: 'ALL'
})
const quickFilter = ref('')

const filters = reactive({
  projectId: undefined,
  caseType: '',
  folderPath: '',
  priority: '',
  status: '',
  reviewStatus: '',
  tag: '',
  keyword: ''
})

const batchUpdateForm = reactive({
  status: '',
  add_tags: []
})

const batchPlanForm = reactive({
  plan_id: undefined,
  order_start: 1,
  allow_unapproved: false
})

const batchReviewForm = reactive({
  review_status: 'IN_REVIEW',
  review_note: ''
})

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach((item) => {
    map[item.id] = item.name
  })
  return map
})

const allTags = computed(() => {
  const tags = new Set()
  list.value.forEach((item) => {
    ;(item.tags_json || []).forEach((tag) => tags.add(tag))
  })
  return Array.from(tags).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const allFolders = computed(() =>
  Array.from(new Set(list.value.map((item) => item.folder_path).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-CN'))
)

const typeCounts = computed(() =>
  list.value.reduce((acc, item) => {
    acc[item.case_type] = (acc[item.case_type] || 0) + 1
    return acc
  }, {})
)

const reviewCounts = computed(() =>
  list.value.reduce((acc, item) => {
    const key = item.review_status || 'DRAFT'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
)

const planOptions = computed(() => {
  if (!selectedRows.value.length) return plans.value
  const projectIds = new Set(selectedRows.value.map((item) => item.project_id))
  if (projectIds.size !== 1) return []
  const [projectId] = Array.from(projectIds)
  return plans.value.filter((item) => item.project_id === projectId)
})

const pagedList = computed(() => {
  const source = quickFilteredList.value
  const start = (page.value - 1) * pageSize.value
  return source.slice(start, start + pageSize.value)
})

const quickFilteredList = computed(() => {
  if (quickFilter.value === 'PENDING_REVIEW') {
    return list.value.filter((item) => ['DRAFT', 'IN_REVIEW', 'REJECTED'].includes(item.review_status || 'DRAFT'))
  }
  if (quickFilter.value === 'RECENT_CHANGED') {
    return [...list.value]
      .sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')))
      .slice(0, 20)
  }
  return list.value
})

const quickReviewRows = computed(() => {
  if (quickFilter.value !== 'PENDING_REVIEW') return []
  return quickFilteredList.value
})

const filteredHistoryList = computed(() => {
  if (historyFilter.mode === 'VERSION_ONLY') {
    return historyList.value.filter((_, index) => historyVersionChanged(index))
  }
  if (historyFilter.mode === 'REVIEW_ONLY') {
    return historyList.value.filter((_, index) => historyReviewChanged(index))
  }
  return historyList.value
})

const pendingReviewProjectStats = computed(() => {
  const counts = {}
  quickReviewRows.value.forEach((item) => {
    const label = projectMap.value[item.project_id] || String(item.project_id)
    counts[label] = (counts[label] || 0) + 1
  })
  return Object.entries(counts)
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
})

const pendingReviewTypeStats = computed(() => {
  const counts = {}
  quickReviewRows.value.forEach((item) => {
    counts[item.case_type] = (counts[item.case_type] || 0) + 1
  })
  return Object.entries(counts)
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
})

const typeTag = (type) => {
  if (type === 'API') return 'success'
  if (type === 'UI') return 'warning'
  if (type === 'PERF') return 'danger'
  return 'info'
}

const caseEntry = (row) => row.path || row.target_url || '-'

const extraSummary = (row) => {
  if (row.case_type === 'UI') return `步骤 ${row.step_count || 0} 个`
  if (row.case_type === 'PERF') return `并发 ${row.concurrency || 0} / 请求 ${row.total_requests || 0}`
  return row.expected_status ? `预期 ${row.expected_status}` : '-'
}

const getList = async () => {
  listLoading.value = true
  try {
    const params = new URLSearchParams()
    if (filters.projectId) params.set('project_id', String(filters.projectId))
    if (filters.caseType) params.set('case_type', filters.caseType)
    if (filters.folderPath) params.set('folder_path', filters.folderPath)
    if (filters.priority) params.set('priority', filters.priority)
    if (filters.status) params.set('status', filters.status)
    if (filters.reviewStatus) params.set('review_status', filters.reviewStatus)
    if (filters.tag) params.set('tag', filters.tag)
    if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
    const query = params.toString() ? `?${params.toString()}` : ''
    const [caseData, projectData, planData] = await Promise.all([
      api.get(`/cases${query}`),
      api.get('/projects'),
      api.get('/test-plans')
    ])
    list.value = caseData
    projects.value = projectData
    plans.value = planData
    page.value = 1
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const handleReset = () => {
  filters.projectId = undefined
  filters.caseType = ''
  filters.folderPath = ''
  filters.priority = ''
  filters.status = ''
  filters.reviewStatus = ''
  filters.tag = ''
  filters.keyword = ''
  quickFilter.value = ''
  getList()
}

const applyQuickFilter = (mode) => {
  quickFilter.value = quickFilter.value === mode ? '' : mode
  page.value = 1
}

const applyPendingProjectFilter = (item) => {
  filters.projectId = projects.value.find((project) => project.name === item.label)?.id
  page.value = 1
}

const applyPendingTypeFilter = (item) => {
  filters.caseType = item.label
  page.value = 1
}

const openDetail = (row) => {
  if (row.case_type === 'API') router.push('/case/api')
  else if (row.case_type === 'UI') router.push('/case/ui')
  else router.push('/case/performance')
}

const formatDate = (value) => {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

const openHistory = async (row) => {
  try {
    historyTarget.value = row
    historyFilter.mode = 'ALL'
    historyList.value = await api.get(`/cases/${row.case_type}/${row.case_id}/history`)
    historyVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const historyVersionChanged = (index) => {
  const current = historyList.value[index]
  const previous = historyList.value[index + 1]
  if (!current) return false
  return !previous || current.version_no !== previous.version_no
}

const historyReviewChanged = (index) => {
  const current = historyList.value[index]
  const previous = historyList.value[index + 1]
  if (!current) return false
  return (
    !previous ||
    current.review_status !== previous.review_status ||
    (current.review_note || '') !== (previous.review_note || '')
  )
}

const historyDiffSummary = (index) => {
  const current = historyList.value[index]
  const previous = historyList.value[index + 1]
  const currentSnapshot = current?.snapshot_json || {}
  const previousSnapshot = previous?.snapshot_json || {}
  if (!current) return '-'
  if (!previous) return '初始版本'

  const labels = [
    ['name', '名称'],
    ['folder_path', '目录'],
    ['method', '方法'],
    ['path', '路径'],
    ['target_url', '目标地址'],
    ['expect_text', '断言文本'],
    ['priority', '优先级'],
    ['status', '状态'],
    ['review_note', '评审备注'],
  ]
  const changes = []
  for (const [field, label] of labels) {
    if ((currentSnapshot[field] || '') !== (previousSnapshot[field] || '')) {
      changes.push(label)
    }
  }
  const currentTags = JSON.stringify(currentSnapshot.tags_json || [])
  const previousTags = JSON.stringify(previousSnapshot.tags_json || [])
  if (currentTags !== previousTags) {
    changes.push('标签')
  }
  if (JSON.stringify(currentSnapshot.steps_json || []) !== JSON.stringify(previousSnapshot.steps_json || [])) {
    changes.push('步骤')
  }
  if (JSON.stringify(currentSnapshot.body_json || {}) !== JSON.stringify(previousSnapshot.body_json || {})) {
    changes.push('请求体')
  }
  if (JSON.stringify(currentSnapshot.headers_json || {}) !== JSON.stringify(previousSnapshot.headers_json || {})) {
    changes.push('请求头')
  }
  if (JSON.stringify(currentSnapshot.assertions_json || []) !== JSON.stringify(previousSnapshot.assertions_json || [])) {
    changes.push('断言')
  }
  if (
    JSON.stringify({
      concurrency: currentSnapshot.concurrency,
      total_requests: currentSnapshot.total_requests,
      max_avg_response_ms: currentSnapshot.max_avg_response_ms,
      max_p95_response_ms: currentSnapshot.max_p95_response_ms,
      max_error_rate: currentSnapshot.max_error_rate,
    }) !==
    JSON.stringify({
      concurrency: previousSnapshot.concurrency,
      total_requests: previousSnapshot.total_requests,
      max_avg_response_ms: previousSnapshot.max_avg_response_ms,
      max_p95_response_ms: previousSnapshot.max_p95_response_ms,
      max_error_rate: previousSnapshot.max_error_rate,
    })
  ) {
    changes.push('性能阈值')
  }
  return changes.length ? changes.join('、') : '无关键字段变化'
}

const handleSelectionChange = (rows) => {
  selectedRows.value = rows
}

const openBatchUpdate = () => {
  batchUpdateForm.status = ''
  batchUpdateForm.add_tags = []
  batchUpdateVisible.value = true
}

const openBatchPlan = () => {
  batchPlanForm.plan_id = planOptions.value[0]?.id
  batchPlanForm.order_start = 1
  batchPlanForm.allow_unapproved = false
  batchPlanVisible.value = true
}

const openBatchReview = () => {
  batchReviewForm.review_status = 'IN_REVIEW'
  batchReviewForm.review_note = ''
  batchReviewVisible.value = true
}

const openQuickReview = () => {
  batchReviewForm.review_status = 'IN_REVIEW'
  batchReviewForm.review_note = ''
  batchReviewVisible.value = true
}

const selectionPayload = () =>
  selectedRows.value.map((item) => ({
    case_type: item.case_type,
    case_id: item.case_id
  }))

const submitBatchUpdate = async () => {
  try {
    await api.post('/cases/batch-update', {
      items: selectionPayload(),
      status: batchUpdateForm.status || null,
      add_tags: batchUpdateForm.add_tags.length ? batchUpdateForm.add_tags : null
    })
    batchUpdateVisible.value = false
    ElMessage.success(`已批量更新 ${selectedRows.value.length} 条用例`)
    selectedRows.value = []
    getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitBatchPlan = async () => {
  try {
    if (!batchPlanForm.plan_id) {
      ElMessage.warning('请先选择测试计划')
      return
    }
    await api.post(`/test-plans/${batchPlanForm.plan_id}/cases/batch`, {
      items: selectionPayload(),
      order_start: batchPlanForm.order_start,
      allow_unapproved: canAdmin.value ? batchPlanForm.allow_unapproved : false
    })
    batchPlanVisible.value = false
    ElMessage.success(`已批量加入 ${selectedRows.value.length} 条用例`)
    selectedRows.value = []
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitBatchReview = async () => {
  try {
    const targetRows = selectedRows.value.length ? selectedRows.value : quickReviewRows.value
    if (!targetRows.length) {
      ElMessage.warning('请先选择用例，或进入待评审快捷视图')
      return
    }
    await api.post('/cases/batch-review', {
      items: targetRows.map((item) => ({
        case_type: item.case_type,
        case_id: item.case_id
      })),
      review_status: batchReviewForm.review_status,
      review_note: batchReviewForm.review_note || null
    })
    batchReviewVisible.value = false
    ElMessage.success(`已批量评审 ${targetRows.length} 条用例`)
    selectedRows.value = []
    getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const goCreate = (type) => {
  if (type === 'API') router.push('/case/api')
  else if (type === 'UI') router.push('/case/ui')
  else router.push('/case/performance')
}

onMounted(() => {
  getList()
})
</script>

<style scoped>
.header-actions,
.summary-bar,
.tag-cell,
.mobile-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.row-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pending-review-board {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.pending-card {
  border-radius: 12px;
}

.pending-stats,
.history-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.clickable-tag {
  cursor: pointer;
}

.batch-plan-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.history-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
}

.history-toolbar {
  margin-bottom: 12px;
}

.mobile-cards {
  display: none;
}

@media (max-width: 960px) {
  .pending-review-board {
    grid-template-columns: 1fr;
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
}
</style>
