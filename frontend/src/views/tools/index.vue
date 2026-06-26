<template>
  <div class="app-page">
    <PageHeader title="常用工具" subtitle="提供常用的测试数据辅助能力" />

    <div class="tools-hero section-gap">
      <el-card class="page-card tools-hero__main" shadow="never">
        <div class="tools-hero__kicker">Utility Layer</div>
        <div class="tools-hero__title">常用工具</div>
        <div class="tools-hero__subtitle">把格式化、编码、时间转换这类辅助能力统一收口，保持平台内部工具的一致视觉。</div>
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="工具页签" :value="3" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="JSON 默认内容" :value="jsonTool.input ? 1 : 0" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="Base64 示例" :value="base64Tool.input ? 1 : 0" />
      </el-card>
      <el-card class="page-card tools-hero__stat" shadow="never">
        <el-statistic title="时间样例" :value="timestampTool.input ? 1 : 0" />
      </el-card>
    </div>

    <el-card class="page-card" shadow="never">
      <el-tabs v-model="activeTab" type="card">
        <el-tab-pane label="JSON 格式化" name="json">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="jsonTool.input" data-testid="json-input" type="textarea" :rows="18" placeholder="请输入 JSON" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="jsonTool.output" data-testid="json-output" type="textarea" :rows="18" readonly placeholder="格式化结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button data-testid="json-format-btn" type="primary" @click="handleJsonFormat">格式化 JSON</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="Base64 编解码" name="base64">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="base64Tool.input" type="textarea" :rows="12" placeholder="请输入内容" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="base64Tool.output" type="textarea" :rows="12" readonly placeholder="结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button type="primary" @click="handleBase64Encode">编码</el-button>
              <el-button @click="handleBase64Decode">解码</el-button>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="时间戳转换" name="timestamp">
          <el-row :gutter="16" class="section-gap">
            <el-col :xs="24" :lg="12">
              <el-input v-model="timestampTool.input" type="textarea" :rows="10" placeholder="请输入时间戳或日期字符串" />
            </el-col>
            <el-col :xs="24" :lg="12">
              <el-input v-model="timestampTool.output" type="textarea" :rows="10" readonly placeholder="转换结果" />
            </el-col>
          </el-row>
          <div class="toolbar">
            <div />
            <div class="toolbar-right">
              <el-button type="primary" @click="handleTimestampConvert">转换</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'

const activeTab = ref('json')

const jsonTool = reactive({
  input: '{\n  "name": "OmniTest",\n  "module": "接口测试"\n}',
  output: ''
})

const base64Tool = reactive({
  input: 'platform-demo',
  output: ''
})

const timestampTool = reactive({
  input: '2026-03-09T09:30:00+08:00',
  output: ''
})

const handleJsonFormat = async () => {
  try {
    const res = await api.post('/tools/json/format', { payload: jsonTool.input })
    jsonTool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleBase64Encode = async () => {
  try {
    const res = await api.post('/tools/base64/encode', { payload: base64Tool.input })
    base64Tool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleBase64Decode = async () => {
  try {
    const res = await api.post('/tools/base64/decode', { payload: base64Tool.input })
    base64Tool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}

const handleTimestampConvert = async () => {
  try {
    const res = await api.post('/tools/timestamp/convert', { payload: timestampTool.input })
    timestampTool.output = res.result
  } catch (error) {
    ElMessage.error(error.message)
  }
}
</script>

<style scoped>
.tools-hero {
  display: grid;
  grid-template-columns: minmax(0, 2fr) repeat(4, minmax(0, 1fr));
  gap: var(--space-12);
}

.tools-hero__main {
  border-radius: 20px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.88)),
    radial-gradient(circle at top right, rgba(99, 102, 241, 0.26), transparent 35%);
  color: #f8fafc;
}

.tools-hero__kicker {
  font-size: 12px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(226, 232, 240, 0.72);
  margin-bottom: 10px;
}

.tools-hero__title {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 10px;
}

.tools-hero__subtitle {
  max-width: 760px;
  color: rgba(226, 232, 240, 0.82);
  line-height: 1.7;
}

.tools-hero__stat {
  border-radius: 18px;
}

@media (max-width: 960px) {
  .tools-hero {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .tools-hero__main {
    grid-column: 1 / -1;
  }
}
</style>
