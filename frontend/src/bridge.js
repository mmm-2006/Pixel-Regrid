export async function waitForBridge() {
  if (window.__TAURI_INTERNALS__) {
    const { createTauriBridge } = await import('./tauriBridge.js')
    return createTauriBridge()
  }
  if (window.pywebview?.api) return window.pywebview.api
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('桌面连接未就绪，请通过对应的启动脚本打开 Pixel Regrid。')), 12000)
    window.addEventListener('pywebviewready', () => {
      clearTimeout(timer)
      resolve(window.pywebview.api)
    }, { once: true })
  })
}

export function optionPayload(options) {
  return JSON.parse(JSON.stringify(options))
}

export function nextSelection(files, selected) {
  const available = new Set(files.map(file => file.key))
  const retained = selected.filter(key => available.has(key))
  return retained.length ? retained : files.length ? [files[0].key] : []
}

export const statusLabels = {
  pending: '待处理', waiting: '等待中', working: '处理中',
  success: '已导出', error: '失败', cancelled: '已取消',
}
