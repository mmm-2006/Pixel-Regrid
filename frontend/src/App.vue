<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Plus, FolderPlus, FolderOpen, ChevronDown, X,
  Grid2X2, ZoomIn, ZoomOut, Maximize, Download,
  Trash2, LoaderCircle, CheckCircle2, CircleAlert } from 'lucide-vue-next'
import PreviewCanvas from './PreviewCanvas.vue'
import FileThumbnail from './FileThumbnail.vue'
import { nextSelection, optionPayload, statusLabels, waitForBridge } from './bridge'

const api = ref(null)
const connected = ref(false)
const files = ref([]), selected = ref([]), activeKey = ref(null)
const revision = ref(-1), busy = ref(false), cancelling = ref(false), closing = ref(false)
const status = ref('连接桌面应用…'), progress = ref({ done: 0, total: 0 }), details = ref([])
const outputDir = ref(''), error = ref(''), showLog = ref(false), showHelp = ref(false)
const pending = ref(false), preview = ref(null), previewError = ref('')
const compare = ref(true), grid = ref(false), background = ref('checker')
const camera = ref({ actual: false, factor: 1, x: 0, y: 0 }), outputScale = ref(1)
const options = reactive({ direct: false, method: 'center', layout: 'original', width: 32,
  height: 32, resample: 'pixel', palette_size: 32, detail: 1, alpha_threshold: 1 })
const activeFile = computed(() => files.value.find(file => file.key === activeKey.value))
const resize = computed(() => ['fit', 'canvas_fit', 'stretch'].includes(options.layout))
const successCount = computed(() => files.value.filter(file => file.status === 'success').length)
const layoutHelp = computed(() => ({ original: '保留识别后的完整尺寸，不缩放、不裁边。',
  keep: '裁透明边，主体不缩放；画布不能小于主体。', fit: '裁透明留白后等比例缩放，适合物品图标。',
  canvas_fit: '连同原有留白等比例缩放，不足部分补透明边。', stretch: '整图铺满目标尺寸，比例不同时会拉伸。' })[options.layout])
const algorithmHelp = computed(() => ({ pixel: '优先保留细线和小色块；较强保护也可能保留噪点。',
  nearest: '保留原有颜色和硬边；缩小时可能丢失细线。', 'k-centroid': '以局部主色形成清晰色块；少量高光可能被舍弃。' })[options.resample])
let pollTimer, previewTimer, generation = 0, disposed = false, pollFailures = 0

function applyState(state) {
  if (!state?.files || state.revision < revision.value) return
  const oldBusy = busy.value, oldFile = activeFile.value
  revision.value = state.revision
  files.value = state.files
  selected.value = nextSelection(state.files, selected.value)
  if (!selected.value.includes(activeKey.value)) activeKey.value = selected.value[0] || null
  busy.value = state.busy; cancelling.value = state.cancelling; closing.value = state.closing
  status.value = state.status; progress.value = state.progress; details.value = state.details; outputDir.value = state.output_dir
  if (oldBusy !== state.busy || oldFile?.output !== activeFile.value?.output || oldFile?.error !== activeFile.value?.error) schedulePreview()
}
async function invoke(method, ...args) {
  error.value = ''
  try {
    if (!api.value) throw new Error('桌面连接未就绪')
    const result = await api.value[method](...args)
    if (!result?.ok) throw new Error(result?.error || '操作失败')
    applyState(result)
    return result
  } catch (exception) { error.value = exception.message; return null }
}
async function poll() {
  if (disposed || !api.value) return
  try {
    const result = await api.value.get_state(revision.value)
    if (!result.ok) throw new Error(result.error)
    applyState(result); pollFailures = 0
  } catch {
    if (++pollFailures === 3) error.value = '与桌面应用的连接中断，请重新打开应用。'
  } finally { if (!disposed) pollTimer = setTimeout(poll, 400) }
}
function schedulePreview() {
  const version = ++generation
  clearTimeout(previewTimer)
  api.value?.cancel_preview().catch(() => {})
  previewError.value = ''
  if (!activeKey.value || !connected.value) { preview.value = null; pending.value = false; return }
  pending.value = true
  previewTimer = setTimeout(async () => {
    try {
      const payload = optionPayload(options)
      if (!busy.value) {
        const configured = await api.value.configure(payload)
        if (version !== generation) return
        if (!configured.ok) throw new Error(configured.error)
      }
      const result = await api.value.preview(activeKey.value, payload)
      if (disposed || version !== generation) return
      if (result.cancelled) return
      if (!result.ok) throw new Error(result.error)
      preview.value = result
    } catch (exception) {
      if (version === generation) { previewError.value = exception.message; preview.value = null }
    } finally { if (version === generation) pending.value = false }
  }, 350)
}
watch(options, () => {
  if (!connected.value) return
  if (activeKey.value) schedulePreview()
  else { clearTimeout(previewTimer); previewTimer = setTimeout(() => invoke('configure', optionPayload(options)), 350) }
}, { deep: true })
watch(activeKey, () => { preview.value = null; camera.value = { actual: false, factor: 1, x: 0, y: 0 }; schedulePreview() })
function selectFile(file, event) {
  if (event.shiftKey && activeKey.value) {
    const a = files.value.findIndex(item => item.key === activeKey.value), b = files.value.indexOf(file)
    selected.value = files.value.slice(Math.min(a, b), Math.max(a, b) + 1).map(item => item.key)
  } else if (event.ctrlKey || event.metaKey) {
    selected.value = selected.value.includes(file.key) ? selected.value.filter(key => key !== file.key) : [...selected.value, file.key]
  } else selected.value = [file.key]
  activeKey.value = selected.value.includes(file.key) ? file.key : selected.value[0] || null
}
function preset(kind) {
  const presets = {
    restore: { direct: false, layout: 'original' },
    item: { layout: 'fit', width: 32, height: 32, resample: 'pixel', palette_size: 0, detail: 1 },
    block: { layout: 'stretch', width: 16, height: 16, resample: 'k-centroid' },
  }
  Object.assign(options, presets[kind])
}
function setSize(size) {
  options.width = options.height = size
  if (options.layout === 'original') options.layout = 'fit'
}
function useDimensions(subject) {
  const size = subject ? preview.value?.info?.subject : preview.value?.info?.grid
  if (!size) return
  Object.assign(options, { width: size[0], height: size[1], layout: subject ? 'keep' : 'canvas_fit' })
}
function zoom(multiplier) {
  const factor = Math.max(.05, Math.min(64, camera.value.factor * multiplier))
  const ratio = factor / camera.value.factor
  camera.value = { ...camera.value, factor, x: camera.value.x * ratio, y: camera.value.y * ratio }
}
function resetView(actual = false) { camera.value = { actual, factor: 1, x: 0, y: 0 } }
async function exportFiles(all) {
  clearTimeout(previewTimer)
  generation++
  pending.value = false
  await invoke('start_export', all ? files.value.map(file => file.key) : selected.value, optionPayload(options))
}
function keydown(event) {
  if (event.target.matches('input, select, textarea') || showHelp.value || showLog.value) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'o') { event.preventDefault(); if (!busy.value) invoke('choose_files') }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') { event.preventDefault(); selected.value = files.value.map(file => file.key) }
  if (event.key === 'Delete' && !busy.value) invoke('remove_files', selected.value)
  if (event.key.toLowerCase() === 'f') resetView()
  if (event.key === '1') resetView(true)
}
onMounted(async () => {
  window.addEventListener('keydown', keydown)
  try {
    api.value = await waitForBridge()
    const result = await api.value.bootstrap()
    if (!result.ok) throw new Error(result.error)
    Object.assign(options, result.options)
    applyState(result); connected.value = true; poll()
  } catch (exception) { error.value = exception.message; status.value = '连接失败' }
})
onBeforeUnmount(() => {
  disposed = true; generation++
  clearTimeout(pollTimer); clearTimeout(previewTimer)
  window.removeEventListener('keydown', keydown)
})
</script>

<template>
  <div class="app-shell" @dragover.prevent @drop.prevent>
    <div v-if="error" class="error-banner" role="alert"><CircleAlert :size="17"/><span>{{ error }}</span><button aria-label="关闭错误提示" @click="error = ''"><X :size="16"/></button></div>

    <main class="workspace">
      <aside class="library">
        <div class="panel-title"><h2>图片 <span>{{ files.length }}</span></h2></div>
        <div class="import-actions"><button class="button" :disabled="busy || !connected" @click="invoke('choose_files')"><Plus :size="14"/>添加图片</button><button class="button" title="添加文件夹（包含子文件夹）" :disabled="busy || !connected" @click="invoke('choose_folder')"><FolderPlus :size="14"/>文件夹</button></div>
        <div class="library-content">
          <div v-if="!files.length" class="library-empty"><p>暂无图片</p><small>PNG、JPG、WebP 等格式</small></div>
          <div v-else class="file-list" role="listbox" aria-label="图片列表" aria-multiselectable="true">
            <button v-for="file in files" :key="file.key" class="file-row" :class="{ selected: selected.includes(file.key), active: file.key === activeKey }"
              role="option" :aria-selected="selected.includes(file.key)" :title="file.path" @click="selectFile(file, $event)">
              <FileThumbnail :file="file" :api="api"/><span class="file-copy"><strong>{{ file.name }}</strong><small :class="file.status">{{ statusLabels[file.status] }}<span v-if="file.size"> · {{ file.size.join(' × ') }}</span></small></span>
              <CheckCircle2 v-if="file.status === 'success'" :size="14" class="success"/><CircleAlert v-else-if="file.status === 'error'" :size="14" class="error"/><LoaderCircle v-else-if="file.status === 'working'" :size="14" class="spin"/>
            </button>
          </div>
        </div>
        <div class="library-footer"><span>已选 {{ selected.length }} 张</span><div><button class="text-button" :disabled="!files.length" @click="selected = files.map(file => file.key)">全选</button><button class="icon-button" title="移除选中（保留源文件）" aria-label="移除选中" :disabled="busy || !selected.length" @click="invoke('remove_files', selected)"><Trash2 :size="15"/></button></div></div>
      </aside>

      <section class="preview-workspace">
        <div class="preview-toolbar"><div class="segmented"><button :class="{ active: compare }" @click="compare = true">并排对比</button><button :class="{ active: !compare }" @click="compare = false">处理结果</button></div>
          <div class="preview-tools"><button class="icon-button" :class="{ toggled: grid }" title="像素网格（放大后显示）" aria-label="切换像素网格" @click="grid = !grid"><Grid2X2 :size="17"/></button><select v-model="background" class="background-select" aria-label="预览背景"><option value="checker">透明背景</option><option value="dark">深色背景</option><option value="light">浅色背景</option></select></div></div>

        <div v-if="!activeFile" class="main-empty"><h2>未选择图片</h2><p>从左侧添加图片，或直接拖入窗口</p></div>
        <template v-else>
          <div class="current-file"><strong :title="activeFile.path">{{ activeFile.name }}</strong><span v-if="pending" class="updating"><LoaderCircle :size="13" class="spin"/>更新预览</span><span v-else class="preview-label">{{ preview?.saved ? '已保存结果' : '实时预览' }}</span></div>
          <div class="preview-panes" :class="{ single: !compare }">
            <article v-if="compare" class="image-pane"><div class="image-heading"><span>原图</span><small v-if="preview?.original">{{ preview.original.width }} × {{ preview.original.height }}</small></div><PreviewCanvas :image="preview?.original" :camera="camera" :grid="grid" :background="background" @camera="camera = $event"/></article>
            <article class="image-pane"><div class="image-heading"><span>{{ preview?.saved ? '已导出' : '处理结果' }}</span><small v-if="preview?.output">{{ preview.output.width }} × {{ preview.output.height }}</small></div><PreviewCanvas :image="preview?.output" :camera="camera" :grid="grid" :background="background" @camera="camera = $event" @scale="outputScale = $event"/>
              <div v-if="previewError || preview?.error" class="preview-error" role="alert"><CircleAlert :size="23"/><strong>暂时无法生成预览</strong><p>{{ previewError || preview.error }}</p><button class="button" :disabled="pending" @click="schedulePreview">重新预览</button></div>
            </article>
          </div>
          <div class="zoom-toolbar"><span>滚轮缩放 · 拖动平移</span><div><button class="icon-button" title="缩小" aria-label="缩小" @click="zoom(.5)"><ZoomOut :size="17"/></button><span class="zoom-value">{{ Math.round(outputScale * 100) }}%</span><button class="icon-button" title="放大" aria-label="放大" @click="zoom(2)"><ZoomIn :size="17"/></button><span class="divider"/><button class="text-button" title="实际像素（1）" @click="resetView(true)">1:1</button><button class="icon-button" title="适应窗口（F）" aria-label="适应窗口" @click="resetView()"><Maximize :size="16"/></button></div></div>
          <div class="preview-info"><span>{{ preview?.info_text || (pending ? '正在识别图片…' : '选择参数查看预览') }}</span><p v-if="preview?.scaling_text" :class="{ attention: preview.attention }"><CircleAlert v-if="preview.attention" :size="14"/>{{ preview.scaling_text }}</p></div>
        </template>
      </section>

      <aside class="settings-panel"><div class="panel-title"><h2>处理设置</h2><button class="text-button" @click="showHelp = true">帮助</button></div>
        <fieldset class="settings-scroll" :disabled="busy || !connected">
          <section class="setting-section"><div class="section-heading">预设</div><div class="preset-actions"><button @click="preset('restore')">网格还原</button><button @click="preset('item')">物品图标</button><button @click="preset('block')">方块贴图</button></div></section>
          <section class="setting-section"><div class="section-heading">输入方式</div><div class="segmented full"><button :class="{ active: !options.direct }" @click="options.direct = false">自动识别网格</button><button :class="{ active: options.direct }" @click="options.direct = true">原图直接转换</button></div><p class="help-text">{{ options.direct ? '跳过网格识别，直接调整原图。' : '识别像素色块，将放大的图片还原成真实像素。' }}</p></section>
          <section class="setting-section"><div class="section-heading">画布与尺寸</div><label class="field-label" for="layout">输出方式</label><select id="layout" v-model="options.layout"><option value="original">保持原画布</option><option value="fit">主体等比例缩放</option><option value="canvas_fit">整图等比例缩放</option><option value="stretch">方块铺满</option><option value="keep">主体不缩放 · 改画布</option></select><p class="help-text">{{ layoutHelp }}</p>
            <label class="field-label">目标尺寸 <span v-if="options.layout === 'original'">选预设启用缩放</span></label><div class="dimension-inputs"><label><input v-model.number="options.width" type="number" min="1" :max="options.layout === 'keep' ? 8192 : 1024" aria-label="画布宽度" :disabled="options.layout === 'original'"/><span>宽</span></label><span>×</span><label><input v-model.number="options.height" type="number" min="1" :max="options.layout === 'keep' ? 8192 : 1024" aria-label="画布高度" :disabled="options.layout === 'original'"/><span>高</span></label><small>px</small></div><div class="size-presets"><button v-for="size in [16, 32, 64, 128]" :key="size" :class="{ chosen: options.layout !== 'original' && options.width === size && options.height === size }" @click="setSize(size)">{{ size }} × {{ size }}</button></div><div class="dimension-actions"><button :disabled="!preview?.info?.grid || pending" @click="useDimensions(false)">用输入尺寸</button><button :disabled="!preview?.info?.subject || pending" @click="useDimensions(true)">裁到主体大小</button></div>
          </section>
          <section v-if="resize" class="setting-section"><div class="section-heading">缩放算法</div><select v-model="options.resample" aria-label="缩放算法"><option value="pixel">目标像素 · 结构保护</option><option value="nearest">像素硬边 · 最近邻</option><option value="k-centroid">k-centroid · 局部主色</option></select><p class="help-text">{{ algorithmHelp }}</p><div v-if="options.resample === 'pixel'" class="paired-fields"><label>目标颜色<select v-model.number="options.palette_size"><option :value="0">保留颜色</option><option v-for="n in [8, 16, 32, 64]" :key="n" :value="n">{{ n }} 色</option></select></label><label>细节保护<select v-model.number="options.detail"><option :value="0">关闭</option><option :value="1">适中</option><option :value="2">较强</option></select></label></div></section>
          <details class="setting-section advanced"><summary><span>高级设置</span><ChevronDown :size="15"/></summary><div class="advanced-content"><label class="field-label">网格取样<select v-model="options.method" :disabled="options.direct"><option value="center">中心取样 · 快速</option><option value="median">中位数 · 去噪</option><option value="majority">多数色 · 较慢</option></select></label><label class="field-label">透明噪点阈值<input v-model.number="options.alpha_threshold" type="number" min="0" max="254"/></label><p class="help-text">0 关闭。裁边时忽略透明度不超过此值的外围杂点，不修改主体内的像素。</p></div></details>
        </fieldset>
      </aside>
    </main>

    <footer class="export-bar"><div class="export-destination"><FolderOpen :size="19"/><div><span>保存位置</span><button :title="outputDir || '每张原图旁的 perfect_pixel_output 文件夹'" :disabled="busy || !connected" @click="invoke('choose_output')">{{ outputDir || '原图旁的 perfect_pixel_output' }}<ChevronDown :size="13"/></button></div><button v-if="outputDir" class="text-button" :disabled="busy" @click="invoke('choose_output', true)">恢复默认</button></div>
      <div class="export-actions"><button class="icon-button" title="打开输出文件夹" aria-label="打开输出文件夹" :disabled="!successCount" @click="invoke('open_output', activeKey)"><FolderOpen :size="19"/></button><template v-if="busy"><button class="button cancel-button" :disabled="cancelling || closing" @click="invoke('cancel')"><X :size="16"/>{{ cancelling ? '正在取消…' : '取消处理' }}</button><button class="button primary" disabled><LoaderCircle :size="16" class="spin"/>{{ progress.total ? `${progress.done} / ${progress.total}` : '扫描中…' }}</button></template><template v-else><button class="button" :disabled="!selected.length || !connected" @click="exportFiles(false)">导出选中 <span class="button-count">{{ selected.length }}</span></button><button class="button primary" :disabled="!files.length || !connected" @click="exportFiles(true)"><Download :size="17"/>导出全部</button></template></div>
    </footer>
    <div class="status-bar"><span class="status-copy">{{ status }}</span><button @click="showLog = true">处理记录</button></div>
    <div v-if="busy && progress.total" class="batch-progress"><span :style="{ width: `${progress.done / progress.total * 100}%` }"/></div>

    <div v-if="showLog || showHelp" class="modal-backdrop" @click.self="showLog = showHelp = false"><section class="modal" role="dialog" aria-modal="true" :aria-label="showLog ? '处理记录' : '操作帮助'"><div class="modal-heading"><h2>{{ showLog ? '处理记录' : '操作帮助' }}</h2><button class="icon-button" aria-label="关闭弹窗" @click="showLog = showHelp = false"><X :size="20"/></button></div><template v-if="showLog"><p v-if="!details.length" class="help-text">导出后在这里查看结果路径和失败原因。</p><pre v-for="(detail, index) in details" :key="index">{{ detail }}</pre></template><template v-else><p>添加图片 → 选择用途或调整参数 → 检查预览 → 导出。</p><p class="help-text">自动识别适合具有一致色块网格的像素风图片。识别失败时，可切换“原图直接转换”。“物品图标”会裁透明边再等比例缩放，“方块贴图”会铺满画布。</p><div class="shortcut-list"><span>添加图片<kbd>Ctrl O</kbd></span><span>全选图片<kbd>Ctrl A</kbd></span><span>移除选中<kbd>Delete</kbd></span><span>适应窗口<kbd>F</kbd></span><span>实际像素<kbd>1</kbd></span></div><p class="help-text">Ctrl 点击多选，Shift 点击选择连续图片。滚轮缩放，拖动平移；网格在像素足够大时显示。并排预览同步操作，两张图分别以适应窗口为基准缩放。</p><p class="help-text">批量导出时，修改参数会暂时禁用。取消或退出会等待当前图片完成，已经保存的结果会保留。</p></template></section></div>
  </div>
</template>
