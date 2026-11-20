<template>
  <el-config-provider :locale="zhCn">
    <!-- Hidden SVG Optical Refraction Filter for Apple Liquid Glass -->
    <svg class="liquid-svg-defs" width="0" height="0" aria-hidden="true">
      <defs>
        <filter id="liquid-glass-refract" x="-15%" y="-15%" width="130%" height="130%" color-interpolation-filters="sRGB">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.008 0.012"
            numOctaves="2"
            seed="12"
            result="noise"
          />
          <feGaussianBlur in="noise" stdDeviation="4" result="smoothNoise" />
          <feDisplacementMap
            in="SourceGraphic"
            in2="smoothNoise"
            scale="18"
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>

    <!-- Rich macOS Tahoe Luminous Mesh Wallpaper (Active in Liquid Glass mode) -->
    <div v-if="isLiquid" class="liquid-backdrop" aria-hidden="true">
      <span class="liquid-orb liquid-orb--blue" />
      <span class="liquid-orb liquid-orb--violet" />
      <span class="liquid-orb liquid-orb--rose" />
      <span class="liquid-orb liquid-orb--mint" />
    </div>

    <router-view />
  </el-config-provider>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useAppStore } from '@/stores/app'

const appStore = useAppStore()
const isLiquid = computed(() => appStore.glassMode === 'liquid')

let rafId = null
const handlePointerMove = (e) => {
  if (!isLiquid.value || rafId) return
  rafId = window.requestAnimationFrame(() => {
    document.documentElement.style.setProperty('--lg-mx', `${e.clientX}px`)
    document.documentElement.style.setProperty('--lg-my', `${e.clientY}px`)
    rafId = null
  })
}

onMounted(() => {
  document.documentElement.dataset.glass = appStore.glassMode
  window.addEventListener('pointermove', handlePointerMove, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', handlePointerMove)
  if (rafId) window.cancelAnimationFrame(rafId)
})
</script>
