<template>
  <div class="rte" :class="{ 'is-disabled': disabled }">
    <div v-if="editor && !disabled" class="rte-toolbar">
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('bold') }" title="加粗" @click="editor.chain().focus().toggleBold().run()"><b>B</b></button>
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('italic') }" title="斜体" @click="editor.chain().focus().toggleItalic().run()"><i>I</i></button>
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('strike') }" title="删除线" @click="editor.chain().focus().toggleStrike().run()"><s>S</s></button>
      <span class="rte-sep" />
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('heading', { level: 3 }) }" title="标题" @click="editor.chain().focus().toggleHeading({ level: 3 }).run()">H</button>
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('bulletList') }" title="无序列表" @click="editor.chain().focus().toggleBulletList().run()">•</button>
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('orderedList') }" title="有序列表" @click="editor.chain().focus().toggleOrderedList().run()">1.</button>
      <button type="button" class="rte-btn" :class="{ active: editor.isActive('codeBlock') }" title="代码块" @click="editor.chain().focus().toggleCodeBlock().run()">&lt;/&gt;</button>
      <span class="rte-sep" />
      <button type="button" class="rte-btn" title="插入图片" @click="pickImage">🖼</button>
      <span v-if="uploading" class="rte-hint">图片上传中…</span>
      <span v-else class="rte-hint rte-hint--tip">支持直接粘贴 / 拖拽图片</span>
      <input ref="fileInput" type="file" accept="image/*" class="rte-file" @change="onFilePicked" />
    </div>
    <editor-content class="rte-content" :editor="editor" />
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { Editor, EditorContent } from '@tiptap/vue-3'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import Placeholder from '@tiptap/extension-placeholder'
import { api } from '@/lib/api'
import { ElMessage } from 'element-plus'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue'])

const fileInput = ref(null)
const uploading = ref(false)

async function uploadImage(file) {
  if (!file || !file.type?.startsWith('image/')) return
  uploading.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await api.postForm('/uploads/image', fd)
    editor.chain().focus().setImage({ src: res.url }).run()
  } catch (error) {
    ElMessage.error(error.message || '图片上传失败')
  } finally {
    uploading.value = false
  }
}

function extractImageFiles(dataTransfer) {
  if (!dataTransfer) return []
  const files = []
  for (const item of dataTransfer.items || []) {
    if (item.kind === 'file' && item.type?.startsWith('image/')) {
      const f = item.getAsFile()
      if (f) files.push(f)
    }
  }
  if (!files.length && dataTransfer.files) {
    for (const f of dataTransfer.files) {
      if (f.type?.startsWith('image/')) files.push(f)
    }
  }
  return files
}

const editor = new Editor({
  content: props.modelValue || '',
  editable: !props.disabled,
  extensions: [
    StarterKit,
    Image.configure({ inline: false, allowBase64: false }),
    Placeholder.configure({ placeholder: props.placeholder })
  ],
  editorProps: {
    handlePaste(_view, event) {
      const images = extractImageFiles(event.clipboardData)
      if (images.length) {
        event.preventDefault()
        images.forEach(uploadImage)
        return true
      }
      return false
    },
    handleDrop(_view, event) {
      const images = extractImageFiles(event.dataTransfer)
      if (images.length) {
        event.preventDefault()
        images.forEach(uploadImage)
        return true
      }
      return false
    }
  },
  onUpdate() {
    const html = editor.getHTML()
    emit('update:modelValue', editor.isEmpty ? '' : html)
  }
})

function pickImage() {
  fileInput.value?.click()
}
function onFilePicked(e) {
  const file = e.target.files?.[0]
  if (file) uploadImage(file)
  e.target.value = ''
}

watch(() => props.modelValue, (val) => {
  const current = editor.isEmpty ? '' : editor.getHTML()
  if ((val || '') !== current) {
    editor.commands.setContent(val || '', false)
  }
})

watch(() => props.disabled, (val) => {
  editor.setEditable(!val)
})

onBeforeUnmount(() => {
  editor.destroy()
})
</script>

<style scoped>
.rte { border: 1px solid var(--el-border-color); border-radius: 6px; overflow: hidden; background: var(--el-fill-color-blank); }
.rte.is-disabled { background: var(--el-fill-color-light); }
.rte-toolbar { display: flex; align-items: center; gap: 2px; flex-wrap: wrap; padding: 4px 6px; border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-fill-color-light); }
.rte-btn { min-width: 26px; height: 26px; padding: 0 6px; border: none; background: transparent; border-radius: 4px; cursor: pointer; font-size: 13px; color: var(--el-text-color-regular); line-height: 1; }
.rte-btn:hover { background: var(--el-fill-color-dark); }
.rte-btn.active { background: var(--el-color-primary-light-8); color: var(--el-color-primary); }
.rte-sep { width: 1px; height: 16px; background: var(--el-border-color); margin: 0 4px; }
.rte-hint { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 6px; }
.rte-hint--tip { color: var(--el-text-color-placeholder); }
.rte-file { display: none; }
.rte-content { padding: 8px 11px; min-height: 90px; max-height: 320px; overflow-y: auto; font-size: 14px; }
.rte-content :deep(.ProseMirror) { outline: none; min-height: 74px; line-height: 1.6; }
.rte-content :deep(.ProseMirror p) { margin: 4px 0; }
.rte-content :deep(.ProseMirror img) { max-width: 100%; border-radius: 4px; display: block; margin: 6px 0; }
.rte-content :deep(.ProseMirror pre) { background: var(--el-fill-color-dark); border-radius: 4px; padding: 8px 10px; overflow-x: auto; }
.rte-content :deep(.ProseMirror p.is-editor-empty:first-child::before) { content: attr(data-placeholder); color: var(--el-text-color-placeholder); float: left; height: 0; pointer-events: none; }
</style>
