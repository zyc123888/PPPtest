<template>
  <img
    src="/logo.png"
    alt="OmniTest"
    :width="size"
    :height="size"
    class="omnitest-brand-img"
    draggable="false"
  />
</template>

<script setup>
defineProps({
  size: {
    type: [Number, String],
    default: 28
  }
})
</script>

<style scoped>
.omnitest-brand-img {
  display: block;
  object-fit: contain;
  flex-shrink: 0;
  user-select: none;
}
</style>
