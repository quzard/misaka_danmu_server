import { useState, useEffect } from 'react'
import { getConfig } from '../apis'

// 默认分页大小
const DEFAULT_PAGE_SIZE = 50

// 缓存配置值，避免重复请求
let cachedPageSize = null
let cachePromise = null

/**
 * 获取默认分页大小的 Hook
 * 从后端配置中读取 defaultPageSize，如果未设置则使用默认值
 * 
 * @param {number} fallback - 如果配置未加载完成时使用的临时默认值
 * @returns {number} 默认分页大小
 */
export function useDefaultPageSize(fallback = DEFAULT_PAGE_SIZE) {
  const [pageSize, setPageSize] = useState(cachedPageSize || fallback)

  useEffect(() => {
    // 如果已有缓存，直接使用
    if (cachedPageSize !== null) {
      setPageSize(cachedPageSize)
      return
    }

    // 如果正在加载，等待加载完成
    if (cachePromise) {
      cachePromise.then((size) => {
        setPageSize(size)
      })
      return
    }

    // 发起请求
    cachePromise = getConfig('defaultPageSize')
      .then((res) => {
        const value = res.data?.value
        const size = value ? parseInt(value, 10) : DEFAULT_PAGE_SIZE
        cachedPageSize = isNaN(size) ? DEFAULT_PAGE_SIZE : size
        setPageSize(cachedPageSize)
        return cachedPageSize
      })
      .catch((err) => {
        console.error('加载默认分页配置失败:', err)
        cachedPageSize = DEFAULT_PAGE_SIZE
        setPageSize(DEFAULT_PAGE_SIZE)
        return DEFAULT_PAGE_SIZE
      })
      .finally(() => {
        // 保留 promise 以便其他组件可以等待
      })
  }, [])

  return pageSize
}

/**
 * 清除缓存，用于配置更新后刷新
 */
export function clearPageSizeCache() {
  cachedPageSize = null
  cachePromise = null
}

/**
 * 获取默认分页大小（非 Hook 版本，用于初始化）
 * @returns {Promise<number>}
 */
export async function getDefaultPageSize() {
  if (cachedPageSize !== null) {
    return cachedPageSize
  }

  try {
    const res = await getConfig('defaultPageSize')
    const value = res.data?.value
    const size = value ? parseInt(value, 10) : DEFAULT_PAGE_SIZE
    cachedPageSize = isNaN(size) ? DEFAULT_PAGE_SIZE : size
    return cachedPageSize
  } catch (err) {
    console.error('加载默认分页配置失败:', err)
    return DEFAULT_PAGE_SIZE
  }
}

