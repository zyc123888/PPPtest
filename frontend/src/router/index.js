import { createRouter, createWebHistory } from 'vue-router'
import Layout from '@/layout/index.vue'
import { useAuthStore } from '@/stores/auth'

const Login = () => import('@/views/login/index.vue')
const Dashboard = () => import('@/views/dashboard/index.vue')
const Workspace = () => import('@/views/workspace/index.vue')
const Project = () => import('@/views/project/index.vue')
const CaseCenter = () => import('@/views/case/index.vue')
const APICase = () => import('@/views/case/api/index.vue')
const UICase = () => import('@/views/case/ui/index.vue')
const PerformanceCase = () => import('@/views/case/performance/index.vue')
const CaseGenerator = () => import('@/views/case/generator/index.vue')
const CaseGenerator2 = () => import('@/views/case/generator2/index.vue')
const Plan = () => import('@/views/plan/index.vue')
const Environment = () => import('@/views/environment/index.vue')
const Execution = () => import('@/views/execution/index.vue')
const Report = () => import('@/views/report/index.vue')
const Tools = () => import('@/views/tools/index.vue')
const User = () => import('@/views/user/index.vue')

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
        path: 'index',
        component: CaseCenter,
        name: 'CaseCenter',
        meta: { title: '用例中心', icon: 'Collection' }
      },
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
      },
      {
        path: 'performance',
        component: PerformanceCase,
        name: 'PerformanceCase',
        meta: { title: '性能用例', icon: 'Histogram' }
      },
      {
        path: 'generator',
        component: CaseGenerator,
        name: 'CaseGenerator',
        meta: { title: '用例生成', icon: 'MagicStick' }
      },
      {
        path: 'generator2',
        component: CaseGenerator2,
        name: 'CaseGenerator2',
        meta: { title: '用例生成2', icon: 'Operation' }
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
        meta: { title: '常用工具', icon: 'Tools', testId: 'tab-tools' }
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
        meta: { title: '用户权限', icon: 'UserFilled', roles: ['admin'] }
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
  const authStore = useAuthStore()
  if (!authStore.isAuthenticated) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  if (!authStore.loaded) {
    try {
      await authStore.fetchProfile()
    } catch {
      await authStore.logout()
      return next({ path: '/login', query: { redirect: to.fullPath } })
    }
  }
  const allowedRoles = to.matched.flatMap((record) => record.meta?.roles || [])
  if (allowedRoles.length > 0 && !allowedRoles.includes(authStore.user?.role)) {
    return next('/dashboard')
  }
  return next()
})

export default router
