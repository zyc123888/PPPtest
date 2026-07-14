<template>
  <div class="app-page case-generator-page">
    <PageHeader title="用例生成2" subtitle="V2 unified skill 流程，支持轻量模式和可信模式。">
      <template #actions>
        <div class="header-actions">
          <el-button @click="fetchJobs">刷新</el-button>
          <el-button type="primary" :loading="submitting" :disabled="submitDisabled" @click="submitJob">开始生成</el-button>
        </div>
      </template>
    </PageHeader>

    <el-alert
      v-if="pageError"
      class="page-error-alert"
      :title="pageError"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="generator-layout">
      <el-card class="page-card generator-composer" shadow="never">
        <div class="panel-head">
          <div>
            <div class="panel-title">生成输入</div>
          </div>
          <el-tag type="success">V2 claw_5skill_unified</el-tag>
        </div>

        <el-form class="composer-form" label-position="top" :model="form">
          <el-form-item label="所属项目" required>
            <el-select v-model="form.project_id" placeholder="请选择项目" filterable>
              <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="任务名称" required>
            <el-input v-model="form.name" placeholder="例如：支付中心 PRD 初版用例生成" />
          </el-form-item>
          <el-form-item label="生成模式">
            <el-radio-group v-model="form.pipeline_mode" class="pipeline-mode-group">
              <el-radio-button
                v-for="item in pipelineModeOptions"
                :key="item.value"
                :value="item.value"
              >
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
            <div class="pipeline-mode-hint">{{ selectedPipelineModeHint }}</div>
          </el-form-item>
          <el-form-item v-if="form.pipeline_mode === 'trusted'" label="可信生成策略">
            <el-radio-group v-model="form.trusted_generation_strategy" class="pipeline-mode-group">
              <el-radio-button value="source_shard">按 source 分片</el-radio-button>
              <el-radio-button value="lite_review">轻量结果审查</el-radio-button>
            </el-radio-group>
            <div class="pipeline-mode-hint">
              {{ form.trusted_generation_strategy === 'source_shard'
                ? '每个 source 独立生成并保留用例追踪证据。'
                : '复用轻量结果后执行可信结构审查，仅适合作为快速预览。' }}
            </div>
          </el-form-item>
          <el-form-item label="模型配置">
            <div class="model-config-panel">
              <el-input
                v-model="modelConfig.name"
                placeholder="配置名称，例如：默认 GPT 配置"
              />
              <el-input
                v-model="modelConfig.api_key"
                type="password"
                show-password
                autocomplete="off"
                placeholder="工作空间级 API Key，保存后供新建和重跑任务复用"
              />
            </div>
          </el-form-item>
          <el-form-item label="模型">
            <el-select v-model="modelConfig.model" class="model-select" placeholder="请选择或输入模型" filterable allow-create default-first-option>
              <el-option-group
                v-for="group in groupedModelOptions"
                :key="group.label"
                :label="group.label"
              >
                <el-option
                  v-for="item in group.options"
                  :key="item.value"
                  :label="item.label"
                  :value="item.value"
                />
              </el-option-group>
            </el-select>
            <el-input
              v-model="modelConfig.base_url"
              placeholder="可选：自定义 OpenAI 兼容 base_url；不填则使用预设"
            />
            <div class="model-config-actions">
              <el-button size="small" @click="loadModelConfig">读取已保存配置</el-button>
              <el-button size="small" type="primary" :loading="savingModelConfig" @click="saveModelConfig">保存模型配置</el-button>
            </div>
          </el-form-item>
          <el-form-item label="需求来源">
            <el-radio-group v-model="form.source_type" class="source-type-group">
              <el-radio-button label="PASTE">粘贴文本</el-radio-button>
              <el-radio-button label="UPLOAD">上传文档</el-radio-button>
              <el-radio-button label="LINK">需求链接</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.source_type === 'PASTE'" label="需求 Markdown" required>
            <el-input
              v-model="form.markdown_text"
              type="textarea"
              :rows="7"
              placeholder="# 登录模块&#10;- 支持用户名密码登录&#10;- 首次登录需要验证码&#10;&#10;# 权限管理&#10;- 不同角色显示不同菜单"
            />
          </el-form-item>
          <el-form-item v-else-if="form.source_type === 'UPLOAD'" label="上传需求文档" required>
            <div class="upload-panel">
              <el-upload
                class="generator-upload"
                drag
                :auto-upload="false"
                :show-file-list="false"
                accept=".md,.markdown,.txt"
                action="#"
                :on-change="handleFileChange"
              >
                <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
                <div class="el-upload__text">拖拽文件到这里，或 <em>点击选择 .md / .txt</em></div>
                <template #tip>
                  <div class="el-upload__tip">文件不会直接上传到服务器，会先在浏览器中读取内容再提交生成任务。</div>
                </template>
              </el-upload>
              <div v-if="uploadedFileName" class="upload-result">
                <el-tag type="success">{{ uploadedFileName }}</el-tag>
                <span class="upload-result__meta">{{ uploadedCharCount }} 字</span>
              </div>
              <el-input
                v-model="form.markdown_text"
                type="textarea"
                :rows="7"
                readonly
                placeholder="读取后的文件内容会显示在这里"
              />
            </div>
          </el-form-item>
          <el-form-item v-else label="需求文档链接" required>
            <el-input
              v-model="form.source_url"
              placeholder="例如：https://docs.example.com/prd/login-center 或 raw markdown 链接"
            />
          </el-form-item>
          <div class="form-footer">
            <el-checkbox v-model="form.export_xmind" disabled>同时导出 XMind</el-checkbox>
            <el-tag type="info">默认开启</el-tag>
          </div>
        </el-form>
      </el-card>

      <div class="generator-side">
        <el-card class="page-card side-card" shadow="never">
          <div class="panel-head">
            <div>
              <div class="panel-title">最近任务</div>
            </div>
            <div class="job-filters">
              <el-select v-model="jobModeFilter" class="job-filter" size="small" clearable placeholder="全部模式" @change="fetchJobs">
                <el-option label="轻量" value="lite" />
                <el-option label="可信" value="trusted" />
              </el-select>
              <el-select v-model="jobStatusFilter" class="job-filter" size="small" clearable placeholder="全部状态" @change="fetchJobs">
                <el-option label="进行中" value="RUNNING" />
                <el-option label="成功" value="SUCCESS" />
                <el-option label="有条件" value="CONDITIONAL" />
                <el-option label="失败" value="FAILED" />
                <el-option label="已取消" value="CANCELLED" />
              </el-select>
            </div>
          </div>
          <div class="job-list">
            <div v-if="pinnedRunningJob" class="job-pinned">
              <div class="job-pinned__label">进行中</div>
              <div
                class="job-item job-item--pinned"
                :class="{ active: currentJob?.id === pinnedRunningJob.id }"
                role="button"
                tabindex="0"
                @click="selectJob(pinnedRunningJob)"
                @keydown.enter.prevent="selectJob(pinnedRunningJob)"
                @keydown.space.prevent="selectJob(pinnedRunningJob)"
              >
                <div class="job-item__title">{{ pinnedRunningJob.name }}</div>
                <div class="job-item__meta">
                  <span>#{{ pinnedRunningJob.id }}</span>
                  <CaseGenerationModeBadge :mode="jobPipelineMode(pinnedRunningJob)" />
                  <el-tag size="small" :type="statusTagType(pinnedRunningJob.status)">{{ pinnedRunningJob.status }}</el-tag>
                </div>
                <div class="job-item__desc">{{ formatJobListSummary(pinnedRunningJob) }}</div>
              </div>
            </div>

            <div
              v-for="item in jobList"
              :key="item.id"
              class="job-item"
              :class="{ active: currentJob?.id === item.id }"
              role="button"
              tabindex="0"
              @click="selectJob(item)"
              @keydown.enter.prevent="selectJob(item)"
              @keydown.space.prevent="selectJob(item)"
            >
              <div class="job-item__title">{{ item.name }}</div>
              <div class="job-item__meta">
                <span>#{{ item.id }}</span>
                <CaseGenerationModeBadge :mode="jobPipelineMode(item)" />
                <el-tag size="small" :type="statusTagType(item.status)">{{ item.status }}</el-tag>
              </div>
              <div class="job-item__desc">{{ formatJobListSummary(item) }}</div>
            </div>
            <el-empty v-if="!jobs.length" description="暂无生成任务" />
            <el-button v-if="jobsHasMore" class="load-more-button" :loading="loadingMoreJobs" @click="loadMoreJobs">加载更多</el-button>
          </div>
        </el-card>

        <el-card class="page-card side-card" shadow="never">
          <div class="panel-head">
            <div>
              <div class="panel-title">结果详情</div>
            </div>
            <div class="detail-actions">
              <div class="detail-actions__primary">
                <el-button v-if="canRerunCurrentJob" size="small" :loading="rerunning" :disabled="rerunDisabled" @click="rerunJob">重跑</el-button>
                <el-button v-if="canCancelCurrentJob" size="small" type="danger" plain @click="cancelJob">停止任务</el-button>
              </div>
              <el-button v-if="currentJob" size="small" class="detail-actions__secondary" @click="refreshCurrentJob">刷新详情</el-button>
            </div>
          </div>

          <div class="detail-body">
            <el-empty v-if="!currentJob" description="请选择一个任务查看详情" />

            <template v-else>
              <div class="detail-summary">
                <div class="summary-line"><span>状态</span><el-tag :type="statusTagType(currentJob.status)">{{ currentJob.status }}</el-tag></div>
                <div class="summary-line"><span>生成模式</span><strong>{{ pipelineModeLabel(currentPipelineMode) }}</strong></div>
                <div class="summary-line" v-if="isTrustedCurrentJob">
                  <span>生成策略</span>
                  <strong>{{ trustedGenerationStrategyLabel(currentJob.input_payload_json?.trusted_generation_strategy) }}</strong>
                </div>
                <div class="summary-line" v-if="isTrustedCurrentJob && scopeIndexStrategy">
                  <span>索引策略</span>
                  <strong>{{ scopeIndexStrategyText }}</strong>
                </div>
                <div class="summary-line" v-if="isTrustedCurrentJob && finalDeliveryGatePassed !== null">
                  <span>交付门禁</span>
                  <el-tag :type="finalDeliveryGatePassed ? 'success' : 'danger'">{{ finalDeliveryGatePassed ? '通过' : '未通过' }}</el-tag>
                </div>
                <div class="summary-line"><span>摘要</span><strong>{{ currentJob.summary || '-' }}</strong></div>
                <div class="summary-line"><span>来源</span><span>{{ currentJob.source_document_name || '-' }}</span></div>
                <div class="summary-line" v-if="currentJob.error_message"><span>错误</span><span class="error-text">{{ currentJob.error_message }}</span></div>
              </div>

              <div v-if="isTrustedCurrentJob && trustedMetrics" class="trusted-metrics">
                <div class="trusted-metric">
                  <span>直接测试对象数</span>
                  <strong>{{ trustedMetrics.source_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>功能点数</span>
                  <strong>{{ trustedMetrics.function_point_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>用例数</span>
                  <strong>{{ trustedMetrics.testcase_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>FP 回执完整率</span>
                  <strong>{{ formatRate(trustedMetrics.function_point_receipt_rate ?? trustedMetrics.function_point_consumption_rate) }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>结构追溯完整率</span>
                  <strong>{{ formatRate(trustedMetrics.source_traceability_rate ?? trustedMetrics.source_with_testcase_rate ?? trustedMetrics.source_coverage_rate) }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>预期依据完整率</span>
                  <strong>{{ formatRate(trustedMetrics.assertion_basis_rate) }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>图片证据用例率</span>
                  <strong>{{ formatRate(trustedMetrics.concrete_image_evidence_rate) }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>must_cover 语义覆盖</span>
                  <strong>{{ formatRate(trustedMetrics.semantic_must_cover_rate) }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>合并覆盖数</span>
                  <strong>{{ trustedMetrics.merged_coverage_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>重复合并数</span>
                  <strong>{{ trustedMetrics.duplicate_case_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>must_cover 缺口</span>
                  <strong>{{ trustedMetrics.must_cover_gap_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>方法消费缺口</span>
                  <strong>{{ trustedMetrics.method_gap_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>待确认数量</span>
                  <strong>{{ trustedMetrics.pending_confirmation_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>弱预期数量</span>
                  <strong>{{ trustedMetrics.weak_expected_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>模糊步骤数</span>
                  <strong>{{ trustedMetrics.ambiguous_step_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>不可验证预期</span>
                  <strong>{{ trustedMetrics.unverifiable_expectation_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>无依据断言</span>
                  <strong>{{ trustedMetrics.unsupported_assertion_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>证据错绑</span>
                  <strong>{{ trustedMetrics.evidence_mismatch_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>旧状态误作预期</span>
                  <strong>{{ trustedMetrics.current_state_as_expected_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>精确验收值丢失</span>
                  <strong>{{ trustedMetrics.exact_value_loss_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>门禁阻断数</span>
                  <strong>{{ trustedMetrics.gate_blocker_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric">
                  <span>风险提示数</span>
                  <strong>{{ trustedMetrics.gate_warning_count ?? 0 }}</strong>
                </div>
                <div class="trusted-metric trusted-metric--wide">
                  <span>gate 结论</span>
                  <el-tag :type="trustedMetrics.gate_passed ? ((trustedMetrics.gate_warning_count ?? 0) > 0 ? 'warning' : 'success') : 'danger'">
                    {{ trustedMetrics.gate_passed ? (((trustedMetrics.gate_warning_count ?? 0) > 0) ? '有风险通过' : '通过') : '未通过' }}
                  </el-tag>
                </div>
                <div class="trusted-metric trusted-metric--wide">
                  <span>语义审查</span>
                  <el-tag :type="trustedMetrics.semantic_release_readiness === 'pass' ? 'success' : 'warning'">
                    {{ trustedMetrics.semantic_release_readiness || '-' }}
                  </el-tag>
                </div>
              </div>

              <div v-if="isTrustedCurrentJob && trustedGateIssues.length" class="gate-issues-panel">
                <div class="gate-issues-title">门禁风险摘要</div>
                <div v-for="gate in trustedGateIssues" :key="gate.key" class="gate-issue-group">
                  <div class="gate-issue-head">
                    <el-tag :type="gate.tagType" size="small">{{ gate.label }} · {{ gate.statusText }}</el-tag>
                    <span v-if="gate.recoveryText" class="gate-recovery">建议：{{ gate.recoveryText }}</span>
                  </div>
                  <div v-if="gate.sourceIds.length || gate.canRerunStage" class="gate-actions">
                    <el-button
                      v-for="sourceId in gate.sourceIds"
                      :key="sourceId"
                      size="small"
                      type="primary"
                      plain
                      :loading="rerunningShard === sourceId"
                      :disabled="!!rerunningShard || ['RUNNING', 'PENDING'].includes(currentJob?.status)"
                      @click="rerunSourceShard({ source_id: sourceId })"
                    >
                      重跑 {{ sourceId }}
                    </el-button>
                    <el-button
                      v-if="gate.canRerunStage"
                      size="small"
                      plain
                      :loading="rerunning"
                      :disabled="rerunDisabled"
                      @click="rerunJob"
                    >
                      重跑任务
                    </el-button>
                  </div>
                  <div v-for="(issue, i) in gate.issues" :key="i" class="gate-issue-msg" :class="`is-${issue.severity || 'warning'}`">
                    {{ issue.message || issue.code || '-' }}
                  </div>
                </div>
              </div>

              <div v-if="isTrustedCurrentJob && sourcesDetail && sourcesDetail.length" class="sources-detail-panel">
                <div class="sources-detail-title">直接测试对象明细</div>
                <table class="sources-detail-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>名称</th>
                      <th>FP 数</th>
                      <th>实际用例数</th>
                      <th>must_cover</th>
                      <th>方法消费</th>
                      <th>合并数</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="src in sourcesDetail" :key="src.source_id" :class="{ 'has-source-gap': hasSourceGap(src) }">
                      <td class="src-id">{{ src.source_id }}</td>
                      <td class="src-title">{{ src.title_path || src.title || '-' }}</td>
                      <td class="src-num">{{ src.fp_count }}</td>
                      <td class="src-num">{{ src.actual_case_count }}</td>
                      <td>
                        <el-tag :type="sourceStatusTag(src.must_cover_status)" size="small">{{ src.must_cover_status || '-' }}</el-tag>
                      </td>
                      <td>
                        <el-tag :type="sourceStatusTag(src.method_consumption_status)" size="small">{{ src.method_consumption_status || '-' }}</el-tag>
                      </td>
                      <td class="src-num">{{ src.merge_count }}</td>
                      <td>
                        <el-tag v-if="hasSourceGap(src)" type="warning" size="small">有缺口</el-tag>
                        <el-tag v-else-if="src.gate_issues && src.gate_issues.length" type="warning" size="small">有问题</el-tag>
                        <el-tag v-else type="success" size="small">正常</el-tag>
                        <div v-if="src.gate_issues && src.gate_issues.length" class="src-issues">
                          <div v-for="(issue, i) in src.gate_issues" :key="i" class="src-issue-msg">{{ issue.message }}</div>
                        </div>
                        <div v-if="src.shard_error" class="src-issue-msg">{{ src.shard_error }}</div>
                      </td>
                      <td class="src-action">
                        <el-button
                          v-if="canRerunShard(src)"
                          size="small"
                          type="primary"
                          plain
                          :loading="rerunningShard === src.source_id"
                          :disabled="!!rerunningShard"
                          @click="rerunSourceShard(src)"
                        >
                          重跑
                        </el-button>
                        <span v-else>-</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="progress-card">
                <div class="progress-card__head">
                  <div>
                    <div class="progress-card__title">执行进度</div>
                    <div class="progress-card__subtitle">{{ progressStatusText }}</div>
                  </div>
                  <div class="progress-percent">{{ progressPercent }}%</div>
                </div>
                <div class="progress-track" aria-hidden="true">
                  <div class="progress-track__fill" :style="{ width: `${progressPercent}%` }"></div>
                </div>
                <div v-if="activeExecutionProof" class="progress-live-proof">
                  {{ activeExecutionProof }}
                </div>
                <div class="progress-stage-rail">
                  <div
                    v-for="stage in displayProgressStageItems"
                    :key="stage.key"
                    class="progress-stage-node"
                    :class="`is-${stage.status}`"
                    :title="stage.childLabels || stage.label"
                  >
                    <div class="progress-stage-node__dot">{{ stage.index }}</div>
                    <div class="progress-stage-node__label">{{ stage.label }}</div>
                    <div v-if="stage.durationText" class="progress-stage-node__duration">{{ stage.durationText }}</div>
                  </div>
                </div>
                <div class="stage-summary-list">
                  <div
                    v-for="stage in stageSummaries"
                    :key="stage.key"
                    class="stage-summary-item"
                    :class="`is-${stage.status || 'pending'}`"
                  >
                    <div class="stage-summary-item__title-wrap">
                      <div class="stage-summary-item__title">{{ stage.title }}</div>
                      <div v-if="formatStageDuration(stage)" class="stage-summary-item__duration">{{ formatStageDuration(stage) }}</div>
                    </div>
                    <el-tag size="small" :type="stageTagType(stage.status)">{{ stage.status }}</el-tag>
                    <div class="stage-summary-item__desc">{{ stage.summary || '-' }}</div>
                  </div>
                </div>
              </div>

              <div v-if="finalXmindArtifact" class="xmind-download-card">
                <div>
                  <div class="xmind-download-card__title">最终 XMind 用例</div>
                  <div class="xmind-download-card__desc">{{ finalXmindArtifact.file_name }}</div>
                </div>
                <el-button type="primary" @click="downloadArtifact(finalXmindArtifact)">下载 .xmind</el-button>
              </div>
              <el-alert
                v-else-if="!isTrustedCurrentJob && ['SUCCESS', 'CONDITIONAL'].includes(currentJob.status)"
                title="当前任务未找到 .xmind 产物"
                type="warning"
                :closable="false"
              />
              <el-alert
                v-if="exportLogArtifact"
                :title="formatArtifactContent(exportLogArtifact)"
                type="error"
                :closable="false"
                class="export-log-alert"
              />
              <div v-if="visibleArtifacts.length" class="artifact-panel">
                <div class="artifact-toolbar">
                  <el-radio-group v-model="activeArtifactType" size="small">
                    <el-radio-button
                      v-for="artifact in visibleArtifacts"
                      :key="artifact.id"
                      :label="artifact.artifact_type"
                    >
                      {{ artifactLabel(artifact) }}
                    </el-radio-button>
                  </el-radio-group>
                  <el-button v-if="activeArtifact" size="small" @click="downloadArtifact(activeArtifact)">下载</el-button>
                </div>
                <pre v-if="activeArtifact" class="artifact-preview">{{ formatArtifactContent(activeArtifact) }}</pre>
              </div>
            </template>
          </div>
        </el-card>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import PageHeader from '@/components/PageHeader.vue'
import CaseGenerationModeBadge from '@/components/CaseGenerationModeBadge.vue'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import {
  cancelCaseGenerationV2Job,
  caseGenerationV2ArtifactLabel,
  caseGenerationV2StatusTagType,
  createCaseGenerationV2Job,
  getCaseGenerationV2ModelConfig,
  getCaseGenerationV2Artifact,
  downloadCaseGenerationV2Artifact,
  formatCaseGenerationV2ArtifactContent,
  getCaseGenerationV2JobDetail,
  listCaseGenerationV2Jobs,
  listCaseGenerationV2ModelOptions,
  rerunCaseGenerationV2Job,
  rerunCaseGenerationV2SourceShard,
  saveCaseGenerationV2ModelConfig
} from '@/lib/caseGenerationV2'
import {
  formatRate,
  nextPollingDelay,
  normalizeModelOptions,
  normalizePipelineMode,
  pipelineModeLabel,
  validateRequirementFile
} from '@/lib/caseGenerationUi'

const projects = ref([])
const jobs = ref([])
const allJobs = ref([])
const currentJob = ref(null)
const currentArtifacts = ref([])
const currentAttempts = ref([])
const activeArtifactType = ref('')
const artifactLoading = ref(false)
const submitting = ref(false)
const rerunning = ref(false)
const rerunningShard = ref('')
const savingModelConfig = ref(false)
const hasSavedModelConfig = ref(false)
const authStore = useAuthStore()

const form = ref({
  project_id: null,
  name: '',
  mode: 'MARKDOWN',
  pipeline_mode: 'lite',
  trusted_generation_strategy: 'source_shard',
  source_type: 'PASTE',
  source_document_name: '',
  source_url: '',
  markdown_text: '',
  export_xmind: true
})
const modelConfig = ref({
  name: '默认模型配置',
  api_key: '',
  model: 'gpt-5.5',
  base_url: ''
})
const uploadedFileName = ref('')
const uploadedCharCount = ref(0)
const pageError = ref('')
const jobStatusFilter = ref('')
const jobModeFilter = ref('')
const jobsHasMore = ref(false)
const loadingMoreJobs = ref(false)

const pipelineModeOptions = [
  { label: '轻量模式', value: 'lite', hint: '轻量适用性判断，生成 XMind。' },
  { label: '可信模式', value: 'trusted', hint: '先建立范围索引，再按 source 追溯、适用方法和 must_cover 生成可解释用例。' }
]
const selectedPipelineModeHint = computed(() =>
  pipelineModeOptions.find((item) => item.value === form.value.pipeline_mode)?.hint || ''
)

const modelOptions = ref([])
const groupedModelOptions = computed(() => {
  const groups = new Map()
  for (const item of modelOptions.value) {
    if (!groups.has(item.provider)) {
      groups.set(item.provider, [])
    }
    groups.get(item.provider).push(item)
  }
  return Array.from(groups.entries()).map(([label, options]) => ({ label, options }))
})

const currentPipelineMode = computed(() => jobPipelineMode(currentJob.value))
const isTrustedCurrentJob = computed(() => normalizePipelineMode(currentPipelineMode.value) === 'trusted')
const trustedReviewArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'trusted_review_report'))
const trustedMetrics = computed(() => trustedReviewArtifact.value?.content_json?.summary || null)
const scopeIndexArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'scope_index'))
const scopeIndexStrategy = computed(() => scopeIndexArtifact.value?.content_json?.execution_strategy || null)
const scopeIndexStrategyText = computed(() => {
  const strategy = scopeIndexStrategy.value
  if (!strategy) return ''
  const label = scopeIndexStrategyLabel(strategy.mode)
  const sections = Number(strategy.section_count || 0)
  const batches = Number(strategy.batch_count || 0)
  const concurrency = Number(strategy.concurrency || 0)
  const parts = [label]
  if (sections) parts.push(`${sections} 章节`)
  if (batches > 1) parts.push(`${batches} 批`)
  if (concurrency > 1) parts.push(`并发 ${concurrency}`)
  if (strategy.uses_lightweight_discovery) parts.push('轻量识别')
  return parts.join(' · ')
})
const finalDeliveryGateArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'final_delivery_gate'))
const finalDeliveryGatePassed = computed(() => {
  const artifactValue = finalDeliveryGateArtifact.value?.content_json?.passed
  if (typeof artifactValue === 'boolean') return artifactValue
  const metricValue = trustedMetrics.value?.final_delivery_gate_passed
  return typeof metricValue === 'boolean' ? metricValue : null
})
const sourcesDetail = computed(() => trustedReviewArtifact.value?.content_json?.sources_detail || null)
const trustedGateIssues = computed(() => {
  if (!isTrustedCurrentJob.value) return []
  const gateArtifacts = [
    { key: 'evidence_trace_gate', label: '证据门禁', pick: (content) => content },
    { key: 'scope_index_gate', label: '范围门禁', pick: (content) => content?.scope_index_gate || content },
    { key: 'requirement_handoff', label: '需求门禁', pick: (content) => content?.requirement_gate || content },
    { key: 'testcase_handoff', label: '用例门禁', pick: (content) => content?.testcase_gate || content },
    { key: 'final_delivery_gate', label: '交付门禁', pick: (content) => content }
  ]
  return gateArtifacts
    .map((gate) => {
      const artifact = currentArtifacts.value.find((item) => item.artifact_type === gate.key)
      const payload = gate.pick(artifact?.content_json || {})
      const issues = Array.isArray(payload?.issues)
        ? payload.issues.filter((item) => item && (item.severity || item.code || item.message)).slice(0, 6)
        : []
      if (!issues.length) return null
      const issueCounts = payload?.issue_counts || {}
      const blockingCount = Number(issueCounts.blocker ?? issues.filter((item) => item.severity === 'blocker').length)
      const warningCount = Number(issueCounts.warning ?? issues.filter((item) => item.severity === 'warning').length)
      const infoCount = issues.filter((item) => !['blocker', 'warning'].includes(item.severity)).length
      const hasActionableIssue = blockingCount > 0 || warningCount > 0
      const recoveryPlan = payload?.recovery_plan
      const sourceIds = Array.isArray(recoveryPlan?.rerun_scope?.source_ids)
        ? recoveryPlan.rerun_scope.source_ids.filter(Boolean).slice(0, 6)
        : []
      const strategy = recoveryPlan?.strategy || ''
      const recoveryText = hasActionableIssue ? formatRecoveryPlan(recoveryPlan) : ''
      return {
        ...gate,
        issues,
        blockingCount,
        warningCount,
        infoCount,
        tagType: blockingCount > 0 ? 'danger' : (warningCount > 0 ? 'warning' : 'info'),
        statusText: blockingCount > 0
          ? `${blockingCount} 项阻断`
          : (warningCount > 0 ? `${warningCount} 项风险` : `${infoCount || issues.length} 项提示`),
        recoveryPlan,
        recoveryText,
        sourceIds,
        canRerunStage: blockingCount > 0 && (strategy === 'stage_rerun' || (!sourceIds.length && strategy && strategy !== 'none'))
      }
    })
    .filter(Boolean)
})
const visibleArtifacts = computed(() => {
  if (isTrustedCurrentJob.value) {
    return currentArtifacts.value.filter((item) =>
      ['source_manifest', 'evidence_trace', 'evidence_trace_gate', 'scope_index', 'scope_index_gate', 'function_points', 'requirement_handoff', 'testcase_base_package', 'testcase_package', 'testcase_handoff', 'trusted_review_report', 'markdown', 'xmindmark', 'xmind', 'final_delivery_gate', 'model_call_trace', 'xmind_export_log'].includes(item.artifact_type)
    )
  }
  return currentArtifacts.value.filter((item) => item.artifact_type === 'xmind' || item.artifact_type === 'xmind_export_log')
})
const activeArtifact = computed(() =>
  visibleArtifacts.value.find((item) => item.artifact_type === activeArtifactType.value) || visibleArtifacts.value[0] || null
)
const finalXmindArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind'))
const exportLogArtifact = computed(() => currentArtifacts.value.find((item) => item.artifact_type === 'xmind_export_log'))
const canRerunCurrentJob = computed(() => !!currentJob.value)
const rerunDisabled = computed(() => rerunning.value || !currentJob.value || ['RUNNING', 'PENDING'].includes(currentJob.value.status))
const currentUserId = computed(() => authStore.user?.id || null)
const activeAttempt = computed(() => currentAttempts.value.find((item) => item.id === currentJob.value?.active_attempt_id) || currentAttempts.value[0] || null)

const pinnedRunningJob = computed(() => jobs.value.find((item) => ['RUNNING', 'PENDING'].includes(item.status)))
const jobList = computed(() => jobs.value.filter((item) => item.id !== pinnedRunningJob.value?.id))
const activeOwnJob = computed(() =>
  allJobs.value.find((item) => item.created_by === currentUserId.value && ['RUNNING', 'PENDING'].includes(item.status))
)
const submitDisabled = computed(() => submitting.value || !!activeOwnJob.value)
const canCancelCurrentJob = computed(
  () =>
    !!currentJob.value &&
    currentJob.value.created_by === currentUserId.value &&
    ['RUNNING', 'PENDING'].includes(currentJob.value.status)
)
const stageSummaries = computed(() => [...(currentJob.value?.progress_json?.stages || [])].reverse())
const latestStageActivity = computed(() => {
  const stages = currentJob.value?.progress_json?.stages || []
  const latest = stages
    .filter((item) => item?.updated_at)
    .slice()
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
  return latest || null
})
const cloneProgressStageKeys = ['collect', 'image_analysis', 'requirement', 'testcase', 'review', 'export']
const trustedProgressStageKeys = ['orchestrate', 'evidence_trace', 'scope_index', 'scope_index_gate', 'requirement', 'requirement_gate', 'testcase_by_source_shard', 'testcase_gate', 'quality_review', 'export', 'final_delivery_gate']
const progressStageKeys = computed(() => (isTrustedCurrentJob.value ? trustedProgressStageKeys : cloneProgressStageKeys))
const trustedDisplayStageGroups = [
  { key: 'prepare', label: '准备', stageKeys: ['orchestrate', 'evidence_trace'] },
  { key: 'analysis', label: '分析', stageKeys: ['scope_index', 'scope_index_gate', 'requirement', 'requirement_gate'] },
  { key: 'generate', label: '生成', stageKeys: ['testcase_by_source_shard', 'testcase_gate'] },
  { key: 'review', label: '复核', stageKeys: ['quality_review'] },
  { key: 'delivery', label: '交付', stageKeys: ['export', 'final_delivery_gate'] }
]
const progressStageLabels = {
  orchestrate: '编排',
  collect: '收集',
  image_analysis: '识图',
  evidence_trace: '证据',
  scope_index: '索引',
  scope_index_gate: '范围门禁',
  requirement: '分析',
  requirement_gate: '需求门禁',
  testcase_by_source_shard: '用例基线',
  testcase: '设计',
  testcase_gate: '用例门禁',
  quality_review: '复核',
  review: '评审',
  export: '导出',
  final_delivery_gate: '交付门禁'
}
const progressStageItems = computed(() => {
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item]))
  return progressStageKeys.value.map((key, index) => {
    const stage = stageMap.get(key)
    return {
      key,
      index: index + 1,
      label: progressStageLabels[key],
      status: stage?.status || 'pending',
      summary: stage?.summary || '',
      durationText: formatStageDuration(stage)
    }
  })
})
const displayProgressStageItems = computed(() => {
  if (!isTrustedCurrentJob.value) return progressStageItems.value
  const stageMap = new Map(stageSummaries.value.map((item) => [item.key, item]))
  return trustedDisplayStageGroups.map((group, index) => {
    const stages = group.stageKeys.map((key) => stageMap.get(key)).filter(Boolean)
    const failed = stages.find((item) => item.status === 'failed')
    const running = stages.find((item) => item.status === 'running')
    const hasAny = stages.length > 0
    const allSuccess = group.stageKeys.every((key) => stageMap.get(key)?.status === 'success')
    const lastFinished = stages
      .filter((item) => item?.updated_at)
      .slice()
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
    const activeStage = failed || running || lastFinished || stages[0]
    return {
      key: group.key,
      index: index + 1,
      label: group.label,
      status: failed ? 'failed' : (running ? 'running' : (allSuccess ? 'success' : (hasAny ? 'running' : 'pending'))),
      summary: activeStage?.summary || '',
      durationText: formatDisplayStageDuration(stages),
      childLabels: group.stageKeys.map((key) => progressStageLabels[key]).filter(Boolean).join(' / ')
    }
  })
})
const progressPercent = computed(() => {
  if (!currentJob.value) return 0
  if (['SUCCESS', 'CONDITIONAL'].includes(currentJob.value.status)) return 100
  const displayItems = displayProgressStageItems.value
  const completedCount = displayItems.filter((item) => item.status === 'success').length
  const runningIndex = displayItems.findIndex((item) => item.status === 'running')
  const failedIndex = displayItems.findIndex((item) => item.status === 'failed')
  const baseIndex = failedIndex >= 0 ? failedIndex : runningIndex
  const inProgressWeight = baseIndex >= 0 ? 0.45 : 0
  const raw = ((completedCount + inProgressWeight) / displayItems.length) * 100
  return Math.min(99, Math.max(0, Math.round(raw)))
})
const progressStatusText = computed(() => {
  if (!currentJob.value) return '请选择任务查看执行状态'
  if (currentJob.value.status === 'SUCCESS') return '全部阶段已完成'
  if (currentJob.value.status === 'CONDITIONAL') return '全部阶段已完成，结果需按风险项复核'
  if (currentJob.value.status === 'FAILED') return '任务执行失败，请查看错误摘要'
  if (currentJob.value.status === 'CANCELLED') return '任务已停止'
  const runningStage = displayProgressStageItems.value.find((item) => item.status === 'running')
  return runningStage ? `当前阶段：${runningStage.label}` : '等待任务调度'
})
const activeExecutionProof = computed(() => {
  if (!currentJob.value || !['RUNNING', 'PENDING'].includes(currentJob.value.status)) return ''
  const parts = []
  const latest = latestStageActivity.value
  if (latest?.updated_at) {
    parts.push(`最近活动 ${formatDateTime(latest.updated_at)}`)
  }
  if (latest?.summary) {
    parts.push(latest.summary)
  }
  if (currentJob.value.task_id) {
    parts.push(`task ${shortTaskId(currentJob.value.task_id)}`)
  }
  if (activeAttempt.value?.heartbeat_at) {
    parts.push(`心跳 ${formatDateTime(activeAttempt.value.heartbeat_at)}`)
  }
  return parts.join(' · ')
})

let pollTimer = null
let pollInFlight = false
let pollDelay = 3000
let pollCycle = 0

function extractRawUrl(value) {
  const raw = (value || '').trim()
  const match = raw.match(/^\[([^\]]+)\]\((https?:\/\/[^)]+)\)$/)
  return match ? match[2].trim() : raw
}

function isQwenModel(model) {
  return (model || '').toLowerCase().startsWith('qwen')
}

function isCodingPlanKey(apiKey) {
  return (apiKey || '').trim().startsWith('sk-sp-')
}

function normalizeApiKey(value) {
  let apiKey = (value || '').trim()
  while (apiKey.length >= 2 && ['"', "'"].includes(apiKey[0]) && apiKey.at(-1) === apiKey[0]) {
    apiKey = apiKey.slice(1, -1).trim()
  }
  return apiKey.replace(/^['"]+|['"]+$/g, '').trim()
}

function jobPipelineMode(job) {
  return job?.input_payload_json?.pipeline_mode || 'lite'
}

function trustedGenerationStrategyLabel(strategy) {
  return strategy === 'lite_review' ? '轻量结果审查' : '按 source 分片'
}

function scopeIndexStrategyLabel(mode) {
  return {
    single_full: '单次完整索引',
    section_batches_full: '完整分批索引',
    section_batches_lightweight: '长文档轻量索引',
    section_batches_full_after_timeout: '超时后分批索引'
  }[mode] || mode || '范围索引'
}

function hasSourceGap(src) {
  return ['gap', 'missing', 'blocked'].includes(src?.must_cover_status) ||
    ['gap', 'missing', 'blocked'].includes(src?.method_consumption_status)
}

function sourceStatusTag(status) {
  if (['covered', 'pass', 'ok'].includes(status)) return 'success'
  if (['gap', 'missing', 'blocked'].includes(status)) return 'warning'
  return 'info'
}

function formatJobListSummary(job) {
  const summary = String(job?.summary || '').trim()
  if (!summary) return '暂无摘要'

  const generatedMatch = summary.match(/已生成\s*(\d+)\s*条用例/)
  const suggestionMatch = summary.match(/(\d+)\s*项改进建议/)

  if (generatedMatch) {
    const parts = [`${generatedMatch[1]} 条用例`]
    if (summary.includes('有条件通过')) {
      parts.push('条件通过')
    } else if (summary.includes('导出 XMind')) {
      parts.push('已导出 XMind')
    }
    if (suggestionMatch) {
      parts.push(`${suggestionMatch[1]} 项建议`)
    }
    return parts.join(' · ')
  }

  return summary
}

function normalizeModelConfigInput() {
  const model = (modelConfig.value.model || '').trim()
  const apiKey = normalizeApiKey(modelConfig.value.api_key)
  const baseUrl = extractRawUrl(modelConfig.value.base_url)
  const matched = modelOptions.value.find((item) => item.value === model)
  let normalizedBaseUrl = baseUrl || matched?.baseUrl || ''

  if (isQwenModel(model)) {
    if (isCodingPlanKey(apiKey)) {
      normalizedBaseUrl = normalizedBaseUrl.includes('coding-intl.dashscope.aliyuncs.com')
        ? 'https://coding-intl.dashscope.aliyuncs.com/v1'
        : 'https://coding.dashscope.aliyuncs.com/v1'
    } else if (!normalizedBaseUrl || normalizedBaseUrl.includes('coding.dashscope.aliyuncs.com')) {
      normalizedBaseUrl = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    }
  }

  return { model, apiKey, baseUrl: normalizedBaseUrl }
}

function resolveModelProvider(model) {
  return modelOptions.value.find((item) => item.value === model)?.provider || 'OPENAI'
}

function validateModelConfigInput() {
  const { model, apiKey, baseUrl } = normalizeModelConfigInput()
  if (!apiKey) {
    return { model, apiKey, baseUrl }
  }
  if (isQwenModel(model)) {
    if (isCodingPlanKey(apiKey)) {
      if (!baseUrl.includes('coding.dashscope.aliyuncs.com/v1') && !baseUrl.includes('coding-intl.dashscope.aliyuncs.com/v1')) {
        throw new Error('sk-sp- 开头的阿里云 Coding Plan Key 必须配合 coding.dashscope.aliyuncs.com/v1 使用')
      }
    } else if (!baseUrl.includes('/compatible-mode/v1')) {
      throw new Error('Qwen 通用 API Key 需要配合 dashscope 的 compatible-mode/v1 地址使用')
    }
  } else if (isCodingPlanKey(apiKey)) {
    throw new Error('sk-sp- 开头的阿里云 Coding Plan Key 仅支持 Qwen 模型')
  }
  return { model, apiKey, baseUrl }
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

function startPolling() {
  stopPolling()
  pollDelay = 3000
  pollCycle = 0
  scheduleNextPoll()
}

function scheduleNextPoll() {
  stopPolling()
  pollTimer = setTimeout(async () => {
    if (pollInFlight) return
    if (!currentJob.value) return
    if (!['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      stopPolling()
      return
    }
    pollInFlight = true
    try {
      await refreshCurrentJob({ refreshList: pollCycle % 4 === 3 })
      pollCycle += 1
      pollDelay = nextPollingDelay(pollDelay)
    } catch {
      pollDelay = nextPollingDelay(pollDelay, true)
    } finally {
      pollInFlight = false
      if (['RUNNING', 'PENDING'].includes(currentJob.value?.status)) {
        scheduleNextPoll()
      }
    }
  }, pollDelay)
}

watch(
  () => currentJob.value?.id,
  () => {
    activeArtifactType.value = visibleArtifacts.value[0]?.artifact_type || ''
  }
)

watch(
  () => activeArtifactType.value,
  async () => {
    if (activeArtifact.value && !activeArtifact.value.content_json && activeArtifact.value.artifact_type !== 'xmind') {
      await loadArtifactContent(activeArtifact.value)
    }
  }
)

watch(
  () => modelConfig.value.model,
  (model) => {
    const matched = modelOptions.value.find((item) => item.value === model)
    if (matched && matched.baseUrl) {
      modelConfig.value.base_url = matched.baseUrl
    }
    if (matched && matched.value === 'custom-openai-compatible' && !modelConfig.value.base_url) {
      modelConfig.value.base_url = ''
    }
  }
)

watch(
  () => currentJob.value?.status,
  (status) => {
    if (!status) {
      stopPolling()
      return
    }
    if (['RUNNING', 'PENDING'].includes(status)) {
      startPolling()
      return
    }
    stopPolling()
  },
  { immediate: true }
)

watch(
  () => form.value.project_id,
  async (projectId) => {
    if (!projectId) return
    await loadModelConfig()
    await fetchJobs()
  }
)

async function fetchProjects() {
  try {
    projects.value = await api.get('/projects')
    pageError.value = ''
    if (!form.value.project_id && projects.value.length) {
      form.value.project_id = projects.value[0].id
    }
    await loadModelConfig()
  } catch (error) {
    pageError.value = error?.message || '加载项目失败'
    ElMessage.error(pageError.value)
  }
}

async function fetchJobs() {
  try {
    const [projectJobs, visibleJobs] = await Promise.all([
      listCaseGenerationV2Jobs({
        projectId: form.value.project_id,
        status: jobStatusFilter.value,
        pipelineMode: jobModeFilter.value,
        limit: 50
      }),
      listCaseGenerationV2Jobs()
    ])
    jobs.value = projectJobs
    jobsHasMore.value = projectJobs.length === 50
    allJobs.value = visibleJobs
    pageError.value = ''
    if (!jobs.value.length) {
      currentJob.value = null
      currentArtifacts.value = []
      return
    }
    if (!currentJob.value) {
      await selectJob(pinnedRunningJob.value || jobs.value[0])
      return
    }
    const matched = jobs.value.find((item) => item.id === currentJob.value.id)
    if (!matched) {
      await selectJob(pinnedRunningJob.value || jobs.value[0])
    }
  } catch (error) {
    pageError.value = error?.message || '加载任务失败'
    throw error
  }
}

async function loadMoreJobs() {
  const beforeId = jobs.value.at(-1)?.id
  if (!beforeId || loadingMoreJobs.value) return
  loadingMoreJobs.value = true
  try {
    const older = await listCaseGenerationV2Jobs({
      projectId: form.value.project_id,
      status: jobStatusFilter.value,
      pipelineMode: jobModeFilter.value,
      beforeId,
      limit: 50
    })
    const existingIds = new Set(jobs.value.map((item) => item.id))
    jobs.value.push(...older.filter((item) => !existingIds.has(item.id)))
    jobsHasMore.value = older.length === 50
  } catch (error) {
    ElMessage.error(error?.message || '加载更多任务失败')
  } finally {
    loadingMoreJobs.value = false
  }
}

async function loadArtifactContent(artifact) {
  if (!currentJob.value || !artifact || artifact.content_json || artifact.artifact_type === 'xmind') return
  artifactLoading.value = true
  try {
    const hydrated = await getCaseGenerationV2Artifact(currentJob.value.id, artifact.id)
    currentArtifacts.value = currentArtifacts.value.map((item) => item.id === hydrated.id ? hydrated : item)
  } finally {
    artifactLoading.value = false
  }
}

async function hydrateSummaryArtifacts() {
  const summaryTypes = new Set([
    'trusted_review_report',
    'scope_index',
    'evidence_trace_gate',
    'scope_index_gate',
    'requirement_handoff',
    'testcase_handoff',
    'final_delivery_gate'
  ])
  const pending = currentArtifacts.value.filter((item) => summaryTypes.has(item.artifact_type) && !item.content_json)
  await Promise.all(pending.map((item) => loadArtifactContent(item)))
}

async function selectJob(job, options = {}) {
  try {
    const detail = await getCaseGenerationV2JobDetail(job.id)
    const previousContent = new Map(currentArtifacts.value.map((item) => [item.id, item.content_json]))
    currentJob.value = detail.job
    currentAttempts.value = detail.attempts || []
    currentArtifacts.value = (detail.artifacts || []).map((item) => ({
      ...item,
      content_json: previousContent.get(item.id) || item.content_json || null
    }))
    activeArtifactType.value = visibleArtifacts.value[0]?.artifact_type || ''
    if (options.hydrate !== false && !['RUNNING', 'PENDING'].includes(currentJob.value.status)) {
      await hydrateSummaryArtifacts()
    }
    pageError.value = ''
  } catch (error) {
    pageError.value = error?.message || '加载任务详情失败'
    ElMessage.error(pageError.value)
  }
}

async function refreshCurrentJob(options = {}) {
  if (!currentJob.value) return
  const wasRunning = ['RUNNING', 'PENDING'].includes(currentJob.value.status)
  await selectJob(currentJob.value, { hydrate: false })
  const index = jobs.value.findIndex((item) => item.id === currentJob.value.id)
  if (index >= 0) jobs.value.splice(index, 1, currentJob.value)
  const allIndex = allJobs.value.findIndex((item) => item.id === currentJob.value.id)
  if (allIndex >= 0) allJobs.value.splice(allIndex, 1, currentJob.value)
  const finished = wasRunning && !['RUNNING', 'PENDING'].includes(currentJob.value.status)
  if (finished) {
    await hydrateSummaryArtifacts()
  }
  if (options.refreshList || finished) {
    await fetchJobs()
  }
}

function currentWorkspaceId() {
  const project = projects.value.find((item) => item.id === form.value.project_id)
  return project?.workspace_id || currentJob.value?.workspace_id || null
}

async function loadModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) return
  const config = await getCaseGenerationV2ModelConfig(workspaceId)
  if (!config) {
    hasSavedModelConfig.value = false
    return
  }
  hasSavedModelConfig.value = true
  modelConfig.value = {
    name: config.name || '默认模型配置',
    api_key: '',
    model: config.model || 'gpt-5.5',
    base_url: config.base_url || ''
  }
}

async function loadModelOptions() {
  modelOptions.value = normalizeModelOptions(await listCaseGenerationV2ModelOptions())
}

async function persistModelConfig() {
  const workspaceId = currentWorkspaceId()
  if (!workspaceId) {
    throw new Error('请先选择所属项目')
  }
  const { model, apiKey, baseUrl } = validateModelConfigInput()
  if (!apiKey) {
    throw new Error('请填写模型 API Key')
  }
  await saveCaseGenerationV2ModelConfig({
    workspace_id: workspaceId,
    provider: resolveModelProvider(model),
    name: modelConfig.value.name || '默认模型配置',
    api_key: apiKey,
    model,
    base_url: baseUrl || null
  })
  hasSavedModelConfig.value = true
  modelConfig.value.model = model
  modelConfig.value.base_url = baseUrl
  modelConfig.value.api_key = ''
}

async function saveModelConfig() {
  savingModelConfig.value = true
  try {
    await persistModelConfig()
    ElMessage.success('模型配置已保存')
  } catch (error) {
    ElMessage.error(error?.message || '保存模型配置失败')
  } finally {
    savingModelConfig.value = false
  }
}

async function submitJob() {
  if (activeOwnJob.value) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  if (!form.value.project_id || !form.value.name.trim()) {
    ElMessage.error('请先填写项目和任务名称')
    return
  }
  const sourceType = form.value.source_type
  const markdownText = (form.value.markdown_text || '').trim()
  const sourceUrl = (form.value.source_url || '').trim()
  if (sourceType === 'LINK' && !sourceUrl) {
    ElMessage.error('请填写需求文档链接')
    return
  }
  if (sourceType !== 'LINK' && markdownText.length < 10) {
    ElMessage.error(sourceType === 'UPLOAD' ? '请先上传需求文档' : '请先填写需求 Markdown')
    return
  }
  submitting.value = true
  try {
    if ((modelConfig.value.api_key || '').trim()) {
      await persistModelConfig()
    } else if (!hasSavedModelConfig.value) {
      ElMessage.error('请先填写并保存模型配置，或在当前页输入 API Key 后直接开始生成')
      return
    }
    const job = await createCaseGenerationV2Job({
      ...form.value,
      name: form.value.name.trim(),
      source_url: sourceUrl || null,
      markdown_text: sourceType === 'LINK' ? null : markdownText,
      ...normalizeModelConfigInput()
    })
    ElMessage.success('生成任务已提交')
    await fetchJobs()
    await selectJob(job)
  } catch (error) {
    ElMessage.error(error?.message || '创建任务失败')
  } finally {
    submitting.value = false
  }
}

function handleFileChange(uploadFile) {
  const rawFile = uploadFile.raw
  if (!rawFile) {
    return
  }
  const validationError = validateRequirementFile(rawFile)
  if (validationError) {
    ElMessage.error(validationError)
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const content = typeof reader.result === 'string' ? reader.result : ''
    form.value.markdown_text = content
    form.value.source_document_name = rawFile.name
    uploadedFileName.value = rawFile.name
    uploadedCharCount.value = content.length
    ElMessage.success('需求文档已读取')
  }
  reader.onerror = () => {
    ElMessage.error('读取文件失败')
  }
  reader.readAsText(rawFile, 'utf-8')
}

async function rerunJob() {
  if (!currentJob.value) return
  if (rerunDisabled.value) return
  if (activeOwnJob.value && activeOwnJob.value.id !== currentJob.value.id) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  rerunning.value = true
  try {
    await rerunCaseGenerationV2Job(currentJob.value.id)
    ElMessage.success('任务已重新提交')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '重跑失败')
  } finally {
    rerunning.value = false
  }
}

function canRerunShard(src) {
  if (!currentJob.value || !isTrustedCurrentJob.value) return false
  if (['RUNNING', 'PENDING'].includes(currentJob.value.status)) return false
  if (!src?.source_id) return false
  return currentJob.value.status === 'FAILED' || src.shard_status === 'failed' || hasSourceGap(src) || (src.gate_issues && src.gate_issues.length)
}

async function rerunSourceShard(src) {
  if (!currentJob.value || !src?.source_id || !canRerunShard(src)) return
  if (activeOwnJob.value && activeOwnJob.value.id !== currentJob.value.id) {
    ElMessage.error(`当前已有进行中的任务 #${activeOwnJob.value.id}`)
    return
  }
  rerunningShard.value = src.source_id
  try {
    await rerunCaseGenerationV2SourceShard(currentJob.value.id, src.source_id)
    ElMessage.success(`${src.source_id} shard 已重新提交`)
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || 'source shard 重跑失败')
  } finally {
    rerunningShard.value = ''
  }
}

async function cancelJob() {
  if (!currentJob.value) return
  try {
    await cancelCaseGenerationV2Job(currentJob.value.id)
    ElMessage.success('任务已停止')
    await refreshCurrentJob()
  } catch (error) {
    ElMessage.error(error?.message || '停止失败')
  }
}

async function downloadArtifact(artifact) {
  if (!currentJob.value) return
  try {
    const blob = await downloadCaseGenerationV2Artifact(currentJob.value.id, artifact.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = artifact.file_name || `${artifact.artifact_type}.dat`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error?.message || '下载失败')
  }
}

function statusTagType(status) {
  return caseGenerationV2StatusTagType(status)
}

function artifactLabel(artifact) {
  return caseGenerationV2ArtifactLabel(artifact)
}

function formatArtifactContent(artifact) {
  return formatCaseGenerationV2ArtifactContent(artifact)
}

function formatRecoveryPlan(plan) {
  if (!plan || !plan.strategy || plan.strategy === 'none') return ''
  const strategyLabel = {
    local_rerun: '局部重跑',
    stage_rerun: '阶段重跑'
  }[plan.strategy] || plan.strategy
  const returnTo = plan.return_to ? `退回 ${progressStageLabels[plan.return_to] || plan.return_to}` : ''
  const sourceIds = Array.isArray(plan.rerun_scope?.source_ids) ? plan.rerun_scope.source_ids.filter(Boolean) : []
  const sourceText = sourceIds.length ? `影响 ${sourceIds.slice(0, 4).join('、')}${sourceIds.length > 4 ? ` 等 ${sourceIds.length} 个 source` : ''}` : ''
  return [strategyLabel, returnTo, sourceText].filter(Boolean).join(' / ')
}

function shortTaskId(taskId) {
  const value = String(taskId || '')
  return value.length > 8 ? value.slice(0, 8) : value
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function stageTagType(status) {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function formatDurationMs(durationMs) {
  const value = Number(durationMs)
  if (!Number.isFinite(value) || value <= 0) return ''
  const totalSeconds = Math.max(1, Math.round(value / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes <= 0) return `${seconds}s`
  if (minutes < 60) return `${minutes}m ${seconds}s`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return `${hours}h ${remainMinutes}m ${seconds}s`
}

function formatStageDuration(stage) {
  if (!stage) return ''
  return formatDurationMs(stage.duration_ms)
}

function formatDisplayStageDuration(stages) {
  const total = (stages || []).reduce((sum, stage) => {
    const value = Number(stage?.duration_ms)
    return Number.isFinite(value) && value > 0 ? sum + value : sum
  }, 0)
  return formatDurationMs(total)
}

onMounted(async () => {
  if (!authStore.user && authStore.token) {
    await authStore.fetchProfile()
  }
  await loadModelOptions()
  await fetchProjects()
  await fetchJobs()
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.case-generator-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.generator-layout {
  display: grid;
  grid-template-columns: minmax(280px, 2fr) minmax(280px, 2fr) minmax(360px, 3fr);
  gap: 18px;
  flex: 1;
  min-height: 0;
}

.generator-composer,
.side-card {
  border-radius: 20px;
  height: 100%;
  min-height: 0;
}

.generator-composer,
.generator-side {
  min-height: 0;
}

.generator-composer :deep(.el-card__body),
.side-card :deep(.el-card__body) {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.composer-form {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.generator-composer .panel-subtitle {
  max-width: 32ch;
}

.generator-composer :deep(.el-form-item) {
  margin-bottom: 14px;
}

.generator-composer :deep(.el-textarea__inner) {
  min-height: 138px !important;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}

.job-filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  width: 100%;
}

.job-filter {
  width: 100%;
}

.load-more-button {
  width: 100%;
  flex: 0 0 auto;
}

.panel-title {
  font-size: 18px;
  font-weight: 700;
}

.panel-subtitle {
  margin-top: 6px;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

.form-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.model-config-panel,
.model-config-actions {
  display: grid;
  gap: 10px;
  width: 100%;
}

.model-config-panel {
  grid-template-columns: 1fr;
}

.model-config-actions {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.source-type-group {
  width: 100%;
  display: flex;
  flex-wrap: nowrap;
  gap: 0;
}

.source-type-group :deep(.el-radio-button) {
  flex: 1 1 0;
  min-width: 0;
  margin-left: -1px;
}

.source-type-group :deep(.el-radio-button:first-child) {
  margin-left: 0;
}

.source-type-group :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
  border-radius: 0;
}

.source-type-group :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: 12px 0 0 12px;
}

.source-type-group :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 12px 12px 0;
}

.source-type-group :deep(.el-radio-button:first-child:last-child .el-radio-button__inner) {
  border-radius: 10px;
}

.pipeline-mode-group {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.pipeline-mode-group :deep(.el-radio-button) {
  min-width: 0;
}

.pipeline-mode-group :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.2;
  white-space: nowrap;
}

.pipeline-mode-hint {
  margin-top: 8px;
  width: 100%;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.model-select {
  width: 100%;
}

.upload-panel {
  display: grid;
  gap: 12px;
  width: 100%;
}

.upload-result {
  display: flex;
  align-items: center;
  gap: 10px;
}

.upload-result__meta {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.generator-side {
  display: contents;
  min-width: 0;
}

.job-list {
  display: grid;
  gap: 12px;
  overflow: auto;
  min-height: 0;
}

.job-item {
  display: grid;
  align-content: start;
  grid-auto-rows: min-content;
  width: 100%;
  box-sizing: border-box;
  appearance: none;
  -webkit-appearance: none;
  font: inherit;
  color: inherit;
  line-height: inherit;
  text-align: left;
  border: 1px solid rgba(99, 102, 241, 0.12);
  border-radius: 16px;
  padding: 12px 14px;
  background: linear-gradient(180deg, rgba(255,255,255,0.96), rgba(246,248,255,0.96));
  cursor: pointer;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
  outline: none;
  min-height: 98px;
}

.job-item--pinned {
  border-color: rgba(79, 70, 229, 0.26);
  background: rgba(246, 248, 255, 0.92);
}

.job-pinned__label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(79, 70, 229, 0.72);
}

.job-item.active {
  border-color: rgba(79, 70, 229, 0.32);
  background: linear-gradient(180deg, rgba(244, 246, 255, 0.92), rgba(248, 250, 255, 0.98));
  box-shadow: 0 8px 18px rgba(99, 102, 241, 0.08);
  position: relative;
  overflow: hidden;
}

.job-item.active::before {
  content: '';
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #6366f1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.job-item__title {
  font-weight: 700;
}

.job-item__meta {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  color: var(--color-text-secondary);
}

.job-item__desc {
  margin-top: 8px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.detail-actions {
  display: flex;
  flex-direction: row;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  margin-left: auto;
  flex-shrink: 0;
}

.detail-actions__primary {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: nowrap;
}

.detail-actions__secondary {
  align-self: auto;
}

.detail-actions :deep(.el-button) {
  flex: 0 0 auto;
  white-space: nowrap;
  padding-inline: 10px;
}

.detail-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.detail-summary {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(248, 250, 255, 0.88);
  border: 1px solid rgba(148, 163, 184, 0.12);
}

.trusted-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 14px;
}

.trusted-metric {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(99, 102, 241, 0.12);
  background: rgba(255, 255, 255, 0.78);
}

.trusted-metric span {
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.3;
}

.trusted-metric strong {
  font-size: 18px;
  line-height: 1.1;
}

.trusted-metric--wide {
  grid-column: span 3;
  grid-template-columns: 1fr auto;
  align-items: center;
}

.gate-issues-panel {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid rgba(239, 68, 68, 0.16);
  background: rgba(255, 247, 247, 0.84);
}

.gate-issues-title {
  font-size: 13px;
  font-weight: 700;
  color: #991b1b;
}

.gate-issue-group {
  display: grid;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid rgba(239, 68, 68, 0.12);
}

.gate-issue-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.gate-recovery {
  color: var(--color-text-secondary);
  font-size: 12px;
}

.gate-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.gate-actions :deep(.el-button) {
  margin-left: 0;
  border-radius: 999px;
  padding-inline: 10px;
  max-width: 100%;
}

.gate-issue-msg {
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}

.gate-issue-msg.is-warning {
  color: #b45309;
}

.gate-issue-msg.is-advice {
  color: #64748b;
}

.sources-detail-panel {
  margin-top: 12px;
  border-radius: 16px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  overflow: hidden;
  background: rgba(255, 255, 255, 0.78);
}

.sources-detail-title {
  font-size: 12px;
  font-weight: 600;
  color: #6e6e73;
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}

.sources-detail-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.sources-detail-table th {
  text-align: left;
  padding: 7px 12px;
  color: #86868b;
  font-weight: 500;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
  white-space: nowrap;
}

.sources-detail-table td {
  padding: 7px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  vertical-align: top;
  color: #1d1d1f;
}

.sources-detail-table .src-action {
  width: 72px;
  text-align: center;
  white-space: nowrap;
}

.sources-detail-table tr:last-child td {
  border-bottom: none;
}

.sources-detail-table tr.has-source-gap td {
  background: rgba(245, 158, 11, 0.05);
}

.src-id {
  font-family: monospace;
  color: #6366f1;
  white-space: nowrap;
}

.src-title {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.src-num {
  text-align: center;
}

.src-issues {
  margin-top: 4px;
}

.src-issue-msg {
  font-size: 11px;
  color: #d97706;
  line-height: 1.4;
}

.stage-summary-list {
  display: grid;
  gap: 10px;
}

.stage-summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 12px;
  align-items: start;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.14);
  background: rgba(255, 255, 255, 0.78);
}

.stage-summary-item.is-running {
  border-color: rgba(79, 70, 229, 0.24);
  background: linear-gradient(135deg, rgba(238, 242, 255, 0.92), rgba(255, 255, 255, 0.82));
}

.stage-summary-item.is-success {
  border-color: rgba(20, 184, 166, 0.2);
}

.stage-summary-item__title {
  font-weight: 600;
}

.stage-summary-item__title-wrap {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.stage-summary-item__duration {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.stage-summary-item :deep(.el-tag) {
  justify-self: end;
  align-self: start;
  min-width: 0;
  padding-inline: 10px;
  border-radius: 999px;
  font-weight: 600;
  text-transform: lowercase;
}

.stage-summary-item__desc {
  grid-column: 1 / -1;
  color: var(--color-text-secondary);
  line-height: 1.5;
  margin-top: 2px;
}

.export-log-alert {
  margin-top: 12px;
}

.progress-card {
  display: grid;
  gap: 14px;
  margin-bottom: 14px;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(99, 102, 241, 0.14);
  background:
    radial-gradient(circle at 8% 0%, rgba(79, 70, 229, 0.1), transparent 32%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(246, 248, 255, 0.9));
  box-shadow: 0 18px 44px rgba(79, 70, 229, 0.08);
}

.progress-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.progress-card__title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.progress-card__subtitle {
  margin-top: 5px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.progress-percent {
  min-width: 58px;
  padding: 6px 10px;
  border-radius: 999px;
  text-align: center;
  font-weight: 800;
  color: #3730a3;
  background: rgba(238, 242, 255, 0.96);
  border: 1px solid rgba(99, 102, 241, 0.16);
}

.progress-track {
  position: relative;
  height: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(226, 232, 240, 0.9);
}

.progress-track__fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #2563eb, #4f46e5 52%, #14b8a6);
  box-shadow: 0 0 18px rgba(79, 70, 229, 0.28);
  transition: width 360ms ease;
}

.progress-live-proof {
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid rgba(79, 70, 229, 0.14);
  background: rgba(238, 242, 255, 0.72);
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.progress-stage-rail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(46px, 1fr));
  gap: 8px;
}

.progress-stage-node {
  display: grid;
  justify-items: center;
  gap: 7px;
  min-width: 0;
  color: var(--color-text-secondary);
}

.progress-stage-node__dot {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(255, 255, 255, 0.88);
  font-size: 12px;
  font-weight: 800;
}

.progress-stage-node__label {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 700;
}

.progress-stage-node__duration {
  font-size: 11px;
  line-height: 1;
  color: var(--color-text-secondary);
}

.progress-stage-node.is-success .progress-stage-node__dot {
  border-color: rgba(20, 184, 166, 0.22);
  color: #0f766e;
  background: linear-gradient(135deg, rgba(204, 251, 241, 0.96), rgba(240, 253, 250, 0.96));
}

.progress-stage-node.is-running .progress-stage-node__dot {
  border-color: rgba(79, 70, 229, 0.34);
  color: #ffffff;
  background: linear-gradient(135deg, #2563eb, #4f46e5);
  box-shadow: 0 10px 22px rgba(79, 70, 229, 0.28);
}

.progress-stage-node.is-failed .progress-stage-node__dot {
  border-color: rgba(220, 38, 38, 0.22);
  color: #b91c1c;
  background: rgba(254, 226, 226, 0.94);
}

.summary-line {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.summary-line span:first-child {
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
  padding-top: 2px;
}

.summary-line strong,
.summary-line > span:last-child {
  min-width: 0;
  line-height: 1.5;
  word-break: break-word;
}

.summary-line :deep(.el-tag) {
  justify-self: start;
  min-width: 96px;
  padding-inline: 12px;
  border-radius: 999px;
  font-weight: 600;
}

.xmind-download-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
  padding: 16px;
  border: 1px solid rgba(22, 163, 74, 0.22);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(240, 253, 244, 0.96), rgba(236, 253, 245, 0.72));
}

.xmind-download-card__title {
  font-weight: 800;
  color: #166534;
}

.xmind-download-card__desc {
  margin-top: 6px;
  color: var(--color-text-secondary);
  word-break: break-all;
}

.artifact-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.artifact-toolbar :deep(.el-radio-group) {
  min-width: 0;
  overflow: auto;
  flex-wrap: nowrap;
}

.artifact-toolbar :deep(.el-radio-button__inner) {
  white-space: nowrap;
}

.artifact-preview {
  margin: 0;
  padding: 14px;
  flex: 1;
  min-height: 240px;
  overflow: auto;
  border-radius: 16px;
  background: #0f172a;
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.error-text {
  color: #dc2626;
}

@media (max-width: 1100px) {
  .generator-layout {
    grid-template-columns: 1fr;
  }

  .generator-side {
    display: grid;
    gap: 18px;
    grid-template-rows: auto;
  }
}

@media (max-width: 768px) {
  .generator-side {
    display: grid;
    grid-template-columns: 1fr;
  }

  .progress-stage-rail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .form-footer,
  .xmind-download-card,
  .panel-head {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-actions {
    justify-content: flex-start;
    margin-left: 0;
  }

  .detail-actions__primary,
  .detail-actions__secondary {
    align-self: auto;
  }

  .detail-actions__primary {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
}
</style>
