<template>
  <div class="app-page">
    <PageHeader title="常用工具" subtitle="提供常用的测试数据辅助能力" />

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
  input: '{\n  "name": "自动化测试平台",\n  "module": "接口测试"\n}',
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
