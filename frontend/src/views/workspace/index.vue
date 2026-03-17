<template>
  <div class="app-page">
    <PageHeader title="工作空间" subtitle="管理工作空间、项目归属与资源隔离">
      <template #actions>
        <el-button type="primary" @click="handleCreate">新增空间</el-button>
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
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">创建时间：{{ formatTime(item.created_at) }}</div>
          <div class="mobile-card-desc">{{ item.description || '-' }}</div>
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
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const list = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const dataFormRef = ref(null)

const filters = reactive({
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  name: '',
  description: ''
})

const rules = {
  name: [{ required: true, message: '空间名称必填', trigger: 'blur' }, { min: 2, message: '至少2个字符', trigger: 'blur' }]
}

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const getList = async () => {
  listLoading.value = true
  try {
    const data = await api.get('/workspaces')
    list.value = data
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  if (!keyword) return list.value
  return list.value.filter((item) => {
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
}
</style>
