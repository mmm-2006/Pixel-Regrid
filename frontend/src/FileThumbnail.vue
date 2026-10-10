<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Image } from 'lucide-vue-next'
const props = defineProps({ file: Object, api: Object })
const host = ref(null), src = ref(null)
let observer, live = true
// Decode only visible rows, with at most two simultaneous bridge calls.
const load = async () => {
  try {
    const result = await props.api.thumbnail(props.file.key)
    if (live && result.ok) src.value = result.image.src
  } catch { /* A corrupt input remains selectable so its error can be inspected. */ }
}
onMounted(() => {
  observer = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); enqueue(load) }
  })
  observer.observe(host.value)
})
onBeforeUnmount(() => { live = false; observer?.disconnect() })
</script>

<script>
const queue = []
let running = 0
function enqueue(task) { queue.push(task); drain() }
function drain() {
  while (running < 2 && queue.length) {
    running++
    Promise.resolve(queue.shift()()).finally(() => { running--; drain() })
  }
}
</script>

<template><span ref="host" class="file-thumbnail"><img v-if="src" :src="src" alt="" /><Image v-else :size="18" /></span></template>
