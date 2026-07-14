<template>
  <el-tag size="small" type="info">{{ pipelineModeLabel(mode) }}</el-tag>
</template>

<script setup>
import { pipelineModeLabel } from '@/lib/caseGenerationUi'

defineProps({
  mode: { type: String, default: 'lite' }
})
</script>
