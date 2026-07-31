<template>
  <div class="app-page ui-case-page">
    <PageHeader title="UI 用例" subtitle="管理可执行的浏览器测试与运行证据">
      <template #actions>
        <el-tooltip content="批量执行记录" placement="bottom">
          <el-button :icon="Tickets" aria-label="批量执行记录" @click="openBatchHistory" />
        </el-tooltip>
        <el-tooltip content="导入 UI 用例" placement="bottom">
          <el-button :icon="Upload" aria-label="导入 UI 用例" @click="openImportDialog" />
        </el-tooltip>
        <el-tooltip content="导出当前结果" placement="bottom">
          <el-button :icon="Download" aria-label="导出当前结果" @click="exportCurrentCases" />
        </el-tooltip>
        <el-tooltip content="刷新" placement="bottom">
          <el-button :icon="Refresh" aria-label="刷新 UI 用例" :loading="listLoading" @click="refreshAll" />
        </el-tooltip>
        <el-button v-if="canTest" :icon="Plus" @click="handleCreate">高级创建</el-button>
        <el-button v-if="canTest" type="primary" :icon="MagicStick" :disabled="listLoading || !projects.length" @click="openAIDialog">AI 创建</el-button>
      </template>
    </PageHeader>

    <section class="summary-strip section-gap" aria-label="UI 用例概览">
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
          <el-select v-model="filters.status" clearable placeholder="全部状态" class="filter-control filter-control--short">
            <el-option label="启用" value="ACTIVE" />
            <el-option label="停用" value="INACTIVE" />
          </el-select>
          <el-select v-model="filters.priority" clearable placeholder="全部优先级" class="filter-control filter-control--short">
            <el-option v-for="item in ['P0', 'P1', 'P2', 'P3']" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="filters.reviewStatus" clearable placeholder="全部评审" class="filter-control filter-control--short">
            <el-option label="草稿" value="DRAFT" />
            <el-option label="评审中" value="IN_REVIEW" />
            <el-option label="已通过" value="APPROVED" />
            <el-option label="已拒绝" value="REJECTED" />
          </el-select>
          <el-input v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索名称、分组、地址或标签" class="filter-search" />
          <span class="filter-result">{{ total }} 条</span>
        </div>

        <CaseTable
          ref="caseTableRef"
          :rows="list"
          :loading="listLoading"
          :total="total"
          :page="page"
          :page-size="pageSize"
          :project-map="projectMap"
          :latest-run-map="latestRunMap"
          :can-test="canTest"
          :can-admin="canAdmin"
          @update:page="page = $event"
          @update:page-size="pageSize = $event"
          @selection-change="selectedRows = $event"
          @detail="openCaseDetail"
          @edit="handleEdit"
          @run="handleRun"
          @delete="handleDelete"
          @batch-run="openBatchRun"
          @batch-edit="openBatchEdit"
          @batch-delete="handleBatchDelete"
        />
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
            <el-option v-for="item in ['P0', 'P1', 'P2', 'P3']" :key="item" :label="item" :value="item" />
          </el-select>
        </el-form-item>
        <el-form-item label="用例状态">
          <el-select v-model="batchEditForm.status" clearable placeholder="不修改" style="width: 100%">
            <el-option label="启用" value="ACTIVE" />
            <el-option label="停用" value="INACTIVE" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="batchEditSubmitting" @click="submitBatchEdit">保存修改</el-button>
      </template>
    </el-dialog>

    <AICaseComposer
      v-model="aiDialogVisible"
      :form="aiForm"
      :projects="projects"
      :draft-ready="aiDraftReady"
      :draft="temp"
      :warnings="aiWarnings"
      :generating="aiGenerating"
      :saving="saving"
      :running="aiSavingRun"
      @project-change="handleAIProjectChange"
      @generate="generateAIDraft"
      @reset="resetAIDraft"
      @advanced-edit="openAIDraftInEditor"
      @save="saveAIDraft(false)"
      @save-run="saveAIDraft(true)"
    />

    <el-dialog v-model="editorVisible" :title="isEditing ? '编辑 UI 用例' : '新增 UI 用例'" width="min(1080px, 96vw)" top="4vh" destroy-on-close>
      <el-form ref="editorFormRef" :model="temp" :rules="rules" label-position="top">
        <el-tabs v-model="editorTab" class="editor-tabs">
          <el-tab-pane label="基本信息" name="basic">
            <div class="form-grid">
              <div v-if="temp.generation_mode === 'ai_skill'" class="ai-origin form-grid__wide">
                <el-tag effect="plain">AI Skill</el-tag>
                <span>{{ temp.skill_name }} · v{{ temp.skill_version }}</span>
              </div>
              <el-form-item label="所属项目" prop="project_id">
                <el-select v-model="temp.project_id" placeholder="请选择项目" style="width: 100%">
                  <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="用例名称" prop="name"><el-input v-model="temp.name" /></el-form-item>
              <el-form-item label="目录/分组">
                <el-tree-select
                  v-model="temp.folder_path"
                  :data="folderSelectOptions"
                  check-strictly
                  filterable
                  allow-create
                  default-first-option
                  clearable
                  placeholder="选择已有目录或输入新路径，如：登录/核心流程"
                  style="width: 100%"
                />
              </el-form-item>
              <el-form-item label="目标地址" prop="target_url"><el-input v-model="temp.target_url" placeholder="http://frontend:3000/login" /></el-form-item>
              <el-form-item label="优先级">
                <el-segmented v-model="temp.priority" :options="['P0', 'P1', 'P2', 'P3']" block />
              </el-form-item>
              <el-form-item label="用例状态">
                <el-radio-group v-model="temp.status"><el-radio-button value="ACTIVE">启用</el-radio-button><el-radio-button value="INACTIVE">停用</el-radio-button></el-radio-group>
              </el-form-item>
              <el-form-item label="标签" class="form-grid__wide">
                <el-select v-model="temp.tags_json" multiple filterable allow-create default-first-option style="width: 100%">
                  <el-option v-for="item in tagOptions" :key="item" :label="item" :value="item" />
                </el-select>
              </el-form-item>
              <el-form-item label="评审状态（只读）">
                <div class="review-readonly">
                  <el-tag effect="plain" :type="reviewTag(temp.review_status)">{{ reviewText(temp.review_status) }}</el-tag>
                  <span>评审在详情页进行；内容变更会自动重置为草稿</span>
                </div>
              </el-form-item>
              <el-form-item label="当前版本"><el-input v-model="temp.version_no" disabled /></el-form-item>
              <el-form-item v-if="temp.review_note" label="评审意见（只读）" class="form-grid__wide">
                <p class="review-note-readonly">{{ temp.review_note }}</p>
              </el-form-item>
              <div class="runtime-config form-grid__wide">
                <div class="runtime-config__head">
                  <div><strong>AI 运行策略</strong><span>{{ executionModeDescription(temp.execution_mode) }}</span></div>
                  <el-tag effect="plain">{{ executionModeText(temp.execution_mode) }}</el-tag>
                </div>
                <el-form-item label="执行模式">
                  <el-segmented v-model="temp.execution_mode" :options="executionModeOptions" block />
                </el-form-item>
                <el-form-item v-if="['stable', 'adaptive'].includes(temp.execution_mode)" label="定位恢复">
                  <el-switch v-model="temp.self_heal_enabled" active-text="允许一次受控 AI 自愈" />
                </el-form-item>
                <el-form-item v-if="temp.execution_mode === 'explore'" label="最大探索步数">
                  <el-input-number v-model="temp.max_agent_steps" :min="1" :max="30" controls-position="right" />
                </el-form-item>
                <el-form-item v-if="temp.execution_mode === 'explore'" label="允许域名">
                  <el-select v-model="temp.allowed_origins_json" multiple allow-create filterable default-first-option style="width: 100%" placeholder="默认仅目标地址和项目地址">
                    <el-option v-for="item in temp.allowed_origins_json" :key="item" :label="item" :value="item" />
                  </el-select>
                </el-form-item>
                <el-form-item v-if="temp.execution_mode === 'explore'" label="禁止操作">
                  <el-select v-model="temp.prohibited_actions_json" multiple allow-create filterable default-first-option style="width: 100%" placeholder="删除、支付、发布等">
                    <el-option v-for="item in defaultProhibitedActions" :key="item" :label="item" :value="item" />
                  </el-select>
                </el-form-item>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`操作步骤 (${temp.steps.length})`" name="steps">
            <div class="builder-toolbar">
              <span class="builder-count">{{ temp.steps.length }} 个步骤</span>
              <el-button type="primary" plain :icon="Plus" @click="addStep">添加步骤</el-button>
            </div>
            <el-empty v-if="!temp.steps.length" description="暂无操作步骤；执行时会自动打开目标地址" :image-size="72" />
            <div v-else class="builder-list">
              <div v-for="(step, index) in temp.steps" :key="step._key" class="builder-row">
                <div class="builder-row__head">
                  <span class="builder-index">{{ index + 1 }}</span>
                  <el-select v-model="step.action" class="builder-action" @change="changeStepAction(step, $event)">
                    <el-option v-for="item in UI_STEP_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                  <el-input v-model="step.name" placeholder="步骤名称（可选）" />
                  <div class="builder-actions">
                    <el-tooltip content="上移"><el-button text :icon="Top" aria-label="上移步骤" :disabled="index === 0" @click="moveItem(temp.steps, index, -1)" /></el-tooltip>
                    <el-tooltip content="下移"><el-button text :icon="Bottom" aria-label="下移步骤" :disabled="index === temp.steps.length - 1" @click="moveItem(temp.steps, index, 1)" /></el-tooltip>
                    <el-tooltip content="复制"><el-button text :icon="CopyDocument" aria-label="复制步骤" @click="duplicateStep(index)" /></el-tooltip>
                    <el-tooltip content="删除"><el-button text type="danger" :icon="Delete" aria-label="删除步骤" @click="temp.steps.splice(index, 1)" /></el-tooltip>
                  </div>
                </div>
                <div class="builder-fields">
                  <div v-if="stepDefinition(step).selector || stepDefinition(step).optionalSelector" class="semantic-fields">
                    <el-input v-model="step.target" placeholder="语义目标，例如：登录按钮" />
                    <el-input v-model="step.role" placeholder="ARIA 角色，例如：button" />
                    <el-input v-model="step.accessible_name" placeholder="可访问名称，例如：登录" />
                    <el-input v-model="step.test_id" placeholder="data-testid（可选）" />
                  </div>
                  <el-input v-if="stepDefinition(step).selector || stepDefinition(step).optionalSelector" v-model="step.selector" :placeholder="stepDefinition(step).optionalSelector ? '限定选择器（可选）' : '选择器，例如 [data-testid=submit]'" />
                  <el-input v-if="stepDefinition(step).needsValue" v-model="step.value" :placeholder="stepDefinition(step).valueLabel" />
                  <el-input-number v-if="stepDefinition(step).duration" v-model="step.duration_ms" :min="1" :max="60000" :step="500" controls-position="right" />
                  <el-select v-if="stepDefinition(step).state" v-model="step.state"><el-option label="可见" value="visible" /><el-option label="隐藏" value="hidden" /><el-option label="已挂载" value="attached" /><el-option label="已移除" value="detached" /></el-select>
                  <el-select v-if="stepDefinition(step).waitUntil" v-model="step.wait_until"><el-option label="DOM 就绪" value="domcontentloaded" /><el-option label="页面加载" value="load" /><el-option label="网络空闲" value="networkidle" /></el-select>
                  <template v-if="stepDefinition(step).viewport">
                    <el-input-number v-model="step.width" :min="320" :max="3840" controls-position="right" /><span class="dimension-separator">×</span><el-input-number v-model="step.height" :min="320" :max="2160" controls-position="right" />
                  </template>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane :label="`断言 (${temp.assertions.length + 1})`" name="assertions">
            <el-form-item label="最终文本断言" prop="expect_text"><el-input v-model="temp.expect_text" placeholder="页面最终必须出现的文本" /></el-form-item>
            <div class="builder-toolbar builder-toolbar--bordered">
              <span class="builder-count">附加断言 {{ temp.assertions.length }} 个</span>
              <el-button type="primary" plain :icon="Plus" @click="addAssertion">添加断言</el-button>
            </div>
            <div class="builder-list">
              <div v-for="(assertion, index) in temp.assertions" :key="assertion._key" class="builder-row assertion-row">
                <div class="builder-row__head">
                  <span class="builder-index">{{ index + 1 }}</span>
                  <el-select v-model="assertion.type" class="builder-action" @change="changeAssertionType(assertion, $event)">
                    <el-option v-for="item in UI_ASSERTION_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
                  </el-select>
                  <el-input v-model="assertion.name" placeholder="断言名称（可选）" />
                  <div class="builder-actions"><el-tooltip content="删除"><el-button text type="danger" :icon="Delete" aria-label="删除断言" @click="temp.assertions.splice(index, 1)" /></el-tooltip></div>
                </div>
                <div class="builder-fields">
                  <div v-if="assertionDefinition(assertion).selector || assertionDefinition(assertion).optionalSelector || assertionDefinition(assertion).semanticTarget" class="semantic-fields">
                    <el-input v-model="assertion.target" placeholder="检查区域或元素，例如：登录表单" />
                    <el-input v-model="assertion.role" placeholder="ARIA 角色（可选）" />
                    <el-input v-model="assertion.accessible_name" placeholder="可访问名称（可选）" />
                    <el-input v-model="assertion.test_id" placeholder="data-testid（可选）" />
                  </div>
                  <el-input v-if="assertionDefinition(assertion).selector || assertionDefinition(assertion).optionalSelector" v-model="assertion.selector" :placeholder="assertionDefinition(assertion).optionalSelector ? '限定选择器（可选）' : '选择器'" />
                  <el-input v-if="assertionDefinition(assertion).needsValue" v-model="assertion.value" :placeholder="assertionDefinition(assertion).valueLabel" />
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <span class="dialog-version">{{ isEditing ? `保存后自动升级版本（当前 ${temp.version_no}）` : '初始版本 1.0.0' }}</span>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveData">保存用例</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="runDialogVisible" title="执行 UI 用例" width="560px">
      <el-form label-position="top" :model="runForm">
        <el-form-item label="执行环境"><el-select v-model="runForm.environment_id" clearable placeholder="直接使用用例目标地址" style="width: 100%"><el-option v-for="item in runEnvironmentOptions" :key="item.id" :label="`${item.name} · ${item.base_url}`" :value="item.id" /></el-select></el-form-item>
        <div class="run-options"><el-form-item label="超时（秒）"><el-input-number v-model="runForm.timeout_seconds" :min="1" :max="600" controls-position="right" /></el-form-item><el-form-item label="自动重试"><el-input-number v-model="runForm.max_retries" :min="0" :max="3" controls-position="right" /></el-form-item></div>
      </el-form>
      <div v-if="precheckResult" class="precheck-panel" :class="{ 'is-invalid': !precheckResult.is_valid }">
        <el-icon><CircleCheck v-if="precheckResult.is_valid" /><WarningFilled v-else /></el-icon>
        <div><strong>{{ precheckResult.summary }}</strong><div v-if="precheckResult.missing_variables?.length" class="precheck-vars">{{ precheckResult.missing_variables.join('、') }}</div></div>
      </div>
      <template #footer><el-button :loading="prechecking" @click="handlePrecheck">执行前校验</el-button><el-button @click="runDialogVisible = false">取消</el-button><el-button type="primary" :loading="submittingRun" @click="submitRun">开始执行</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" size="min(780px, 94vw)" destroy-on-close @closed="stopPolling">
      <template #header>
        <div v-if="currentCase" class="drawer-title"><div><strong>{{ currentCase.name }}</strong><span>#{{ currentCase.id }} · v{{ currentCase.version_no }}</span></div><el-tag :type="currentCase.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(currentCase.status) }}</el-tag></div>
      </template>
      <el-tabs v-if="currentCase" v-model="detailTab">
        <el-tab-pane label="用例定义" name="definition">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="项目">{{ projectMap[currentCase.project_id] || currentCase.project_id }}</el-descriptions-item><el-descriptions-item label="优先级">{{ currentCase.priority }}</el-descriptions-item>
            <el-descriptions-item label="分组">{{ currentCase.folder_path || '-' }}</el-descriptions-item><el-descriptions-item label="评审">{{ reviewText(currentCase.review_status) }}</el-descriptions-item>
            <el-descriptions-item label="生成方式">{{ currentCase.generation_mode === 'ai_skill' ? 'AI Skill' : '手工' }}</el-descriptions-item><el-descriptions-item label="Skill">{{ currentCase.skill_name ? `${currentCase.skill_name} · v${currentCase.skill_version}` : '-' }}</el-descriptions-item>
            <el-descriptions-item label="执行模式">{{ executionModeText(currentCase.execution_mode) }}</el-descriptions-item><el-descriptions-item label="AI 自愈">{{ currentCase.self_heal_enabled ? '允许一次' : '关闭' }}</el-descriptions-item>
            <el-descriptions-item label="目标地址" :span="2">{{ currentCase.target_url }}</el-descriptions-item><el-descriptions-item label="最终文本" :span="2">{{ currentCase.expect_text }}</el-descriptions-item>
            <el-descriptions-item v-if="currentCase.ai_goal" label="测试目标" :span="2">{{ currentCase.ai_goal }}</el-descriptions-item>
          </el-descriptions>
          <ReviewPanel :case-data="currentCase" :can-test="canTest" :current-user-id="currentUserId" @changed="refreshCurrentCase" />
          <section class="detail-section"><div class="detail-section__head"><h3>操作步骤</h3><span>{{ (currentCase.steps_json || []).length }} 步</span></div><div v-if="currentCase.steps_json?.length" class="definition-list"><div v-for="(step, index) in currentCase.steps_json" :key="index" class="definition-item"><span>{{ index + 1 }}</span><div><strong>{{ step.name || stepLabel(step.action) }}</strong><p v-if="step.target">目标：{{ step.target }}</p><code v-if="step.selector">{{ step.selector }}</code><p v-if="step.value !== undefined">{{ step.value }}</p></div></div></div><el-empty v-else description="无附加步骤" :image-size="60" /></section>
          <section class="detail-section"><div class="detail-section__head"><h3>断言</h3><span>{{ (currentCase.assertions_json || []).length + 1 }} 项</span></div><div class="definition-list"><div class="definition-item"><span>1</span><div><strong>最终文本可见</strong><p>{{ currentCase.expect_text }}</p></div></div><div v-for="(assertion, index) in currentCase.assertions_json || []" :key="index" class="definition-item"><span>{{ index + 2 }}</span><div><strong>{{ assertion.name || assertionLabel(assertion.type) }}</strong><code v-if="assertion.selector">{{ assertion.selector }}</code><p>{{ assertion.value ?? assertion.expected }}</p></div></div></div></section>
        </el-tab-pane>
        <el-tab-pane :label="`执行记录 (${caseRuns.length})`" name="runs">
          <div class="run-list-toolbar"><el-button v-if="canTest" type="primary" :icon="VideoPlay" @click="handleRun(currentCase)">立即执行</el-button></div>
          <el-table :data="caseRuns" size="small" highlight-current-row @current-change="selectRun">
            <el-table-column label="执行" width="84"><template #default="scope">#{{ scope.row.id }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="executionStatusTag(scope.row.status)">{{ executionStatusText(scope.row.status) }}</el-tag></template></el-table-column><el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip /><el-table-column label="耗时" width="90"><template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template></el-table-column><el-table-column label="时间" width="145"><template #default="scope">{{ formatShortTime(scope.row.created_at) }}</template></el-table-column>
          </el-table>

          <section v-if="selectedRun" class="run-detail" v-loading="runDetailLoading">
            <div class="run-detail__head"><div><h3>执行 #{{ selectedRun.id }}</h3><p>{{ selectedRun.summary || '-' }}</p></div><el-tag :type="executionStatusTag(selectedRun.status)">{{ executionStatusText(selectedRun.status) }}</el-tag></div>
            <el-collapse v-if="selectedRun.stderr_text" class="run-technical">
              <el-collapse-item title="技术详情（排障使用）" name="stderr">
                <pre>{{ selectedRun.stderr_text }}</pre>
              </el-collapse-item>
            </el-collapse>
            <div v-if="selectedRun.response_payload?.execution_mode" class="runtime-evidence">
              <span>模式 <strong>{{ executionModeText(selectedRun.response_payload.execution_mode) }}</strong></span>
              <span>AI 自愈 <strong>{{ selectedRun.response_payload.healing_count || 0 }} 次</strong></span>
              <span v-if="selectedRun.response_payload.visual_reviews?.length">视觉检查 <strong>{{ selectedRun.response_payload.visual_reviews.length }} 项</strong></span>
              <span v-if="selectedRun.response_payload.release_gate_eligible === false">探索结果 <strong>不作为发布门禁</strong></span>
            </div>
            <div class="run-detail-grid">
              <div class="run-steps"><h4>步骤结果</h4><div v-for="(step, index) in selectedRunSteps" :key="index" class="run-step"><el-icon :class="step.status === 'SUCCESS' ? 'is-success' : 'is-failed'"><CircleCheck v-if="step.status === 'SUCCESS'" /><WarningFilled v-else /></el-icon><div><strong>{{ step.name || `步骤 ${index + 1}` }}</strong><p>{{ formatStepDetail(step.detail) }}</p></div><span>{{ formatDuration(step.duration_ms) }}</span></div></div>
              <div class="run-artifacts"><h4>执行产物</h4><button v-for="(artifact, index) in selectedRunArtifacts" :key="`${artifact.name}-${index}`" type="button" class="artifact-item" @click="previewArtifact(index, artifact)"><el-icon><Picture v-if="isImageArtifact(artifact)" /><Document v-else /></el-icon><span>{{ artifact.name }}</span><el-button text :icon="Download" :aria-label="`下载 ${artifact.name}`" @click.stop="downloadArtifact(index, artifact)" /></button><div v-if="previewUrl" class="artifact-preview"><img :src="previewUrl" alt="UI 执行截图" /></div></div>
            </div>
          </section>
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <el-dialog v-model="importVisible" title="导入 UI 用例" width="680px">
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
  Bottom, CircleCheck, CopyDocument, Delete, Document, DocumentCopy, Download, Files, Finished,
  MagicStick, Picture, Plus, Refresh, Search, Tickets, Top, TrendCharts, Upload, VideoPlay, WarningFilled
} from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import AICaseComposer from './components/AICaseComposer.vue'
import FolderTree from './components/FolderTree.vue'
import CaseTable from './components/CaseTable.vue'
import BatchRunDialog from './components/BatchRunDialog.vue'
import BatchRunDrawer from './components/BatchRunDrawer.vue'
import ReviewPanel from './components/ReviewPanel.vue'
import { usePermissions } from '@/lib/permissions'
import { useAuthStore } from '@/stores/auth'
import { executionStatusTag, executionStatusText } from '@/lib/execution'
import {
  UI_ASSERTION_OPTIONS, UI_STEP_OPTIONS, createUiAssertion, createUiStep,
  getAssertionDefinition, getStepDefinition, normalizeUiAssertion, normalizeUiStep,
  serializeUiAssertions, serializeUiSteps, validateUiWorkflow
} from '@/lib/uiCase'

const list = ref([])
const total = ref(0)
const projects = ref([])
const environments = ref([])
const listLoading = ref(true)
const saving = ref(false)
const editorVisible = ref(false)
const editorTab = ref('basic')
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
const selectedRunSteps = ref([])
const selectedRunArtifacts = ref([])
const runDetailLoading = ref(false)
const previewUrl = ref('')
const importVisible = ref(false)
const importText = ref('')
const aiDialogVisible = ref(false)
const aiGenerating = ref(false)
const aiDraftReady = ref(false)
const aiWarnings = ref([])
const aiSavingRun = ref(false)
const stats = reactive({ total: 0, active: 0, approved: 0, recent_success_rate: null })
const folderTree = ref({ total: 0, ungrouped: 0, folders: [] })
const selectedFolder = ref('')
const treeDrawerVisible = ref(false)
const latestRunMap = ref({})
const caseNameCache = reactive({})
const caseTableRef = ref(null)
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
let itemKey = 0
let pollTimer = null
let keywordTimer = null

const filters = reactive({ projectId: undefined, status: '', priority: '', reviewStatus: '', keyword: '' })
const page = ref(1)
const pageSize = ref(20)
const temp = reactive({
  project_id: undefined, name: '', folder_path: '', target_url: '', priority: 'P1', status: 'ACTIVE',
  review_status: 'DRAFT', version_no: '1.0.0', review_note: '', expect_text: '', tags_json: [], steps: [], assertions: [],
  generation_mode: 'manual', execution_mode: 'stable', self_heal_enabled: false, max_agent_steps: 10,
  allowed_origins_json: [], prohibited_actions_json: [], ai_goal: '', skill_name: '', skill_version: '', generation_meta_json: null
})
const aiForm = reactive({ project_id: undefined, target_url: '', goal: '', context: '', max_steps: 12, execution_mode: 'adaptive' })
const runForm = reactive({ case_id: undefined, project_id: undefined, environment_id: undefined, timeout_seconds: 60, max_retries: 0 })
const executionModeOptions = [
  { label: '稳定回归', value: 'stable' },
  { label: '适应执行', value: 'adaptive' },
  { label: '自主探索', value: 'explore' },
  { label: '视觉测试', value: 'visual' }
]
const defaultProhibitedActions = ['删除', '支付', '购买', '发布', '发送', '授权']
const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '请输入用例名称', trigger: 'blur' }, { min: 2, message: '名称至少 2 个字符', trigger: 'blur' }],
  target_url: [{ required: true, message: '请输入目标地址', trigger: 'blur' }],
  expect_text: [{ required: true, message: '请输入最终文本断言', trigger: 'blur' }]
}
const withKey = (item) => ({ ...item, _key: ++itemKey })
const projectMap = computed(() => Object.fromEntries(projects.value.map((item) => [item.id, item.name])))
const tagOptions = computed(() => [...new Set(list.value.flatMap((item) => item.tags_json || []))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))
const recentSuccessRate = computed(() => (stats.recent_success_rate == null ? '-' : `${Math.round(stats.recent_success_rate * 100)}%`))
const mapFolderNode = (node) => ({ value: node.path, label: node.name, children: (node.children || []).map(mapFolderNode) })
const folderSelectOptions = computed(() => (folderTree.value.folders || []).map(mapFolderNode))

const buildListQuery = () => {
  const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
  if (filters.projectId) params.set('project_id', String(filters.projectId))
  if (filters.status) params.set('status', filters.status)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.reviewStatus) params.set('review_status', filters.reviewStatus)
  if (selectedFolder.value) params.set('folder', selectedFolder.value)
  if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
  return params
}

const loadLatestRuns = async (caseIds) => {
  if (!caseIds.length) { latestRunMap.value = {}; return }
  try {
    const rows = await api.get(`/executions/runs/latest?case_type=UI&case_ids=${caseIds.join(',')}`)
    latestRunMap.value = Object.fromEntries(rows.map((run) => [run.case_id, run]))
  } catch {
    latestRunMap.value = {}
  }
}

const getList = async () => {
  listLoading.value = true
  try {
    const data = await api.get(`/ui-cases?${buildListQuery()}`)
    list.value = data.items
    total.value = data.total
    data.items.forEach((item) => { caseNameCache[item.id] = item.name })
    await loadLatestRuns(data.items.map((item) => item.id))
    if (currentCase.value) currentCase.value = data.items.find((item) => item.id === currentCase.value.id) || currentCase.value
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const loadStats = async () => {
  try {
    const suffix = filters.projectId ? `?project_id=${filters.projectId}` : ''
    Object.assign(stats, await api.get(`/ui-cases/stats${suffix}`))
  } catch {
    /* 概览统计失败不阻塞列表 */
  }
}

const loadFolders = async () => {
  try {
    const suffix = filters.projectId ? `?project_id=${filters.projectId}` : ''
    folderTree.value = await api.get(`/ui-cases/folders${suffix}`)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const loadProjects = async () => {
  try {
    projects.value = await api.get('/projects')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const refreshAll = () => Promise.all([getList(), loadStats(), loadFolders()])

const handleFolderRename = async ({ oldPath, newPath }) => {
  if (!filters.projectId) {
    ElMessage.warning('请先在筛选中选择项目，再重命名目录')
    return
  }
  try {
    const result = await api.post('/ui-cases/folders/rename', { project_id: filters.projectId, old_path: oldPath, new_path: newPath })
    ElMessage.success(`目录已重命名，共更新 ${result.affected} 条用例`)
    if (selectedFolder.value === oldPath || selectedFolder.value.startsWith(`${oldPath}/`)) {
      selectedFolder.value = newPath + selectedFolder.value.slice(oldPath.length)
    }
    await Promise.all([loadFolders(), getList()])
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openBatchRun = async () => {
  const projectIds = [...new Set(selectedRows.value.map((row) => row.project_id))]
  if (projectIds.length > 1) {
    ElMessage.warning('批量执行的用例必须属于同一项目')
    return
  }
  const inactive = selectedRows.value.filter((row) => row.status !== 'ACTIVE')
  if (inactive.length) {
    ElMessage.warning(`以下用例未启用，无法批量执行：${inactive.map((row) => row.name).join('、')}`)
    return
  }
  try {
    batchEnvironments.value = await api.get(`/environments?project_id=${projectIds[0]}`)
    batchRunVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const submitBatchRun = async (payload) => {
  batchSubmitting.value = true
  try {
    const batch = await api.post('/executions/ui/batch-run', { case_ids: selectedRows.value.map((row) => row.id), ...payload })
    batchRunVisible.value = false
    caseTableRef.value?.clearSelection()
    ElMessage.success(`批量执行 #${batch.id} 已提交`)
    activeBatchId.value = batch.id
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
  Object.assign(batchEditForm, { folder_path: '', priority: '', status: '' })
  batchEditVisible.value = true
}

const submitBatchEdit = async () => {
  const patch = {}
  if (batchEditForm.folder_path && batchEditForm.folder_path.trim()) patch.folder_path = batchEditForm.folder_path.trim()
  if (batchEditForm.priority) patch.priority = batchEditForm.priority
  if (batchEditForm.status) patch.status = batchEditForm.status
  if (!Object.keys(patch).length) {
    ElMessage.warning('请至少填写一个要修改的字段')
    return
  }
  batchEditSubmitting.value = true
  try {
    const result = await api.put('/ui-cases/batch', { case_ids: selectedRows.value.map((row) => row.id), patch })
    ElMessage.success(`已批量更新 ${result.affected} 条用例`)
    batchEditVisible.value = false
    caseTableRef.value?.clearSelection()
    await Promise.all([getList(), loadFolders(), loadStats()])
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    batchEditSubmitting.value = false
  }
}

const handleBatchDelete = async () => {
  try {
    await ElMessageBox.confirm(`确认删除已选的 ${selectedRows.value.length} 条 UI 用例？该操作不可恢复。`, '批量删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    const result = await api.delete('/ui-cases/batch', { case_ids: selectedRows.value.map((row) => row.id) })
    ElMessage.success(`已删除 ${result.affected} 条 UI 用例`)
    caseTableRef.value?.clearSelection()
    await refreshAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const refreshCurrentCase = async () => {
  if (!currentCase.value) return
  try {
    currentCase.value = await api.get(`/ui-cases/${currentCase.value.id}`)
    await getList()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const resetTemp = () => {
  const project = projects.value[0]
  Object.assign(temp, {
    project_id: project?.id, name: '', folder_path: '', target_url: project?.base_url || 'http://frontend:3000',
    priority: 'P1', status: 'ACTIVE', review_status: 'DRAFT', version_no: '1.0.0', review_note: '',
    expect_text: '', tags_json: [], steps: [], assertions: [], generation_mode: 'manual', ai_goal: '',
    execution_mode: 'stable', self_heal_enabled: false, max_agent_steps: 10, allowed_origins_json: [],
    prohibited_actions_json: [], skill_name: '', skill_version: '', generation_meta_json: null
  })
}

const handleAIProjectChange = (projectId) => {
  const project = projects.value.find((item) => item.id === projectId)
  if (project) aiForm.target_url = project.base_url || ''
}

const openAIDialog = () => {
  const project = projects.value.find((item) => item.id === filters.projectId) || projects.value[0]
  Object.assign(aiForm, {
    project_id: project?.id,
    target_url: project?.base_url || 'http://frontend:3000',
    goal: '',
    context: '',
    max_steps: 12,
    execution_mode: 'adaptive'
  })
  aiDraftReady.value = false
  aiWarnings.value = []
  aiDialogVisible.value = true
}

const generateAIDraft = async () => {
  aiGenerating.value = true
  try {
    const result = await api.post('/ui-cases/ai/generate', {
      project_id: aiForm.project_id,
      target_url: aiForm.target_url.trim(),
      goal: aiForm.goal.trim(),
      context: aiForm.context.trim() || null,
      max_steps: aiForm.max_steps,
      execution_mode: aiForm.execution_mode
    })
    const draft = result.draft
    Object.assign(temp, {
      project_id: draft.project_id, name: draft.name, folder_path: draft.folder_path || '', target_url: draft.target_url,
      priority: draft.priority || 'P2', status: draft.status || 'ACTIVE', review_status: 'DRAFT',
      version_no: draft.version_no || '1.0.0', review_note: '', expect_text: draft.expect_text,
      tags_json: [...(draft.tags_json || [])], steps: (draft.steps_json || []).map((step) => withKey(normalizeUiStep(step))),
      assertions: (draft.assertions_json || []).map((assertion) => withKey(normalizeUiAssertion(assertion))),
      generation_mode: draft.generation_mode || 'ai_skill', ai_goal: draft.ai_goal || aiForm.goal.trim(),
      execution_mode: draft.execution_mode || aiForm.execution_mode, self_heal_enabled: Boolean(draft.self_heal_enabled),
      max_agent_steps: draft.max_agent_steps || aiForm.max_steps, allowed_origins_json: [...(draft.allowed_origins_json || [])],
      prohibited_actions_json: [...(draft.prohibited_actions_json || [])],
      skill_name: draft.skill_name || result.skill_name, skill_version: draft.skill_version || result.skill_version,
      generation_meta_json: draft.generation_meta_json || null
    })
    aiWarnings.value = result.warnings || []
    aiDraftReady.value = true
    if (result.warnings?.length) ElMessage.warning(`已生成测试步骤，其中 ${result.warnings.length} 项需要留意`)
    else ElMessage.success('测试步骤已生成')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    aiGenerating.value = false
  }
}

const resetAIDraft = () => {
  aiDraftReady.value = false
  aiWarnings.value = []
}

const openAIDraftInEditor = () => {
  aiDialogVisible.value = false
  isEditing.value = false
  editingCaseId.value = null
  editorTab.value = 'steps'
  editorVisible.value = true
  nextTick(() => editorFormRef.value?.clearValidate())
}

const handleCreate = () => {
  resetTemp()
  isEditing.value = false
  editingCaseId.value = null
  editorTab.value = 'basic'
  editorVisible.value = true
  nextTick(() => editorFormRef.value?.clearValidate())
}

const handleEdit = (row) => {
  Object.assign(temp, {
    project_id: row.project_id, name: row.name, folder_path: row.folder_path || '', target_url: row.target_url,
    priority: row.priority || 'P2', status: row.status || 'ACTIVE', review_status: row.review_status || 'DRAFT',
    version_no: row.version_no || '1.0.0', review_note: row.review_note || '', expect_text: row.expect_text,
    tags_json: [...(row.tags_json || [])], steps: (row.steps_json || []).map((step) => withKey(normalizeUiStep(step))),
    assertions: (row.assertions_json || []).map((assertion) => withKey(normalizeUiAssertion(assertion))),
    generation_mode: row.generation_mode || 'manual', ai_goal: row.ai_goal || '', skill_name: row.skill_name || '',
    execution_mode: row.execution_mode || 'stable', self_heal_enabled: Boolean(row.self_heal_enabled),
    max_agent_steps: row.max_agent_steps || 10, allowed_origins_json: [...(row.allowed_origins_json || [])],
    prohibited_actions_json: [...(row.prohibited_actions_json || [])],
    skill_version: row.skill_version || '', generation_meta_json: row.generation_meta_json || null
  })
  isEditing.value = true
  editingCaseId.value = row.id
  editorTab.value = 'basic'
  editorVisible.value = true
  nextTick(() => editorFormRef.value?.clearValidate())
}

const stepDefinition = (step) => getStepDefinition(step.action)
const assertionDefinition = (assertion) => getAssertionDefinition(assertion.type)
const addStep = () => temp.steps.push(withKey(createUiStep('click')))
const addAssertion = () => temp.assertions.push(withKey(createUiAssertion()))
const changeStepAction = (step, action) => Object.assign(step, withKey(createUiStep(action)), { action })
const changeAssertionType = (assertion, type) => Object.assign(assertion, withKey(createUiAssertion(type)), { type })
const duplicateStep = (index) => temp.steps.splice(index + 1, 0, withKey({ ...temp.steps[index] }))
const moveItem = (items, index, offset) => {
  const target = index + offset
  if (target < 0 || target >= items.length) return
  const [item] = items.splice(index, 1)
  items.splice(target, 0, item)
}

const buildTempPayload = () => ({
  project_id: temp.project_id,
  name: temp.name.trim(),
  folder_path: temp.folder_path.trim() || null,
  target_url: temp.target_url.trim(),
  priority: temp.priority,
  status: temp.status,
  review_status: temp.review_status,
  version_no: temp.version_no,
  review_note: temp.review_note.trim() || null,
  tags_json: temp.tags_json.length ? temp.tags_json : null,
  steps_json: serializeUiSteps(temp.steps),
  assertions_json: temp.assertions.length ? serializeUiAssertions(temp.assertions) : null,
  expect_text: temp.expect_text.trim(),
  generation_mode: temp.generation_mode || 'manual',
  ai_goal: temp.ai_goal.trim() || null,
  execution_mode: temp.execution_mode || 'stable',
  self_heal_enabled: Boolean(temp.self_heal_enabled),
  max_agent_steps: temp.max_agent_steps || 10,
  allowed_origins_json: temp.allowed_origins_json.length ? temp.allowed_origins_json : null,
  prohibited_actions_json: temp.prohibited_actions_json.length ? temp.prohibited_actions_json : null,
  skill_name: temp.skill_name || null,
  skill_version: temp.skill_version || null,
  generation_meta_json: temp.generation_meta_json
})

const validateTempWorkflow = () => {
  if (!temp.project_id || !temp.name.trim() || !temp.target_url.trim() || !temp.expect_text.trim()) {
    ElMessage.error('AI 草稿缺少名称、地址或通过条件，请返回修改后重新生成')
    return false
  }
  const workflowErrors = validateUiWorkflow(temp.steps, temp.assertions)
  if (workflowErrors.length) {
    ElMessage.error(workflowErrors[0])
    return false
  }
  return true
}

const saveData = async () => {
  const valid = await editorFormRef.value?.validate().catch(() => false)
  if (!valid) {
    editorTab.value = temp.expect_text ? 'basic' : 'assertions'
    return
  }
  const workflowErrors = validateUiWorkflow(temp.steps, temp.assertions)
  if (workflowErrors.length) {
    editorTab.value = workflowErrors[0].startsWith('步骤') ? 'steps' : 'assertions'
    ElMessage.error(workflowErrors[0])
    return
  }
  saving.value = true
  try {
    const payload = buildTempPayload()
    if (isEditing.value) await api.put(`/ui-cases/${editingCaseId.value}`, payload)
    else await api.post('/ui-cases', payload)
    editorVisible.value = false
    ElMessage.success(isEditing.value ? 'UI 用例已更新' : 'UI 用例已创建')
    await getList()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

const saveAIDraft = async (runAfterSave) => {
  if (!validateTempWorkflow()) return
  if (runAfterSave) aiSavingRun.value = true
  else saving.value = true
  let created = null
  try {
    created = await api.post('/ui-cases', buildTempPayload())
    await getList()
    if (!runAfterSave) {
      aiDialogVisible.value = false
      ElMessage.success('UI 用例已保存')
      return
    }

    const precheck = await api.get(`/executions/ui/${created.id}/precheck`)
    if (!precheck.is_valid) {
      aiDialogVisible.value = false
      throw new Error(`用例已保存，但试运行前校验未通过：${precheck.summary}`)
    }
    const run = await api.post(`/executions/ui/${created.id}/run`, {
      environment_id: null,
      timeout_seconds: 60,
      max_retries: 0
    })
    aiDialogVisible.value = false
    ElMessage.success(`用例已保存，试运行 #${run.id} 已提交`)
    await openCaseDetail(created, 'runs')
    await selectRun(run)
    startPolling()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
    aiSavingRun.value = false
  }
}

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(`确认删除 UI 用例「${row.name}」？`, '删除确认', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await api.delete(`/ui-cases/${row.id}`)
    ElMessage.success('UI 用例已删除')
    await getList()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error.message)
  }
}

const handleRun = async (row) => {
  Object.assign(runForm, { case_id: row.id, project_id: row.project_id, environment_id: undefined, timeout_seconds: 60, max_retries: 0 })
  precheckResult.value = null
  try {
    environments.value = await api.get(`/environments?project_id=${row.project_id}`)
    runDialogVisible.value = true
  } catch (error) { ElMessage.error(error.message) }
}
const precheckRun = async () => {
  const suffix = runForm.environment_id ? `?environment_id=${runForm.environment_id}` : ''
  precheckResult.value = await api.get(`/executions/ui/${runForm.case_id}/precheck${suffix}`)
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
    const run = await api.post(`/executions/ui/${runForm.case_id}/run`, { environment_id: runForm.environment_id, timeout_seconds: runForm.timeout_seconds, max_retries: runForm.max_retries })
    runDialogVisible.value = false
    ElMessage.success(`执行 #${run.id} 已提交`)
    const row = list.value.find((item) => item.id === runForm.case_id)
    if (row) await openCaseDetail(row, 'runs')
    await selectRun(run)
    startPolling()
  } catch (error) { ElMessage.error(error.message) } finally { submittingRun.value = false }
}

const openCaseDetail = async (row, tab = 'definition') => {
  try {
    currentCase.value = await api.get(`/ui-cases/${row.id}`)
    caseRuns.value = await api.get(`/executions/runs?case_type=UI&case_id=${row.id}&limit=100`)
    detailTab.value = tab
    detailVisible.value = true
    if (tab === 'runs' && caseRuns.value.length) await selectRun(caseRuns.value[0])
  } catch (error) { ElMessage.error(error.message) }
}

const normalizeRunSteps = (rows, fallback) => {
  if (rows?.length) return rows.map((row) => row.raw_json || { name: row.name, status: row.status, duration_ms: row.duration_ms, detail: row.detail })
  return fallback || []
}
const selectRun = async (run) => {
  if (!run?.id) return
  runDetailLoading.value = true
  revokePreview()
  try {
    const [detail, steps, artifacts] = await Promise.all([
      api.get(`/executions/runs/${run.id}`), api.get(`/executions/runs/${run.id}/steps`), api.get(`/executions/runs/${run.id}/artifacts`)
    ])
    selectedRun.value = detail
    selectedRunSteps.value = normalizeRunSteps(steps, detail.step_results_json)
    selectedRunArtifacts.value = artifacts.artifacts || []
    const imageIndex = selectedRunArtifacts.value.findIndex(isImageArtifact)
    if (imageIndex >= 0) await previewArtifact(imageIndex, selectedRunArtifacts.value[imageIndex])
    if (['PENDING', 'RUNNING'].includes(detail.status)) startPolling()
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
        caseRuns.value = await api.get(`/executions/runs?case_type=UI&case_id=${detail.case_id}&limit=100`)
        await selectRun(detail)
        await getList()
      }
    } catch { stopPolling() }
  }, 2000)
}
const stopPolling = () => { if (pollTimer) window.clearInterval(pollTimer); pollTimer = null }
const revokePreview = () => { if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
const isImageArtifact = (artifact) => /\.(png|jpe?g|webp)$/i.test(artifact?.name || '') || ['png', 'jpg', 'jpeg', 'webp'].includes(String(artifact?.type || '').toLowerCase())
const previewArtifact = async (index, artifact) => {
  if (!selectedRun.value || !isImageArtifact(artifact)) return
  try { revokePreview(); previewUrl.value = URL.createObjectURL(await api.getBlob(`/executions/runs/${selectedRun.value.id}/artifacts/${index}/download`)) } catch (error) { ElMessage.error(error.message) }
}
const downloadArtifact = async (index, artifact) => {
  try {
    const blob = await api.getBlob(`/executions/runs/${selectedRun.value.id}/artifacts/${index}/download`)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = artifact.name || `artifact-${index}`; link.click(); URL.revokeObjectURL(url)
  } catch (error) { ElMessage.error(error.message) }
}

const exportCurrentCases = async () => {
  try {
    const params = new URLSearchParams({ case_type: 'UI' })
    if (filters.projectId) params.set('project_id', String(filters.projectId))
    if (filters.status) params.set('status', filters.status)
    if (filters.priority) params.set('priority', filters.priority)
    if (filters.keyword.trim()) params.set('keyword', filters.keyword.trim())
    const payload = await api.get(`/cases/export?${params}`)
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = `ui-cases-${Date.now()}.json`; link.click(); URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${payload.count || 0} 条 UI 用例`)
  } catch (error) { ElMessage.error(error.message) }
}
const openImportDialog = () => {
  importText.value = JSON.stringify({ items: [{ case_type: 'UI', project_id: projects.value[0]?.id || 1, name: '示例 UI 用例', target_url: 'http://frontend:3000', steps_json: [], assertions_json: [], expect_text: '登录' }] }, null, 2)
  importVisible.value = true
}
const handleImportFile = async (file) => { try { importText.value = await file.raw.text() } catch { ElMessage.error('文件读取失败') } }
const submitImportCases = async () => {
  try {
    const payload = JSON.parse(importText.value || '{}')
    if (!Array.isArray(payload.items) || payload.items.some((item) => item.case_type !== 'UI')) throw new Error('导入文件只能包含 UI 用例')
    await api.post('/cases/import', payload); importVisible.value = false; ElMessage.success('UI 用例导入成功'); await getList()
  } catch (error) { ElMessage.error(error.message) }
}

const priorityTag = (priority) => ({ P0: 'danger', P1: 'warning', P2: '', P3: 'info' }[priority] || 'info')
const caseStatusText = (status) => ({ ACTIVE: '启用', INACTIVE: '停用' }[status] || status)
const reviewText = (status) => ({ DRAFT: '草稿', IN_REVIEW: '评审中', APPROVED: '已通过', REJECTED: '已拒绝' }[status] || status)
const reviewTag = (status) => ({ APPROVED: 'success', IN_REVIEW: 'warning', REJECTED: 'danger', DRAFT: 'info' }[status] || 'info')
const stepLabel = (action) => UI_STEP_OPTIONS.find((item) => item.value === action)?.label || action
const assertionLabel = (type) => UI_ASSERTION_OPTIONS.find((item) => item.value === type)?.label || (type === 'text_present' ? '文本可见' : type)
const executionModeText = (mode) => ({ stable: '稳定回归', adaptive: '适应执行', explore: '自主探索', visual: '视觉测试' }[mode] || '稳定回归')
const executionModeDescription = (mode) => ({
  stable: '本地语义定位优先，适合日常回归和发布门禁。',
  adaptive: '页面变化时允许一次受控 AI 定位恢复，断言仍按保存规则执行。',
  explore: 'AI 在安全边界内按目标探索并记录发现，不作为发布门禁。',
  visual: '在确定性步骤之外使用多模态模型检查布局和视觉期望。'
}[mode] || '')
const formatShortTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'
const formatDuration = (value) => value === null || value === undefined ? '-' : value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(1)}s`
const formatStepDetail = (detail) => {
  if (!detail) return '-'
  if (typeof detail === 'string') return detail
  const resolution = detail.resolution
  const resolutionText = resolution?.method && resolution.method !== 'not_applicable'
    ? `定位：${({ test_id: 'test-id', role_name: '角色/名称', label: '标签', placeholder: '占位文本', visible_text: '可见文本', selector_fallback: '选择器兜底', ai_healing: 'AI 自愈', ai_exploration: 'AI 探索', visual_model: 'AI 视觉' }[resolution.method] || resolution.method)}`
    : ''
  const parts = [detail.action, detail.target, detail.selector, detail.value, resolutionText, detail.error].filter(Boolean)
  return parts.join(' · ') || JSON.stringify(detail)
}

watch(() => filters.projectId, () => {
  selectedFolder.value = ''
  page.value = 1
  refreshAll()
})
watch([() => filters.status, () => filters.priority, () => filters.reviewStatus], () => {
  page.value = 1
  getList()
})
watch(() => filters.keyword, () => {
  clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    getList()
  }, 300)
})
watch(selectedFolder, () => {
  page.value = 1
  getList()
})
watch(page, () => getList())
watch(pageSize, () => {
  page.value = 1
  getList()
})

onMounted(async () => {
  await loadProjects()
  await refreshAll()
})
onUnmounted(() => { stopPolling(); revokePreview() })
</script>

<style scoped>
.ui-case-page { min-width: 0; }
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
.filter-bar { min-height: 62px; padding: 12px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.filter-control { width: 190px; }
.filter-control--short { width: 140px; }
.filter-search { width: min(360px, 32vw); }
.filter-result { margin-left: auto; color: var(--color-text-secondary); font-size: 13px; white-space: nowrap; }
.case-table { width: 100%; }
.case-name { border: 0; padding: 0; background: none; color: var(--el-color-primary); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.case-name:hover { text-decoration: underline; }
.case-meta { margin-top: 5px; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; color: var(--color-text-secondary); font-size: 11px; line-height: 1.4; }
.last-run { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }
.muted { color: var(--color-text-secondary); }
.row-actions { display: flex; justify-content: flex-end; gap: 6px; }
.mobile-cards { display: none; }
:deep(.case-table .el-table__header th) { height: 44px; background: #f8fafc; color: #667085; font-weight: 600; }
:deep(.case-table .el-table__row td) { padding: 12px 0; }
:deep(.case-table .el-table__row:hover > td) { background: #f8faff !important; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.form-grid__wide { grid-column: 1 / -1; }
.ai-form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
.ai-origin { min-height: 38px; margin-bottom: 16px; display: flex; align-items: center; gap: 10px; color: var(--color-text-secondary); font-size: 13px; }
.field-help { margin-top: 7px; color: var(--color-text-secondary); font-size: 12px; line-height: 1.5; }
.runtime-config { margin: 8px 0 14px; padding: 14px; border: 1px solid var(--el-border-color); background: #f8fafc; }
.runtime-config__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.runtime-config__head div { display: flex; flex-direction: column; gap: 4px; }
.runtime-config__head strong { font-size: 14px; }
.runtime-config__head span { color: var(--color-text-secondary); font-size: 12px; }
.runtime-config > .el-form-item:last-child { margin-bottom: 0; }
.editor-tabs :deep(.el-tabs__content) { min-height: 480px; max-height: 62vh; overflow: auto; padding: 4px 2px 12px; }
.builder-toolbar { display: flex; align-items: center; justify-content: space-between; margin: 2px 0 12px; }
.builder-toolbar--bordered { padding-top: 14px; border-top: 1px solid var(--el-border-color-lighter); }
.builder-count { color: var(--color-text-secondary); font-size: 13px; }
.builder-list { display: grid; gap: 10px; }
.builder-row { border: 1px solid var(--el-border-color); border-radius: 6px; padding: 12px; background: #fff; }
.builder-row__head { display: grid; grid-template-columns: 32px 180px minmax(180px, 1fr) auto; gap: 10px; align-items: center; }
.builder-index { width: 28px; height: 28px; display: grid; place-items: center; border: 1px solid var(--el-border-color); border-radius: 50%; color: var(--color-text-secondary); font-size: 12px; }
.builder-action { width: 180px; }
.builder-actions { display: flex; }
.builder-fields { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 10px 0 0 42px; }
.builder-fields > .el-input, .builder-fields > .el-select { flex: 1; min-width: 0; }
.semantic-fields { flex: 1 0 100%; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.dimension-separator { color: var(--color-text-secondary); }
.dialog-version { margin-right: auto; color: var(--color-text-secondary); font-size: 12px; }
:deep(.el-dialog__footer) { display: flex; align-items: center; }
.run-options { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.run-options :deep(.el-input-number) { width: 100%; }
.precheck-panel { display: flex; gap: 10px; align-items: flex-start; padding: 12px; border: 1px solid var(--el-color-success-light-5); background: var(--el-color-success-light-9); color: var(--el-color-success); border-radius: 6px; }
.precheck-panel.is-invalid { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.precheck-vars { margin-top: 4px; font-size: 12px; }
.drawer-title { width: 100%; display: flex; align-items: center; justify-content: space-between; padding-right: 16px; }
.drawer-title div { display: flex; flex-direction: column; gap: 3px; }
.drawer-title strong { color: var(--color-text); font-size: 17px; }
.drawer-title span { color: var(--color-text-secondary); font-size: 12px; }
.detail-section { margin-top: 22px; }
.detail-section__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.detail-section h3, .run-detail h3, .run-detail h4 { margin: 0; font-size: 14px; }
.detail-section__head span { color: var(--color-text-secondary); font-size: 12px; }
.definition-list { border-top: 1px solid var(--el-border-color-lighter); }
.definition-item { display: grid; grid-template-columns: 30px minmax(0, 1fr); gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--el-border-color-lighter); }
.definition-item > span { color: var(--color-text-secondary); font-size: 12px; }
.definition-item strong { display: block; font-size: 13px; }
.definition-item code, .definition-item p { display: block; margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.run-list-toolbar { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.run-detail { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--el-border-color); }
.run-detail__head { display: flex; justify-content: space-between; align-items: flex-start; }
.run-detail__head p { margin: 5px 0 0; color: var(--color-text-secondary); font-size: 12px; }
.run-technical { margin-top: 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 0 12px; }
.run-technical pre { max-height: 260px; margin: 0; padding: 10px; overflow: auto; background: #f7f8fa; color: var(--color-text-secondary); border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.55; }
.runtime-evidence { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 12px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); background: #f8fafc; font-size: 12px; color: var(--color-text-secondary); }
.runtime-evidence strong { margin-left: 4px; color: var(--color-text); }
.run-detail-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(240px, .8fr); gap: 20px; margin-top: 18px; }
.run-steps h4, .run-artifacts h4 { margin-bottom: 10px; }
.run-step { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; gap: 8px; padding: 9px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.run-step .is-success { color: var(--el-color-success); }
.run-step .is-failed { color: var(--el-color-danger); }
.run-step strong { font-size: 12px; }
.run-step p { margin: 3px 0 0; color: var(--color-text-secondary); font-size: 11px; overflow-wrap: anywhere; }
.run-step > span { color: var(--color-text-secondary); font-size: 11px; }
.artifact-item { width: 100%; display: grid; grid-template-columns: 20px minmax(0, 1fr) 30px; gap: 8px; align-items: center; padding: 6px 4px; border: 0; border-bottom: 1px solid var(--el-border-color-lighter); background: none; cursor: pointer; text-align: left; }
.artifact-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.artifact-preview { margin-top: 12px; border: 1px solid var(--el-border-color); background: #f7f8fa; min-height: 180px; display: grid; place-items: center; }
.artifact-preview img { display: block; max-width: 100%; max-height: 360px; object-fit: contain; }
.import-editor { margin-top: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

@media (max-width: 900px) {
  .case-layout { grid-template-columns: 1fr; }
  .case-layout__tree { display: none; }
  .tree-drawer-trigger { display: inline-flex; }
  .summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n+2) { border-bottom: 1px solid var(--el-border-color-lighter); }
  .filter-bar { flex-wrap: wrap; }
  .filter-control, .filter-control--short, .filter-search { width: calc(50% - 5px); }
  .filter-result { width: 100%; margin-left: 0; }
  .case-table { display: none; }
  .mobile-cards { display: grid; gap: 10px; padding: 12px; }
  .mobile-case { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 6px; }
  .mobile-case__title { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
  .case-sequence { flex: 0 0 auto; color: var(--color-text-secondary); font-size: 12px; }
  .mobile-case__tags { display: flex; gap: 6px; margin: 8px 0; }
  .mobile-case__url { margin-bottom: 10px; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
  .form-grid { grid-template-columns: 1fr; }
  .form-grid__wide { grid-column: auto; }
  .ai-form-grid { grid-template-columns: 1fr; gap: 0; }
  .builder-row__head { grid-template-columns: 32px minmax(0, 1fr) auto; }
  .builder-row__head > .el-input { grid-column: 2 / -1; }
  .builder-action { width: 100%; }
  .builder-fields { padding-left: 0; flex-wrap: wrap; }
  .semantic-fields { grid-template-columns: 1fr; }
  .run-detail-grid { grid-template-columns: 1fr; }
}
</style>
