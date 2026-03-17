import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layout/index.vue'
import Login from '@/views/login/index.vue'
import Dashboard from '@/views/dashboard/index.vue'
import Workspace from '@/views/workspace/index.vue'
import Project from '@/views/project/index.vue'
import APICase from '@/views/case/api/index.vue'
import UICase from '@/views/case/ui/index.vue'
import Plan from '@/views/plan/index.vue'
import Environment from '@/views/environment/index.vue'
import Execution from '@/views/execution/index.vue'
import Report from '@/views/report/index.vue'
import Tools from '@/views/tools/index.vue'
import User from '@/views/user/index.vue'

export const constantRoutes = [
  {
    path: '/login',
    component: Login,
    name: 'Login',
    meta: { public: true, title: '登录' }
  },
  {
    path: '/',
    component: Layout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        component: Dashboard,
        name: 'Dashboard',
        meta: { title: '工作台', icon: 'Odometer', affix: true }
      }
    ]
  },
  {
    path: '/workspace',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Workspace,
        name: 'Workspace',
        meta: { title: '工作空间', icon: 'OfficeBuilding' }
      }
    ]
  },
  {
    path: '/project',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Project,
        name: 'Project',
        meta: { title: '项目管理', icon: 'Folder' }
      }
    ]
  },
  {
    path: '/case',
    component: Layout,
    meta: { title: '用例管理', icon: 'List' },
    children: [
      {
        path: 'api',
        component: APICase,
        name: 'APICase',
        meta: { title: '接口用例', icon: 'Link' }
      },
      {
        path: 'ui',
        component: UICase,
        name: 'UICase',
        meta: { title: 'UI 用例', icon: 'Monitor' }
      }
    ]
  },
  {
    path: '/plan',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Plan,
        name: 'Plan',
        meta: { title: '测试计划', icon: 'Calendar' }
      }
    ]
  },
  {
    path: '/environment',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Environment,
        name: 'Environment',
        meta: { title: '环境管理', icon: 'Grid' }
      }
    ]
  },
  {
    path: '/execution',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Execution,
        name: 'Execution',
        meta: { title: '执行中心', icon: 'VideoPlay' }
      }
    ]
  },
  {
    path: '/report',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Report,
        name: 'Report',
        meta: { title: '报告中心', icon: 'Document' }
      }
    ]
  },
  {
    path: '/tools',
    component: Layout,
    children: [
      {
        path: 'index',
        component: Tools,
        name: 'Tools',
        meta: { title: '常用工具', icon: 'Tools' }
      }
    ]
  },
  {
    path: '/user',
    component: Layout,
    children: [
      {
        path: 'index',
        component: User,
        name: 'User',
        meta: { title: '用户权限', icon: 'UserFilled' }
      }
    ]
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/dashboard'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes: constantRoutes
})

router.beforeEach(async (to, from, next) => {
  if (to.meta?.public) {
    return next()
  }
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()
  if (!authStore.isAuthenticated) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  if (!authStore.loaded) {
    try {
      await authStore.fetchProfile()
    } catch (error) {
      await authStore.logout()
      return next({ path: '/login', query: { redirect: to.fullPath } })
    }
  }
  return next()
})

export default router
