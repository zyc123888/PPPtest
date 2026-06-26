<template>
  <div class="login-page">
    <div class="login-shell">
      <section class="login-hero">
        <div class="brand-badge">QA Platform</div>
        <h1 class="cyber-title">OmniTest</h1>
        <p>统一管理测试资产、计划、执行与报告，支撑团队的交付效率。</p>
        <ul class="hero-points">
          <li>用例与计划一体化管理</li>
          <li>接口、UI、性能测试统一入口</li>
          <li>执行结果可视化与回溯</li>
        </ul>
        <div class="hero-foot">
          版本 1.0 · 企业级测试协作
        </div>
      </section>

      <section class="login-panel">
        <div class="panel-card">
          <div class="panel-title">欢迎登录</div>
          <div class="panel-subtitle">请输入账号与密码以进入工作台</div>

          <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="login-form">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="form.username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" class="login-button" @click="handleLogin">
                登录
              </el-button>
            </el-form-item>
          </el-form>

          <div class="login-hint">默认管理员：admin / admin123</div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: 'admin',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const handleLogin = () => {
  formRef.value?.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await authStore.login(form.username.trim(), form.password)
      const redirect = route.query.redirect || '/dashboard'
      router.replace(redirect)
    } catch (error) {
      ElMessage.error(error.message || '登录失败')
    } finally {
      loading.value = false
    }
  })
}

onMounted(() => {
  if (authStore.isAuthenticated) {
    const redirect = route.query.redirect || '/dashboard'
    router.replace(redirect)
  }
})
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.18), transparent 45%),
    radial-gradient(circle at 85% 0%, rgba(168, 85, 247, 0.2), transparent 50%),
    linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
  padding: 48px 24px;
  position: relative;
  overflow: hidden;
}

.login-page::before,
.login-page::after {
  content: "";
  position: absolute;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  filter: blur(0);
  opacity: 0.22;
  pointer-events: none;
}

.login-page::before {
  background: #0f766e;
  top: -140px;
  left: -120px;
}

.login-page::after {
  background: #2563eb;
  right: -140px;
  bottom: -120px;
}

.login-shell {
  width: min(1100px, 100%);
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
  gap: 36px;
  align-items: stretch;
  position: relative;
  z-index: 1;
}

.login-hero {
  color: #0f172a;
  padding: 32px 24px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.brand-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(99, 102, 241, 0.12);
  color: #4f46e5;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  width: fit-content;
}

.cyber-title {
  font-size: 48px;
  font-weight: 800;
  background: linear-gradient(135deg, #4f46e5 0%, #a855f7 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 16px;
  letter-spacing: -1px;
}

.login-hero p {
  margin: 0;
  color: #475569;
  font-size: 16px;
  line-height: 1.6;
}

.hero-points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
  color: #0f172a;
  font-weight: 500;
}

.hero-points li {
  padding-left: 20px;
  position: relative;
}

.hero-points li::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #0f766e;
  position: absolute;
  left: 0;
  top: 7px;
}

.hero-foot {
  margin-top: auto;
  font-size: 13px;
  color: #64748b;
}

.login-panel {
  display: flex;
  align-items: center;
  justify-content: center;
}

.panel-card {
  width: min(420px, 100%);
  background: var(--color-surface);
  border-radius: 16px;
  box-shadow: var(--shadow-soft);
  padding: 32px 28px;
  border: 1px solid rgba(148, 163, 184, 0.2);
}

.panel-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 6px;
}

.panel-subtitle {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin-bottom: 24px;
}

.login-form :deep(.el-form-item) {
  margin-bottom: var(--space-16);
}

.login-button {
  width: 100%;
}

.login-hint {
  margin-top: var(--space-16);
  font-size: var(--font-12);
  color: var(--color-text-secondary);
  text-align: center;
}

@media (max-width: 900px) {
  .login-shell {
    grid-template-columns: 1fr;
  }

  .login-hero {
    text-align: center;
    align-items: center;
  }

  .hero-points {
    justify-items: center;
  }

  .hero-points li {
    padding-left: 0;
  }

  .hero-points li::before {
    display: none;
  }
}
</style>
