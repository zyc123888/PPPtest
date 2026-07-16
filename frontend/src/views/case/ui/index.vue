<template>
  <div class="app-page ui-case-page">
    <PageHeader title="UI 用例" subtitle="编排浏览器步骤、断言并查看执行证据">
      <template #actions>
        <el-tooltip content="导入 UI 用例" placement="bottom">
          <el-button :icon="Upload" aria-label="导入 UI 用例" @click="openImportDialog" />
        </el-tooltip>
        <el-tooltip content="导出当前结果" placement="bottom">
          <el-button :icon="Download" aria-label="导出当前结果" @click="exportCurrentCases" />
        </el-tooltip>
        <el-tooltip content="刷新" placement="bottom">
          <el-button :icon="Refresh" aria-label="刷新 UI 用例" :loading="listLoading" @click="getList" />
        </el-tooltip>
        <el-button v-if="canTest" :icon="MagicStick" @click="openAIDialog">AI 创建</el-button>
        <el-button v-if="canTest" type="primary" :icon="Plus" @click="handleCreate">新增 UI 用例</el-button>
      </template>
    </PageHeader>

    <section class="summary-strip section-gap" aria-label="UI 用例概览">
      <div class="summary-item">
        <span class="summary-item__label">用例总数</span>
        <strong>{{ list.length }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-item__label">启用</span>
        <strong>{{ activeCount }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-item__label">已评审</span>
        <strong>{{ approvedCount }}</strong>
      </div>
      <div class="summary-item">
        <span class="summary-item__label">最近成功率</span>
        <strong>{{ recentSuccessRate }}</strong>
      </div>
    </section>

    <section class="workspace-panel">
      <div class="filter-bar">
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
        <el-input v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索名称、分组、地址或标签" class="filter-search" />
        <span class="filter-result">{{ filteredList.length }} 条</span>
      </div>

      <el-table v-loading="listLoading" :data="pagedList" class="case-table" row-key="id" @row-dblclick="openCaseDetail">
        <el-table-column label="用例" min-width="260">
          <template #default="scope">
            <button class="case-name" type="button" @click="openCaseDetail(scope.row)">{{ scope.row.name }}</button>
            <div class="case-meta">
              <span>{{ scope.row.folder_path || '未分组' }}</span>
              <span>v{{ scope.row.version_no }}</span>
              <span>{{ (scope.row.steps_json || []).length }} 步</span>
              <el-tag v-if="scope.row.generation_mode === 'ai_skill'" size="small" effect="plain">AI</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="项目" width="160" show-overflow-tooltip>
          <template #default="scope">{{ projectMap[scope.row.project_id] || scope.row.project_id }}</template>
        </el-table-column>
        <el-table-column label="优先级" width="90" align="center">
          <template #default="scope"><el-tag size="small" :type="priorityTag(scope.row.priority)">{{ scope.row.priority }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="scope"><el-tag size="small" :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(scope.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="评审" width="110" align="center">
          <template #default="scope"><el-tag size="small" effect="plain" :type="reviewTag(scope.row.review_status)">{{ reviewText(scope.row.review_status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="目标地址" prop="target_url" min-width="230" show-overflow-tooltip />
        <el-table-column label="最近执行" width="150">
          <template #default="scope">
            <div v-if="latestRunMap[scope.row.id]" class="last-run">
              <el-tag size="small" :type="executionStatusTag(latestRunMap[scope.row.id].status)">{{ executionStatusText(latestRunMap[scope.row.id].status) }}</el-tag>
              <span>{{ formatShortTime(latestRunMap[scope.row.id].created_at) }}</span>
            </div>
            <span v-else class="muted">未执行</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="right" width="176" fixed="right">
          <template #default="scope">
            <div class="row-actions">
              <el-tooltip content="查看详情" placement="top"><el-button circle size="small" :icon="View" aria-label="查看 UI 用例" @click="openCaseDetail(scope.row)" /></el-tooltip>
              <el-tooltip v-if="canTest" content="编辑" placement="top"><el-button circle size="small" :icon="Edit" aria-label="编辑 UI 用例" @click="handleEdit(scope.row)" /></el-tooltip>
              <el-tooltip v-if="canTest" content="立即执行" placement="top"><el-button circle size="small" type="primary" :icon="VideoPlay" aria-label="执行 UI 用例" @click="handleRun(scope.row)" /></el-tooltip>
              <el-tooltip v-if="canAdmin" content="删除" placement="top"><el-button circle size="small" type="danger" plain :icon="Delete" aria-label="删除 UI 用例" @click="handleDelete(scope.row)" /></el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <article v-for="item in pagedList" :key="item.id" class="mobile-case">
          <button class="case-name" type="button" @click="openCaseDetail(item)">{{ item.name }}</button>
          <div class="mobile-case__tags">
            <el-tag size="small" :type="priorityTag(item.priority)">{{ item.priority }}</el-tag>
            <el-tag size="small" :type="item.status === 'ACTIVE' ? 'success' : 'info'">{{ caseStatusText(item.status) }}</el-tag>
            <el-tag v-if="item.generation_mode === 'ai_skill'" size="small" effect="plain">AI</el-tag>
          </div>
          <div class="mobile-case__url">{{ item.target_url }}</div>
          <div class="row-actions">
            <el-button size="small" :icon="View" @click="openCaseDetail(item)">详情</el-button>
            <el-button v-if="canTest" size="small" type="primary" :icon="VideoPlay" @click="handleRun(item)">执行</el-button>
          </div>
        </article>
      </div>

      <div class="table-pagination">
        <el-pagination v-model:page-size="pageSize" v-model:current-page="page" layout="total, sizes, prev, pager, next" :total="filteredList.length" :page-sizes="[10, 20, 50]" />
      </div>
    </section>

    <el-dialog v-model="aiDialogVisible" title="AI 创建 UI 用例" width="min(680px, 94vw)" destroy-on-close>
      <el-form ref="aiFormRef" :model="aiForm" :rules="aiRules" label-position="top">
        <div class="ai-form-grid">
          <el-form-item label="所属项目" prop="project_id">
            <el-select v-model="aiForm.project_id" style="width: 100%" @change="handleAIProjectChange">
              <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="Skill">
            <el-input model-value="ui-case-designer · v1.0.0" disabled />
          </el-form-item>
        </div>
        <el-form-item label="目标地址" prop="target_url">
          <el-input v-model="aiForm.target_url" placeholder="https://example.com" />
        </el-form-item>
        <el-form-item label="测试目标" prop="goal">
          <el-input v-model="aiForm.goal" type="textarea" :rows="4" maxlength="4000" show-word-limit placeholder="例如：打开 Google，搜索 OmniTest，并验证结果页显示 OmniTest" />
        </el-form-item>
        <el-form-item label="补充上下文">
          <el-input v-model="aiForm.context" type="textarea" :rows="3" maxlength="8000" placeholder="可填写测试数据、登录前置条件或已知的稳定选择器" />
        </el-form-item>
        <el-form-item label="最多步骤">
          <el-input-number v-model="aiForm.max_steps" :min="1" :max="30" controls-position="right" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="aiDialogVisible = false">取消</el-button>
        <el-button type="primary" :icon="MagicStick" :loading="aiGenerating" @click="generateAIDraft">生成草稿</el-button>
      </template>
    </el-dialog>

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
              <el-form-item label="目录/分组"><el-input v-model="temp.folder_path" placeholder="例如：登录/核心流程" /></el-form-item>
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
              <el-form-item label="评审状态">
                <el-select v-model="temp.review_status" style="width: 100%">
                  <el-option label="草稿" value="DRAFT" /><el-option label="评审中" value="IN_REVIEW" /><el-option label="已通过" value="APPROVED" /><el-option label="已拒绝" value="REJECTED" />
                </el-select>
              </el-form-item>
              <el-form-item label="当前版本"><el-input v-model="temp.version_no" disabled /></el-form-item>
              <el-form-item label="评审备注" class="form-grid__wide"><el-input v-model="temp.review_note" type="textarea" :rows="3" /></el-form-item>
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
            <el-descriptions-item label="目标地址" :span="2">{{ currentCase.target_url }}</el-descriptions-item><el-descriptions-item label="最终文本" :span="2">{{ currentCase.expect_text }}</el-descriptions-item>
            <el-descriptions-item v-if="currentCase.ai_goal" label="测试目标" :span="2">{{ currentCase.ai_goal }}</el-descriptions-item>
          </el-descriptions>
          <section class="detail-section"><div class="detail-section__head"><h3>操作步骤</h3><span>{{ (currentCase.steps_json || []).length }} 步</span></div><div v-if="currentCase.steps_json?.length" class="definition-list"><div v-for="(step, index) in currentCase.steps_json" :key="index" class="definition-item"><span>{{ index + 1 }}</span><div><strong>{{ step.name || stepLabel(step.action) }}</strong><code v-if="step.selector">{{ step.selector }}</code><p v-if="step.value !== undefined">{{ step.value }}</p></div></div></div><el-empty v-else description="无附加步骤" :image-size="60" /></section>
          <section class="detail-section"><div class="detail-section__head"><h3>断言</h3><span>{{ (currentCase.assertions_json || []).length + 1 }} 项</span></div><div class="definition-list"><div class="definition-item"><span>1</span><div><strong>最终文本可见</strong><p>{{ currentCase.expect_text }}</p></div></div><div v-for="(assertion, index) in currentCase.assertions_json || []" :key="index" class="definition-item"><span>{{ index + 2 }}</span><div><strong>{{ assertion.name || assertionLabel(assertion.type) }}</strong><code v-if="assertion.selector">{{ assertion.selector }}</code><p>{{ assertion.value ?? assertion.expected }}</p></div></div></div></section>
        </el-tab-pane>
        <el-tab-pane :label="`执行记录 (${caseRuns.length})`" name="runs">
          <div class="run-list-toolbar"><el-button v-if="canTest" type="primary" :icon="VideoPlay" @click="handleRun(currentCase)">立即执行</el-button></div>
          <el-table :data="caseRuns" size="small" highlight-current-row @current-change="selectRun">
            <el-table-column label="执行" width="84"><template #default="scope">#{{ scope.row.id }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="executionStatusTag(scope.row.status)">{{ executionStatusText(scope.row.status) }}</el-tag></template></el-table-column><el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip /><el-table-column label="耗时" width="90"><template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template></el-table-column><el-table-column label="时间" width="145"><template #default="scope">{{ formatShortTime(scope.row.created_at) }}</template></el-table-column>
          </el-table>

          <section v-if="selectedRun" class="run-detail" v-loading="runDetailLoading">
            <div class="run-detail__head"><div><h3>执行 #{{ selectedRun.id }}</h3><p>{{ selectedRun.summary || '-' }}</p></div><el-tag :type="executionStatusTag(selectedRun.status)">{{ executionStatusText(selectedRun.status) }}</el-tag></div>
            <div v-if="selectedRun.stderr_text" class="run-error">{{ selectedRun.stderr_text }}</div>
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
  Bottom, CircleCheck, CopyDocument, Delete, Document, Download, Edit, MagicStick, Picture, Plus,
  Refresh, Search, Top, Upload, VideoPlay, View, WarningFilled
} from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import { usePermissions } from '@/lib/permissions'
import { executionStatusTag, executionStatusText } from '@/lib/execution'
import {
  UI_ASSERTION_OPTIONS, UI_STEP_OPTIONS, createUiAssertion, createUiStep,
  getAssertionDefinition, getStepDefinition, normalizeUiAssertion, normalizeUiStep,
  serializeUiAssertions, serializeUiSteps, validateUiWorkflow
} from '@/lib/uiCase'

const list = ref([])
const projects = ref([])
const environments = ref([])
const runs = ref([])
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
const aiFormRef = ref(null)
const { canAdmin, canTest } = usePermissions()
let itemKey = 0
let pollTimer = null

const filters = reactive({ projectId: undefined, status: '', priority: '', keyword: '' })
const page = ref(1)
const pageSize = ref(10)
const temp = reactive({
  project_id: undefined, name: '', folder_path: '', target_url: '', priority: 'P1', status: 'ACTIVE',
  review_status: 'DRAFT', version_no: '1.0.0', review_note: '', expect_text: '', tags_json: [], steps: [], assertions: [],
  generation_mode: 'manual', ai_goal: '', skill_name: '', skill_version: '', generation_meta_json: null
})
const aiForm = reactive({ project_id: undefined, target_url: '', goal: '', context: '', max_steps: 12 })
const runForm = reactive({ case_id: undefined, project_id: undefined, environment_id: undefined, timeout_seconds: 60, max_retries: 0 })
const rules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  name: [{ required: true, message: '请输入用例名称', trigger: 'blur' }, { min: 2, message: '名称至少 2 个字符', trigger: 'blur' }],
  target_url: [{ required: true, message: '请输入目标地址', trigger: 'blur' }],
  expect_text: [{ required: true, message: '请输入最终文本断言', trigger: 'blur' }]
}
const aiRules = {
  project_id: [{ required: true, message: '请选择项目', trigger: 'change' }],
  target_url: [{ required: true, message: '请输入目标地址', trigger: 'blur' }],
  goal: [{ required: true, message: '请输入测试目标', trigger: 'blur' }, { min: 5, message: '测试目标至少 5 个字符', trigger: 'blur' }]
}

const withKey = (item) => ({ ...item, _key: ++itemKey })
const projectMap = computed(() => Object.fromEntries(projects.value.map((item) => [item.id, item.name])))
const tagOptions = computed(() => [...new Set(list.value.flatMap((item) => item.tags_json || []))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const runEnvironmentOptions = computed(() => environments.value.filter((item) => item.project_id === runForm.project_id))
const activeCount = computed(() => list.value.filter((item) => item.status === 'ACTIVE').length)
const approvedCount = computed(() => list.value.filter((item) => item.review_status === 'APPROVED').length)
const recentSuccessRate = computed(() => {
  const recent = runs.value.slice(0, 50).filter((item) => !['PENDING', 'RUNNING'].includes(item.status))
  if (!recent.length) return '-'
  return `${Math.round(recent.filter((item) => item.status === 'SUCCESS').length / recent.length * 100)}%`
})
const latestRunMap = computed(() => {
  const map = {}
  runs.value.forEach((run) => { if (!map[run.case_id]) map[run.case_id] = run })
  return map
})
const filteredList = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return list.value.filter((item) => {
    if (filters.projectId && item.project_id !== filters.projectId) return false
    if (filters.status && item.status !== filters.status) return false
    if (filters.priority && item.priority !== filters.priority) return false
    if (!keyword) return true
    return [item.name, item.folder_path, item.target_url, ...(item.tags_json || [])].some((value) => String(value || '').toLowerCase().includes(keyword))
  })
})
const pagedList = computed(() => filteredList.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

watch(() => [filters.projectId, filters.status, filters.priority, filters.keyword], () => { page.value = 1 })

const getList = async () => {
  listLoading.value = true
  try {
    const [caseData, projectData, runData] = await Promise.all([
      api.get('/ui-cases'), api.get('/projects'), api.get('/executions/runs?case_type=UI&limit=200')
    ])
    list.value = caseData
    projects.value = projectData
    runs.value = runData
    if (currentCase.value) currentCase.value = caseData.find((item) => item.id === currentCase.value.id) || currentCase.value
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const resetTemp = () => {
  const project = projects.value[0]
  Object.assign(temp, {
    project_id: project?.id, name: '', folder_path: '', target_url: project?.base_url || 'http://frontend:3000',
    priority: 'P1', status: 'ACTIVE', review_status: 'DRAFT', version_no: '1.0.0', review_note: '',
    expect_text: '', tags_json: [], steps: [], assertions: [], generation_mode: 'manual', ai_goal: '',
    skill_name: '', skill_version: '', generation_meta_json: null
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
    max_steps: 12
  })
  aiDialogVisible.value = true
  nextTick(() => aiFormRef.value?.clearValidate())
}

const generateAIDraft = async () => {
  const valid = await aiFormRef.value?.validate().catch(() => false)
  if (!valid) return
  aiGenerating.value = true
  try {
    const result = await api.post('/ui-cases/ai/generate', {
      project_id: aiForm.project_id,
      target_url: aiForm.target_url.trim(),
      goal: aiForm.goal.trim(),
      context: aiForm.context.trim() || null,
      max_steps: aiForm.max_steps
    })
    const draft = result.draft
    Object.assign(temp, {
      project_id: draft.project_id, name: draft.name, folder_path: draft.folder_path || '', target_url: draft.target_url,
      priority: draft.priority || 'P2', status: draft.status || 'ACTIVE', review_status: 'DRAFT',
      version_no: draft.version_no || '1.0.0', review_note: '', expect_text: draft.expect_text,
      tags_json: [...(draft.tags_json || [])], steps: (draft.steps_json || []).map((step) => withKey(normalizeUiStep(step))),
      assertions: (draft.assertions_json || []).map((assertion) => withKey(normalizeUiAssertion(assertion))),
      generation_mode: draft.generation_mode || 'ai_skill', ai_goal: draft.ai_goal || aiForm.goal.trim(),
      skill_name: draft.skill_name || result.skill_name, skill_version: draft.skill_version || result.skill_version,
      generation_meta_json: draft.generation_meta_json || null
    })
    aiDialogVisible.value = false
    isEditing.value = false
    editingCaseId.value = null
    editorTab.value = 'steps'
    editorVisible.value = true
    if (result.warnings?.length) ElMessage.warning(`AI 草稿已生成，含 ${result.warnings.length} 项待确认`)
    else ElMessage.success('AI 草稿已生成，请确认后保存')
    nextTick(() => editorFormRef.value?.clearValidate())
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    aiGenerating.value = false
  }
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
    const payload = {
      project_id: temp.project_id, name: temp.name.trim(), folder_path: temp.folder_path.trim() || null,
      target_url: temp.target_url.trim(), priority: temp.priority, status: temp.status, review_status: temp.review_status,
      version_no: temp.version_no, review_note: temp.review_note.trim() || null, tags_json: temp.tags_json.length ? temp.tags_json : null,
      steps_json: serializeUiSteps(temp.steps), assertions_json: temp.assertions.length ? serializeUiAssertions(temp.assertions) : null,
      expect_text: temp.expect_text.trim(), generation_mode: temp.generation_mode || 'manual', ai_goal: temp.ai_goal.trim() || null,
      skill_name: temp.skill_name || null, skill_version: temp.skill_version || null, generation_meta_json: temp.generation_meta_json
    }
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
const formatShortTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'
const formatDuration = (value) => value === null || value === undefined ? '-' : value < 1000 ? `${value}ms` : `${(value / 1000).toFixed(1)}s`
const formatStepDetail = (detail) => {
  if (!detail) return '-'
  if (typeof detail === 'string') return detail
  const parts = [detail.action, detail.selector, detail.value, detail.error].filter(Boolean)
  return parts.join(' · ') || JSON.stringify(detail)
}

onMounted(getList)
onUnmounted(() => { stopPolling(); revokePreview() })
</script>

<style scoped>
.ui-case-page { min-width: 0; }
.summary-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--el-border-color-lighter); background: #fff; }
.summary-item { min-height: 76px; padding: 14px 20px; display: flex; flex-direction: column; justify-content: center; border-right: 1px solid var(--el-border-color-lighter); }
.summary-item:last-child { border-right: 0; }
.summary-item__label { color: var(--color-text-secondary); font-size: 12px; }
.summary-item strong { margin-top: 4px; font-size: 22px; line-height: 1.2; }
.workspace-panel { background: #fff; border: 1px solid var(--el-border-color-lighter); }
.filter-bar { min-height: 62px; padding: 12px 16px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid var(--el-border-color-lighter); }
.filter-control { width: 190px; }
.filter-control--short { width: 140px; }
.filter-search { width: min(360px, 32vw); }
.filter-result { margin-left: auto; color: var(--color-text-secondary); font-size: 13px; white-space: nowrap; }
.case-table { width: 100%; }
.case-name { border: 0; padding: 0; background: none; color: var(--el-color-primary); font: inherit; font-weight: 600; cursor: pointer; text-align: left; }
.case-name:hover { text-decoration: underline; }
.case-meta { margin-top: 5px; display: flex; gap: 12px; color: var(--color-text-secondary); font-size: 12px; }
.last-run { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 12px; }
.muted { color: var(--color-text-secondary); }
.row-actions { display: flex; justify-content: flex-end; gap: 6px; }
.mobile-cards { display: none; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; }
.form-grid__wide { grid-column: 1 / -1; }
.ai-form-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; }
.ai-origin { min-height: 38px; margin-bottom: 16px; display: flex; align-items: center; gap: 10px; color: var(--color-text-secondary); font-size: 13px; }
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
.builder-fields { display: flex; gap: 10px; align-items: center; padding: 10px 0 0 42px; }
.builder-fields > .el-input, .builder-fields > .el-select { flex: 1; min-width: 0; }
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
.run-error { margin-top: 12px; padding: 10px; background: var(--el-color-danger-light-9); color: var(--el-color-danger); border-radius: 4px; white-space: pre-wrap; font-size: 12px; }
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
  .summary-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(-n+2) { border-bottom: 1px solid var(--el-border-color-lighter); }
  .filter-bar { flex-wrap: wrap; }
  .filter-control, .filter-control--short, .filter-search { width: calc(50% - 5px); }
  .filter-result { width: 100%; margin-left: 0; }
  .case-table { display: none; }
  .mobile-cards { display: grid; gap: 10px; padding: 12px; }
  .mobile-case { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 6px; }
  .mobile-case__tags { display: flex; gap: 6px; margin: 8px 0; }
  .mobile-case__url { margin-bottom: 10px; color: var(--color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
  .form-grid { grid-template-columns: 1fr; }
  .form-grid__wide { grid-column: auto; }
  .ai-form-grid { grid-template-columns: 1fr; gap: 0; }
  .builder-row__head { grid-template-columns: 32px minmax(0, 1fr) auto; }
  .builder-row__head > .el-input { grid-column: 2 / -1; }
  .builder-action { width: 100%; }
  .builder-fields { padding-left: 0; flex-wrap: wrap; }
  .run-detail-grid { grid-template-columns: 1fr; }
}
</style>
