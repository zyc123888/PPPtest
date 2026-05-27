<template>
  <div class="app-page">
    <PageHeader title="接口用例" subtitle="维护 API 用例并投递执行任务">
      <template #actions>
        <el-button v-if="canTest" type="primary" @click="handleCreate">新增接口用例</el-button>
      </template>
    </PageHeader>

    <el-card class="page-card section-gap" shadow="never">
      <el-form :inline="true" class="query-form" label-position="top" :model="filters">
        <el-form-item label="所属项目">
          <el-select v-model="filters.projectId" clearable placeholder="全部" style="width: 200px">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="请求方法">
          <el-select v-model="filters.method" clearable placeholder="全部" style="width: 160px">
            <el-option label="GET" value="GET" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
            <el-option label="DELETE" value="DELETE" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable placeholder="名称/路径" style="width: 260px" />
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
          <el-dropdown>
            <el-button>
              更多
              <el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>导入</el-dropdown-item>
                <el-dropdown-item disabled>导出</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button @click="getList">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="项目" width="160" show-overflow-tooltip>
          <template #default="scope">
            {{ projectMap[scope.row.project_id] || scope.row.project_id }}
          </template>
        </el-table-column>
        <el-table-column label="名称" prop="name" min-width="180" show-overflow-tooltip />
        <el-table-column label="方法" prop="method" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="methodType(scope.row.method)">{{ scope.row.method }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="路径" prop="path" min-width="220" show-overflow-tooltip />
        <el-table-column label="优先级" prop="priority" width="100" align="center" />
        <el-table-column label="版本" prop="version_no" width="100" align="center" />
        <el-table-column label="评审" prop="review_status" width="110" align="center" />
        <el-table-column label="状态" prop="status" width="100" align="center" />
        <el-table-column label="预期状态码" prop="expected_status" width="120" align="center" />
        <el-table-column label="操作" align="center" width="280">
          <template #default="scope">
            <el-button v-if="canTest" size="small" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button v-if="canTest" size="small" type="primary" @click="handleRun(scope.row)">立即执行</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in pagedList" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.name }}</div>
          <div class="mobile-card-meta">项目：{{ projectMap[item.project_id] || item.project_id }}</div>
          <div class="mobile-card-meta">方法：{{ item.method }} · {{ item.expected_status }}</div>
          <div class="mobile-card-desc">{{ item.path }}</div>
          <div class="mobile-card-actions">
            <el-button v-if="canTest" size="small" type="primary" @click="handleRun(item)">立即执行</el-button>
            <el-button v-if="canAdmin" size="small" type="danger" @click="handleDelete(item)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑接口用例' : '新增接口用例'" width="640px">
      <el-form
        ref="dataFormRef"
        :model="temp"
        :rules="rules"
        label-position="top"
      >
        <div class="curl-import-box">
          <div class="request-editor-toolbar">
            <span>已有 cURL 命令时，可直接粘贴导入接口信息</span>
            <el-button size="small" @click="curlImportVisible = !curlImportVisible">
              {{ curlImportVisible ? '收起 cURL 导入' : '从 cURL 粘贴导入' }}
            </el-button>
          </div>
          <div v-if="curlImportVisible" class="curl-import-panel">
            <el-input
              v-model="curlImportText"
              type="textarea"
              :rows="5"
              placeholder="curl 'https://api.example.com/users?page=1' -X POST -H 'Content-Type: application/json' --data-raw '{&quot;name&quot;:&quot;ppp&quot;}'"
            />
            <div class="curl-import-actions">
              <el-button size="small" @click="curlImportText = ''">清空</el-button>
              <el-button size="small" type="primary" @click="applyCurlImport">解析并填充</el-button>
            </div>
          </div>
        </div>
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option
              v-for="item in projects"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称" prop="name">
          <el-input v-model="temp.name" placeholder="请输入用例名称" />
        </el-form-item>
        <el-form-item label="目录/分组">
          <el-input v-model="temp.folder_path" placeholder="例如：登录模块/健康检查" />
        </el-form-item>
        <el-row>
          <el-col :span="12">
            <el-form-item label="请求方法" prop="method">
              <el-select v-model="temp.method" placeholder="请选择" style="width: 100%">
                <el-option v-for="item in methodOptions" :key="item" :value="item" :label="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="预期状态码" prop="expected_status">
              <el-input-number v-model="temp.expected_status" :min="100" :max="599" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row>
          <el-col :span="12">
            <el-form-item label="优先级" prop="priority">
              <el-select v-model="temp.priority" style="width: 100%">
                <el-option label="P0" value="P0" />
                <el-option label="P1" value="P1" />
                <el-option label="P2" value="P2" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态" prop="status">
              <el-select v-model="temp.status" style="width: 100%">
                <el-option label="ACTIVE" value="ACTIVE" />
                <el-option label="DISABLED" value="DISABLED" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="请求路径" prop="path">
          <el-input v-model="temp.path" placeholder="/api/v1/..." />
        </el-form-item>
        <el-tabs v-model="requestTab" class="request-editor">
          <el-tab-pane label="Params" name="params">
            <div class="request-editor-toolbar">
              <span>Query 参数会同步到请求路径</span>
              <el-button size="small" @click="addQueryParam">添加参数</el-button>
            </div>
            <el-table :data="temp.query_params" border size="small">
              <el-table-column label="启用" width="70" align="center">
                <template #default="scope">
                  <el-checkbox v-model="scope.row.enabled" @change="syncPathFromParams" />
                </template>
              </el-table-column>
              <el-table-column label="Key" min-width="160">
                <template #default="scope">
                  <el-input v-model="scope.row.key" placeholder="key" @input="syncPathFromParams" />
                </template>
              </el-table-column>
              <el-table-column label="Value" min-width="180">
                <template #default="scope">
                  <el-input v-model="scope.row.value" placeholder="value" @input="syncPathFromParams" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90" align="center">
                <template #default="scope">
                  <el-button size="small" type="danger" @click="removeQueryParam(scope.$index)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="Headers" name="headers">
            <div class="request-editor-toolbar">
              <span>请求头按 Key / Value 编辑，保存时自动转换为对象</span>
              <el-button size="small" @click="addHeaderRow">添加 Header</el-button>
            </div>
            <el-table :data="temp.headers" border size="small">
              <el-table-column label="启用" width="70" align="center">
                <template #default="scope">
                  <el-checkbox v-model="scope.row.enabled" />
                </template>
              </el-table-column>
              <el-table-column label="Key" min-width="180">
                <template #default="scope">
                  <el-input v-model="scope.row.key" placeholder="Content-Type" />
                </template>
              </el-table-column>
              <el-table-column label="Value" min-width="220">
                <template #default="scope">
                  <el-input v-model="scope.row.value" placeholder="application/json" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="90" align="center">
                <template #default="scope">
                  <el-button size="small" type="danger" @click="removeHeaderRow(scope.$index)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane :label="bodyTabLabel" name="body">
            <el-alert
              :title="methodBodyTip"
              :type="methodSupportsBody ? 'info' : 'warning'"
              :closable="false"
              class="section-gap"
            />
            <div class="body-mode-bar">
              <el-radio-group v-model="temp.body_mode" :disabled="!methodSupportsBody">
                <el-radio-button label="none">none</el-radio-button>
                <el-radio-button label="form-data">form-data</el-radio-button>
                <el-radio-button label="x-www-form-urlencoded">x-www-form-urlencoded</el-radio-button>
                <el-radio-button label="raw">raw</el-radio-button>
                <el-radio-button label="binary">binary</el-radio-button>
                <el-radio-button label="graphql">GraphQL</el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="methodSupportsBody && temp.body_mode === 'form-data'">
              <div class="request-editor-toolbar">
                <span>当前支持文本字段；文件字段后续接入上传存储后再启用</span>
                <el-button size="small" @click="addFormDataRow">添加字段</el-button>
              </div>
              <el-table :data="temp.form_data" border size="small">
                <el-table-column label="启用" width="70" align="center">
                  <template #default="scope">
                    <el-checkbox v-model="scope.row.enabled" />
                  </template>
                </el-table-column>
                <el-table-column label="Key" min-width="150">
                  <template #default="scope">
                    <el-input v-model="scope.row.key" placeholder="key" />
                  </template>
                </el-table-column>
                <el-table-column label="Type" width="110">
                  <template #default="scope">
                    <el-select v-model="scope.row.type">
                      <el-option label="Text" value="text" />
                      <el-option label="File（未启用）" value="file" disabled />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="Value" min-width="180">
                  <template #default="scope">
                    <el-input v-model="scope.row.value" placeholder="value" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="90" align="center">
                  <template #default="scope">
                    <el-button size="small" type="danger" @click="removeFormDataRow(scope.$index)">移除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            <div v-else-if="methodSupportsBody && temp.body_mode === 'x-www-form-urlencoded'">
              <div class="request-editor-toolbar">
                <span>按表单编码发送到后端</span>
                <el-button size="small" @click="addUrlencodedRow">添加字段</el-button>
              </div>
              <el-table :data="temp.urlencoded_data" border size="small">
                <el-table-column label="启用" width="70" align="center">
                  <template #default="scope">
                    <el-checkbox v-model="scope.row.enabled" />
                  </template>
                </el-table-column>
                <el-table-column label="Key" min-width="160">
                  <template #default="scope">
                    <el-input v-model="scope.row.key" placeholder="key" />
                  </template>
                </el-table-column>
                <el-table-column label="Value" min-width="180">
                  <template #default="scope">
                    <el-input v-model="scope.row.value" placeholder="value" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="90" align="center">
                  <template #default="scope">
                    <el-button size="small" type="danger" @click="removeUrlencodedRow(scope.$index)">移除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
            <div v-else-if="methodSupportsBody && temp.body_mode === 'raw'">
              <el-form-item label="Raw 类型">
                <el-select v-model="temp.body_raw_type" style="width: 180px">
                  <el-option label="JSON" value="json" />
                  <el-option label="Text" value="text" />
                  <el-option label="XML" value="xml" />
                  <el-option label="HTML" value="html" />
                </el-select>
              </el-form-item>
              <el-form-item label="Raw 内容" prop="body_text">
                <el-input v-model="temp.body_text" type="textarea" :rows="7" placeholder="{}" />
              </el-form-item>
            </div>
            <div v-else-if="methodSupportsBody && temp.body_mode === 'binary'">
              <el-alert
                title="Binary 当前支持填写 base64 或普通文本内容；暂不做本地文件上传"
                type="warning"
                :closable="false"
                class="section-gap"
              />
              <el-form-item label="文件名">
                <el-input v-model="temp.binary_filename" placeholder="payload.bin" />
              </el-form-item>
              <el-form-item label="内容">
                <el-input v-model="temp.binary_content" type="textarea" :rows="6" placeholder="base64 或文本内容" />
              </el-form-item>
              <el-checkbox v-model="temp.binary_is_base64">内容是 base64</el-checkbox>
            </div>
            <div v-else-if="methodSupportsBody && temp.body_mode === 'graphql'">
              <el-form-item label="Query">
                <el-input v-model="temp.graphql_query" type="textarea" :rows="5" placeholder="query { viewer { id } }" />
              </el-form-item>
              <el-form-item label="Variables JSON" prop="graphql_variables_text">
                <el-input v-model="temp.graphql_variables_text" type="textarea" :rows="4" placeholder="{}" />
              </el-form-item>
            </div>
            <el-empty v-else-if="methodSupportsBody" description="none：不发送请求体" :image-size="72" />
          </el-tab-pane>
          <el-tab-pane label="Assertions" name="assertions">
            <el-form-item label="断言 JSON" prop="assertions_text">
              <el-input
                v-model="temp.assertions_text"
                type="textarea"
                :rows="5"
                placeholder='[{"type": "status_code", "expected": 200}]'
              />
            </el-form-item>
          </el-tab-pane>
        </el-tabs>
        <el-row>
          <el-col :span="12">
            <el-form-item label="评审状态">
              <el-select v-model="temp.review_status" style="width: 100%">
                <el-option label="DRAFT" value="DRAFT" />
                <el-option label="IN_REVIEW" value="IN_REVIEW" />
                <el-option label="APPROVED" value="APPROVED" />
                <el-option label="REJECTED" value="REJECTED" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="当前版本">
              <el-input v-model="temp.version_no" disabled />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="评审备注">
          <el-input v-model="temp.review_note" type="textarea" :rows="3" placeholder="例如：通过接口自检，待计划回归；或填写拒绝原因" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：smoke、core">
            <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveData">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="执行接口用例" width="520px">
      <el-form label-position="top" :model="runForm">
        <el-form-item label="执行环境">
          <el-select v-model="runForm.environment_id" clearable placeholder="不指定环境，使用用例原始配置" style="width: 100%">
            <el-option v-for="item in runEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）">
          <el-input-number v-model="runForm.timeout_seconds" :min="1" :max="600" style="width: 100%" />
        </el-form-item>
        <el-form-item label="失败后自动重试">
          <el-input-number v-model="runForm.max_retries" :min="0" :max="3" style="width: 100%" />
        </el-form-item>
      </el-form>
      <div v-if="precheckResult" class="precheck-panel">
        <div class="precheck-summary" :class="{ invalid: !precheckResult.is_valid }">{{ precheckResult.summary }}</div>
        <div v-if="precheckResult.missing_variables?.length" class="precheck-tags">
          <el-tag v-for="item in precheckResult.missing_variables" :key="item" size="small" type="danger">{{ item }}</el-tag>
        </div>
        <el-table
          v-if="precheckResult.issues?.length"
          :data="precheckResult.issues.slice(0, 20)"
          size="small"
          border
          class="precheck-table"
        >
          <el-table-column label="范围" prop="scope" min-width="140" show-overflow-tooltip />
          <el-table-column label="字段" prop="field" min-width="140" show-overflow-tooltip />
          <el-table-column label="缺失变量" min-width="160" show-overflow-tooltip>
            <template #default="scope">
              {{ scope.row.missing_variables.join(', ') }}
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="handlePrecheck">执行前校验</el-button>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRun">确认执行</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'

const list = ref([])
const projects = ref([])
const environments = ref([])
const listLoading = ref(true)
const dialogVisible = ref(false)
const runDialogVisible = ref(false)
const isEditing = ref(false)
const editingCaseId = ref(undefined)
const dataFormRef = ref(null)
const precheckResult = ref(null)
const requestTab = ref('params')
const curlImportVisible = ref(false)
const curlImportText = ref('')
const { canAdmin, canTest } = usePermissions()
const methodOptions = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
const bodyModes = new Set(['none', 'form-data', 'x-www-form-urlencoded', 'raw', 'binary', 'graphql'])
const methodProfiles = {
  GET: { supportsBody: false, defaultBodyMode: 'none', tip: 'GET 主要通过 Params 传参；保存时不会发送 Body。' },
  POST: { supportsBody: true, defaultBodyMode: 'raw', tip: 'POST 支持 Body，可选择 form-data、x-www-form-urlencoded、raw、binary 或 GraphQL。' },
  PUT: { supportsBody: true, defaultBodyMode: 'raw', tip: 'PUT 通常发送完整资源 Body，默认使用 raw JSON。' },
  PATCH: { supportsBody: true, defaultBodyMode: 'raw', tip: 'PATCH 通常发送局部更新 Body，默认使用 raw JSON。' },
  DELETE: { supportsBody: true, defaultBodyMode: 'none', tip: 'DELETE 通常不带 Body；如接口需要，可手动选择 Body 类型。' },
  HEAD: { supportsBody: false, defaultBodyMode: 'none', tip: 'HEAD 只获取响应头；保存时不会发送 Body。' },
  OPTIONS: { supportsBody: false, defaultBodyMode: 'none', tip: 'OPTIONS 通常用于能力探测；保存时不会发送 Body。' }
}

const filters = reactive({
  projectId: undefined,
  method: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(10)

const temp = reactive({
  project_id: undefined,
  name: '',
  folder_path: '',
  method: 'GET',
  path: '',
  tags_json: [],
  review_status: 'DRAFT',
  version_no: '1.0.0',
  review_note: '',
  query_params: [],
  headers: [{ enabled: true, key: 'accept', value: 'application/json' }],
  body_mode: 'none',
  body_raw_type: 'json',
  body_text: '',
  form_data: [],
  urlencoded_data: [],
  binary_filename: '',
  binary_content: '',
  binary_is_base64: true,
  graphql_query: '',
  graphql_variables_text: '{}',
  assertions_text: '[\n  { "type": "status_code", "expected": 200 }\n]',
  priority: 'P2',
  status: 'ACTIVE',
  expected_status: 200
})

const runForm = reactive({
  case_id: undefined,
  project_id: undefined,
  environment_id: undefined,
  timeout_seconds: 60,
  max_retries: 0
})

const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }],
  path: [{ required: true, message: '路径必填', trigger: 'blur' }],
  body_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value && methodSupportsBody.value && temp.body_mode === 'raw' && temp.body_raw_type === 'json') {
          JSON.parse(value)
        }
        callback()
      } catch (e) {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }],
  graphql_variables_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value && methodSupportsBody.value && temp.body_mode === 'graphql') JSON.parse(value)
        callback()
      } catch (e) {
        callback(new Error('GraphQL Variables 必须是 JSON'))
      }
    }, trigger: 'blur'
  }],
  assertions_text: [{
    validator: (rule, value, callback) => {
      try {
        if (value) {
          const parsed = JSON.parse(value)
          if (!Array.isArray(parsed)) {
            callback(new Error('断言必须是 JSON 数组'))
            return
          }
        }
        callback()
      } catch (e) {
        callback(new Error('JSON 格式错误'))
      }
    }, trigger: 'blur'
  }]
}

const projectMap = computed(() => {
  const map = {}
  projects.value.forEach(p => {
    map[p.id] = p.name
  })
  return map
})

const tagOptions = computed(() => {
  const tags = new Set()
  list.value.forEach((item) => (item.tags_json || []).forEach((tag) => tags.add(tag)))
  return Array.from(tags).sort((a, b) => a.localeCompare(b, 'zh-CN'))
})

const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))

const currentMethodProfile = computed(() => methodProfiles[temp.method] || methodProfiles.GET)
const methodSupportsBody = computed(() => currentMethodProfile.value.supportsBody)
const bodyTabLabel = computed(() => (methodSupportsBody.value ? 'Body' : 'Body（不适用）'))
const methodBodyTip = computed(() => currentMethodProfile.value.tip)

const methodType = (method) => {
  const map = {
    GET: '',
    POST: 'success',
    PUT: 'warning',
    PATCH: 'warning',
    DELETE: 'danger',
    HEAD: 'info',
    OPTIONS: 'info'
  }
  return map[method] || 'info'
}

const parseQueryParams = (path) => {
  const query = String(path || '').split('?')[1] || ''
  if (!query) return []
  return query
    .split('&')
    .filter(Boolean)
    .map((item) => {
      const [key, ...rest] = item.split('=')
      return {
        enabled: true,
        key: decodeURIComponent(key || ''),
        value: decodeURIComponent(rest.join('=') || '')
      }
    })
}

const pathWithoutQuery = (path) => String(path || '').split('?')[0] || ''

const buildQueryString = () =>
  temp.query_params
    .filter((item) => item.enabled && String(item.key || '').trim())
    .map((item) => `${encodeURIComponent(String(item.key).trim())}=${encodeURIComponent(String(item.value || ''))}`)
    .join('&')

const syncPathFromParams = () => {
  const basePath = pathWithoutQuery(temp.path) || '/'
  const query = buildQueryString()
  temp.path = query ? `${basePath}?${query}` : basePath
}

const hydrateParamsFromPath = () => {
  temp.query_params = parseQueryParams(temp.path)
}

const addQueryParam = () => {
  temp.query_params.push({ enabled: true, key: '', value: '' })
}

const removeQueryParam = (index) => {
  temp.query_params.splice(index, 1)
  syncPathFromParams()
}

const hydrateHeaders = (headersJson) => {
  const entries = Object.entries(headersJson || {})
  temp.headers = entries.length
    ? entries.map(([key, value]) => ({ enabled: true, key, value: String(value ?? '') }))
    : [{ enabled: true, key: 'accept', value: 'application/json' }]
}

const addHeaderRow = () => {
  temp.headers.push({ enabled: true, key: '', value: '' })
}

const removeHeaderRow = (index) => {
  temp.headers.splice(index, 1)
}

const buildHeadersJson = () => {
  const headers = {}
  temp.headers
    .filter((row) => row.enabled && String(row.key || '').trim())
    .forEach((row) => {
      headers[String(row.key).trim()] = row.value ?? ''
    })
  return Object.keys(headers).length ? headers : null
}

const findHeaderRow = (name) => temp.headers.find(
  (row) => String(row.key || '').trim().toLowerCase() === name.toLowerCase()
)

const setHeaderValue = (name, value) => {
  const existing = findHeaderRow(name)
  if (existing) {
    existing.enabled = true
    existing.value = value
    return
  }
  temp.headers.push({ enabled: true, key: name, value })
}

const removeHeader = (name) => {
  const index = temp.headers.findIndex((row) => String(row.key || '').trim().toLowerCase() === name.toLowerCase())
  if (index >= 0) temp.headers.splice(index, 1)
}

const syncContentTypeForBodyMode = () => {
  if (!methodSupportsBody.value || temp.body_mode === 'none') {
    removeHeader('Content-Type')
    return
  }
  if (temp.body_mode === 'raw') {
    if (temp.body_raw_type === 'json') setHeaderValue('Content-Type', 'application/json')
    else if (temp.body_raw_type === 'xml') setHeaderValue('Content-Type', 'application/xml')
    else if (temp.body_raw_type === 'html') setHeaderValue('Content-Type', 'text/html')
    else setHeaderValue('Content-Type', 'text/plain')
    return
  }
  if (temp.body_mode === 'x-www-form-urlencoded') {
    setHeaderValue('Content-Type', 'application/x-www-form-urlencoded')
    return
  }
  if (temp.body_mode === 'graphql') {
    setHeaderValue('Content-Type', 'application/json')
    return
  }
  if (temp.body_mode === 'form-data') {
    // multipart boundary is generated by the HTTP client; a manual header would be wrong.
    removeHeader('Content-Type')
  }
}

const resetBodyFields = (mode = 'none') => {
  temp.body_mode = mode
  temp.body_raw_type = 'json'
  temp.body_text = mode === 'raw' ? '{}' : ''
  temp.form_data = []
  temp.urlencoded_data = []
  temp.binary_filename = ''
  temp.binary_content = ''
  temp.binary_is_base64 = true
  temp.graphql_query = ''
  temp.graphql_variables_text = '{}'
}

const addFormDataRow = () => {
  temp.form_data.push({ enabled: true, key: '', value: '', type: 'text' })
}

const removeFormDataRow = (index) => {
  temp.form_data.splice(index, 1)
}

const addUrlencodedRow = () => {
  temp.urlencoded_data.push({ enabled: true, key: '', value: '' })
}

const removeUrlencodedRow = (index) => {
  temp.urlencoded_data.splice(index, 1)
}

const normalizeRows = (rows, withType = false) => (Array.isArray(rows) ? rows : []).map((row) => ({
  enabled: row.enabled !== false,
  key: row.key || '',
  value: row.value ?? '',
  ...(withType ? { type: row.type || 'text' } : {})
}))

const tokenizeCurl = (input) => {
  const normalized = String(input || '').replace(/\\\r?\n/g, ' ')
  const tokens = []
  let current = ''
  let quote = ''
  let escaping = false
  for (const char of normalized) {
    if (escaping) {
      current += char
      escaping = false
      continue
    }
    if (char === '\\') {
      escaping = true
      continue
    }
    if (quote) {
      if (char === quote) quote = ''
      else current += char
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (/\s/.test(char)) {
      if (current) {
        tokens.push(current)
        current = ''
      }
      continue
    }
    current += char
  }
  if (current) tokens.push(current)
  return tokens
}

const splitHeader = (header) => {
  const index = String(header || '').indexOf(':')
  if (index < 0) return null
  const key = header.slice(0, index).trim()
  if (!key) return null
  return { enabled: true, key, value: header.slice(index + 1).trim() }
}

const contentTypeFromHeaders = (headers) => {
  const row = headers.find((item) => item.key.toLowerCase() === 'content-type')
  return String(row?.value || '').toLowerCase()
}

const appendQueryRows = (rows, queryText) => {
  const query = String(queryText || '').replace(/^\?/, '')
  if (!query) return
  new URLSearchParams(query).forEach((value, key) => {
    rows.push({ enabled: true, key, value })
  })
}

const applyCurlImport = () => {
  try {
    const tokens = tokenizeCurl(curlImportText.value)
    if (!tokens.length || tokens[0] !== 'curl') {
      ElMessage.error('请粘贴以 curl 开头的命令')
      return
    }
    let method = ''
    let url = ''
    const headers = []
    const dataParts = []
    const formRows = []
    const urlencodedRows = []
    let useGetWithData = false

    for (let index = 1; index < tokens.length; index += 1) {
      const token = tokens[index]
      const next = () => tokens[++index] || ''
      if (token === '-X' || token === '--request') method = next().toUpperCase()
      else if (token.startsWith('-X') && token.length > 2) method = token.slice(2).toUpperCase()
      else if (token === '-H' || token === '--header') {
        const parsed = splitHeader(next())
        if (parsed) headers.push(parsed)
      } else if (token.startsWith('-H') && token.length > 2) {
        const parsed = splitHeader(token.slice(2))
        if (parsed) headers.push(parsed)
      } else if (['-d', '--data', '--data-raw', '--data-binary', '--data-ascii'].includes(token)) {
        dataParts.push(next())
      } else if (token.startsWith('--data=') || token.startsWith('--data-raw=')) {
        dataParts.push(token.split('=').slice(1).join('='))
      } else if (token === '--data-urlencode') {
        const pair = next()
        const [key, ...rest] = pair.split('=')
        urlencodedRows.push({ enabled: true, key, value: rest.join('=') })
      } else if (token === '-F' || token === '--form' || token === '--form-string') {
        const pair = next()
        const [key, ...rest] = pair.split('=')
        formRows.push({ enabled: true, key, value: rest.join('=').replace(/^@/, ''), type: pair.includes('=@') ? 'file' : 'text' })
      } else if (token === '-G' || token === '--get') {
        useGetWithData = true
      } else if (!token.startsWith('-') && !url) {
        url = token
      }
    }

    if (!url) {
      ElMessage.error('未识别到请求 URL')
      return
    }

    temp.method = method || (dataParts.length || formRows.length || urlencodedRows.length ? 'POST' : 'GET')
    temp.path = url
    temp.query_params = parseQueryParams(url)
    if (!temp.name) {
      try {
        const parsedUrl = new URL(url)
        temp.name = `${temp.method} ${parsedUrl.pathname || '/'}`
      } catch (error) {
        temp.name = `${temp.method} ${pathWithoutQuery(url) || '/'}`
      }
    }
    temp.headers = headers.length ? headers : [{ enabled: true, key: 'accept', value: 'application/json' }]

    if (useGetWithData && dataParts.length) {
      temp.method = 'GET'
      const rows = [...temp.query_params]
      dataParts.forEach((part) => appendQueryRows(rows, part))
      temp.query_params = rows
      syncPathFromParams()
      resetBodyFields('none')
    } else if (formRows.length) {
      temp.body_mode = 'form-data'
      temp.form_data = formRows
      temp.urlencoded_data = []
      temp.body_text = ''
    } else if (urlencodedRows.length || contentTypeFromHeaders(headers).includes('application/x-www-form-urlencoded')) {
      temp.body_mode = 'x-www-form-urlencoded'
      temp.urlencoded_data = urlencodedRows.length
        ? urlencodedRows
        : dataParts.join('&').split('&').filter(Boolean).map((pair) => {
          const [key, ...rest] = pair.split('=')
          return { enabled: true, key: decodeURIComponent(key || ''), value: decodeURIComponent(rest.join('=') || '') }
        })
      temp.form_data = []
      temp.body_text = ''
    } else if (dataParts.length) {
      temp.body_mode = 'raw'
      const contentType = contentTypeFromHeaders(headers)
      temp.body_raw_type = contentType.includes('xml') ? 'xml' : contentType.includes('html') ? 'html' : contentType.includes('text') ? 'text' : 'json'
      temp.body_text = dataParts.join('&')
    } else {
      applyMethodBodyProfile()
    }

    syncContentTypeForBodyMode()
    requestTab.value = temp.query_params.length ? 'params' : (methodSupportsBody.value ? 'body' : 'params')
    ElMessage.success('cURL 已解析并填充')
  } catch (error) {
    ElMessage.error(`cURL 解析失败：${error.message}`)
  }
}

const hydrateBody = (bodyJson) => {
  if (!bodyJson) {
    resetBodyFields('none')
    return
  }
  if (typeof bodyJson === 'object' && bodyModes.has(bodyJson.mode)) {
    resetBodyFields(bodyJson.mode)
    temp.body_raw_type = bodyJson.raw_type || 'json'
    temp.body_text = bodyJson.raw ?? ''
    temp.form_data = normalizeRows(bodyJson.form_data, true)
    temp.urlencoded_data = normalizeRows(bodyJson.urlencoded)
    temp.binary_filename = bodyJson.binary?.filename || ''
    temp.binary_content = bodyJson.binary?.content || bodyJson.binary?.content_base64 || ''
    temp.binary_is_base64 = bodyJson.binary?.encoding !== 'text'
    temp.graphql_query = bodyJson.graphql?.query || ''
    temp.graphql_variables_text = JSON.stringify(bodyJson.graphql?.variables || {}, null, 2)
    return
  }
  resetBodyFields('raw')
  temp.body_text = JSON.stringify(bodyJson, null, 2)
}

const buildBodyJson = () => {
  if (!methodSupportsBody.value || temp.body_mode === 'none') return null
  if (temp.body_mode === 'form-data') {
    return {
      mode: 'form-data',
      form_data: temp.form_data
        .filter((row) => row.enabled && String(row.key || '').trim())
        .map((row) => ({ enabled: true, key: row.key.trim(), value: row.value ?? '', type: row.type || 'text' }))
    }
  }
  if (temp.body_mode === 'x-www-form-urlencoded') {
    return {
      mode: 'x-www-form-urlencoded',
      urlencoded: temp.urlencoded_data
        .filter((row) => row.enabled && String(row.key || '').trim())
        .map((row) => ({ enabled: true, key: row.key.trim(), value: row.value ?? '' }))
    }
  }
  if (temp.body_mode === 'raw') {
    return {
      mode: 'raw',
      raw_type: temp.body_raw_type,
      raw: temp.body_text || ''
    }
  }
  if (temp.body_mode === 'binary') {
    return {
      mode: 'binary',
      binary: {
        filename: temp.binary_filename || null,
        content: temp.binary_content || '',
        encoding: temp.binary_is_base64 ? 'base64' : 'text'
      }
    }
  }
  if (temp.body_mode === 'graphql') {
    return {
      mode: 'graphql',
      graphql: {
        query: temp.graphql_query || '',
        variables: temp.graphql_variables_text ? JSON.parse(temp.graphql_variables_text) : {}
      }
    }
  }
  return null
}

const applyMethodBodyProfile = () => {
  const profile = currentMethodProfile.value
  if (!profile.supportsBody) {
    resetBodyFields('none')
  } else if (temp.body_mode === 'none' && profile.defaultBodyMode !== 'none') {
    resetBodyFields(profile.defaultBodyMode)
  }
  syncContentTypeForBodyMode()
}

const getList = async () => {
  listLoading.value = true
  try {
    const [caseData, projectData] = await Promise.all([
      api.get('/api-cases'),
      api.get('/projects')
    ])
    list.value = caseData
    projects.value = projectData
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((c) => {
    if (filters.projectId && c.project_id !== filters.projectId) return false
    if (filters.method && c.method !== filters.method) return false
    if (!keyword) return true
    return (
      String(c.name || '').toLowerCase().includes(keyword) ||
      String(c.path || '').toLowerCase().includes(keyword)
    )
  })
})

const pagedList = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredList.value.slice(start, start + pageSize.value)
})

const handleCreate = () => {
  temp.project_id = projects.value.length > 0 ? projects.value[0].id : undefined
  temp.name = ''
  temp.folder_path = ''
  temp.method = 'GET'
  temp.path = ''
  temp.tags_json = []
  temp.review_status = 'DRAFT'
  temp.version_no = '1.0.0'
  temp.review_note = ''
  temp.query_params = []
  hydrateHeaders(null)
  resetBodyFields('none')
  temp.assertions_text = '[\n  { "type": "status_code", "expected": 200 }\n]'
  temp.priority = 'P2'
  temp.status = 'ACTIVE'
  temp.expected_status = 200
  requestTab.value = 'params'
  isEditing.value = false
  editingCaseId.value = undefined
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const handleSearch = () => {
  page.value = 1
}

const handleReset = () => {
  filters.projectId = undefined
  filters.method = ''
  filters.keyword = ''
  page.value = 1
}

const handleEdit = (row) => {
  temp.project_id = row.project_id
  temp.name = row.name
  temp.folder_path = row.folder_path || ''
  temp.method = row.method
  temp.path = row.path
  temp.tags_json = [...(row.tags_json || [])]
  temp.review_status = row.review_status || 'DRAFT'
  temp.version_no = row.version_no || '1.0.0'
  temp.review_note = row.review_note || ''
  temp.query_params = parseQueryParams(row.path)
  hydrateHeaders(row.headers_json)
  hydrateBody(row.body_json)
  applyMethodBodyProfile()
  temp.assertions_text = row.assertions_json ? JSON.stringify(row.assertions_json, null, 2) : '[\n  { "type": "status_code", "expected": 200 }\n]'
  temp.priority = row.priority
  temp.status = row.status
  temp.expected_status = row.expected_status
  requestTab.value = 'params'
  isEditing.value = true
  editingCaseId.value = row.id
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        const payload = {
          project_id: temp.project_id,
          name: temp.name,
          folder_path: temp.folder_path || null,
          method: temp.method,
          path: temp.path,
          tags_json: temp.tags_json.length ? temp.tags_json : null,
          review_status: temp.review_status,
          version_no: temp.version_no,
          review_note: temp.review_note || null,
          headers_json: buildHeadersJson(),
          body_json: buildBodyJson(),
          assertions_json: temp.assertions_text ? JSON.parse(temp.assertions_text) : null,
          priority: temp.priority,
          status: temp.status,
          expected_status: temp.expected_status
        }
        if (isEditing.value && editingCaseId.value) {
          await api.put(`/api-cases/${editingCaseId.value}`, payload)
        } else {
          await api.post('/api-cases', payload)
        }
        dialogVisible.value = false
        ElMessage.success(isEditing.value ? '更新成功' : '创建成功')
        getList()
      } catch (error) {
        ElMessage.error(error.message)
      }
    }
  })
}

const handleRun = async (row) => {
  runForm.case_id = row.id
  runForm.project_id = row.project_id
  runForm.environment_id = undefined
  runForm.timeout_seconds = 60
  runForm.max_retries = 0
  precheckResult.value = null
  try {
    environments.value = await api.get(`/environments?project_id=${row.project_id}`)
    runDialogVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitRun = async () => {
  try {
    const passed = await precheckRun()
    if (!passed) return
    await api.post(`/executions/api/${runForm.case_id}/run`, {
      environment_id: runForm.environment_id,
      timeout_seconds: runForm.timeout_seconds,
      max_retries: runForm.max_retries
    })
    runDialogVisible.value = false
    ElMessage.success('任务已投递')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const showPrecheckResult = async (result) => {
  precheckResult.value = result
  if (result.is_valid) {
    ElMessage.success('执行预检通过')
    return true
  }
  return false
}

const precheckRun = async () => {
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  const result = await api.get(`/executions/api/${runForm.case_id}/precheck${suffix}`)
  return showPrecheckResult(result)
}

const handlePrecheck = async () => {
  try {
    await precheckRun()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确认删除接口用例「${row.name}」？该用例将从测试计划中自动移除。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await api.delete(`/api-cases/${row.id}`)
    ElMessage.success('删除成功')
    getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

watch(() => temp.method, (method) => {
  applyMethodBodyProfile()
  if (!(methodProfiles[method] || methodProfiles.GET).supportsBody && requestTab.value === 'body') {
    requestTab.value = 'params'
  }
})

watch(() => temp.body_mode, (mode) => {
  if (mode === 'form-data' && temp.form_data.length === 0) addFormDataRow()
  if (mode === 'x-www-form-urlencoded' && temp.urlencoded_data.length === 0) addUrlencodedRow()
  if (mode === 'raw' && !temp.body_text) temp.body_text = '{}'
  if (mode === 'graphql' && !temp.graphql_variables_text) temp.graphql_variables_text = '{}'
  syncContentTypeForBodyMode()
})

watch(() => temp.body_raw_type, () => {
  syncContentTypeForBodyMode()
})

onMounted(() => {
  getList()
})
</script>

<style scoped>
.mobile-cards {
  display: none;
}

.precheck-panel {
  margin-top: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 12px;
  background: #f8fafc;
}

.precheck-summary {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.precheck-summary.invalid {
  color: var(--el-color-danger);
}

.precheck-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.precheck-table {
  margin-top: 12px;
}

.request-editor {
  margin-bottom: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 12px;
}

.request-editor-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.body-mode-bar {
  margin-bottom: 14px;
  overflow-x: auto;
  white-space: nowrap;
}

.curl-import-box {
  margin-bottom: 16px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 12px;
  background: #f8fafc;
}

.curl-import-panel {
  display: grid;
  gap: 10px;
}

.curl-import-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
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
