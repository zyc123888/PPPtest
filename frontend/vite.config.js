import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    plugins: [
      vue(),
      // 按需自动导入 Element Plus 的 JS API（ElMessage/ElMessageBox 等）
      // importStyle:false —— 样式仍由 main.js 全量 CSS 提供，避免重复注入，仅对 JS 做 tree-shaking
      AutoImport({ resolvers: [ElementPlusResolver({ importStyle: false })] }),
      // 按需自动导入 Element Plus 组件与指令（v-loading 等），实现 JS tree-shaking
      Components({ resolvers: [ElementPlusResolver({ importStyle: false })] })
    ],
    test: {
      environment: 'jsdom',
      globals: true
    },
    build: {
      // 已完成实质分包（按需引入 + tiptap/图标/路由级拆分），
      // 剩余 element-plus 核心组件 chunk 为本应用固有基线（gzip 约 277KB），上调阈值避免噪声告警
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          // 使用函数形式分块：仅将“经 tree-shaking 后实际被引入”的依赖归组，
          // 避免数组形式强制打包整包导致 tree-shaking 失效
          manualChunks(id) {
            if (!id.includes('node_modules')) return
            if (/[\\/]node_modules[\\/]@tiptap[\\/]/.test(id)) return 'tiptap'
            if (id.includes('node_modules/@element-plus/icons-vue')) return 'element-plus-icons'
            if (id.includes('node_modules/element-plus')) return 'element-plus'
            if (/[\\/]node_modules[\\/](vue|@vue|vue-router|pinia)[\\/]/.test(id)) return 'vue'
          }
        }
      }
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    },
    preview: {
      host: '0.0.0.0',
      port: 3000
    }
  }
})
