<template>
  <div class="app-page">
    <PageHeader title="报告中心" subtitle="查看测试计划执行报告、失败明细与下载产物">
      <template #actions>
        <el-button :loading="listLoading" @click="getList">刷新</el-button>
      </template>
    </PageHeader>

    <div class="kpi-grid section-gap">
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--indigo">
          <el-icon><Document /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">报告数量</div>
          <div class="kpi-card__value">{{ filteredReports.length }}</div>
          <div class="kpi-card__sub">成功 {{ successCount }} · 失败 {{ failedCount }}</div>
        </div>
      </el-card>
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--teal">
          <el-icon><TrendCharts /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">近 50 次成功率</div>
          <div class="kpi-card__value">{{ insights.success_rate }}<span class="kpi-card__unit">%</span></div>
          <div class="kpi-card__sub">
            <span :class="trendDeltaClass(insights.success_rate_delta)">{{ formatDelta(insights.success_rate_delta) }}</span>
            <span class="kpi-card__muted">较前一区间</span>
          </div>
        </div>
      </el-card>
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--sky">
          <el-icon><Odometer /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">平均通过率</div>
          <div class="kpi-card__value">{{ insights.average_pass_rate }}<span class="kpi-card__unit">%</span></div>
          <el-progress
            :percentage="Math.max(0, Math.min(insights.average_pass_rate || 0, 100))"
            :stroke-width="6"
            :show-text="false"
            class="kpi-card__progress"
          />
        </div>
      </el-card>
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--amber">
          <el-icon><Medal /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">质量评分</div>
          <div class="kpi-card__value">{{ insights.quality_score }}<span class="kpi-card__unit">/100</span></div>
          <div class="kpi-card__sub kpi-card__muted">由成功率与波动综合评估</div>
        </div>
      </el-card>
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--rose">
          <el-icon><WarningFilled /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">失败用例</div>
          <div class="kpi-card__value">{{ failedCaseCount }}</div>
          <div class="kpi-card__sub kpi-card__muted">预检失败 {{ insights.config_fail_count }}</div>
        </div>
      </el-card>
      <el-card class="kpi-card" shadow="never">
        <div class="kpi-card__icon kpi-card__icon--slate">
          <el-icon><Timer /></el-icon>
        </div>
        <div class="kpi-card__body">
          <div class="kpi-card__label">平均耗时</div>
          <div class="kpi-card__value">{{ formatDuration(insights.average_duration_ms) }}</div>
          <div class="kpi-card__sub kpi-card__muted">单次计划执行</div>
        </div>
      </el-card>
    </div>

    <div class="health-strip section-gap">
      <template v-if="healthChips.length">
        <el-tag v-for="chip in healthChips" :key="chip.key" :type="chip.type" effect="light" round>
          {{ chip.text }}
        </el-tag>
      </template>
      <el-tag v-else type="success" effect="light" round>近 50 次执行全部健康</el-tag>
    </div>

    <div class="insight-panels section-gap">
      <el-card class="page-card" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <span class="card-title">通过率趋势</span>
              <span class="card-subtitle">近 {{ trendSeries.length }} 次执行</span>
            </div>
            <div v-if="latestTrendPoint" class="card-head__aside">
              最新 <strong>{{ latestTrendPoint.value }}%</strong>
            </div>
          </div>
        </template>
        <el-empty v-if="!trendSeries.length" description="暂无趋势数据" />
        <TrendChart v-else :data="trendSeries" :height="240" aria-label="通过率趋势图" />
      </el-card>

      <el-card class="page-card" shadow="never">
        <template #header>
          <div class="card-head">
            <div>
              <span class="card-title">失败原因分布</span>
              <span class="card-subtitle">近 50 次失败聚合</span>
            </div>
          </div>
        </template>
        <el-empty v-if="!failureDistribution.length" description="暂无失败，保持住！" />
        <div v-else class="distribution-list">
          <div v-for="item in failureDistribution" :key="item.errorType" class="distribution-row">
            <div class="distribution-row__head">
              <span>{{ item.label }}</span>
              <strong>{{ item.count }} 次 · {{ item.percent }}%</strong>
            </div>
            <div class="distribution-row__bar">
              <div
                class="distribution-row__fill"
                :class="distributionBarClass(item.errorType)"
                :style="{ width: `${item.percent}%` }"
              />
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <el-card class="page-card section-gap" shadow="never">
      <template #header>
        <div class="card-head">
          <div>
            <span class="card-title">计划健康度</span>
            <span class="card-subtitle">按计划聚合的最近执行表现与稳定性</span>
          </div>
        </div>
      </template>
      <el-empty v-if="!filteredPlanHistories.length" description="暂无计划执行历史" />
      <el-table v-else :data="filteredPlanHistories">
        <el-table-column label="计划" prop="plan_name" min-width="180" show-overflow-tooltip />
        <el-table-column label="最新状态" width="110" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.latest_status)">{{ statusText(scope.row.latest_status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最新通过率" width="170">
          <template #default="scope">
            <div class="rate-cell">
              <el-progress
                :percentage="Math.max(0, Math.min(scope.row.latest_pass_rate || 0, 100))"
                :stroke-width="6"
                :show-text="false"
                class="rate-cell__bar"
              />
              <span>{{ scope.row.latest_pass_rate }}%</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="平均通过率" width="110" align="center">
          <template #default="scope">{{ scope.row.average_pass_rate }}%</template>
        </el-table-column>
        <el-table-column label="波动" width="90" align="center">
          <template #default="scope">
            <span :class="trendDeltaClass(scope.row.pass_rate_delta)">
              {{ formatDelta(scope.row.pass_rate_delta) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="执行次数" prop="run_count" width="90" align="center" />
        <el-table-column label="近况摘要" min-width="200">
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
            <span v-else class="cell-muted">无失败记录</span>
          </template>
        </el-table-column>
        <el-table-column label="最近执行" width="170" align="center">
          <template #default="scope">{{ formatTime(scope.row.latest_created_at) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card class="page-card" shadow="never">
      <template #header>
        <div class="card-head card-head--wrap">
          <div>
            <span class="card-title">报告列表</span>
            <span class="card-subtitle">共 {{ filteredReports.length }} 份</span>
          </div>
          <div class="list-tools">
            <div v-if="reportListFailureSummary.length" class="failure-reason-summary">
              <el-tag
                v-for="item in reportListFailureSummary"
                :key="item.errorType"
                size="small"
                :type="errorTypeTag(item.errorType)"
              >
                {{ item.label }} {{ item.count }}
              </el-tag>
            </div>
            <el-input
              v-model="searchKeyword"
              clearable
              placeholder="搜索计划 / 项目"
              class="list-tools__search"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select
              v-model="reportFailureFilter"
              clearable
              placeholder="按失败原因筛选"
              class="list-tools__filter"
            >
              <el-option
                v-for="item in EXECUTION_ERROR_TYPE_OPTIONS"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </div>
        </div>
      </template>

      <el-table v-loading="listLoading" :data="pagedReports">
        <el-table-column label="ID" prop="id" align="center" width="70" />
        <el-table-column label="计划" prop="plan_name" min-width="170" show-overflow-tooltip />
        <el-table-column label="项目" prop="project_name" min-width="140" show-overflow-tooltip />
        <el-table-column label="环境" min-width="110" show-overflow-tooltip>
          <template #default="scope">
            <span v-if="scope.row.environment_name">{{ scope.row.environment_name }}</span>
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="scope">
            <el-tag size="small" :type="statusType(scope.row.status)">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果" width="170">
          <template #default="scope">
            <div class="rate-cell">
              <el-progress
                :percentage="passPercent(scope.row)"
                :stroke-width="6"
                :show-text="false"
                :status="scope.row.fail_count ? 'exception' : undefined"
                class="rate-cell__bar"
              />
              <span>
                {{ scope.row.pass_count }}/{{ scope.row.total_count }}
                <span v-if="scope.row.fail_count" class="rate-cell__fail">败 {{ scope.row.fail_count }}</span>
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="失败原因" min-width="180">
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
            <span v-else class="cell-muted">-</span>
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="165" align="center">
          <template #default="scope">
            {{ formatTime(scope.row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="180">
          <template #default="scope">
            <el-button size="small" @click="openDetail(scope.row)">详情</el-button>
            <el-button size="small" @click="openFailures(scope.row)">失败项</el-button>
          </template>
        </el-table-column>
        <el-table-column label="下载" align="center" width="130">
          <template #default="scope">
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'json')">JSON</el-button>
            <el-button link type="primary" @click="downloadReport(scope.row.id, 'junit')">JUnit</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="table-footer">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="filteredReports.length"
          layout="total, prev, pager, next"
          background
        />
      </div>

      <div class="mobile-cards">
        <div v-for="item in pagedReports" :key="item.id" class="mobile-card">
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
        <el-descriptions-item label="耗时">{{ formatDuration(report.plan_run.duration_ms) }}</el-descriptions-item>
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
            <template #default="scope">{{ formatDuration(scope.row.duration_ms) }}</template>
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
            {{ formatDuration(scope.row.duration_ms) }}
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
      <template #footer>
        <div class="share-footer">
          <div v-if="shareUrl" class="share-link">
            <el-input :model-value="shareUrl" readonly size="small">
              <template #prepend>分享链接</template>
              <template #append>
                <el-button @click="copyShareUrl">复制</el-button>
              </template>
            </el-input>
          </div>
          <div class="share-actions">
            <el-button size="small" @click="downloadReport(report.plan_run.id, 'json')">导出 JSON</el-button>
            <el-button size="small" @click="downloadReport(report.plan_run.id, 'junit')">导出 JUnit</el-button>
            <el-button
              v-if="shareUrl"
              size="small"
              type="danger"
              plain
              :loading="shareLoading"
              @click="disableShare"
            >关闭分享</el-button>
            <el-button
              v-else
              size="small"
              type="primary"
              :loading="shareLoading"
              @click="enableShare"
            >生成分享链接</el-button>
          </div>
        </div>
      </template>
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import TrendChart from '@/components/TrendChart.vue'
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
const shareUrl = ref('')
const shareLoading = ref(false)
const failureVisible = ref(false)
const defectDialogVisible = ref(false)
const failureRuns = ref([])
const failureFilter = ref('')
const reportFailureFilter = ref('')
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = 10
const insights = reactive({
  report_count: 0,
  success_count: 0,
  failed_count: 0,
  failed_case_count: 0,
  config_fail_count: 0,
  success_rate: 0,
  average_pass_rate: 0,
  average_duration_ms: null,
  quality_score: 0,
  success_rate_delta: 0,
  flaky_plan_count: 0,
  unstable_run_count: 0,
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
  let result = list.value
  if (reportFailureFilter.value) {
    result = result.filter((item) => (item.failure_reason_counts?.[reportFailureFilter.value] || 0) > 0)
  }
  const keyword = searchKeyword.value.trim().toLowerCase()
  if (keyword) {
    result = result.filter((item) =>
      `${item.plan_name || ''} ${item.project_name || ''}`.toLowerCase().includes(keyword)
    )
  }
  return result
})
const pagedReports = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return filteredReports.value.slice(start, start + pageSize)
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
const filteredFailureRuns = computed(() => {
  if (!failureFilter.value) return failureRuns.value
  return failureRuns.value.filter((item) => item.error_type === failureFilter.value)
})
const healthChips = computed(() => {
  const chips = []
  if (failedCount.value > 0) {
    chips.push({ key: 'failed', type: 'danger', text: `失败计划 ${failedCount.value}` })
  }
  if (insights.config_fail_count > 0) {
    chips.push({ key: 'config', type: 'warning', text: `预检失败用例 ${insights.config_fail_count}` })
  }
  if (insights.flaky_plan_count > 0) {
    chips.push({ key: 'flaky', type: 'warning', text: `波动计划 ${insights.flaky_plan_count}` })
  }
  if (insights.unstable_run_count > 0) {
    chips.push({ key: 'unstable', type: 'warning', text: `不稳定执行 ${insights.unstable_run_count}` })
  }
  return chips
})

const trendSeries = computed(() =>
  [...(insights.recent_trend || [])].reverse().map((item) => {
    const rate = Math.max(0, Math.min(Number(item.pass_rate) || 0, 100))
    return {
      key: item.plan_run_id,
      label: `#${item.plan_run_id}`,
      value: rate,
      title: `#${item.plan_run_id} · ${rate}% · ${formatTime(item.created_at)}`
    }
  })
)
const latestTrendPoint = computed(() =>
  trendSeries.value.length ? trendSeries.value[trendSeries.value.length - 1] : null
)

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

const formatDuration = (ms) => {
  const value = Number(ms)
  if (!value || Number.isNaN(value)) return '-'
  if (value < 1000) return `${Math.round(value)}ms`
  if (value < 60000) return `${(value / 1000).toFixed(1)}s`
  const minutes = Math.floor(value / 60000)
  const seconds = Math.round((value % 60000) / 1000)
  return `${minutes}m${seconds ? ` ${seconds}s` : ''}`
}

const passPercent = (row) => {
  if (!row.total_count) return 0
  return Math.round(((row.pass_count || 0) / row.total_count) * 100)
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

watch([reportFailureFilter, searchKeyword], () => {
  currentPage.value = 1
})

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

function buildShareUrl(path) {
  if (!path) return ''
  return `${window.location.origin}${path}`
}

const openDetail = async (row) => {
  try {
    const data = await api.get(`/reports/${row.id}`)
    report.plan_name = row.plan_name || ''
    report.plan_run = data.plan_run
    report.test_runs = data.test_runs
    report.recent_history = data.recent_history || []
    report.defects = data.defects || []
    shareUrl.value = data.plan_run?.share_token ? buildShareUrl(`/shared-report/${data.plan_run.share_token}`) : ''
    detailVisible.value = true
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const enableShare = async () => {
  shareLoading.value = true
  try {
    const res = await api.post(`/reports/${report.plan_run.id}/share`)
    report.plan_run.share_token = res.share_token
    shareUrl.value = buildShareUrl(res.share_url)
    ElMessage.success('分享链接已生成')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    shareLoading.value = false
  }
}

const disableShare = async () => {
  shareLoading.value = true
  try {
    await api.delete(`/reports/${report.plan_run.id}/share`)
    report.plan_run.share_token = null
    shareUrl.value = ''
    ElMessage.success('分享已关闭')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    shareLoading.value = false
  }
}

const copyShareUrl = async () => {
  if (!shareUrl.value) return
  try {
    await navigator.clipboard.writeText(shareUrl.value)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动复制')
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
    const blob = await api.getBlob(`/reports/${planRunId}/download?format=${format}`)
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
.share-footer {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.share-footer .share-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--space-12);
}

.kpi-card :deep(.el-card__body) {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
}

.kpi-card {
  border-radius: 16px;
}

.kpi-card__icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.kpi-card__icon--indigo {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.kpi-card__icon--teal {
  background: rgba(20, 184, 166, 0.12);
  color: #0f766e;
}

.kpi-card__icon--sky {
  background: rgba(14, 165, 233, 0.12);
  color: #0284c7;
}

.kpi-card__icon--amber {
  background: rgba(245, 158, 11, 0.14);
  color: #d97706;
}

.kpi-card__icon--rose {
  background: rgba(244, 63, 94, 0.12);
  color: #e11d48;
}

.kpi-card__icon--slate {
  background: rgba(100, 116, 139, 0.14);
  color: #475569;
}

.kpi-card__body {
  min-width: 0;
  flex: 1;
}

.kpi-card__label {
  font-size: 12px;
  color: var(--color-text-secondary);
  white-space: nowrap;
}

.kpi-card__value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.kpi-card__unit {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-secondary);
  margin-left: 2px;
}

.kpi-card__sub {
  margin-top: 2px;
  font-size: 12px;
  display: flex;
  gap: 6px;
  align-items: baseline;
  white-space: nowrap;
}

.kpi-card__muted {
  color: var(--color-text-secondary);
}

.kpi-card__progress {
  margin-top: 8px;
}

.health-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-12);
}

.card-head--wrap {
  flex-wrap: wrap;
}

.card-title {
  font-weight: 600;
}

.card-subtitle {
  margin-left: 10px;
  font-size: 12px;
  font-weight: 400;
  color: var(--color-text-secondary);
}

.card-head__aside {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.card-head__aside strong {
  color: #0f766e;
  font-size: 15px;
}

.insight-panels {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: var(--space-12);
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
  height: 8px;
  background: #eef2f7;
  border-radius: 999px;
  overflow: hidden;
}

.distribution-row__fill {
  height: 100%;
  border-radius: 999px;
  transition: width 0.4s ease;
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

.rate-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.rate-cell__bar {
  flex: 1;
  min-width: 60px;
}

.rate-cell__fail {
  color: var(--el-color-danger);
  margin-left: 4px;
}

.cell-muted {
  color: var(--color-text-secondary);
}

.list-tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-8);
}

.list-tools__search {
  width: 200px;
}

.list-tools__filter {
  width: 180px;
}

.table-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: var(--space-12);
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

@media (max-width: 1440px) {
  .kpi-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .insight-panels {
    grid-template-columns: 1fr;
  }

  .el-table {
    display: none;
  }

  .table-footer {
    justify-content: center;
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
