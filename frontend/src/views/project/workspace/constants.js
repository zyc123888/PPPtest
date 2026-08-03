// 项目工作台共享常量：状态机、看板列、标签配色

export const REQUIREMENT_COLUMNS = [
  { key: 'PENDING', label: '待处理' },
  { key: 'PLANNING', label: '规划中' },
  { key: 'IN_PROGRESS', label: '实现中' },
  { key: 'TESTING', label: '测试中' },
  { key: 'DONE', label: '已完成' },
  { key: 'CLOSED', label: '已关闭' }
]

export const REQUIREMENT_STATUS_LABELS = {
  PENDING: '待处理',
  PLANNING: '规划中',
  IN_PROGRESS: '实现中',
  TESTING: '测试中',
  DONE: '已完成',
  CLOSED: '已关闭',
  REJECTED: '已拒绝'
}

export const TASK_COLUMNS = [
  { key: 'TODO', label: '待办' },
  { key: 'DOING', label: '进行中' },
  { key: 'REVIEW', label: '评审中' },
  { key: 'DONE', label: '已完成' }
]

export const TASK_STATUS_LABELS = {
  TODO: '待办',
  DOING: '进行中',
  REVIEW: '评审中',
  DONE: '已完成'
}

export const DEFECT_COLUMNS = [
  { key: 'NEW', label: '新建' },
  { key: 'CONFIRMED', label: '已确认' },
  { key: 'IN_PROGRESS', label: '处理中' },
  { key: 'RESOLVED', label: '已解决' },
  { key: 'VERIFYING', label: '验证中' },
  { key: 'CLOSED', label: '已关闭' }
]

export const DEFECT_STATUS_LABELS = {
  NEW: '新建',
  CONFIRMED: '已确认',
  IN_PROGRESS: '处理中',
  RESOLVED: '已解决',
  VERIFYING: '验证中',
  CLOSED: '已关闭',
  REOPENED: '重新打开',
  WONTFIX: '不予处理'
}

export const STATUS_TAG_TYPE = {
  PENDING: 'info',
  PLANNING: '',
  IN_PROGRESS: 'warning',
  TESTING: 'warning',
  DONE: 'success',
  CLOSED: 'info',
  REJECTED: 'danger',
  TODO: 'info',
  DOING: 'warning',
  REVIEW: 'warning',
  NEW: 'danger',
  CONFIRMED: 'warning',
  RESOLVED: 'success',
  VERIFYING: 'warning',
  REOPENED: 'danger',
  WONTFIX: 'info'
}

export const PRIORITY_OPTIONS = ['P0', 'P1', 'P2', 'P3']

export const PRIORITY_TAG_TYPE = {
  P0: 'danger',
  P1: 'warning',
  P2: '',
  P3: 'info'
}

export const SEVERITY_OPTIONS = ['BLOCKER', 'CRITICAL', 'MAJOR', 'MINOR', 'TRIVIAL']

export const SEVERITY_LABELS = {
  BLOCKER: '致命',
  CRITICAL: '严重',
  MAJOR: '一般',
  MINOR: '次要',
  TRIVIAL: '轻微'
}

export const SEVERITY_TAG_TYPE = {
  BLOCKER: 'danger',
  CRITICAL: 'danger',
  MAJOR: 'warning',
  MINOR: 'info',
  TRIVIAL: 'info'
}

export const REQUIREMENT_TYPE_OPTIONS = [
  { value: 'FEATURE', label: '功能' },
  { value: 'OPTIMIZATION', label: '优化' },
  { value: 'TECH_DEBT', label: '技术债' }
]

export const DEFECT_TYPE_OPTIONS = [
  { value: 'FUNCTION', label: '功能缺陷' },
  { value: 'PERFORMANCE', label: '性能缺陷' },
  { value: 'UI', label: '界面/交互' },
  { value: 'COMPATIBILITY', label: '兼容性' },
  { value: 'USABILITY', label: '易用性' },
  { value: 'SECURITY', label: '安全' },
  { value: 'DATA', label: '数据' },
  { value: 'OTHER', label: '其他' }
]

export const DEFECT_TYPE_LABELS = DEFECT_TYPE_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label
  return acc
}, {})

export const REPRODUCIBILITY_OPTIONS = [
  { value: 'ALWAYS', label: '必现' },
  { value: 'SOMETIMES', label: '偶现' },
  { value: 'RARELY', label: '极少复现' },
  { value: 'UNABLE', label: '无法复现' }
]

export const REPRODUCIBILITY_LABELS = REPRODUCIBILITY_OPTIONS.reduce((acc, item) => {
  acc[item.value] = item.label
  return acc
}, {})

export const PROJECT_ROLE_LABELS = {
  owner: '所有者',
  manager: '管理者',
  member: '成员',
  viewer: '观察者'
}

export const WORKSPACE_TABS = [
  { name: 'ProjectOverview', label: '概览', icon: 'Odometer' },
  { name: 'ProjectRequirements', label: '需求', icon: 'Tickets' },
  { name: 'ProjectIterations', label: '迭代', icon: 'Calendar' },
  { name: 'ProjectTasks', label: '任务', icon: 'Finished' },
  { name: 'ProjectDefects', label: '缺陷', icon: 'Warning' },
  { name: 'ProjectTrace', label: '追溯', icon: 'Share' },
  { name: 'ProjectSettings', label: '设置', icon: 'Setting' }
]
