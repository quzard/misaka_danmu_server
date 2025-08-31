/**
 * 存到本地存储的操作都在这里定义，方便统一处理
 */

export function setStorage(key, data) {
  localStorage.setItem(key, JSON.stringify(data))
}

export function getStorage(key) {
  try {
    const value = localStorage.getItem(key)
    // 如果值不存在（null），则直接返回 null
    if (value === null) {
      return null
    }
    return JSON.parse(value)
  } catch (error) {
    console.error(`解析本地存储 '${key}' 失败，数据可能已损坏:`, error)
    // 如果解析JSON失败，说明存储的数据已损坏或格式不兼容。
    // 清除损坏的数据并返回 null，以防止应用持续崩溃。
    localStorage.removeItem(key)
    return null
  }
}

export function clearStorage(key) {
  localStorage.removeItem(key)
}
