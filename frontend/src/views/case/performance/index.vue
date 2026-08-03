<template>
  <div class="app-page perf-case-page">
    <PageHeader title="性能用例" subtitle="维护 HTTP 压测用例并投递性能执行任务">
      <template #actions>
        <el-tooltip content="批量执行记录" placement="bottom">
          <el-button :icon="Tickets" aria-label="批量执行记录" @click="openBatchHistory" />
        </el-tooltip>
        <el-tooltip content="导入性能用例" placement="bottom">
          <el-button :icon="Upload" aria-label="导入性能用例" @click="openImportDialog" />
        </el-tooltip>
        <el-tooltip content="导出当前结果" placement="bottom">
          <el-button :icon="Download" aria-label="导出当前结果" @click="exportCurrentCases" />
        </el-tooltip>
        <el-tooltip content="刷新" placement="bottom">
          <el-button :icon="Refresh" aria-label="刷新性能用例" :loading="listLoading" @click="refreshAll" />
        </el-tooltip>
        <el-button v-if="canTest" type="primary" :icon="Plus" :disabled="!projects.length" @click="handleCreate">新增性能用例</el-button>
      </template>
    </PageHeader>

    <section class="summary-strip section-gap" aria-label="性能用例概览">
      <div class="summary-item">
        <span class="summary-item__icon is-primary"><el-icon><DocumentCopy /></el-icon></span>
        <div><span class="summary-item__label">用例总数</span><strong>{{ stats.total }}</strong></div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-success"><el-icon><CircleCheck /></el-icon></span>
        <div><span class="summary-item__label">启用</span><strong>{{ stats.active }}</strong></div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-review"><el-icon><Finished /></el-icon></span>
        <div><span class="summary-item__label">已评审</span><strong>{{ stats.approved }}</strong></div>
      </div>
      <div class="summary-item">
        <span class="summary-item__icon is-rate"><el-icon><TrendCharts /></el-icon></span>
        <div><span class="summary-item__label">最近成功率</span><strong>{{ recentSuccessRate }}</strong></div>
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
          <el-select v-model="filters.method" clearable placeholder="全部方法" class="filter-control filter-control--short">
            <el-option v-for="item in ['GET', 'POST', 'PUT', 'DELETE']" :key="item" :label="item" :value="item" />
          </el-select>
          <el-input v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索名称、分组、路径或标签" class="filter-search" />
          <span class="filter-result">{{ total }} 条</span>
        </div>

        <div class="case-table-wrap">
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
            @selection-change="selectedRows = $event"
          >
            <el-table-column type="selection" width="42" :reserve-selection="true" />
            <el-table-column label="序号" width="58" align="center">
              <template #default="scope">{{ caseSequence(scope.$index) }}</template>
            </el-table-column>
            <el-table-column label="用例" min-width="210">
              <template #default="scope">
                <button class="case-name" type="button" @click="openCaseDetail(scope.row)">{{ scope.row.name }}</button>
                <div class="case-meta">
                  <span>{{ scope.row.folder_path || '未分组' }}</span>
                  <span>v{{ scope.row.version_no }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="项目" width="110" show-overflow-tooltip>
              <template #default="scope">{{ projectMap[scope.row.project_id] || scope.row.project_id }}</template>
            </el-table-column>
            <el-table-column label="方法" width="76" align="center">
              <template #default="scope"><el-tag size="small" effect="plain">{{ scope.row.method }}</el-tag></template>
            </el-table-column>
            <el-table-column label="优先级" width="70" align="center">
              <template #default="scope"><el-tag size="small" :type="priorityTag(scope.row.priority)">{{ scope.row.priority }}</el-tag></template>
            </el-table-column>
            <el-table-column label="状态" width="72" align="center">
              <template #default="scope"><el-tag size="small" :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(scope.row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="评审" width="82" align="center">
              <template #default="scope">
                <el-tooltip :disabled="!scope.row.reviewed_by" placement="top" :content="reviewTooltip(scope.row)">
                  <el-tag size="small" effect="plain" :type="reviewTag(scope.row.review_status)">{{ reviewText(scope.row.review_status) }}</el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="并发" prop="concurrency" width="66" align="center" />
            <el-table-column label="总请求" prop="total_requests" width="76" align="center" />
            <el-table-column label="阈值" min-width="180" show-overflow-tooltip>
              <template #default="scope">{{ thresholdSummary(scope.row) }}</template>
            </el-table-column>
            <el-table-column label="最近执行" width="120">
              <template #default="scope">
                <div v-if="latestRunMap[scope.row.id]" class="last-run">
                  <el-tag size="small" :type="executionStatusTag(latestRunMap[scope.row.id].status)">{{ executionStatusText(latestRunMap[scope.row.id].status) }}</el-tag>
                  <span>{{ formatShortTime(latestRunMap[scope.row.id].created_at) }}</span>
                </div>
                <span v-else class="muted">未执行</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" align="right" width="160" fixed="right">
              <template #default="scope">
                <div class="row-actions">
                  <el-tooltip content="查看详情" placement="top"><el-button circle size="small" :icon="View" aria-label="查看性能用例" @click="openCaseDetail(scope.row)" /></el-tooltip>
                  <el-tooltip v-if="canTest" content="编辑" placement="top"><el-button circle size="small" :icon="Edit" aria-label="编辑性能用例" @click="handleEdit(scope.row)" /></el-tooltip>
                  <el-tooltip v-if="canTest" content="立即执行" placement="top"><el-button circle size="small" type="primary" :icon="VideoPlay" aria-label="执行性能用例" @click="handleRun(scope.row)" /></el-tooltip>
                  <el-tooltip v-if="canAdmin" content="删除" placement="top"><el-button circle size="small" type="danger" plain :icon="Delete" aria-label="删除性能用例" @click="handleDelete(scope.row)" /></el-tooltip>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <div class="mobile-cards">
            <article v-for="(item, index) in list" :key="item.id" class="mobile-case">
              <div class="mobile-case__title">
                <span class="case-sequence">#{{ caseSequence(index) }}</span>
                <button class="case-name" type="button" @click="openCaseDetail(item)">{{ item.name }}</button>
              </div>
              <div class="mobile-case__tags">
                <el-tag size="small" effect="plain">{{ item.method }}</el-tag>
                <el-tag size="small" :type="priorityTag(item.priority)">{{ item.priority }}</el-tag>
                <el-tag size="small" :type="item.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(item.status) }}</el-tag>
                <el-tag size="small" effect="plain" :type="reviewTag(item.review_status)">{{ reviewText(item.review_status) }}</el-tag>
              </div>
              <div class="mobile-case__url">{{ item.path }} · 并发 {{ item.concurrency }} · {{ thresholdSummary(item) }}</div>
              <div class="row-actions">
                <el-button size="small" :icon="View" @click="openCaseDetail(item)">详情</el-button>
                <el-button v-if="canTest" size="small" type="primary" :icon="VideoPlay" @click="handleRun(item)">执行</el-button>
              </div>
            </article>
          </div>

          <div class="table-pagination">
            <el-pagination
              v-model:current-page="page"
              v-model:page-size="pageSize"
              layout="total, sizes, prev, pager, next"
              :total="total"
              :page-sizes="[10, 20, 50]"
            />
          </div>
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
      :environments="batchEnvironments"
      :count="selectedRows.length"
      :submitting="batchSubmitting"
      @submit="submitBatchRun"
    />

    <BatchRunDrawer
      v-model="batchDrawerVisible"
      case-type="PERF"
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
          <el-tree-select v-model="batchEditForm.folder_path" :data="folderSelectOptions" check-strictly filterable allow-create default-first-option clearable placeholder="选择已有目录或输入新路径" style="width: 100%" />
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

    <el-dialog v-model="editorVisible" :title="isEditing ? '编辑性能用例' : '新增性能用例'" width="min(720px, 96vw)" top="5vh" destroy-on-close>
      <el-form ref="editorFormRef" :model="temp" :rules="rules" label-position="top">
        <el-form-item label="所属项目" prop="project_id">
          <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例名称" prop="name"><el-input v-model="temp.name" /></el-form-item>
        <el-form-item label="目录/分组">
          <el-tree-select v-model="temp.folder_path" :data="folderSelectOptions" check-strictly filterable allow-create default-first-option clearable placeholder="选择已有目录或输入新路径，如：压测基线/系统接口" style="width: 100%" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="请求方法" prop="method">
              <el-select v-model="temp.method" style="width: 100%">
                <el-option v-for="item in ['GET', 'POST', 'PUT', 'DELETE']" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8"><el-form-item label="预期状态码" prop="expected_status"><el-input-number v-model="temp.expected_status" :min="100" :max="599" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8">
            <el-form-item label="优先级"><el-segmented v-model="temp.priority" :options="['P0', 'P1', 'P2']" block /></el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="请求路径" prop="path"><el-input v-model="temp.path" placeholder="/api/v1/system/health" /></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="用例状态">
              <el-radio-group v-model="temp.status"><el-radio-button value="ACTIVE">启用</el-radio-button><el-radio-button value="DISABLED">停用</el-radio-button></el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="当前版本"><el-input v-model="temp.version_no" disabled /></el-form-item></el-col>
        </el-row>
        <el-form-item label="标签">
          <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%" placeholder="例如：baseline、perf-smoke">
            <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="评审状态（只读）">
          <div class="review-readonly">
            <el-tag effect="plain" :type="reviewTag(temp.review_status)">{{ reviewText(temp.review_status) }}</el-tag>
            <span>评审在详情页进行；内容变更会自动重置为草稿</span>
          </div>
        </el-form-item>
        <el-form-item v-if="temp.review_note" label="评审意见（只读）"><p class="review-note-readonly">{{ temp.review_note }}</p></el-form-item>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="并发数" prop="concurrency"><el-input-number v-model="temp.concurrency" :min="1" :max="50" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="总请求数" prop="total_requests"><el-input-number v-model="temp.total_requests" :min="1" :max="1000" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="8"><el-form-item label="平均响应阈值(ms)"><el-input-number v-model="temp.max_avg_response_ms" :min="1" :max="60000" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="P95 阈值(ms)"><el-input-number v-model="temp.max_p95_response_ms" :min="1" :max="60000" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="8"><el-form-item label="错误率阈值"><el-input-number v-model="temp.max_error_rate" :min="0" :max="1" :step="0.01" :precision="2" style="width: 100%" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="请求头 JSON" prop="headers_text"><el-input v-model="temp.headers_text" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="请求体 JSON" prop="body_text"><el-input v-model="temp.body_text" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-version">{{ isEditing ? `保存后按需升级版本（当前 ${temp.version_no}）` : '初始版本 1.0.0' }}</span>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveData">保存用例</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="执行性能用例" width="520px">
      <el-form label-position="top" :model="runForm">
        <el-form-item label="执行环境">
          <el-select v-model="runForm.environment_id" clearable placeholder="不指定环境，使用项目基础地址" style="width: 100%">
            <el-option v-for="item in runEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时（秒）"><el-input-number v-model="runForm.timeout_seconds" :min="1" :max="600" style="width: 100%" /></el-form-item>
      </el-form>
      <div v-if="precheckResult" class="precheck-panel" :class="{ 'is-invalid': !precheckResult.is_valid }">
        <el-icon><CircleCheck v-if="precheckResult.is_valid" /><WarningFilled v-else /></el-icon>
        <div><strong>{{ precheckResult.summary }}</strong><div v-if="precheckResult.missing_variables?.length" class="precheck-vars">{{ precheckResult.missing_variables.join('、') }}</div></div>
      </div>
      <template #footer>
        <el-button :loading="prechecking" @click="handlePrecheck">执行前校验</el-button>
        <el-button @click="runDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingRun" @click="submitRun">开始执行</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" size="min(780px, 94vw)" destroy-on-close @closed="stopPolling">
      <template #header>
        <div v-if="currentCase" class="drawer-title"><div><strong>{{ currentCase.name }}</strong><span>#{{ currentCase.id }} · v{{ currentCase.version_no }}</span></div><el-tag :type="currentCase.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(currentCase.status) }}</el-tag></div>
      </template>
      <el-tabs v-if="currentCase" v-model="detailTab">
        <el-tab-pane label="用例定义" name="definition">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="项目">{{ projectMap[currentCase.project_id] || currentCase.project_id }}</el-descriptions-item>
            <el-descriptions-item label="优先级">{{ currentCase.priority }}</el-descriptions-item>
            <el-descriptions-item label="分组">{{ currentCase.folder_path || '-' }}</el-descriptions-item>
            <el-descriptions-item label="评审">{{ reviewText(currentCase.review_status) }}</el-descriptions-item>
            <el-descriptions-item label="方法">{{ currentCase.method }}</el-descriptions-item>
            <el-descriptions-item label="预期状态码">{{ currentCase.expected_status }}</el-descriptions-item>
            <el-descriptions-item label="并发">{{ currentCase.concurrency }}</el-descriptions-item>
            <el-descriptions-item label="总请求数">{{ currentCase.total_requests }}</el-descriptions-item>
            <el-descriptions-item label="路径" :span="2">{{ currentCase.path }}</el-descriptions-item>
            <el-descriptions-item label="阈值" :span="2">{{ thresholdSummary(currentCase) }}</el-descriptions-item>
          </el-descriptions>
          <ReviewPanel :case-data="currentCase" case-type="PERF" :can-test="canTest" :current-user-id="currentUserId" @changed="refreshCurrentCase" />
          <section v-if="currentCase.headers_json" class="detail-section">
            <div class="detail-section__head"><h3>请求头</h3></div>
            <pre class="json-block">{{ formatJson(currentCase.headers_json) }}</pre>
          </section>
          <section v-if="currentCase.body_json" class="detail-section">
            <div class="detail-section__head"><h3>请求体</h3></div>
            <pre class="json-block">{{ formatJson(currentCase.body_json) }}</pre>
          </section>
        </el-tab-pane>
        <el-tab-pane :label="`执行记录 (${caseRuns.length})`" name="runs">
          <div class="run-list-toolbar"><el-button v-if="canTest" type="primary" :icon="VideoPlay" @click="handleRun(currentCase)">立即执行</el-button></div>
          <el-table :data="caseRuns" size="small" highlight-current-row @current-change="selectRun">
            <el-table-column label="执行" width="84"><template #default="scope">#{{ scope.row.id }}</template></el-table-column>
            <el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="executionStatusTag(scope.row.status)">{{ executionStatusText(scope.row.status) }}</el-tag></template></el-table-column>
            <el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip />
            <el-table-column label="耗时" width="90"><template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template></el-table-column>
            <el-table-column label="时间" width="145"><template #default="scope">{{ formatShortTime(scope.row.created_at) }}</template></el-table-column>
          </el-table>

          <section v-if="selectedRun" class="run-detail" v-loading="runDetailLoading">
            <div class="run-detail__head"><div><h3>执行 #{{ selectedRun.id }}</h3><p>{{ selectedRun.summary || '-' }}</p></div><el-tag :type="executionStatusTag(selectedRun.status)">{{ executionStatusText(selectedRun.status) }}</el-tag></div>
            <div v-if="runMetrics" class="runtime-evidence">
              <span>平均 <strong>{{ runMetrics.avg_response_ms }}ms</strong></span>
              <span>P95 <strong>{{ runMetrics.p95_response_ms }}ms</strong></span>
              <span>错误率 <strong>{{ Math.round((runMetrics.error_rate || 0) * 100) }}%</strong></span>
              <span>吞吐 <strong>{{ runMetrics.throughput_rps }} rps</strong></span>
              <span>成功 <strong>{{ runMetrics.success_count }}/{{ runMetrics.success_count + runMetrics.failure_count }}</strong></span>
            </div>
            <el-collapse v-if="selectedRun.stderr_text" class="run-technical">
              <el-collapse-item title="阈值/错误详情" name="stderr"><pre>{{ selectedRun.stderr_text }}</pre></el-collapse-item>
            </el-collapse>
          </section>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <el-dialog v-model="importVisible" title="导入性能用例" width="680px">
      <el-upload :auto-upload="false" :show-file-list="false" accept="application/json,.json" :on-change="handleImportFile"><el-button :icon="Upload">选择 JSON 文件</el-button></el-upload>
      <el-input v-model="importText" type="textarea" :rows="14" class="import-editor" />
      <template #footer><el-button @click="importVisible = false">取消</el-button><el-button type="primary" @click="submitImportCases">导入</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '@/lib/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  CircleCheck, Delete, DocumentCopy, Download, Edit, EditPen, Files, Finished,
  Plus, Refresh, Search, Tickets, TrendCharts, Upload, VideoPlay, View, WarningFilled
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
const total = ref(0)
const projects = ref([])
const environments = ref([])
const listLoading = ref(true)
const saving = ref(false)
const editorVisible = ref(false)
const isEditing = ref(false)
const editingCaseId = ref(null)
const editorFormRef = ref(null)
const runDialogVisible = ref(false)
const precheckResult = ref(null)
const prechecking = ref(false)
const submittingRun = ref(false)
const detailVisible = ref(false)
const detailTab = ref('definition')
const currentCase = ref(null)
const caseRuns = ref([])
const selectedRun = ref(null)
const runDetailLoading = ref(false)
const importVisible = ref(false)
const importText = ref('')
const stats = reactive({ total: 0, active: 0, approved: 0, recent_success_rate: null })
const folderTree = ref({ total: 0, ungrouped: 0, folders: [] })
const selectedFolder = ref('')
const treeDrawerVisible = ref(false)
const latestRunMap = ref({})
const caseNameCache = reactive({})
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
const { canAdmin, canTest } = usePermissions()
const authStore = useAuthStore()
const currentUserId = computed(() => authStore.user?.id || null)
let pollTimer = null
let keywordTimer = null

const filters = reactive({ projectId: undefined, status: '', priority: '', reviewStatus: '', method: '', keyword: '' })
const page = ref(1)
const pageSize = ref(20)

const DEFAULT_TEMP = {
  project_id: undefined, name: '', folder_path: '', method: 'GET', path: '', priority: 'P2', status: 'ACTIVE',
  review_status: 'DRAFT', version_no: '1.0.0', review_note: '', tags_json: [],
  headers_text: '{\n  "accept": "application/json"\n}', body_text: '', expected_status: 200,
  concurrency: 5, total_requests: 20, max_avg_response_ms: 1500, max_p95_response_ms: 2500, max_error_rate: 0.1
}
const temp = reactive({ ...DEFAULT_TEMP })
const runForm = reactive({ case_id: undefined, project_id: undefined, environment_id: undefined, timeout_seconds: 120 })

const jsonValidator = { validator: (rule, value, callback) => { try { if (value) JSON.parse(value); callback() } catch { callback(new Error('JSON 格式错误')) } }, trigger: 'blur' }
const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '名称必填', trigger: 'blur' }, { min: 2, message: '至少2字符', trigger: 'blur' }],
  path: [{ required: true, message: '路径必填', trigger: 'blur' }],
  headers_text: [jsonValidator],
  body_text: [jsonValidator]
}

const projectMap = computed(() => Object.fromEntries(projects.value.map((item) => [item.id, item.name])))
const tagOptions = computed(() => [...new Set(list.value.flatMap((item) => item.tags_json || []))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))
const recentSuccessRate = computed(() => (stats.recent_success_rate == null ? '-' : `${Math.round(stats.recent_success_rate * 100)}%`))
const mapFolderNode = (node) => ({ value: node.path, label: node.name, children: (node.children || []).map(mapFolderNode) })
const folderSelectOptions = computed(() => (folderTree.value.folders || []).map(mapFolderNode))
const runMetrics = computed(() => selectedRun.value?.response_payload || null)

const caseSequence = (pageIndex) => total.value - ((page.value - 1) * pageSize.value + pageIndex)
const priorityTag = (priority) => ({ P0: 'danger', P1: 'warning', P2: '', P3: 'info' }[priority] || 'info')
const caseStatusText = (status) => ({ ACTIVE: '启用', DISABLED: '停用' }[status] || status)
const reviewText = (status) => ({ DRAFT: '草稿', IN_REVIEW: '评审中', APPROVED: '已通过', REJECTED: '已拒绝' }[status] || status)
const reviewTag = (status) => ({ APPROVED: 'success', IN_REVIEW: 'warning', REJECTED: 'danger', DRAFT: 'info' }[status] || 'info')
const reviewTooltip = (row) => `评审人：用户 #${row.reviewed_by} · ${row.reviewed_at ? new Date(row.reviewed_at).toLocaleString('zh-CN') : '-'}`
const formatShortTime = (value) => (value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-')
const formatDuration = (value) => (value === null || value === undefined ? '-' : value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(1)}s`)
const formatJson = (value) => { try { return JSON.stringify(value, null, 2) } catch { return String(value) } }
const thresholdSummary = (item) => [
  item.max_avg_response_ms ? `AVG≤${item.max_avg_response_ms}ms` : null,
  item.max_p95_response_ms ? `P95≤${item.max_p95_response_ms}ms` : null,
  item.max_error_rate !== null && item.max_error_rate !== undefined ? `ERR≤${Math.round(item.max_error_rate * 100)}%` : null
].filter(Boolean).join('，') || '-'

const clearSelection = () => tableRef.value?.clearSelection()

const buildListQuery = () => {
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
  if (filters.projectId) params.set('project_id', String(filters.projectId))
  if (filters.status) params.set('status', filters.status)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.reviewStatus) params.set('review_status', filters.reviewStatus)
  if (filters.method) params.set('method', filters.method)
  if (selectedFolder.value) params.set('folder', selectedFolder.value)
  if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
  return params
}

const loadLatestRuns = async (caseIds) => {
  if (!caseIds.length) { latestRunMap.value = {}; return }
  try {
    const rows = await api.get(`/executions/runs/latest?case_type=PERF&case_ids=${caseIds.join(',')}`)
    latestRunMap.value = Object.fromEntries(rows.map((run) => [run.case_id, run]))
  } catch { latestRunMap.value = {} }
}

const getList = async () => {
  listLoading.value = true
  try {
    const data = await api.get(`/performance-cases?${buildListQuery()}`)
    list.value = data.items
    total.value = data.total
    data.items.forEach((item) => { caseNameCache[item.id] = item.name })
    await loadLatestRuns(data.items.map((item) => item.id))
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const loadStats = async () => {
  try {
    const suffix = filters.projectId ? `?project_id=${filters.projectId}` : ''
    Object.assign(stats, await api.get(`/performance-cases/stats${suffix}`))
  } catch { /* 概览统计失败不阻塞列表 */ }
}

const loadFolders = async () => {
  try {
    const suffix = filters.projectId ? `?project_id=${filters.projectId}` : ''
    folderTree.value = await api.get(`/performance-cases/folders${suffix}`)
  } catch (error) { ElMessage.error(error.message) }
}

const loadProjects = async () => {
  try { projects.value = await api.get('/projects') } catch (error) { ElMessage.error(error.message) }
}

const refreshAll = () => Promise.all([getList(), loadStats(), loadFolders()])

const handleFolderRename = async ({ oldPath, newPath }) => {
  if (!filters.projectId) { ElMessage.warning('请先在筛选中选择项目，再重命名目录'); return }
  try {
    const result = await api.post('/performance-cases/folders/rename', { project_id: filters.projectId, old_path: oldPath, new_path: newPath })
    ElMessage.success(`目录已重命名，共更新 ${result.affected} 条用例`)
    if (selectedFolder.value === oldPath || selectedFolder.value.startsWith(`${oldPath}/`)) {
      selectedFolder.value = newPath + selectedFolder.value.slice(oldPath.length)
    }
    await Promise.all([loadFolders(), getList()])
  } catch (error) { ElMessage.error(error.message) }
}

const openBatchRun = async () => {
  const projectIds = [...new Set(selectedRows.value.map((row) => row.project_id))]
  if (projectIds.length > 1) { ElMessage.warning('批量执行的用例必须属于同一项目'); return }
  const inactive = selectedRows.value.filter((row) => row.status !== 'ACTIVE')
  if (inactive.length) { ElMessage.warning(`以下用例未启用，无法批量执行：${inactive.map((row) => row.name).join('、')}`); return }
  try {
    batchEnvironments.value = await api.get(`/environments?project_id=${projectIds[0]}`)
    batchRunVisible.value = true
  } catch (error) { ElMessage.error(error.message) }
}

const submitBatchRun = async (payload) => {
  batchSubmitting.value = true
  try {
    const batch = await api.post('/executions/perf/batch-run', { case_ids: selectedRows.value.map((row) => row.id), ...payload })
    batchRunVisible.value = false
    clearSelection()
    ElMessage.success(`批量执行 #${batch.id} 已提交`)
    activeBatchId.value = batch.id
    batchDrawerVisible.value = true
  } catch (error) { ElMessage.error(error.message) } finally { batchSubmitting.value = false }
}

const openBatchHistory = () => { activeBatchId.value = null; batchDrawerVisible.value = true }

const handleOpenRunFromBatch = async (run) => {
  batchDrawerVisible.value = false
  await openCaseDetail({ id: run.case_id }, 'runs')
  await selectRun(run)
}

const openBatchEdit = () => { Object.assign(batchEditForm, { folder_path: '', priority: '', status: '' }); batchEditVisible.value = true }

const submitBatchEdit = async () => {
  const patch = {}
  if (batchEditForm.folder_path && batchEditForm.folder_path.trim()) patch.folder_path = batchEditForm.folder_path.trim()
  if (batchEditForm.priority) patch.priority = batchEditForm.priority
  if (batchEditForm.status) patch.status = batchEditForm.status
  if (!Object.keys(patch).length) { ElMessage.warning('请至少填写一个要修改的字段'); return }
  batchEditSubmitting.value = true
  try {
    const result = await api.put('/performance-cases/batch', { case_ids: selectedRows.value.map((row) => row.id), patch })
    ElMessage.success(`已批量更新 ${result.affected} 条用例`)
    batchEditVisible.value = false
    clearSelection()
    await Promise.all([getList(), loadFolders(), loadStats()])
  } catch (error) { ElMessage.error(error.message) } finally { batchEditSubmitting.value = false }
}

const handleBatchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确认删除已选的 ${selectedRows.value.length} 条性能用例？该操作不可恢复。`, '批量删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const result = await api.delete('/performance-cases/batch', { case_ids: selectedRows.value.map((row) => row.id) })
    ElMessage.success(`已删除 ${result.affected} 条性能用例`)
    clearSelection()
    await refreshAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const refreshCurrentCase = async () => {
  if (!currentCase.value) return
  try {
    currentCase.value = await api.get(`/performance-cases/${currentCase.value.id}`)
    await getList()
  } catch (error) { ElMessage.error(error.message) }
}

const handleCreate = () => {
  Object.assign(temp, { ...DEFAULT_TEMP, project_id: projects.value[0]?.id })
  isEditing.value = false
  editingCaseId.value = null
  editorVisible.value = true
  nextTick(() => editorFormRef.value?.clearValidate())
}

const handleEdit = (row) => {
  Object.assign(temp, {
    project_id: row.project_id, name: row.name, folder_path: row.folder_path || '', method: row.method, path: row.path,
    priority: row.priority || 'P2', status: row.status || 'ACTIVE', review_status: row.review_status || 'DRAFT',
    version_no: row.version_no || '1.0.0', review_note: row.review_note || '', tags_json: [...(row.tags_json || [])],
    headers_text: row.headers_json ? JSON.stringify(row.headers_json, null, 2) : '',
    body_text: row.body_json ? JSON.stringify(row.body_json, null, 2) : '',
    expected_status: row.expected_status, concurrency: row.concurrency, total_requests: row.total_requests,
    max_avg_response_ms: row.max_avg_response_ms, max_p95_response_ms: row.max_p95_response_ms, max_error_rate: row.max_error_rate
  })
  isEditing.value = true
  editingCaseId.value = row.id
  editorVisible.value = true
  nextTick(() => editorFormRef.value?.clearValidate())
}

const buildTempPayload = () => ({
  project_id: temp.project_id,
  name: temp.name.trim(),
  folder_path: temp.folder_path?.trim() || null,
  method: temp.method,
  path: temp.path.trim(),
  priority: temp.priority,
  status: temp.status,
  review_status: temp.review_status,
  version_no: temp.version_no,
  review_note: temp.review_note?.trim() || null,
  tags_json: temp.tags_json.length ? temp.tags_json : null,
  headers_json: temp.headers_text ? JSON.parse(temp.headers_text) : null,
  body_json: temp.body_text ? JSON.parse(temp.body_text) : null,
  expected_status: temp.expected_status,
  concurrency: temp.concurrency,
  total_requests: temp.total_requests,
  max_avg_response_ms: temp.max_avg_response_ms,
  max_p95_response_ms: temp.max_p95_response_ms,
  max_error_rate: temp.max_error_rate
})

const saveData = async () => {
  const valid = await editorFormRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload = buildTempPayload()
    if (isEditing.value) await api.put(`/performance-cases/${editingCaseId.value}`, payload)
    else await api.post('/performance-cases', payload)
    editorVisible.value = false
    ElMessage.success(isEditing.value ? '性能用例已更新' : '性能用例已创建')
    await refreshAll()
  } catch (error) { ElMessage.error(error.message) } finally { saving.value = false }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除性能用例「${row.name}」？`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await api.delete(`/performance-cases/${row.id}`)
    ElMessage.success('性能用例已删除')
    await refreshAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleRun = async (row) => {
  Object.assign(runForm, { case_id: row.id, project_id: row.project_id, environment_id: undefined, timeout_seconds: 120 })
  precheckResult.value = null
  try {
    environments.value = await api.get(`/environments?project_id=${row.project_id}`)
    runDialogVisible.value = true
  } catch (error) { ElMessage.error(error.message) }
}

const precheckRun = async () => {
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  precheckResult.value = await api.get(`/executions/perf/${runForm.case_id}/precheck${suffix}`)
  return precheckResult.value.is_valid
}

const handlePrecheck = async () => {
  prechecking.value = true
  try { if (await precheckRun()) ElMessage.success('执行预检通过') } catch (error) { ElMessage.error(error.message) } finally { prechecking.value = false }
}

const submitRun = async () => {
  submittingRun.value = true
  try {
    if (!(await precheckRun())) return
    const run = await api.post(`/executions/perf/${runForm.case_id}/run`, { environment_id: runForm.environment_id, timeout_seconds: runForm.timeout_seconds, max_retries: 0 })
    runDialogVisible.value = false
    ElMessage.success(`性能任务 #${run.id} 已提交`)
    const row = list.value.find((item) => item.id === runForm.case_id)
    if (row) await openCaseDetail(row, 'runs')
    await selectRun(run)
    startPolling()
  } catch (error) { ElMessage.error(error.message) } finally { submittingRun.value = false }
}

const openCaseDetail = async (row, tab = 'definition') => {
  try {
    currentCase.value = await api.get(`/performance-cases/${row.id}`)
    caseRuns.value = await api.get(`/executions/runs?case_type=PERF&case_id=${row.id}&limit=100`)
    selectedRun.value = null
    detailTab.value = tab
    detailVisible.value = true
    if (tab === 'runs' && caseRuns.value.length) await selectRun(caseRuns.value[0])
  } catch (error) { ElMessage.error(error.message) }
}

const selectRun = async (run) => {
  if (!run?.id) return
  runDetailLoading.value = true
  try {
    selectedRun.value = await api.get(`/executions/runs/${run.id}`)
    if (['PENDING', 'RUNNING'].includes(selectedRun.value.status)) startPolling()
  } catch (error) { ElMessage.error(error.message) } finally { runDetailLoading.value = false }
}

const startPolling = () => {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    if (!detailVisible.value || !selectedRun.value?.id) return stopPolling()
    try {
      const detail = await api.get(`/executions/runs/${selectedRun.value.id}`)
      selectedRun.value = detail
      if (!['PENDING', 'RUNNING'].includes(detail.status)) {
        stopPolling()
        caseRuns.value = await api.get(`/executions/runs?case_type=PERF&case_id=${detail.case_id}&limit=100`)
        await getList()
      }
    } catch { stopPolling() }
  }, 2000)
}
const stopPolling = () => { if (pollTimer) window.clearInterval(pollTimer); pollTimer = null }

const exportCurrentCases = async () => {
  try {
    const params = new URLSearchParams({ case_type: 'PERF' })
    if (filters.projectId) params.set('project_id', String(filters.projectId))
    if (filters.status) params.set('status', filters.status)
    if (filters.priority) params.set('priority', filters.priority)
    if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
    const payload = await api.get(`/cases/export?${params}`)
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = `performance-cases-${Date.now()}.json`; link.click(); URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${payload.count || 0} 条性能用例`)
  } catch (error) { ElMessage.error(error.message) }
}
const openImportDialog = () => {
  importText.value = JSON.stringify({ items: [{ case_type: 'PERF', project_id: projects.value[0]?.id || 1, name: '示例性能用例', method: 'GET', path: '/api/v1/system/health', concurrency: 5, total_requests: 20, expected_status: 200 }] }, null, 2)
  importVisible.value = true
}
const handleImportFile = async (file) => { try { importText.value = await file.raw.text() } catch { ElMessage.error('文件读取失败') } }
const submitImportCases = async () => {
  try {
    const payload = JSON.parse(importText.value || '{}')
    if (!Array.isArray(payload.items) || payload.items.some((item) => item.case_type !== 'PERF')) throw new Error('导入文件只能包含性能用例')
    await api.post('/cases/import', payload); importVisible.value = false; ElMessage.success('性能用例导入成功'); await refreshAll()
  } catch (error) { ElMessage.error(error.message) }
}

watch(() => filters.projectId, () => { selectedFolder.value = ''; page.value = 1; refreshAll() })
watch([() => filters.status, () => filters.priority, () => filters.reviewStatus, () => filters.method], () => { page.value = 1; getList() })
watch(() => filters.keyword, () => { clearTimeout(keywordTimer); keywordTimer = setTimeout(() => { page.value = 1; getList() }, 300) })
watch(selectedFolder, () => { page.value = 1; getList() })
watch(page, () => getList())
watch(pageSize, () => { page.value = 1; getList() })

onMounted(async () => {
  await loadProjects()
  await refreshAll()
})
onUnmounted(() => { stopPolling() })
</script>

<style scoped>
.perf-case-page { min-width: 0; }
.summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); overflow: hidden; border: 1px solid #e4e7ed; border-radius: 8px; background: #fff; box-shadow: 0 4px 14px rgb(15 23 42 / 3%); }
.summary-item { min-height: 84px; padding: 14px 20px; display: flex; align-items: center; gap: 13px; border-right: 1px solid var(--el-border-color-lighter); }
.summary-item:last-child { border-right: 0; }
.summary-item > div { min-width: 0; display: flex; flex-direction: column; justify-content: center; }
.summary-item__icon { width: 36px; height: 36px; flex: 0 0 36px; display: grid; place-items: center; border: 1px solid; border-radius: 8px; font-size: 17px; }
.summary-item__icon.is-primary { border-color: #c7d2fe; background: #eef2ff; color: #4f46e5; }
.summary-item__icon.is-success { border-color: #bbebd4; background: #effaf5; color: #159a62; }
.summary-item__icon.is-review { border-color: #bfdbfe; background: #eff6ff; color: #2563eb; }
.summary-item__icon.is-rate { border-color: #fed7aa; background: #fff7ed; color: #c2410c; }
.summary-item__label { color: var(--color-text-secondary); font-size: 12px; }
.summary-item strong { margin-top: 3px; color: #172033; font-size: 22px; line-height: 1.2; }
.workspace-panel { overflow: hidden; background: #fff; border: 1px solid #e4e7ed; border-radius: 8px; box-shadow: 0 5px 18px rgb(15 23 42 / 3%); }
.case-layout { margin-top: 14px; display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: start; }
.case-layout__tree { padding: 12px 10px; position: sticky; top: 16px; max-height: calc(100vh - 120px); overflow: auto; }
.case-layout__main { min-width: 0; }
.tree-drawer-trigger { display: none; }
.filter-bar { min-height: 62px; padding: 12px 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.filter-control { width: 180px; }
.filter-control--short { width: 130px; }
.filter-search { width: min(320px, 30vw); }
.filter-result { margin-left: auto; color: var(--color-text-secondary); font-size: 13px; white-space: nowrap; }
.case-table-wrap { min-width: 0; }
.batch-bar { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-color-primary-light-9); }
.batch-bar__count { color: var(--el-color-primary); font-size: 13px; font-weight: 600; }
.case-table { width: 100%; }
.case-name { border: 0; padding: 0; background: none; color: var(--el-color-primary); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.case-name:hover { text-decoration: underline; }
.case-meta { margin-top: 5px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.4; }
.last-run { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }
.muted { color: var(--color-text-secondary); }
.row-actions { display: flex; justify-content: flex-end; gap: 6px; }
.mobile-cards { display: none; }
.table-pagination { display: flex; justify-content: flex-end; padding: 12px 16px; }
:deep(.case-table .el-table__header th) { height: 44px; background: #f8fafc; color: #667085; font-weight: 600; }
:deep(.case-table .el-table__row td) { padding: 12px 0; }
:deep(.case-table .el-table__row:hover > td) { background: #f8faff !important; }
.batch-edit-hint { margin: 0 0 14px; color: var(--color-text-secondary); font-size: 13px; }
.review-readonly { display: flex; align-items: center; gap: 10px; color: var(--color-text-secondary); font-size: 12px; }
.review-note-readonly { margin: 0; color: var(--color-text-secondary); font-size: 12px; }
.dialog-version { margin-right: auto; color: var(--color-text-secondary); font-size: 12px; }
:deep(.el-dialog__footer) { display: flex; align-items: center; }
.precheck-panel { display: flex; gap: 10px; align-items: flex-start; margin-top: 12px; padding: 12px; border: 1px solid var(--el-color-success-light-5); background: var(--el-color-success-light-9); color: var(--el-color-success); border-radius: 6px; }
.precheck-panel.is-invalid { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.precheck-vars { margin-top: 4px; font-size: 12px; }
.drawer-title { width: 100%; display: flex; align-items: center; justify-content: space-between; padding-right: 16px; }
.drawer-title div { display: flex; flex-direction: column; gap: 3px; }
.drawer-title strong { color: var(--color-text); font-size: 17px; }
.drawer-title span { color: var(--color-text-secondary); font-size: 12px; }
.detail-section { margin-top: 22px; }
.detail-section__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.detail-section h3, .run-detail h3 { margin: 0; font-size: 14px; }
.json-block { margin: 0; padding: 10px; max-height: 240px; overflow: auto; background: #f7f8fa; color: var(--color-text-secondary); border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; line-height: 1.55; }
.run-list-toolbar { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.run-detail { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--el-border-color); }
.run-detail__head { display: flex; justify-content: space-between; align-items: flex-start; }
.run-detail__head p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; }
.runtime-evidence { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); background: #f8fafc; font-size: 12px; color: var(--color-text-secondary); }
.runtime-evidence strong { margin-left: 4px; color: var(--color-text); }
.run-technical { margin-top: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 0 12px; }
.run-technical pre { max-height: 260px; margin: 0; padding: 10px; overflow: auto; background: #f7f8fa; color: var(--color-text-secondary); border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.55; }
.import-editor { margin-top: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (max-width: 900px) {
  .case-layout { grid-template-columns: 1fr; }
  .case-layout__tree { display: none; }
  .tree-drawer-trigger { display: inline-flex; }
  .summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n+2) { border-bottom: 1px solid var(--el-border-color-lighter); }
  .filter-control, .filter-control--short, .filter-search { width: calc(50% - 5px); }
  .filter-result { width: 100%; margin-left: 0; }
  .case-table { display: none; }
  .mobile-cards { display: grid; gap: 10px; padding: 12px; }
  .mobile-case { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 6px; }
  .mobile-case__title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .case-sequence { flex: 0 0 auto; color: var(--color-text-secondary); font-size: 12px; }
  .mobile-case__tags { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
  .mobile-case__url { margin-bottom: 10px; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
}
</style>
