<template>
  <div class="app-page">
    <PageHeader title="报告中心" subtitle="查看测试计划执行报告、失败明细与下载产物">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <div class="summary-grid section-gap">
      <el-card class="summary-card" shadow="never">
        <el-statistic title="报告数量" :value="filteredReports.length" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="成功计划" :value="successCount" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="失败计划" :value="failedCount" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="失败用例" :value="failedCaseCount" />
      </el-card>
    </div>

    <div class="quality-grid section-gap">
      <el-card class="summary-card" shadow="never">
        <el-statistic title="近 50 次成功率" :value="insights.success_rate">
          <template #suffix>%</template>
        </el-statistic>
        <el-progress :percentage="insights.success_rate" :stroke-width="8" :show-text="false" class="metric-progress" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="质量评分" :value="insights.quality_score">
          <template #suffix>/100</template>
        </el-statistic>
        <div class="metric-subline" :class="trendDeltaClass(insights.success_rate_delta)">
          成功率波动 {{ formatDelta(insights.success_rate_delta) }}
        </div>
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="平均通过率" :value="insights.average_pass_rate">
          <template #suffix>%</template>
        </el-statistic>
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="预检失败用例" :value="insights.config_fail_count" />
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="平均耗时" :value="insights.average_duration_ms || 0">
          <template #suffix>ms</template>
        </el-statistic>
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="波动计划数" :value="insights.flaky_plan_count" />
        <div class="metric-subline">近 5 次内成功/失败混合</div>
      </el-card>
      <el-card class="summary-card" shadow="never">
        <el-statistic title="不稳定执行数" :value="insights.unstable_run_count" />
        <div class="metric-subline">包含失败、超时或配置异常</div>
      </el-card>
    </div>

    <div v-if="reportListFailureSummary.length" class="failure-reason-summary section-gap">
      <span class="failure-reason-summary__label">报告失败原因概览</span>
      <el-tag
        v-for="item in reportListFailureSummary"
        :key="item.errorType"
        size="small"
        :type="errorTypeTag(item.errorType)"
      >
        {{ item.label }} {{ item.count }}
      </el-tag>
    </div>

    <div v-if="insights.failure_reason_summary?.length" class="failure-reason-summary section-gap">
      <span class="failure-reason-summary__label">近 50 次失败聚合</span>
      <el-tag
        v-for="item in insightsFailureReasonSummary"
        :key="item.errorType"
        size="small"
        :type="errorTypeTag(item.errorType)"
      >
        {{ item.label }} {{ item.count }}
      </el-tag>
    </div>

    <div class="insight-panels section-gap">
      <el-card class="page-card" shadow="never">
        <template #header>通过率趋势图</template>
        <el-empty v-if="!trendChart.points.length" description="暂无趋势数据" />
        <div v-else class="chart-panel">
          <svg class="trend-chart" viewBox="0 0 320 180" preserveAspectRatio="none" aria-label="通过率趋势图">
            <polyline class="trend-chart__grid" points="24,20 24,156 304,156" />
            <polyline class="trend-chart__line" :points="trendChart.polyline" />
            <circle
              v-for="point in trendChart.points"
              :key="point.key"
              class="trend-chart__point"
              :cx="point.x"
              :cy="point.y"
              r="4"
            />
          </svg>
          <div class="chart-legend">
            <div v-for="point in trendChart.points.slice(-5)" :key="point.key" class="chart-legend__item">
              <span>{{ point.label }}</span>
              <strong>{{ point.value }}%</strong>
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="page-card" shadow="never">
        <template #header>失败原因分布</template>
        <el-empty v-if="!failureDistribution.length" description="暂无失败分布" />
        <div v-else class="distribution-list">
          <div v-for="item in failureDistribution" :key="item.errorType" class="distribution-row">
            <div class="distribution-row__head">
              <span>{{ item.label }}</span>
              <strong>{{ item.count }}</strong>
            </div>
            <div class="distribution-row__bar">
              <div class="distribution-row__fill" :class="distributionBarClass(item.errorType)" :style="{ width: `${item.percent}%` }" />
            </div>
          </div>
        </div>
      </el-card>

      <el-card class="page-card" shadow="never">
        <template #header>最近执行趋势</template>
        <el-empty v-if="!insights.recent_trend.length" description="暂无趋势数据" />
        <el-table v-else :data="insights.recent_trend" border>
          <el-table-column label="计划" prop="plan_name" min-width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="110" align="center">
            <template #default="scope">
              <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通过率" width="110" align="center">
            <template #default="scope">{{ scope.row.pass_rate }}%</template>
          </el-table-column>
          <el-table-column label="失败数" prop="fail_count" width="90" align="center" />
          <el-table-column label="错误类型" width="120" align="center">
            <template #default="scope">
              <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
                {{ errorTypeText(scope.row.error_type) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="执行时间" width="180" align="center">
            <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="page-card" shadow="never">
        <template #header>计划历史对比</template>
        <el-empty v-if="!filteredPlanHistories.length" description="暂无历史对比数据" />
        <el-table v-else :data="filteredPlanHistories" border>
          <el-table-column label="计划" prop="plan_name" min-width="180" show-overflow-tooltip />
          <el-table-column label="最新状态" width="110" align="center">
            <template #default="scope">
              <el-tag size="small" :type="statusType(scope.row.latest_status)">{{ statusText(scope.row.latest_status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="最新通过率" width="120" align="center">
            <template #default="scope">{{ scope.row.latest_pass_rate }}%</template>
          </el-table-column>
          <el-table-column label="平均通过率" width="120" align="center">
            <template #default="scope">{{ scope.row.average_pass_rate }}%</template>
          </el-table-column>
          <el-table-column label="波动" width="110" align="center">
            <template #default="scope">
              <span :class="trendDeltaClass(scope.row.pass_rate_delta)">
                {{ formatDelta(scope.row.pass_rate_delta) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="近况摘要" min-width="220">
            <template #default="scope">
              <div v-if="scope.row.failure_reason_summary?.length" class="reason-cell">
                <el-tag
                  v-for="item in scope.row.failure_reason_summary.slice(0, 3)"
                  :key="`${scope.row.plan_id}-${item}`"
                  size="small"
                >
                  {{ item }}
                </el-tag>
              </div>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="最近执行" width="180" align="center">
            <template #default="scope">{{ formatTime(scope.row.latest_created_at) }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card class="page-card" shadow="never">
        <template #header>稳定度观察</template>
        <el-empty v-if="!stabilityCards.length" description="暂无稳定度数据" />
        <div v-else class="stability-grid">
          <div v-for="item in stabilityCards" :key="item.plan_id" class="stability-card">
            <div class="stability-card__title">{{ item.plan_name }}</div>
            <div class="stability-card__meta">
              <span>最新 {{ item.latest_pass_rate }}%</span>
              <span :class="trendDeltaClass(item.pass_rate_delta)">{{ formatDelta(item.pass_rate_delta) }}</span>
            </div>
            <div class="stability-card__meter">
              <div class="stability-card__fill" :style="{ width: `${Math.max(0, Math.min(100, item.average_pass_rate))}%` }" />
            </div>
            <div class="stability-card__foot">
              <span>均值 {{ item.average_pass_rate }}%</span>
              <span>{{ item.run_count }} 次</span>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card class="page-card" shadow="never">
      <div class="report-toolbar section-gap">
        <el-select v-model="reportFailureFilter" clearable placeholder="按失败原因筛选报告" style="width: 200px">
          <el-option
            v-for="item in EXECUTION_ERROR_TYPE_OPTIONS"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </div>

      <el-table v-loading="listLoading" :data="filteredReports" border>
        <el-table-column label="ID" prop="id" align="center" width="80" />
        <el-table-column label="计划" prop="plan_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="项目" prop="project_name" min-width="160" show-overflow-tooltip />
        <el-table-column label="环境" prop="environment_name" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="120" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="总数" prop="total_count" width="90" align="center" />
        <el-table-column label="成功" prop="pass_count" width="90" align="center" />
        <el-table-column label="失败" prop="fail_count" width="90" align="center" />
        <el-table-column label="失败原因概览" min-width="220">
          <template #default="scope">
            <div v-if="scope.row.failure_reason_summary?.length" class="reason-cell">
              <el-tag
                v-for="item in scope.row.failure_reason_summary.slice(0, 3)"
                :key="`${scope.row.id}-${item}`"
                size="small"
              >
                {{ item }}
              </el-tag>
            </div>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="180" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="200">
          <template #default="scope">
            <el-button size="small" @click="openDetail(scope.row)">详情</el-button>
            <el-button size="small" @click="openFailures(scope.row)">失败项</el-button>
          </template>
        </el-table-column>
        <el-table-column label="下载" align="center" width="180">
          <template #default="scope">
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'json')">JSON</el-button>
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'junit')">JUnit</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="mobile-cards">
        <div v-for="item in filteredReports" :key="item.id" class="mobile-card">
          <div class="mobile-card-title">{{ item.plan_name }}</div>
          <div class="mobile-card-meta">项目：{{ item.project_name }}</div>
          <div class="mobile-card-meta">状态：{{ statusText(item.status) }} · 成功：{{ item.pass_count }}/{{ item.total_count }}</div>
          <div class="mobile-card-meta">失败原因：{{ item.failure_reason_summary?.join('，') || '-' }}</div>
          <div class="mobile-card-desc">环境：{{ item.environment_name || '-' }}</div>
          <div class="mobile-card-actions">
            <el-button size="small" @click="openDetail(item)">详情</el-button>
            <el-button size="small" @click="openFailures(item)">失败项</el-button>
            <el-button size="small" @click="downloadReport(item.id, 'json')">JSON</el-button>
            <el-button size="small" @click="downloadReport(item.id, 'junit')">JUnit</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-dialog v-model="detailVisible" title="报告详情" width="960px">
      <el-descriptions :column="3" border class="section-gap">
        <el-descriptions-item label="计划">{{ report.plan_name || report.plan_run.plan_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ statusText(report.plan_run.status) }}</el-descriptions-item>
        <el-descriptions-item label="错误类型">{{ errorTypeText(report.plan_run.error_type) }}</el-descriptions-item>
        <el-descriptions-item label="总数">{{ report.plan_run.total_count }}</el-descriptions-item>
        <el-descriptions-item label="成功">{{ report.plan_run.pass_count }}</el-descriptions-item>
        <el-descriptions-item label="失败">{{ report.plan_run.fail_count }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(report.plan_run.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="结束时间">{{ formatTime(report.plan_run.finished_at) }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ report.plan_run.duration_ms ? report.plan_run.duration_ms + 'ms' : '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="hasConfigFailures"
        title="该报告包含执行前预检失败的用例，请优先检查环境变量和模板配置。"
        type="warning"
        :closable="false"
        class="section-gap"
      />

      <div v-if="failureReasonSummary.length" class="failure-reason-summary section-gap">
        <span class="failure-reason-summary__label">失败原因统计</span>
        <el-tag
          v-for="item in failureReasonSummary"
          :key="item.errorType"
          size="small"
          :type="errorTypeTag(item.errorType)"
        >
          {{ item.label }} {{ item.count }}
        </el-tag>
      </div>

      <div class="defect-panel section-gap">
        <div class="defect-panel__header">
          <span class="failure-reason-summary__label">关联缺陷</span>
          <el-button size="small" type="primary" @click="openDefectDialog">提缺陷</el-button>
        </div>
        <el-empty v-if="!report.defects?.length" description="当前报告暂无关联缺陷" />
        <el-table v-else :data="report.defects" border>
          <el-table-column label="标题" prop="title" min-width="180" show-overflow-tooltip />
          <el-table-column label="平台" prop="platform" width="110" align="center" />
          <el-table-column label="外部单号" prop="external_key" width="140" align="center" />
          <el-table-column label="状态" prop="status" width="110" align="center" />
          <el-table-column label="严重级别" prop="severity" width="110" align="center" />
          <el-table-column label="链接" width="120" align="center">
            <template #default="scope">
              <el-link v-if="scope.row.external_url" :href="scope.row.external_url" target="_blank" type="primary">打开</el-link>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div v-if="report.recent_history?.length" class="section-gap">
        <div class="failure-reason-summary history-header">
          <span class="failure-reason-summary__label">同计划最近 5 次对比</span>
        </div>
        <el-table :data="report.recent_history" border>
          <el-table-column label="执行ID" prop="plan_run_id" width="90" align="center" />
          <el-table-column label="状态" width="110" align="center">
            <template #default="scope">
              <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="通过率" width="110" align="center">
            <template #default="scope">{{ scope.row.pass_rate }}%</template>
          </el-table-column>
          <el-table-column label="失败数" prop="fail_count" width="90" align="center" />
          <el-table-column label="错误类型" width="120" align="center">
            <template #default="scope">
              <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
                {{ errorTypeText(scope.row.error_type) }}
              </el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="耗时" width="110" align="center">
            <template #default="scope">{{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}</template>
          </el-table-column>
          <el-table-column label="执行时间" width="180" align="center">
            <template #default="scope">{{ formatTime(scope.row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <el-table :data="report.test_runs" border>
        <el-table-column label="类型" prop="case_type" width="90" align="center" />
        <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="200" show-overflow-tooltip />
        <el-table-column label="错误类型" width="120" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
              {{ errorTypeText(scope.row.error_type) }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="110" align="center">
          <template #default="scope">
            {{ scope.row.duration_ms ? scope.row.duration_ms + 'ms' : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="产物" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ artifactSummary(scope.row.artifacts_json) }}
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ configHint(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="scope">
            <el-button size="small" @click="jumpToExecution(scope.row.id)">执行详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="failureVisible" title="失败明细" width="920px">
      <el-empty v-if="!failureRuns.length" description="当前报告没有失败项" />
      <template v-else>
        <div class="failure-toolbar section-gap">
          <div class="failure-reason-summary">
            <span class="failure-reason-summary__label">失败原因统计</span>
            <el-tag
              v-for="item in failureDialogReasonSummary"
              :key="item.errorType"
              size="small"
              :type="errorTypeTag(item.errorType)"
            >
              {{ item.label }} {{ item.count }}
            </el-tag>
          </div>
          <el-select v-model="failureFilter" clearable placeholder="按失败原因筛选" style="width: 180px">
            <el-option
              v-for="item in EXECUTION_ERROR_TYPE_OPTIONS"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </div>
        <el-table :data="filteredFailureRuns" border>
        <el-table-column label="用例名称" prop="case_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="错误类型" width="120" align="center">
          <template #default="scope">
            <el-tag v-if="scope.row.error_type" size="small" :type="errorTypeTag(scope.row.error_type)">
              {{ errorTypeText(scope.row.error_type) }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="摘要" prop="summary" min-width="220" show-overflow-tooltip />
        <el-table-column label="产物" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ artifactSummary(scope.row.artifacts_json) }}
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="180" show-overflow-tooltip>
          <template #default="scope">
            {{ configHint(scope.row) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="scope">
            <el-button size="small" @click="jumpToExecution(scope.row.id)">执行详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      </template>
    </el-dialog>

    <el-dialog v-model="defectDialogVisible" title="提缺陷" width="560px">
      <el-form label-position="top" :model="defectForm">
        <el-form-item label="标题">
          <el-input v-model="defectForm.title" placeholder="例如：首页登录按钮点击失败" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="8">
            <el-form-item label="平台">
              <el-select v-model="defectForm.platform" style="width: 100%">
                <el-option label="JIRA" value="JIRA" />
                <el-option label="禅道" value="ZENTAO" />
                <el-option label="飞书" value="LARK" />
                <el-option label="通用" value="GENERIC" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="外部单号">
              <el-input v-model="defectForm.external_key" placeholder="QA-123" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="严重级别">
              <el-select v-model="defectForm.severity" style="width: 100%">
                <el-option label="P0" value="P0" />
                <el-option label="P1" value="P1" />
                <el-option label="P2" value="P2" />
                <el-option label="P3" value="P3" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="外部链接">
          <el-input v-model="defectForm.external_url" placeholder="https://jira.example.com/browse/QA-123" />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="defectForm.summary" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="defectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitDefect">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import {
  EXECUTION_ERROR_TYPE_OPTIONS,
  executionErrorTypeTag,
  executionErrorTypeText,
  executionStatusTag,
  executionStatusText
} from '@/lib/execution'

const router = useRouter()
const list = ref([])
const listLoading = ref(false)
const detailVisible = ref(false)
const failureVisible = ref(false)
const defectDialogVisible = ref(false)
const failureRuns = ref([])
const failureFilter = ref('')
const reportFailureFilter = ref('')
const insights = reactive({
  report_count: 0,
  success_count: 0,
  failed_count: 0,
  failed_case_count: 0,
  config_fail_count: 0,
  success_rate: 0,
  average_pass_rate: 0,
  average_duration_ms: null,
  failure_reason_counts: {},
  failure_reason_summary: [],
  recent_trend: [],
  plan_histories: []
})
const report = reactive({
  plan_name: '',
  plan_run: {},
  test_runs: [],
  recent_history: [],
  defects: []
})
const defectForm = reactive({
  title: '',
  platform: 'GENERIC',
  external_key: '',
  external_url: '',
  severity: 'P2',
  summary: ''
})

const statusText = executionStatusText
const statusType = executionStatusTag

const filteredReports = computed(() => {
  if (!reportFailureFilter.value) return list.value
  return list.value.filter((item) => (item.failure_reason_counts?.[reportFailureFilter.value] || 0) > 0)
})
const successCount = computed(() => filteredReports.value.filter((item) => item.status === 'SUCCESS').length)
const failedCount = computed(() => filteredReports.value.filter((item) => item.status !== 'SUCCESS').length)
const failedCaseCount = computed(() => filteredReports.value.reduce((sum, item) => sum + (item.fail_count || 0), 0))
const hasConfigFailures = computed(() => report.test_runs.some((item) => item.error_type === 'CONFIG'))
const reportListFailureSummary = computed(() => {
  const counts = filteredReports.value.reduce((acc, item) => {
    const reasonCounts = item.failure_reason_counts || {}
    Object.entries(reasonCounts).forEach(([errorType, count]) => {
      acc[errorType] = (acc[errorType] || 0) + count
    })
    return acc
  }, {})
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([errorType, count]) => ({
      errorType,
      count,
      label: errorTypeText(errorType)
    }))
})
const insightsFailureReasonSummary = computed(() =>
  Object.entries(insights.failure_reason_counts || {})
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([errorType, count]) => ({
      errorType,
      count,
      label: errorTypeText(errorType)
    }))
)
const failureDistribution = computed(() => {
  const entries = Object.entries(insights.failure_reason_counts || {})
  const total = entries.reduce((sum, [, count]) => sum + count, 0)
  return entries
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([errorType, count]) => ({
      errorType,
      count,
      label: errorTypeText(errorType),
      percent: total ? Math.round((count / total) * 100) : 0
    }))
})
const filteredPlanHistories = computed(() => {
  if (!reportFailureFilter.value) return insights.plan_histories
  return insights.plan_histories.filter((item) => (item.failure_reason_counts?.[reportFailureFilter.value] || 0) > 0)
})
const stabilityCards = computed(() => filteredPlanHistories.value.slice(0, 6))
const filteredFailureRuns = computed(() => {
  if (!failureFilter.value) return failureRuns.value
  return failureRuns.value.filter((item) => item.error_type === failureFilter.value)
})

const trendChart = computed(() => {
  const series = [...(insights.recent_trend || [])].reverse()
  if (!series.length) {
    return { points: [], polyline: '' }
  }
  const width = 280
  const height = 136
  const points = series.map((item, index) => {
    const x = 24 + (series.length === 1 ? width / 2 : (width / Math.max(series.length - 1, 1)) * index)
    const y = 156 - (Math.max(0, Math.min(item.pass_rate, 100)) / 100) * height
    return {
      key: item.plan_run_id,
      x: Math.round(x * 10) / 10,
      y: Math.round(y * 10) / 10,
      value: item.pass_rate,
      label: `#${item.plan_run_id}`
    }
  })
  return {
    points,
    polyline: points.map((point) => `${point.x},${point.y}`).join(' ')
  }
})

const errorTypeText = executionErrorTypeText
const errorTypeTag = executionErrorTypeTag

const summarizeErrorTypes = (runs) => {
  const counts = runs.reduce((acc, item) => {
    if (!item.error_type) return acc
    acc[item.error_type] = (acc[item.error_type] || 0) + 1
    return acc
  }, {})
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([errorType, count]) => ({
      errorType,
      count,
      label: errorTypeText(errorType)
    }))
}

const failureReasonSummary = computed(() =>
  summarizeErrorTypes(report.test_runs.filter((item) => item.status !== 'SUCCESS'))
)
const failureDialogReasonSummary = computed(() => summarizeErrorTypes(failureRuns.value))

const formatTime = (val) => {
  if (!val) return '-'
  return new Date(val).toLocaleString()
}

const configHint = (run) => {
  if (run?.error_type === 'CONFIG') return '预检失败，请检查环境变量或模板配置'
  return '-'
}

const artifactSummary = (artifacts) => {
  if (!Array.isArray(artifacts) || !artifacts.length) return '-'
  return artifacts.slice(0, 3).map((item) => item.name).join('，')
}

const formatDelta = (value) => {
  if (!value) return '0%'
  return `${value > 0 ? '+' : ''}${value}%`
}

const trendDeltaClass = (value) => {
  if (value > 0) return 'trend-up'
  if (value < 0) return 'trend-down'
  return 'trend-flat'
}

const distributionBarClass = (errorType) => {
  if (errorType === 'CONFIG') return 'distribution-row__fill--warning'
  if (errorType === 'CANCELLED') return 'distribution-row__fill--info'
  return 'distribution-row__fill--danger'
}

const loadInsights = async () => {
  const data = await api.get('/reports/insights')
  Object.assign(insights, data || {})
}

const getList = async () => {
  listLoading.value = true
  try {
    const [reports] = await Promise.all([
      api.get('/reports'),
      loadInsights()
    ])
    list.value = reports
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    listLoading.value = false
  }
}

const openDetail = async (row) => {
  try {
    const data = await api.get(`/reports/${row.id}`)
    report.plan_name = row.plan_name || ''
    report.plan_run = data.plan_run
    report.test_runs = data.test_runs
    report.recent_history = data.recent_history || []
    report.defects = data.defects || []
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openDefectDialog = () => {
  const firstFailure = report.test_runs.find((item) => item.status !== 'SUCCESS')
  defectForm.title = firstFailure ? `${report.plan_name || '测试计划'} - ${firstFailure.case_name}` : `${report.plan_name || '测试计划'} 缺陷`
  defectForm.platform = 'GENERIC'
  defectForm.external_key = ''
  defectForm.external_url = ''
  defectForm.severity = 'P2'
  defectForm.summary = firstFailure?.summary || report.plan_run.summary || ''
  defectDialogVisible.value = true
}

const submitDefect = async () => {
  try {
    await api.post('/defects', {
      project_id: report.plan_run.project_id,
      plan_run_id: report.plan_run.id,
      run_id: report.test_runs.find((item) => item.status !== 'SUCCESS')?.id,
      title: defectForm.title,
      platform: defectForm.platform,
      external_key: defectForm.external_key || null,
      external_url: defectForm.external_url || null,
      status: 'OPEN',
      severity: defectForm.severity,
      summary: defectForm.summary || null
    })
    defectDialogVisible.value = false
    const refreshed = await api.get(`/reports/${report.plan_run.id}`)
    report.defects = refreshed.defects || []
    ElMessage.success('缺陷记录已创建')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const openFailures = async (row) => {
  try {
    const data = await api.get(`/reports/${row.id}`)
    failureRuns.value = data.test_runs.filter((item) => item.status !== 'SUCCESS')
    failureFilter.value = ''
    failureVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const jumpToExecution = (runId) => {
  detailVisible.value = false
  failureVisible.value = false
  router.push({ path: '/execution/index', query: { run_id: String(runId) } })
}

const downloadReport = async (planRunId, format) => {
  try {
    const token = localStorage.getItem('tp_token')
    const response = await fetch(`/api/v1/reports/${planRunId}/download?format=${format}`, {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail || '下载失败')
    }
    const blob = await response.blob()
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = `plan_run_${planRunId}.${format === 'json' ? 'json' : 'xml'}`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(objectUrl)
  } catch (error) {
    ElMessage.error(error.message || '下载失败')
  }
}

onMounted(() => {
  getList()
})
</script>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.summary-card {
  border-radius: 16px;
}

.quality-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-12);
}

.metric-progress {
  margin-top: var(--space-12);
}

.metric-subline {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.insight-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-12);
}

.chart-panel {
  display: grid;
  gap: 12px;
}

.trend-chart {
  width: 100%;
  height: 180px;
  background: linear-gradient(180deg, rgba(14, 165, 233, 0.06), rgba(14, 165, 233, 0));
  border-radius: 12px;
}

.trend-chart__grid {
  fill: none;
  stroke: rgba(148, 163, 184, 0.5);
  stroke-width: 1;
}

.trend-chart__line {
  fill: none;
  stroke: #0f766e;
  stroke-width: 3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.trend-chart__point {
  fill: #0f766e;
}

.chart-legend {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.chart-legend__item {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  font-size: 12px;
  display: flex;
  justify-content: space-between;
  gap: 8px;
}

.distribution-list {
  display: grid;
  gap: 14px;
}

.distribution-row__head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 13px;
}

.distribution-row__bar {
  height: 10px;
  background: #e2e8f0;
  border-radius: 999px;
  overflow: hidden;
}

.distribution-row__fill {
  height: 100%;
  border-radius: 999px;
}

.distribution-row__fill--warning {
  background: #f59e0b;
}

.distribution-row__fill--danger {
  background: #ef4444;
}

.distribution-row__fill--info {
  background: #64748b;
}

.stability-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.stability-card {
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.stability-card__title {
  font-weight: 600;
  margin-bottom: 8px;
}

.stability-card__meta,
.stability-card__foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

.stability-card__meter {
  margin: 10px 0;
  height: 10px;
  border-radius: 999px;
  background: #e2e8f0;
  overflow: hidden;
}

.stability-card__fill {
  height: 100%;
  background: linear-gradient(90deg, #0f766e, #14b8a6);
  border-radius: 999px;
}

.report-toolbar {
  display: flex;
  justify-content: flex-end;
}

.failure-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-12);
  flex-wrap: wrap;
}

.failure-reason-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.failure-reason-summary__label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.reason-cell {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.history-header {
  margin-bottom: var(--space-8);
}

.defect-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-8);
}

.trend-up {
  color: var(--el-color-success);
  font-weight: 600;
}

.trend-down {
  color: var(--el-color-danger);
  font-weight: 600;
}

.trend-flat {
  color: var(--color-text-secondary);
}

.mobile-cards {
  display: none;
}

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quality-grid,
  .insight-panels {
    grid-template-columns: 1fr;
  }

  .chart-legend,
  .stability-grid {
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

  .mobile-card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-8);
  }
}
</style>
