<template>
  <div v-if="gates.length" class="gate-issues-panel">
    <div class="gate-issues-title">门禁风险摘要</div>
    <div v-for="gate in gates" :key="gate.key" class="gate-issue-group">
      <div class="gate-issue-head">
        <el-tag :type="gate.tagType" size="small">{{ gate.label }} · {{ gate.statusText }}</el-tag>
        <span v-if="gate.recoveryText" class="gate-recovery">建议：{{ gate.recoveryText }}</span>
      </div>
      <div v-if="gate.recoveryActions?.length" class="gate-actions">
        <template v-for="action in gate.recoveryActions" :key="`${action.action}:${action.source_id || gate.key}`">
          <el-button
            size="small"
            type="primary"
            plain
            :title="action.reason || ''"
            :loading="action.action === 'rerun_source' ? rerunningShard === action.source_id : rerunning"
            :disabled="!action.enabled || !!rerunningShard || rerunning || ['RUNNING', 'PENDING'].includes(jobStatus)"
            @click="action.action === 'rerun_source' ? emit('rerun-source', { source_id: action.source_id }) : emit('rerun-job')"
          >
            {{ action.label }}
          </el-button>
          <span v-if="!action.enabled && action.reason" class="gate-action-reason">
            {{ action.reason }}
          </span>
        </template>
      </div>
      <div v-for="(issue, index) in gate.issues" :key="index" class="gate-issue-msg" :class="`is-${issue.severity || 'warning'}`">
        {{ issue.message || issue.code || '-' }}
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  gates: { type: Array, default: () => [] },
  jobStatus: { type: String, default: '' },
  rerunningShard: { type: String, default: '' },
  rerunning: { type: Boolean, default: false },
})

const emit = defineEmits(['rerun-source', 'rerun-job'])
</script>

<style scoped>
.gate-issues-panel {
  display: grid;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid rgba(239, 68, 68, 0.16);
  border-radius: 14px;
  background: rgba(255, 247, 247, 0.84);
}

.gate-issues-title {
  color: #991b1b;
  font-size: 13px;
  font-weight: 700;
}

.gate-issue-group {
  display: grid;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid rgba(239, 68, 68, 0.12);
}

.gate-issue-head,
.gate-actions {
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

.gate-action-reason {
  color: #b45309;
  font-size: 12px;
}

.gate-actions :deep(.el-button) {
  max-width: 100%;
  margin-left: 0;
  padding-inline: 10px;
  border-radius: 999px;
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
</style>
