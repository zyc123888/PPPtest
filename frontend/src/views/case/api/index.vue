<template>
  <div class="app-page api-case-page">
    <PageHeader title="接口用例" subtitle="维护 API 用例并投递执行任务">
      <template #actions>
        <el-tooltip content="批量执行记录" placement="bottom">
          <el-button :icon="Tickets" aria-label="批量执行记录" @click="openBatchHistory" />
        </el-tooltip>
        <el-tooltip content="导入接口用例" placement="bottom">
          <el-button :icon="Upload" aria-label="导入接口用例" @click="openImportDialog" />
        </el-tooltip>
        <el-tooltip content="导出当前结果" placement="bottom">
          <el-button :icon="Download" aria-label="导出当前结果" @click="exportCurrentCases" />
        </el-tooltip>
        <el-tooltip content="刷新" placement="bottom">
          <el-button :icon="Refresh" aria-label="刷新接口用例" :loading="listLoading" @click="refreshAll" />
        </el-tooltip>
        <el-button v-if="canTest" type="primary" :icon="Plus" @click="handleCreate">新增接口用例</el-button>
      </template>
    </PageHeader>

    <section class="summary-strip section-gap" aria-label="接口用例概览">
      <div class="summary-item">
        <span class="summary-item__icon is-primary"><el-icon><DocumentCopy /></el-icon></span>
        <div>
          <span class="summary-item__label">用例总数</span>
          <strong>{{ stats.total }}</strong>
        </div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-success"><el-icon><CircleCheck /></el-icon></span>
        <div>
          <span class="summary-item__label">启用</span>
          <strong>{{ stats.active }}</strong>
        </div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-review"><el-icon><Finished /></el-icon></span>
        <div>
          <span class="summary-item__label">已评审</span>
          <strong>{{ stats.approved }}</strong>
        </div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-rate"><el-icon><TrendCharts /></el-icon></span>
        <div>
          <span class="summary-item__label">最近成功率</span>
          <strong>{{ recentSuccessRate }}</strong>
        </div>
      </div>
    </section>

    <div class="case-layout">
      <section class="workspace-panel case-layout__tree">
        <FolderTree
          v-model="selectedFolder"
          :folders="folderTree.folders"
          :total="folderTree.total"
          :ungrouped="folderTree.ungrouped"
          :can-rename="canTest"
          @rename="handleFolderRename"
          @refresh="loadFolders"
        />
      </section>

      <section class="workspace-panel case-layout__main">
        <div class="filter-bar">
          <el-button class="tree-drawer-trigger" :icon="Files" aria-label="打开用例目录" @click="treeDrawerVisible = true" />
          <el-select v-model="filters.projectId" clearable placeholder="全部项目" class="filter-control">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
          <el-select v-model="filters.method" clearable placeholder="全部方法" class="filter-control filter-control--short">
            <el-option v-for="item in methodOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-control filter-control--short">
            <el-option label="启用" value="ACTIVE" />
            <el-option label="停用" value="DISABLED" />
          </el-select>
          <el-select v-model="filters.priority" clearable placeholder="全部优先级" class="filter-control filter-control--short">
            <el-option v-for="item in ['P0', 'P1', 'P2']" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="filters.reviewStatus" clearable placeholder="全部评审" class="filter-control filter-control--short">
            <el-option label="草稿" value="DRAFT" />
            <el-option label="评审中" value="IN_REVIEW" />
            <el-option label="已通过" value="APPROVED" />
            <el-option label="已拒绝" value="REJECTED" />
          </el-select>
          <el-input v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索名称、分组或路径" class="filter-search" />
          <span class="filter-result">{{ total }} 条</span>
        </div>

        <div v-if="selectedRows.length" class="batch-bar">
          <span class="batch-bar__count">已选 {{ selectedRows.length }} 条</span>
          <el-button v-if="canTest" type="primary" size="small" :icon="VideoPlay" @click="openBatchRun">批量执行</el-button>
          <el-button v-if="canTest" size="small" :icon="EditPen" @click="openBatchEdit">批量修改</el-button>
          <el-button v-if="canAdmin" type="danger" plain size="small" :icon="Delete" @click="handleBatchDelete">批量删除</el-button>
          <el-button text size="small" @click="clearSelection">取消选择</el-button>
        </div>

        <el-table
          ref="tableRef"
          v-loading="listLoading"
          :data="list"
          class="case-table"
          row-key="id"
          @row-dblclick="(row) => openCaseDetail(row)"
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="42" :reserve-selection="true" />
          <el-table-column label="序号" width="60" align="center">
            <template #default="scope">{{ total - ((page - 1) * pageSize + scope.$index) }}</template>
          </el-table-column>
          <el-table-column label="用例" min-width="230">
            <template #default="scope">
              <button class="case-name" type="button" @click="openCaseDetail(scope.row)">{{ scope.row.name }}</button>
              <div class="case-meta">
                <span>{{ scope.row.folder_path || '未分组' }}</span>
                <span>v{{ scope.row.version_no }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="项目" width="120" show-overflow-tooltip>
            <template #default="scope">{{ projectMap[scope.row.project_id] || scope.row.project_id }}</template>
          </el-table-column>
          <el-table-column label="方法" width="86" align="center">
            <template #default="scope"><el-tag size="small" :type="methodType(scope.row.method)">{{ scope.row.method }}</el-tag></template>
          </el-table-column>
          <el-table-column label="路径" prop="path" min-width="200" show-overflow-tooltip />
          <el-table-column label="优先级" width="70" align="center">
            <template #default="scope"><el-tag size="small" :type="priorityTag(scope.row.priority)">{{ scope.row.priority }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="74" align="center">
            <template #default="scope"><el-tag size="small" :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(scope.row.status) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="评审" width="86" align="center">
            <template #default="scope">
              <el-tooltip :disabled="!scope.row.reviewed_by" placement="top" :content="reviewTooltip(scope.row)">
                <el-tag size="small" effect="plain" :type="reviewTag(scope.row.review_status)">{{ reviewText(scope.row.review_status) }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="最近执行" width="126">
            <template #default="scope">
              <div v-if="latestRunMap[scope.row.id]" class="last-run">
                <el-tag size="small" :type="executionStatusTag(latestRunMap[scope.row.id].status)">{{ executionStatusText(latestRunMap[scope.row.id].status) }}</el-tag>
                <span>{{ formatShortTime(latestRunMap[scope.row.id].created_at) }}</span>
              </div>
              <span v-else class="muted">未执行</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" align="right" width="164" fixed="right">
            <template #default="scope">
              <div class="row-actions">
                <el-tooltip content="查看详情" placement="top"><el-button circle size="small" :icon="View" aria-label="查看接口用例" @click="openCaseDetail(scope.row)" /></el-tooltip>
                <el-tooltip v-if="canTest" content="编辑" placement="top"><el-button circle size="small" :icon="Edit" aria-label="编辑接口用例" @click="handleEdit(scope.row)" /></el-tooltip>
                <el-tooltip v-if="canTest" content="立即执行" placement="top"><el-button circle size="small" type="primary" :icon="VideoPlay" aria-label="执行接口用例" @click="handleRun(scope.row)" /></el-tooltip>
                <el-tooltip v-if="canAdmin" content="删除" placement="top"><el-button circle size="small" type="danger" plain :icon="Delete" aria-label="删除接口用例" @click="handleDelete(scope.row)" /></el-tooltip>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <div class="mobile-cards">
          <article v-for="(item, index) in list" :key="item.id" class="mobile-case">
            <div class="mobile-case__title">
              <span class="case-sequence">#{{ total - ((page - 1) * pageSize + index) }}</span>
              <button class="case-name" type="button" @click="openCaseDetail(item)">{{ item.name }}</button>
            </div>
            <div class="mobile-case__tags">
              <el-tag size="small" :type="methodType(item.method)">{{ item.method }}</el-tag>
              <el-tag size="small" :type="priorityTag(item.priority)">{{ item.priority }}</el-tag>
              <el-tag size="small" :type="item.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(item.status) }}</el-tag>
              <el-tag size="small" effect="plain" :type="reviewTag(item.review_status)">{{ reviewText(item.review_status) }}</el-tag>
            </div>
            <div class="mobile-case__url">{{ item.method }} {{ item.path }}</div>
            <div class="row-actions">
              <el-button size="small" :icon="View" @click="openCaseDetail(item)">详情</el-button>
              <el-button v-if="canTest" size="small" type="primary" :icon="VideoPlay" @click="handleRun(item)">执行</el-button>
            </div>
          </article>
        </div>

        <div class="table-pagination">
          <el-pagination
            :current-page="page"
            :page-size="pageSize"
            layout="total, sizes, prev, pager, next"
            :total="total"
            :page-sizes="[10, 20, 50]"
            @update:current-page="page = $event"
            @update:page-size="handlePageSizeChange"
          />
        </div>
      </section>
    </div>

    <el-drawer v-model="treeDrawerVisible" title="用例目录" direction="ltr" size="min(300px, 86vw)">
      <FolderTree
        :model-value="selectedFolder"
        :folders="folderTree.folders"
        :total="folderTree.total"
        :ungrouped="folderTree.ungrouped"
        :can-rename="canTest"
        @update:model-value="(value) => { selectedFolder = value; treeDrawerVisible = false }"
        @rename="handleFolderRename"
        @refresh="loadFolders"
      />
    </el-drawer>

    <BatchRunDialog
      v-model="batchRunVisible"
      title="批量执行接口用例"
      :environments="batchEnvironments"
      :count="selectedRows.length"
      :submitting="batchSubmitting"
      @submit="submitBatchRun"
    />

    <BatchRunDrawer
      v-model="batchDrawerVisible"
      case-type="API"
      :batch-id="activeBatchId"
      :project-id="filters.projectId || null"
      :case-name-map="caseNameCache"
      :can-test="canTest"
      @open-run="handleOpenRunFromBatch"
      @finished="getList"
    />

    <el-dialog v-model="batchEditVisible" title="批量修改用例" width="520px">
      <p class="batch-edit-hint">将对已选的 <strong>{{ selectedRows.length }}</strong> 条用例应用以下修改；留空的字段不会变更。</p>
      <el-form label-position="top" :model="batchEditForm">
        <el-form-item label="移动到目录">
          <el-tree-select
            v-model="batchEditForm.folder_path"
            :data="folderSelectOptions"
            check-strictly
            filterable
            allow-create
            default-first-option
            clearable
            placeholder="选择已有目录或输入新路径"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="优先级">
          <el-select v-model="batchEditForm.priority" clearable placeholder="不修改" style="width: 100%">
            <el-option v-for="item in ['P0', 'P1', 'P2']" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例状态">
          <el-select v-model="batchEditForm.status" clearable placeholder="不修改" style="width: 100%">
            <el-option label="启用" value="ACTIVE" />
            <el-option label="停用" value="DISABLED" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchEditSubmitting" @click="submitBatchEdit">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑接口用例' : '新增接口用例'" width="1120px" class="api-editor-dialog">
      <el-form
        ref="dataFormRef"
        :model="temp"
        :rules="rules"
        label-position="top"
      >
        <div class="api-editor-shell">
          <div class="api-editor-intro section-gap">
            <div>
              <div class="api-editor-title">请求构建器</div>
              <div class="api-editor-subtitle">优先配置 Method、Path、Auth、Body 和即时调试，元数据收纳到下方折叠区。</div>
            </div>
            <el-button size="small" @click="curlImportVisible = !curlImportVisible">
              {{ curlImportVisible ? '收起 cURL 导入' : '从 cURL 粘贴导入' }}
            </el-button>
          </div>

          <div class="curl-import-box">
            <div class="request-editor-toolbar">
              <span>已有 cURL 命令时，可直接粘贴导入接口信息</span>
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

          <div class="request-composer section-gap">
            <div class="request-composer-head">
              <div>
                <div class="panel-title">Request</div>
                <div class="panel-subtitle">先定义请求，再切换到 Params / Headers / Auth / Body 细化。</div>
              </div>
              <el-form-item label="预期状态码" prop="expected_status" class="expected-status-item">
                <el-input-number v-model="temp.expected_status" :min="100" :max="599" style="width: 160px" />
              </el-form-item>
            </div>

            <el-form-item label="用例名称" prop="name">
              <el-input v-model="temp.name" placeholder="请输入用例名称，例如：登录接口冒烟检查" />
            </el-form-item>
            <el-form-item prop="path" class="request-bar">
              <div class="request-bar-row">
                <el-select v-model="temp.method" class="request-bar-method" placeholder="Method">
                  <el-option v-for="item in methodOptions" :key="item" :value="item" :label="item" />
                </el-select>
                <el-input v-model="temp.path" placeholder="/api/v1/..." class="request-bar-path" />
              </div>
            </el-form-item>
          </div>

          <div class="editor-main-grid section-gap">
            <div class="editor-left">
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
                <el-tab-pane label="Auth" name="auth">
                  <el-form-item label="认证类型">
                    <el-select v-model="temp.auth_type" style="width: 240px">
                      <el-option label="No Auth" value="none" />
                      <el-option label="Bearer Token" value="bearer" />
                      <el-option label="Basic Auth" value="basic" />
                      <el-option label="API Key" value="api_key" />
                    </el-select>
                  </el-form-item>
                  <el-form-item v-if="temp.auth_type === 'bearer'" label="Token">
                    <el-input v-model="temp.auth_token" placeholder="{{token}} 或实际 token" show-password />
                  </el-form-item>
                  <el-row v-if="temp.auth_type === 'basic'" :gutter="12">
                    <el-col :span="12">
                      <el-form-item label="Username">
                        <el-input v-model="temp.auth_username" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="12">
                      <el-form-item label="Password">
                        <el-input v-model="temp.auth_password" show-password />
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-row v-if="temp.auth_type === 'api_key'" :gutter="12">
                    <el-col :span="8">
                      <el-form-item label="Key">
                        <el-input v-model="temp.auth_api_key_name" placeholder="x-api-key" />
                      </el-form-item>
                    </el-col>
                    <el-col :span="10">
                      <el-form-item label="Value">
                        <el-input v-model="temp.auth_api_key_value" show-password />
                      </el-form-item>
                    </el-col>
                    <el-col :span="6">
                      <el-form-item label="Add To">
                        <el-select v-model="temp.auth_api_key_in">
                          <el-option label="Header" value="header" />
                          <el-option label="Query Params" value="query" />
                        </el-select>
                      </el-form-item>
                    </el-col>
                  </el-row>
                  <el-alert title="Auth 会在保存和调试时自动合并到 Headers 或 Params，避免手写 Authorization。" type="info" :closable="false" />
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
                      <el-input v-model="temp.body_text" type="textarea" :rows="9" placeholder="{}" />
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
                      :rows="7"
                      placeholder='[{"type": "status_code", "expected": 200}]'
                    />
                  </el-form-item>
                </el-tab-pane>
              </el-tabs>
            </div>

            <div class="editor-right">
              <div class="debug-panel">
                <div class="debug-header">
                  <div class="debug-title">
                    <div class="debug-title-main">即时调试</div>
                    <div class="debug-title-sub">不会保存用例，也不会创建执行记录</div>
                  </div>
                  <div class="debug-controls">
                    <el-select v-model="temp.debug_environment_id" clearable size="small" placeholder="调试环境" class="debug-env-select">
                      <el-option v-for="item in debugEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
                    </el-select>
                    <el-input-number v-model="temp.debug_timeout_seconds" size="small" :min="1" :max="300" controls-position="right" class="debug-timeout" />
                    <el-button size="small" type="primary" :loading="debugLoading" class="debug-send" @click="sendDebugRequest">Send</el-button>
                  </div>
                </div>
                <div v-if="debugResponse" class="debug-response">
                  <div class="debug-metrics">
                    <el-tag :type="debugResponse.response.status_code < 400 ? 'success' : 'danger'">
                      {{ debugResponse.response.status_code }}
                    </el-tag>
                    <span>{{ debugResponse.duration_ms }} ms</span>
                    <span>{{ debugResponse.response.size }} bytes</span>
                    <span>{{ debugResponse.request.method }} {{ debugResponse.request.url }}</span>
                  </div>
                  <el-tabs v-model="debugResponseTab">
                    <el-tab-pane label="Body" name="body">
                      <pre class="response-pre">{{ formatDebugBody(debugResponse.response.body) }}</pre>
                    </el-tab-pane>
                    <el-tab-pane label="Headers" name="headers">
                      <pre class="response-pre">{{ JSON.stringify(debugResponse.response.headers, null, 2) }}</pre>
                    </el-tab-pane>
                    <el-tab-pane label="Request" name="request">
                      <pre class="response-pre">{{ JSON.stringify(debugResponse.request, null, 2) }}</pre>
                    </el-tab-pane>
                  </el-tabs>
                </div>
                <div v-else class="debug-empty">
                  <div class="debug-empty-title">调试结果会显示在这里</div>
                  <div class="debug-empty-text">先选择调试环境和超时，再点击 Send 查看响应、Headers 和实际请求。</div>
                </div>
              </div>
            </div>
          </div>

          <el-collapse v-model="editorMetaPanels" class="editor-meta-collapse">
            <el-collapse-item name="meta">
              <template #title>
                <div class="meta-collapse-title">
                  <span>用例元信息</span>
                  <span class="meta-collapse-subtitle">项目、目录、优先级、版本、评审和标签等非核心请求配置</span>
                </div>
              </template>
              <div class="meta-grid">
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
                <el-form-item label="目录/分组">
                  <el-tree-select
                    v-model="temp.folder_path"
                    :data="folderSelectOptions"
                    check-strictly
                    filterable
                    allow-create
                    default-first-option
                    clearable
                    placeholder="选择已有目录或输入新路径，如：登录模块/健康检查"
                    style="width: 100%"
                  />
                </el-form-item>
                <el-form-item label="优先级" prop="priority">
                  <el-select v-model="temp.priority" style="width: 100%">
                    <el-option label="P0" value="P0" />
                    <el-option label="P1" value="P1" />
                    <el-option label="P2" value="P2" />
                  </el-select>
                </el-form-item>
                <el-form-item label="状态" prop="status">
                  <el-select v-model="temp.status" style="width: 100%">
                    <el-option label="ACTIVE" value="ACTIVE" />
                    <el-option label="DISABLED" value="DISABLED" />
                  </el-select>
                </el-form-item>
                <el-form-item label="评审状态（只读）">
                  <div class="review-readonly">
                    <el-tag effect="plain" :type="reviewTag(temp.review_status)">{{ reviewText(temp.review_status) }}</el-tag>
                    <span>评审在详情页进行；内容变更会自动重置为草稿</span>
                  </div>
                </el-form-item>
                <el-form-item label="当前版本">
                  <el-input v-model="temp.version_no" disabled />
                </el-form-item>
                <div v-if="temp.review_note" class="meta-grid-span-2">
                  <el-form-item label="评审意见（只读）">
                    <p class="review-note-readonly">{{ temp.review_note }}</p>
                  </el-form-item>
                </div>
                <div class="meta-grid-span-2">
                  <el-form-item label="标签">
                    <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：smoke、core">
                      <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
                    </el-select>
                  </el-form-item>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>
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

    <el-drawer v-model="detailVisible" :title="currentCase ? currentCase.name : '用例详情'" size="min(720px, 96vw)" @closed="stopPolling">
      <div v-if="currentCase" class="case-detail">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="定义" name="definition">
            <div class="detail-section">
              <h4 class="drawer-title">基本信息</h4>
              <dl class="definition-list">
                <div><dt>请求</dt><dd><el-tag size="small" :type="methodType(currentCase.method)">{{ currentCase.method }}</el-tag> {{ currentCase.path }}</dd></div>
                <div><dt>项目</dt><dd>{{ projectMap[currentCase.project_id] || currentCase.project_id }}</dd></div>
                <div><dt>目录</dt><dd>{{ currentCase.folder_path || '未分组' }}</dd></div>
                <div><dt>优先级</dt><dd><el-tag size="small" :type="priorityTag(currentCase.priority)">{{ currentCase.priority }}</el-tag></dd></div>
                <div><dt>状态</dt><dd><el-tag size="small" :type="currentCase.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(currentCase.status) }}</el-tag></dd></div>
                <div><dt>预期状态码</dt><dd>{{ currentCase.expected_status }}</dd></div>
                <div><dt>版本</dt><dd>v{{ currentCase.version_no }}</dd></div>
              </dl>
              <div class="detail-actions">
                <el-button v-if="canTest" :icon="Edit" @click="handleEdit(currentCase)">编辑</el-button>
                <el-button v-if="canTest" type="primary" :icon="VideoPlay" @click="handleRun(currentCase)">立即执行</el-button>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane label="评审" name="review">
            <ReviewPanel
              :case-data="currentCase"
              case-type="API"
              :can-test="canTest"
              :current-user-id="currentUserId"
              @changed="refreshCurrentCase"
            />
          </el-tab-pane>
          <el-tab-pane label="执行记录" name="runs">
            <div class="detail-section">
              <el-table :data="caseRuns" size="small" @row-click="selectRun">
                <el-table-column label="状态" width="96">
                  <template #default="scope"><el-tag size="small" :type="executionStatusTag(scope.row.status)">{{ executionStatusText(scope.row.status) }}</el-tag></template>
                </el-table-column>
                <el-table-column label="时间" min-width="150">
                  <template #default="scope">{{ formatShortTime(scope.row.created_at) }}</template>
                </el-table-column>
                <el-table-column label="耗时" width="90">
                  <template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template>
                </el-table-column>
              </el-table>
              <div v-if="currentRun" class="run-detail">
                <h4 class="drawer-title">执行详情</h4>
                <div class="run-technical">
                  <div class="run-technical__block">
                    <span class="run-technical__label">响应</span>
                    <pre>{{ formatDebugBody(currentRun.response_payload) || '（无响应内容）' }}</pre>
                  </div>
                  <div v-if="currentRun.stderr" class="run-technical__block">
                    <span class="run-technical__label">错误输出</span>
                    <pre>{{ currentRun.stderr }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <el-dialog v-model="importVisible" title="导入接口用例" width="520px">
      <el-alert type="info" :closable="false" show-icon class="section-gap" title="支持导入平台导出的 JSON 文件，同名用例将新增为新版本。" />
      <input ref="importInputRef" type="file" accept="application/json,.json" style="display: none" @change="handleImportFile" />
      <el-button :icon="Upload" @click="importInputRef?.click()">选择文件</el-button>
      <span v-if="importFileName" class="import-file-name">{{ importFileName }}</span>
      <div v-if="importPreview" class="import-editor">
        <p>共解析出 <strong>{{ importPreview.length }}</strong> 条用例。</p>
      </div>
      <template #footer>
        <el-button @click="importVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!importPreview" :loading="importSubmitting" @click="submitImportCases">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, nextTick, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck, Delete, DocumentCopy, Download, Edit, EditPen, Files, Finished, Plus,
  Refresh, Search, Tickets, TrendCharts, Upload, VideoPlay, View
} from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import FolderTree from '../ui/components/FolderTree.vue'
import BatchRunDialog from '../ui/components/BatchRunDialog.vue'
import BatchRunDrawer from '../ui/components/BatchRunDrawer.vue'
import ReviewPanel from '../ui/components/ReviewPanel.vue'
import { usePermissions } from '@/lib/permissions'
import { useAuthStore } from '@/stores/auth'
import { executionStatusTag, executionStatusText } from '@/lib/execution'

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
const debugLoading = ref(false)
const debugResponse = ref(null)
const debugResponseTab = ref('body')
const editorMetaPanels = ref([])
const { canAdmin, canTest } = usePermissions()
const authStore = useAuthStore()
const currentUserId = computed(() => authStore.user?.id || null)

const total = ref(0)
const stats = reactive({ total: 0, active: 0, approved: 0, recent_success_rate: 0 })
const folderTree = reactive({ total: 0, ungrouped: 0, folders: [] })
const selectedFolder = ref('')
const treeDrawerVisible = ref(false)
const latestRunMap = ref({})
const caseNameCache = ref({})
const tableRef = ref(null)
const selectedRows = ref([])

const batchRunVisible = ref(false)
const batchSubmitting = ref(false)
const batchEnvironments = ref([])
const batchDrawerVisible = ref(false)
const activeBatchId = ref(null)
const batchEditVisible = ref(false)
const batchEditSubmitting = ref(false)
const batchEditForm = reactive({ folder_path: '', priority: '', status: '' })

const detailVisible = ref(false)
const detailTab = ref('definition')
const currentCase = ref(null)
const caseRuns = ref([])
const currentRun = ref(null)
let pollTimer = null
let keywordTimer = null

const importVisible = ref(false)
const importInputRef = ref(null)
const importFileName = ref('')
const importPreview = ref(null)
const importSubmitting = ref(false)
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
  status: '',
  priority: '',
  reviewStatus: '',
  keyword: ''
})

const page = ref(1)
const pageSize = ref(20)

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
  auth_type: 'none',
  auth_token: '',
  auth_username: '',
  auth_password: '',
  auth_api_key_name: 'x-api-key',
  auth_api_key_value: '',
  auth_api_key_in: 'header',
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
  expected_status: 200,
  debug_environment_id: undefined,
  debug_timeout_seconds: 30
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
const debugEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === temp.project_id))

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

const recentSuccessRate = computed(() => {
  const rate = stats.recent_success_rate
  if (rate === null || rate === undefined) return '—'
  return `${Math.round(rate * 100)}%`
})

const mapFolderNode = (node) => ({
  value: node.path,
  label: node.name || node.path,
  children: (node.children || []).map(mapFolderNode)
})
const folderSelectOptions = computed(() => folderTree.folders.map(mapFolderNode))

const priorityTag = (priority) => ({ P0: 'danger', P1: 'warning', P2: '', P3: 'info' }[priority] || 'info')
const caseStatusText = (status) => ({ ACTIVE: '启用', DISABLED: '停用', INACTIVE: '停用' }[status] || status)
const reviewText = (status) => ({ DRAFT: '草稿', IN_REVIEW: '评审中', APPROVED: '已通过', REJECTED: '已拒绝' }[status] || status || '草稿')
const reviewTag = (status) => ({ DRAFT: 'info', IN_REVIEW: 'warning', APPROVED: 'success', REJECTED: 'danger' }[status] || 'info')
const reviewTooltip = (row) => (row.reviewed_by ? `用户#${row.reviewed_by} · ${formatShortTime(row.reviewed_at)}` : '')

const formatShortTime = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
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
  if (temp.auth_type === 'bearer' && temp.auth_token) {
    headers.Authorization = `Bearer ${temp.auth_token}`
  } else if (temp.auth_type === 'basic' && (temp.auth_username || temp.auth_password)) {
    headers.Authorization = `Basic ${btoa(`${temp.auth_username}:${temp.auth_password}`)}`
  } else if (temp.auth_type === 'api_key' && temp.auth_api_key_in === 'header' && temp.auth_api_key_name) {
    headers[temp.auth_api_key_name] = temp.auth_api_key_value || ''
  }
  return Object.keys(headers).length ? headers : null
}

const buildRequestPath = () => {
  if (temp.auth_type !== 'api_key' || temp.auth_api_key_in !== 'query' || !temp.auth_api_key_name) {
    return temp.path
  }
  const rows = [
    ...temp.query_params.filter((row) => row.enabled && String(row.key || '').trim()),
    { enabled: true, key: temp.auth_api_key_name, value: temp.auth_api_key_value || '' }
  ]
  const basePath = pathWithoutQuery(temp.path) || '/'
  const query = rows
    .map((item) => `${encodeURIComponent(String(item.key).trim())}=${encodeURIComponent(String(item.value || ''))}`)
    .join('&')
  return query ? `${basePath}?${query}` : basePath
}

const hydrateAuthFromHeaders = () => {
  const authHeader = findHeaderRow('Authorization')
  temp.auth_type = 'none'
  temp.auth_token = ''
  temp.auth_username = ''
  temp.auth_password = ''
  if (!authHeader?.value) return
  const value = String(authHeader.value)
  if (value.toLowerCase().startsWith('bearer ')) {
    temp.auth_type = 'bearer'
    temp.auth_token = value.slice(7)
  } else if (value.toLowerCase().startsWith('basic ')) {
    temp.auth_type = 'basic'
  }
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
    hydrateAuthFromHeaders()

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

const buildListQuery = () => {
  const params = new URLSearchParams()
  params.set('page', page.value)
  params.set('page_size', pageSize.value)
  if (filters.projectId) params.set('project_id', filters.projectId)
  if (filters.status) params.set('status', filters.status)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.reviewStatus) params.set('review_status', filters.reviewStatus)
  if (filters.method) params.set('method', filters.method)
  if (selectedFolder.value) params.set('folder', selectedFolder.value)
  const keyword = filters.keyword.trim()
  if (keyword) params.set('keyword', keyword)
  return params.toString()
}

const loadLatestRuns = async (ids) => {
  if (!ids.length) { latestRunMap.value = {}; return }
  try {
    const params = new URLSearchParams()
    params.set('case_type', 'API')
    params.set('case_ids', ids.join(','))
    const data = await api.get(`/executions/runs/latest?${params.toString()}`)
    const map = {}
    ;(data || []).forEach((run) => { map[run.case_id] = run })
    latestRunMap.value = map
  } catch (error) {
    latestRunMap.value = {}
  }
}

const getList = async () => {
  listLoading.value = true
  try {
    const data = await api.get(`/api-cases?${buildListQuery()}`)
    const items = data.items || []
    list.value = items
    total.value = data.total ?? items.length
    const cache = { ...caseNameCache.value }
    items.forEach((item) => { cache[item.id] = item.name })
    caseNameCache.value = cache
    await loadLatestRuns(items.map((item) => item.id))
    if (currentCase.value) {
      const fresh = items.find((item) => item.id === currentCase.value.id)
      if (fresh) currentCase.value = fresh
    }
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const loadStats = async () => {
  try {
    const params = filters.projectId ? `?project_id=${filters.projectId}` : ''
    const data = await api.get(`/api-cases/stats${params}`)
    Object.assign(stats, data)
  } catch (error) {
    Object.assign(stats, { total: 0, active: 0, approved: 0, recent_success_rate: 0 })
  }
}

const loadFolders = async () => {
  try {
    const params = filters.projectId ? `?project_id=${filters.projectId}` : ''
    const data = await api.get(`/api-cases/folders${params}`)
    folderTree.total = data.total
    folderTree.ungrouped = data.ungrouped
    folderTree.folders = data.folders || []
  } catch (error) {
    folderTree.folders = []
  }
}

const loadProjects = async () => {
  try {
    const [projectData, environmentData] = await Promise.all([
      api.get('/projects'),
      api.get('/environments')
    ])
    projects.value = projectData
    environments.value = environmentData
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const refreshAll = () => Promise.all([getList(), loadStats(), loadFolders()])

const handleFolderRename = async ({ oldPath, newPath }) => {
  if (!filters.projectId) {
    ElMessage.warning('请先选择项目后再重命名目录')
    return
  }
  try {
    const data = await api.post('/api-cases/folders/rename', {
      project_id: filters.projectId,
      old_path: oldPath,
      new_path: newPath
    })
    ElMessage.success(`已更新 ${data.affected} 条用例`)
    if (selectedFolder.value === oldPath) selectedFolder.value = newPath
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleSelectionChange = (rows) => { selectedRows.value = rows }
const clearSelection = () => { tableRef.value?.clearSelection(); selectedRows.value = [] }
const handlePageSizeChange = (size) => { pageSize.value = size; page.value = 1 }

const openBatchRun = () => {
  const projectIds = new Set(selectedRows.value.map((row) => row.project_id))
  if (projectIds.size > 1) {
    ElMessage.warning('批量执行需选择同一项目下的用例')
    return
  }
  const inactive = selectedRows.value.filter((row) => row.status !== 'ACTIVE')
  if (inactive.length) {
    ElMessage.warning(`有 ${inactive.length} 条用例未启用，请先启用后再执行`)
    return
  }
  const projectId = selectedRows.value[0].project_id
  batchEnvironments.value = environments.value.filter((item) => item.project_id === projectId)
  batchRunVisible.value = true
}

const submitBatchRun = async (payload) => {
  batchSubmitting.value = true
  try {
    const data = await api.post('/executions/api/batch-run', {
      case_ids: selectedRows.value.map((row) => row.id),
      ...payload
    })
    ElMessage.success('已提交批量执行')
    batchRunVisible.value = false
    clearSelection()
    activeBatchId.value = data.batch_id || data.id
    batchDrawerVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    batchSubmitting.value = false
  }
}

const openBatchHistory = () => {
  activeBatchId.value = null
  batchDrawerVisible.value = true
}

const handleOpenRunFromBatch = async (run) => {
  batchDrawerVisible.value = false
  await openCaseDetail({ id: run.case_id }, 'runs')
  await selectRun(run)
}

const openBatchEdit = () => {
  batchEditForm.folder_path = ''
  batchEditForm.priority = ''
  batchEditForm.status = ''
  batchEditVisible.value = true
}

const submitBatchEdit = async () => {
  const patch = {}
  if (batchEditForm.folder_path) patch.folder_path = batchEditForm.folder_path
  if (batchEditForm.priority) patch.priority = batchEditForm.priority
  if (batchEditForm.status) patch.status = batchEditForm.status
  if (!Object.keys(patch).length) {
    ElMessage.warning('请至少选择一个要修改的字段')
    return
  }
  batchEditSubmitting.value = true
  try {
    const data = await api.put('/api-cases/batch', {
      case_ids: selectedRows.value.map((row) => row.id),
      patch
    })
    ElMessage.success(`已修改 ${data.affected} 条用例`)
    batchEditVisible.value = false
    clearSelection()
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    batchEditSubmitting.value = false
  }
}

const handleBatchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确认删除已选的 ${selectedRows.value.length} 条用例？该操作不可恢复。`, '批量删除', {
      type: 'warning'
    })
    const data = await api.delete('/api-cases/batch', { case_ids: selectedRows.value.map((row) => row.id) })
    ElMessage.success(`已删除 ${data.affected} 条用例`)
    clearSelection()
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.message)
  }
}

const refreshCurrentCase = async () => {
  if (!currentCase.value) return
  try {
    currentCase.value = await api.get(`/api-cases/${currentCase.value.id}`)
    await getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openCaseDetail = async (row, tab = 'definition') => {
  detailTab.value = tab
  currentRun.value = null
  detailVisible.value = true
  try {
    currentCase.value = await api.get(`/api-cases/${row.id}`)
    caseRuns.value = await api.get(`/executions/runs?case_type=API&case_id=${row.id}&limit=100`)
    if (tab === 'runs' && caseRuns.value.length) await selectRun(caseRuns.value[0])
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const selectRun = async (run) => {
  if (!run) return
  try {
    currentRun.value = await api.get(`/executions/runs/${run.id}`)
  } catch (error) {
    currentRun.value = run
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (!detailVisible.value || !currentCase.value) { stopPolling(); return }
    try {
      const data = await api.get(`/executions/runs?case_type=API&case_id=${currentCase.value.id}&limit=100`)
      caseRuns.value = data || []
      const running = (data || []).some((run) => run.status === 'RUNNING' || run.status === 'PENDING')
      if (!running) { stopPolling(); await loadLatestRuns(list.value.map((item) => item.id)) }
    } catch (error) {
      stopPolling()
    }
  }, 2000)
}

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const exportCurrentCases = async () => {
  try {
    const params = new URLSearchParams()
    params.set('case_type', 'API')
    if (filters.projectId) params.set('project_id', String(filters.projectId))
    if (filters.status) params.set('status', filters.status)
    if (filters.priority) params.set('priority', filters.priority)
    if (selectedFolder.value) params.set('folder', selectedFolder.value)
    if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
    const payload = await api.get(`/cases/export?${params.toString()}`)
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `api-cases-${Date.now()}.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${payload.count || 0} 条接口用例`)
  } catch (error) {
    ElMessage.error(error.message || '导出失败')
  }
}

const openImportDialog = () => {
  importFileName.value = ''
  importPreview.value = null
  importVisible.value = true
}

const handleImportFile = (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  importFileName.value = file.name
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result)
      const items = parsed.items || parsed.cases || (Array.isArray(parsed) ? parsed : [])
      if (!Array.isArray(items) || !items.length) throw new Error('文件中未找到用例')
      if (items.some((item) => item.case_type && item.case_type !== 'API')) throw new Error('导入文件只能包含接口用例')
      importPreview.value = items
    } catch (error) {
      importPreview.value = null
      ElMessage.error(`解析失败：${error.message}`)
    }
  }
  reader.readAsText(file)
  event.target.value = ''
}

const submitImportCases = async () => {
  if (!importPreview.value) return
  importSubmitting.value = true
  try {
    const items = importPreview.value.map((item) => ({ ...item, case_type: 'API' }))
    await api.post('/cases/import', { items })
    ElMessage.success(`成功导入 ${items.length} 条用例`)
    importVisible.value = false
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.message || '导入失败')
  } finally {
    importSubmitting.value = false
  }
}

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
  temp.auth_type = 'none'
  temp.auth_token = ''
  temp.auth_username = ''
  temp.auth_password = ''
  temp.auth_api_key_name = 'x-api-key'
  temp.auth_api_key_value = ''
  temp.auth_api_key_in = 'header'
  resetBodyFields('none')
  temp.assertions_text = '[\n  { "type": "status_code", "expected": 200 }\n]'
  temp.priority = 'P2'
  temp.status = 'ACTIVE'
  temp.expected_status = 200
  temp.debug_environment_id = undefined
  temp.debug_timeout_seconds = 30
  debugResponse.value = null
  requestTab.value = 'params'
  editorMetaPanels.value = []
  isEditing.value = false
  editingCaseId.value = undefined
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
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
  hydrateAuthFromHeaders()
  hydrateBody(row.body_json)
  applyMethodBodyProfile()
  temp.assertions_text = row.assertions_json ? JSON.stringify(row.assertions_json, null, 2) : '[\n  { "type": "status_code", "expected": 200 }\n]'
  temp.priority = row.priority
  temp.status = row.status
  temp.expected_status = row.expected_status
  temp.debug_environment_id = undefined
  temp.debug_timeout_seconds = 30
  debugResponse.value = null
  requestTab.value = 'params'
  editorMetaPanels.value = []
  isEditing.value = true
  editingCaseId.value = row.id
  dialogVisible.value = true
  nextTick(() => {
    dataFormRef.value?.clearValidate()
  })
}

const buildCasePayload = () => ({
  project_id: temp.project_id,
  name: temp.name || `${temp.method} ${pathWithoutQuery(temp.path) || '/'}`,
  folder_path: temp.folder_path || null,
  method: temp.method,
  path: buildRequestPath(),
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
})

const formatDebugBody = (body) => {
  if (typeof body === 'string') return body
  return JSON.stringify(body, null, 2)
}

const sendDebugRequest = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (!valid) return
    debugLoading.value = true
    try {
      debugResponse.value = await api.post('/api-cases/debug', {
        ...buildCasePayload(),
        environment_id: temp.debug_environment_id || null,
        timeout_seconds: temp.debug_timeout_seconds
      })
      debugResponseTab.value = 'body'
      ElMessage.success('调试请求完成')
    } catch (error) {
      ElMessage.error(error.message)
    } finally {
      debugLoading.value = false
    }
  })
}

const saveData = () => {
  dataFormRef.value?.validate(async (valid) => {
    if (valid) {
      try {
        const payload = buildCasePayload()
        if (isEditing.value && editingCaseId.value) {
          await api.put(`/api-cases/${editingCaseId.value}`, payload)
        } else {
          await api.post('/api-cases', payload)
        }
        dialogVisible.value = false
        ElMessage.success(isEditing.value ? '更新成功' : '创建成功')
        refreshAll()
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
    const row = list.value.find((item) => item.id === runForm.case_id)
    if (row) {
      await openCaseDetail(row, 'runs')
      startPolling()
    }
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
    refreshAll()
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

watch(() => filters.projectId, () => {
  selectedFolder.value = ''
  page.value = 1
  refreshAll()
})

watch([() => filters.status, () => filters.priority, () => filters.reviewStatus, () => filters.method], () => {
  page.value = 1
  getList()
})

watch(() => filters.keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    getList()
  }, 300)
})

watch(() => selectedFolder.value, () => {
  page.value = 1
  getList()
})

watch(() => page.value, () => {
  getList()
})

onMounted(async () => {
  await loadProjects()
  await refreshAll()
})

onUnmounted(() => {
  stopPolling()
  if (keywordTimer) clearTimeout(keywordTimer)
})
</script>

<style scoped>
/* ========== 页面整体布局 ========== */
.api-editor-shell {
  display: grid;
  gap: 16px;
}

.api-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.api-hero__main {
  border-radius: 20px;
  background:
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.16), transparent 34%),
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.10), transparent 32%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.96));
  color: var(--color-text);
}

.api-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--color-primary-strong);
  margin-bottom: 10px;
}

.api-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
  color: var(--color-text);
}

.api-hero__subtitle {
  max-width: 760px;
  line-height: 1.7;
  color: var(--color-text-secondary);
}

.api-hero__stat {
  border-radius: 18px;
}

/* ========== PageHeader 主按钮 ========== */
:deep(.page-header-actions .el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.18);
  border-radius: 12px;
  font-weight: 600;
  padding: 10px 24px;
  font-size: 14px;
  transition: all 0.2s ease;
}

:deep(.page-header-actions .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 10px 26px rgba(99, 102, 241, 0.26);
  transform: translateY(-1px);
}

:deep(.page-header-actions .el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
  transform: translateY(0);
}

/* ========== 卡片容器 ========== */
:deep(.page-card) {
  border-radius: 16px;
  border: 1px solid rgba(129, 140, 248, 0.1);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.06);
  background: linear-gradient(180deg, #ffffff, rgba(248, 250, 255, 0.6));
}

:deep(.page-card .el-card__body) {
  padding: 20px 24px;
}

/* ========== 查询表单区域 ========== */
.query-form {
  margin-bottom: 0;
}

.query-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.query-form :deep(.el-form-item__label) {
  font-weight: 600;
  color: #312e81;
  font-size: 13px;
}

.query-form :deep(.el-input__wrapper),
.query-form :deep(.el-select .el-input__wrapper) {
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.15) inset;
  transition: all 0.2s ease;
}

.query-form :deep(.el-input__wrapper:hover),
.query-form :deep(.el-select .el-input__wrapper:hover) {
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.2) inset, 0 0 0 3px rgba(99, 102, 241, 0.06);
}

.query-form :deep(.el-input__wrapper.is-focus),
.query-form :deep(.el-select .el-input__wrapper.is-focus) {
  border-color: rgba(99, 102, 241, 0.5);
  box-shadow: 0 0 0 1px rgba(99, 102, 241, 0.3) inset, 0 0 0 4px rgba(99, 102, 241, 0.1);
}

.query-actions {
  margin-bottom: 0;
}

.query-actions :deep(.el-form-item__content) {
  display: flex;
  gap: 8px;
}

.query-actions :deep(.el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 6px 14px rgba(99, 102, 241, 0.16);
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.query-actions :deep(.el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.22);
}

.query-actions :deep(.el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
}

.query-actions :deep(.el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
  border-radius: 10px;
  font-weight: 500;
  padding: 8px 20px;
  transition: all 0.2s ease;
}

.query-actions :deep(.el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

/* ========== 工具栏 ========== */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.04);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar :deep(.el-button) {
  border-radius: 10px;
  font-weight: 500;
  font-size: 13px;
  padding: 8px 16px;
  transition: all 0.2s ease;
}

.toolbar :deep(.el-button:not(.el-button--primary)) {
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(248, 250, 255, 0.9));
  border-color: rgba(129, 140, 248, 0.18);
  color: #4f46e5;
}

.toolbar :deep(.el-button:not(.el-button--primary):hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border-color: rgba(99, 102, 241, 0.3);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.08);
}

.toolbar :deep(.el-dropdown) {
  border-radius: 10px;
}

/* ========== 表格区域 ========== */
:deep(.el-table) {
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.06);
}

:deep(.el-table::before) {
  height: 0;
}

:deep(.el-table th.el-table__cell) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.98), rgba(250, 245, 255, 0.98));
  border-bottom: 1px solid rgba(129, 140, 248, 0.15);
  color: #312e81;
  font-weight: 600;
  font-size: 13px;
  padding: 14px 0;
}

:deep(.el-table td.el-table__cell) {
  padding: 12px 0;
  color: #475569;
  font-size: 13px;
}

:deep(.el-table .el-table__row:hover) {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.7), rgba(250, 245, 255, 0.7));
}

:deep(.el-table .el-table__row) {
  transition: background 0.15s ease;
}

:deep(.el-table .el-button) {
  border-radius: 8px;
  font-weight: 500;
  font-size: 12px;
  padding: 6px 12px;
  transition: all 0.15s ease;
}

:deep(.el-table .el-button--primary) {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.15);
}

:deep(.el-table .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.22);
}

:deep(.el-table .el-button--danger) {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.12), rgba(239, 68, 68, 0.08));
  border-color: rgba(239, 68, 68, 0.2);
  color: #dc2626;
}

:deep(.el-table .el-button--danger:hover) {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.2), rgba(239, 68, 68, 0.15));
  border-color: rgba(239, 68, 68, 0.35);
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.1);
}

:deep(.el-table .el-button:not(.el-button--primary):not(.el-button--danger)) {
  background: rgba(99, 102, 241, 0.06);
  border-color: rgba(129, 140, 248, 0.15);
  color: #4f46e5;
}

:deep(.el-table .el-button:not(.el-button--primary):not(.el-button--danger):hover) {
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.25);
}

/* ========== 分页 ========== */
.table-pagination {
  display: flex;
  justify-content: flex-end;
  padding: 16px 0 0;
}

.table-pagination :deep(.el-pagination) {
  padding: 12px 18px;
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.95), rgba(250, 245, 255, 0.95));
  border: 1px solid rgba(129, 140, 248, 0.12);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.04);
}

.table-pagination :deep(.el-pager li) {
  border-radius: 8px;
  font-weight: 500;
  min-width: 32px;
  height: 32px;
  line-height: 32px;
}

.table-pagination :deep(.el-pager li.is-active) {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  color: #fff;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.2);
}

.table-pagination :deep(.el-pager li:not(.is-active):hover) {
  background: rgba(99, 102, 241, 0.08);
  color: #4f46e5;
}

.table-pagination :deep(.btn-prev),
.table-pagination :deep(.btn-next) {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(129, 140, 248, 0.15);
}

.table-pagination :deep(.btn-prev:hover),
.table-pagination :deep(.btn-next:hover) {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.3);
}

.table-pagination :deep(.el-select .el-input__wrapper) {
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.8);
}

/* ========== 弹窗通用样式 ========== */
:deep(.el-dialog) {
  border-radius: 20px;
  overflow: hidden;
  border: 1px solid rgba(129, 140, 248, 0.15);
  box-shadow: 0 24px 64px rgba(99, 102, 241, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.5) inset;
}

:deep(.el-dialog__header) {
  padding: 20px 24px 16px;
  background: transparent;
  border-bottom: 1px solid rgba(129, 140, 248, 0.1);
}

:deep(.el-dialog__title) {
  font-weight: 700;
  color: #312e81;
  font-size: 16px;
}

:deep(.el-dialog__body) {
  padding: 20px 24px;
  background: linear-gradient(180deg, #ffffff, rgba(248, 250, 255, 0.5));
}

:deep(.el-dialog__footer) {
  padding: 16px 24px 20px;
  border-top: 1px solid rgba(129, 140, 248, 0.08);
  background: rgba(248, 250, 255, 0.5);
}

:deep(.api-editor-dialog .el-dialog__headerbtn) {
  top: 14px;
  right: 14px;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.14);
  color: #4f46e5;
  transition: background-color 0.18s ease, border-color 0.18s ease, color 0.18s ease, transform 0.18s ease;
}

:deep(.api-editor-dialog .el-dialog__headerbtn:hover) {
  background: rgba(99, 102, 241, 0.14);
  border-color: rgba(99, 102, 241, 0.26);
  color: #3730a3;
  transform: translateY(-1px);
}

:deep(.api-editor-dialog .el-dialog__close) {
  color: currentColor;
  font-size: 16px;
}

/* ========== 列设置弹窗 ========== */
.column-config-list {
  padding: 8px 0;
}

.column-config-item {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  margin-bottom: 6px;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.6), rgba(250, 245, 255, 0.6));
  border: 1px solid rgba(129, 140, 248, 0.08);
  transition: all 0.15s ease;
}

.column-config-item:hover {
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.9), rgba(250, 245, 255, 0.9));
  border-color: rgba(99, 102, 241, 0.15);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.06);
}

.column-config-item :deep(.el-checkbox__label) {
  font-weight: 500;
  color: #312e81;
  font-size: 14px;
}

.column-config-item :deep(.el-checkbox__inner) {
  border-radius: 6px;
  border-color: rgba(129, 140, 248, 0.3);
  transition: all 0.15s ease;
}

.column-config-item :deep(.el-checkbox__inner:hover) {
  border-color: rgba(99, 102, 241, 0.5);
}

.column-config-item :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  border-color: transparent;
  box-shadow: 0 2px 6px rgba(99, 102, 241, 0.2);
}

/* ========== 执行弹窗 ========== */
.run-dialog :deep(.el-form-item__label) {
  font-weight: 600;
  color: #312e81;
  font-size: 13px;
}

.run-dialog :deep(.el-input-number .el-input__wrapper) {
  border-radius: 10px;
}

/* ========== 预检面板 ========== */
.precheck-panel {
  margin-top: 12px;
  border: 1px solid rgba(129, 140, 248, 0.15);
  border-radius: 14px;
  padding: 14px;
  background: linear-gradient(135deg, rgba(248, 250, 255, 0.9), rgba(250, 245, 255, 0.9));
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.04);
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
  border-radius: 10px;
  overflow: hidden;
}

/* ========== 编辑器外壳 ========== */
.api-editor-shell {
  display: grid;
  gap: 16px;
}

.api-editor-intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 16px;
  background:
    radial-gradient(circle at top left, rgba(99, 102, 241, 0.22), transparent 36%),
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.16), transparent 32%),
    linear-gradient(135deg, rgba(239, 246, 255, 0.98), rgba(250, 245, 255, 0.98));
  border: 1px solid rgba(129, 140, 248, 0.18);
  box-shadow: 0 18px 45px rgba(99, 102, 241, 0.08);
}

.api-editor-title,
.panel-title {
  font-size: 15px;
  font-weight: 700;
  color: #312e81;
}

.api-editor-subtitle,
.panel-subtitle {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #5b5f7a;
}

/* ========== 移动端卡片 ========== */
.mobile-cards {
  display: none;
}

/* ========== 请求编辑器 ========== */
.request-editor {
  height: 100%;
  border: 1px solid rgba(99, 102, 241, 0.14);
  border-radius: 16px;
  padding: 14px 16px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 255, 0.98));
  box-shadow: 0 12px 32px rgba(99, 102, 241, 0.06);
}

.request-composer {
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 16px;
  padding: 16px;
  background:
    radial-gradient(circle at 0% 0%, rgba(52, 211, 153, 0.12), transparent 24%),
    linear-gradient(180deg, rgba(247, 250, 255, 0.98), rgba(255, 255, 255, 0.98));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.75);
}

.request-composer-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  position: relative;
  padding-bottom: 10px;
}

.request-composer-head::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  width: 88px;
  height: 3px;
  border-radius: 999px;
  background: linear-gradient(90deg, #34d399, #6366f1, #a855f7);
}

.expected-status-item {
  margin-bottom: 0;
}

.request-bar {
  margin-bottom: 0;
  width: 100%;
}
.request-bar-row {
  display: grid;
  grid-template-columns: 118px minmax(0, 1fr);
  gap: 12px;
  width: 100%;
  align-items: stretch;
}
.request-bar-method {
  width: 100%;
}
.request-bar-method :deep(.el-select__wrapper) {
  min-height: 44px;
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.12) inset;
}
.request-bar-path {
  width: 100%;
}
.request-bar-path :deep(.el-input__wrapper) {
  min-height: 44px;
  border-radius: 12px;
  box-shadow: 0 0 0 1px rgba(129, 140, 248, 0.12) inset;
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
  border: 1px dashed rgba(129, 140, 248, 0.25);
  border-radius: 14px;
  padding: 12px;
  background:
    linear-gradient(180deg, rgba(250, 250, 255, 0.98), rgba(248, 252, 255, 0.98));
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

.editor-main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(320px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.editor-left,
.editor-right {
  min-width: 0;
}

.debug-panel {
  border: 1px solid rgba(168, 85, 247, 0.16);
  border-radius: 16px;
  padding: 14px;
  background:
    radial-gradient(circle at top right, rgba(168, 85, 247, 0.12), transparent 30%),
    linear-gradient(180deg, rgba(252, 249, 255, 0.98), rgba(255, 255, 255, 0.98));
  box-shadow: 0 12px 34px rgba(168, 85, 247, 0.08);
}

.debug-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  position: relative;
  padding-bottom: 10px;
}

.debug-header::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  width: 72px;
  height: 3px;
  border-radius: 999px;
  background: linear-gradient(90deg, #6366f1, #a855f7);
}

.debug-title-main {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  line-height: 18px;
}

.debug-title-sub {
  margin-top: 2px;
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 16px;
}

.debug-empty {
  border-top: 1px solid rgba(129, 140, 248, 0.12);
  margin-top: 10px;
  padding-top: 14px;
}

.debug-empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
}

.debug-empty-text {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-text-secondary);
}

.debug-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.debug-env-select {
  width: 280px;
}

.debug-timeout {
  width: 140px;
}

.column-config-list {
  padding: 16px 0;
}
.column-config-item {
  display: flex;
  align-items: center;
  margin-bottom: 12px;
}

.debug-metrics {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.response-pre {
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 12px;
  border-radius: 12px;
  background: #0f172a;
  color: #dbeafe;
  white-space: pre-wrap;
  word-break: break-word;
}

.editor-meta-collapse {
  border: 1px solid rgba(52, 211, 153, 0.18);
  border-radius: 16px;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(52, 211, 153, 0.08), transparent 24%),
    #ffffff;
}

.editor-meta-collapse :deep(.el-collapse-item__header) {
  padding: 0 18px;
  min-height: 60px;
  border-bottom: 1px solid rgba(52, 211, 153, 0.12);
  background: linear-gradient(90deg, rgba(240, 253, 250, 0.9), rgba(255, 255, 255, 0.95));
}

.editor-meta-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.editor-meta-collapse :deep(.el-collapse-item__content) {
  padding: 0 18px 18px;
}

.meta-collapse-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  position: relative;
  padding-left: 14px;
}

.meta-collapse-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  width: 4px;
  height: 30px;
  border-radius: 999px;
  background: linear-gradient(180deg, #34d399, #10b981);
}

.meta-collapse-subtitle {
  font-size: 12px;
  color: #5f6b76;
  font-weight: 400;
}

.request-editor :deep(.el-tabs__item.is-active) {
  color: #4f46e5;
}

.api-editor-shell :deep(.el-button--primary),
:deep(.api-editor-dialog .el-button--primary) {
  --el-button-bg-color: transparent;
  --el-button-border-color: rgba(129, 140, 248, 0.26);
  --el-button-hover-bg-color: transparent;
  --el-button-hover-border-color: rgba(99, 102, 241, 0.34);
  --el-button-active-bg-color: transparent;
  --el-button-active-border-color: rgba(79, 70, 229, 0.42);
  --el-button-text-color: #ffffff;
  background: linear-gradient(135deg, #818cf8 0%, #6366f1 42%, #8b5cf6 100%);
  box-shadow: 0 10px 20px rgba(99, 102, 241, 0.18);
}

.api-editor-shell :deep(.el-button--primary.is-plain),
:deep(.api-editor-dialog .el-button--primary.is-plain) {
  --el-button-bg-color: rgba(99, 102, 241, 0.08);
  --el-button-border-color: rgba(99, 102, 241, 0.18);
  --el-button-text-color: #4f46e5;
}

.api-editor-shell :deep(.el-button--primary.is-disabled),
.api-editor-shell :deep(.el-button--primary.is-loading),
:deep(.api-editor-dialog .el-button--primary.is-disabled),
:deep(.api-editor-dialog .el-button--primary.is-loading) {
  box-shadow: none;
}

.api-editor-shell :deep(.el-button--primary:hover),
:deep(.api-editor-dialog .el-button--primary:hover) {
  background: linear-gradient(135deg, #7c83ff 0%, #5b5ff3 42%, #7c3aed 100%);
}

.api-editor-shell :deep(.el-button--primary:active),
:deep(.api-editor-dialog .el-button--primary:active) {
  background: linear-gradient(135deg, #6f76f7 0%, #4f46e5 42%, #6d28d9 100%);
}

.request-editor :deep(.el-tabs__active-bar) {
  background: linear-gradient(90deg, #6366f1, #a855f7);
}

.request-editor :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: linear-gradient(90deg, #6366f1, #8b5cf6);
  border-color: #7c3aed;
  box-shadow: -1px 0 0 0 #7c3aed;
}

.request-editor :deep(.el-alert--info) {
  --el-alert-bg-color: rgba(99, 102, 241, 0.08);
  --el-alert-border-color-light: rgba(99, 102, 241, 0.16);
}

.request-editor :deep(.el-alert--warning) {
  --el-alert-bg-color: rgba(245, 158, 11, 0.1);
}

.debug-metrics :deep(.el-tag.el-tag--success) {
  background: rgba(52, 211, 153, 0.14);
  border-color: rgba(52, 211, 153, 0.18);
  color: #047857;
}

.debug-metrics :deep(.el-tag.el-tag--danger) {
  background: rgba(244, 63, 94, 0.12);
  border-color: rgba(244, 63, 94, 0.16);
  color: #be123c;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.meta-grid-span-2 {
  grid-column: span 2;
}

/* ========== 概览统计条 ========== */
.summary-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 16px;
  background: linear-gradient(180deg, #ffffff, rgba(248, 250, 255, 0.6));
  border: 1px solid rgba(129, 140, 248, 0.1);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.06);
}

.summary-item__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  font-size: 20px;
}

.summary-item__icon.is-primary { background: rgba(99, 102, 241, 0.12); color: #4f46e5; }
.summary-item__icon.is-success { background: rgba(16, 185, 129, 0.12); color: #059669; }
.summary-item__icon.is-review { background: rgba(245, 158, 11, 0.14); color: #b45309; }
.summary-item__icon.is-rate { background: rgba(56, 189, 248, 0.14); color: #0284c7; }

.summary-item__label {
  display: block;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.summary-item strong {
  font-size: 22px;
  font-weight: 700;
  color: var(--color-text);
}

/* ========== 左树右表布局 ========== */
.case-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: var(--space-16);
  align-items: start;
}

.workspace-panel {
  border-radius: 16px;
  border: 1px solid rgba(129, 140, 248, 0.1);
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.06);
  background: linear-gradient(180deg, #ffffff, rgba(248, 250, 255, 0.6));
  padding: 16px;
}

.case-layout__tree {
  position: sticky;
  top: 12px;
}

.case-layout__main {
  min-width: 0;
}

/* ========== 筛选栏 ========== */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.tree-drawer-trigger { display: none; }

.filter-control { width: 150px; }
.filter-control--short { width: 118px; }
.filter-search { width: 220px; flex: 1 1 200px; }
.filter-result {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-text-secondary);
}

/* ========== 批量操作栏 ========== */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  margin-bottom: 12px;
  border-radius: 12px;
  background: rgba(99, 102, 241, 0.06);
  border: 1px solid rgba(129, 140, 248, 0.16);
}

.batch-bar__count {
  font-weight: 600;
  color: #4f46e5;
}

/* ========== 表格内元素 ========== */
.case-name {
  border: none;
  background: none;
  padding: 0;
  cursor: pointer;
  color: #4f46e5;
  font-weight: 600;
  font-size: 14px;
  text-align: left;
}

.case-name:hover { text-decoration: underline; }

.case-meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.last-run {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.muted { color: var(--color-text-secondary); font-size: 12px; }

.row-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}

.review-readonly {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.review-note-readonly {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(99, 102, 241, 0.05);
  border: 1px solid rgba(129, 140, 248, 0.12);
  white-space: pre-wrap;
  color: var(--color-text);
}

/* ========== 详情抽屉 ========== */
.drawer-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 700;
  color: #312e81;
}

.detail-section { margin-bottom: 18px; }

.definition-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 20px;
  margin: 0;
}

.definition-list div { display: flex; flex-direction: column; gap: 4px; }
.definition-list dt { font-size: 12px; color: var(--color-text-secondary); }
.definition-list dd { margin: 0; font-size: 14px; color: var(--color-text); }

.detail-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}

.run-detail { margin-top: 16px; }

.run-technical {
  display: grid;
  gap: 12px;
}

.run-technical__block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.run-technical__label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.run-technical pre {
  margin: 0;
  padding: 12px 14px;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
  max-height: 320px;
}

.batch-edit-hint {
  margin: 0 0 14px;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.batch-edit-hint strong { color: var(--el-color-primary); }

.import-file-name {
  margin-left: 12px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.import-editor { margin-top: 12px; font-size: 13px; }

/* ========== 移动端卡片（默认桌面隐藏） ========== */
.mobile-cards { display: none; }
.mobile-case {
  background: #ffffff;
  border: 1px solid rgba(129, 140, 248, 0.14);
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
  display: grid;
  gap: 10px;
}
.mobile-case__title { display: flex; align-items: center; gap: 10px; }
.mobile-case__tags { display: flex; flex-wrap: wrap; gap: 6px; }
.mobile-case__url { font-size: 12px; color: var(--color-text-secondary); word-break: break-all; }
.case-sequence { font-size: 12px; color: var(--color-text-secondary); }

/* ========== 响应式 ========== */
@media (max-width: 960px) {
  .summary-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .case-layout {
    grid-template-columns: 1fr;
  }

  .case-layout__tree { display: none; }

  .tree-drawer-trigger { display: inline-flex; }

  .api-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .api-hero__main {
    grid-column: 1 / -1;
  }

  .api-editor-intro,
  .request-composer-head,
  .debug-header {
    flex-direction: column;
    align-items: stretch;
  }

  .editor-main-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }

  .meta-grid-span-2 {
    grid-column: span 1;
  }

  .request-bar-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .case-table {
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
