<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({ image: Object, camera: Object, grid: Boolean, background: String, compact: Boolean })
const emit = defineEmits(['camera', 'scale'])
const canvas = ref(null)
const host = ref(null)
let bitmap = null
let observer = null
let drag = null
let imageVersion = 0
let frame = null
const dragging = ref(false)
const backgroundClass = computed(() => `background-${props.background}`)

function dimensions() {
  return { w: host.value?.clientWidth || 1, h: host.value?.clientHeight || 1 }
}
function scale() {
  if (!props.image) return 1
  const { w, h } = dimensions()
  const margin = props.compact ? 24 : 56
  const fit = Math.min((w - margin) / props.image.width, (h - margin) / props.image.height)
  return (props.camera.actual ? 1 : Math.max(.001, fit)) * props.camera.factor
}
function draw() {
  frame = null
  if (!canvas.value) return
  const { w, h } = dimensions()
  const dpr = window.devicePixelRatio || 1
  canvas.value.width = Math.round(w * dpr)
  canvas.value.height = Math.round(h * dpr)
  const context = canvas.value.getContext('2d')
  context.scale(dpr, dpr)
  context.clearRect(0, 0, w, h)
  if (!bitmap || !props.image) return
  const s = scale()
  emit('scale', s)
  const iw = props.image.width * s, ih = props.image.height * s
  const x = (w - iw) / 2 + props.camera.x, y = (h - ih) / 2 + props.camera.y
  context.imageSmoothingEnabled = false
  context.drawImage(bitmap, x, y, iw, ih)
  if (props.grid && s >= 6 && !props.image.limited) {
    context.strokeStyle = 'rgba(150,160,150,.42)'
    context.lineWidth = 1
    context.beginPath()
    const left = Math.max(0, Math.floor(-x / s)), right = Math.min(props.image.width, Math.ceil((w - x) / s))
    const top = Math.max(0, Math.floor(-y / s)), bottom = Math.min(props.image.height, Math.ceil((h - y) / s))
    for (let i = left; i <= right; i++) {
      context.moveTo(x + i * s, Math.max(0, y)); context.lineTo(x + i * s, Math.min(h, y + ih))
    }
    for (let i = top; i <= bottom; i++) {
      context.moveTo(Math.max(0, x), y + i * s); context.lineTo(Math.min(w, x + iw), y + i * s)
    }
    context.stroke()
  }
}
function redraw() {
  if (!frame) frame = requestAnimationFrame(draw)
}
watch(() => props.image?.src, src => {
  const version = ++imageVersion
  bitmap = null
  redraw()
  if (!src) return
  const image = new Image()
  image.onload = () => { if (version === imageVersion) { bitmap = image; redraw() } }
  image.src = src
}, { immediate: true })
watch(() => [props.camera, props.grid, props.background, props.compact], redraw, { deep: true })
onMounted(() => { observer = new ResizeObserver(redraw); observer.observe(host.value); redraw() })
onBeforeUnmount(() => { observer?.disconnect(); if (frame) cancelAnimationFrame(frame) })
function pointerDown(event) {
  if (!props.image || event.button !== 0) return
  drag = { x: event.clientX, y: event.clientY, startX: props.camera.x, startY: props.camera.y }
  dragging.value = true
  canvas.value.setPointerCapture(event.pointerId)
}
function pointerMove(event) {
  if (!drag) return
  emit('camera', { ...props.camera, x: drag.startX + event.clientX - drag.x, y: drag.startY + event.clientY - drag.y })
}
function pointerUp() { drag = null; dragging.value = false }
function wheel(event) {
  if (!props.image) return
  const factor = Math.max(.05, Math.min(64, props.camera.factor * Math.exp(-event.deltaY * .002)))
  const ratio = factor / props.camera.factor
  const rect = canvas.value.getBoundingClientRect()
  const x = event.clientX - rect.left - rect.width / 2, y = event.clientY - rect.top - rect.height / 2
  emit('camera', { ...props.camera, factor, x: x - (x - props.camera.x) * ratio, y: y - (y - props.camera.y) * ratio })
}
</script>

<template>
  <div ref="host" class="canvas-host" :class="[backgroundClass, { dragging }]">
    <canvas ref="canvas" aria-label="图片预览，滚轮缩放，拖动平移" @pointerdown="pointerDown" @pointermove="pointerMove"
      @pointerup="pointerUp" @pointercancel="pointerUp" @wheel.prevent="wheel" />
    <span v-if="image?.limited" class="canvas-note">大图预览已抽样 · 导出使用完整尺寸</span>
    <span v-if="!image" class="canvas-placeholder">等待预览</span>
  </div>
</template>
