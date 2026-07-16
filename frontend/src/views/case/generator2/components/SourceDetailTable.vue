<template>
  <div v-if="sources.length" class="sources-detail-panel">
    <div class="sources-detail-title">直接测试对象明细</div>
    <div class="sources-detail-scroll">
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
          <tr v-for="source in sources" :key="source.source_id" :class="{ 'has-source-gap': hasSourceGap(source) }">
            <td class="src-id">{{ source.source_id }}</td>
            <td class="src-title">{{ source.title_path || source.title || '-' }}</td>
            <td class="src-num">{{ source.fp_count }}</td>
            <td class="src-num">{{ source.actual_case_count }}</td>
            <td><el-tag :type="sourceStatusTag(source.must_cover_status)" size="small">{{ source.must_cover_status || '-' }}</el-tag></td>
            <td><el-tag :type="sourceStatusTag(source.method_consumption_status)" size="small">{{ source.method_consumption_status || '-' }}</el-tag></td>
            <td class="src-num">{{ source.merge_count }}</td>
            <td>
              <el-tag v-if="hasSourceGap(source)" type="warning" size="small">有缺口</el-tag>
              <el-tag v-else-if="source.gate_issues?.length" type="warning" size="small">有问题</el-tag>
              <el-tag v-else type="success" size="small">正常</el-tag>
              <div v-if="source.gate_issues?.length" class="src-issues">
                <div v-for="(issue, index) in source.gate_issues" :key="index" class="src-issue-msg">{{ issue.message }}</div>
              </div>
              <div v-if="source.shard_error" class="src-issue-msg">{{ source.shard_error }}</div>
            </td>
            <td class="src-action">
              <el-button
                v-if="canRerun(source)"
                size="small"
                type="primary"
                plain
                :loading="rerunningShard === source.source_id"
                :disabled="!!rerunningShard"
                @click="emit('rerun-source', source)"
              >
                重跑
              </el-button>
              <span v-else>-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { canRerunSourceShard, hasSourceGap, sourceStatusTag } from '../presentation'

const props = defineProps({
  sources: { type: Array, default: () => [] },
  job: { type: Object, default: null },
  trusted: { type: Boolean, default: false },
  rerunningShard: { type: String, default: '' }
})

const emit = defineEmits(['rerun-source'])
const canRerun = (source) => canRerunSourceShard(props.job, props.trusted, source)
</script>

<style scoped>
.sources-detail-panel {
  margin: 12px 0 14px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.14);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.78);
}

.sources-detail-title {
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  color: #6e6e73;
  font-size: 12px;
  font-weight: 600;
}

.sources-detail-scroll {
  overflow-x: auto;
}

.sources-detail-table {
  width: 100%;
  min-width: 840px;
  border-collapse: collapse;
  font-size: 12px;
}

.sources-detail-table th,
.sources-detail-table td {
  padding: 7px 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  text-align: left;
  vertical-align: top;
}

.sources-detail-table th {
  color: #86868b;
  font-weight: 500;
  white-space: nowrap;
}

.sources-detail-table tr:last-child td {
  border-bottom: 0;
}

.sources-detail-table tr.has-source-gap td {
  background: rgba(245, 158, 11, 0.05);
}

.src-id {
  color: #6366f1;
  font-family: monospace;
  white-space: nowrap;
}

.src-title {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.src-num,
.src-action {
  text-align: center !important;
}

.src-action {
  width: 72px;
  white-space: nowrap;
}

.src-issues {
  margin-top: 4px;
}

.src-issue-msg {
  color: #d97706;
  font-size: 11px;
  line-height: 1.4;
}
</style>
