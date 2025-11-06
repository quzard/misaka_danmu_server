import axios from 'axios'
import Cookies from 'js-cookie'

const getURL = url => {
  const baseURL = import.meta.env.DEV ? 'http://0.0.0.0:7768' : '/'
  return { baseURL, url }
}

const instance = axios.create({
  headers: {
    'Content-Type': 'application/json',
  },
})

instance.interceptors.request.use(
  async config => {
    const token = Cookies.get('danmu_token')
    if (config.headers && !!token) {
      config.headers['Authorization'] = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

instance.interceptors.response.use(
  res => res,
  error => {
    console.log('resError', error.response?.data, error.response?.config.url)
    const errorData = error.response?.data || {}
    // 统一转换为message字段,兼容FastAPI的detail字段和自定义的message字段
    const errorObj = {
      ...errorData,
      message: errorData.detail || errorData.message || '未知错误',
      code: error.response?.status
    }
    return Promise.reject(errorObj)
  }
)

const api = {
  get(url, data, other = { headers: {} }) {
    return instance({
      method: 'get',
      baseURL: getURL(url).baseURL,
      url: getURL(url).url,
      headers: { ...other.headers },
      params: data,
      onDownloadProgress: other.onDownloadProgress,
    })
  },
  post(url, data, other = { headers: {} }) {
    return instance({
      method: 'post',
      baseURL: getURL(url).baseURL,
      url: getURL(url).url,
      headers: { ...other.headers },
      data,
      // 同时支持上传和下载进度
      onUploadProgress: other.onUploadProgress,
      onDownloadProgress: other.onDownloadProgress,
    })
  },
  // patch/put/delete 与 post 类似，根据实际需求添加进度配置
  patch(url, data, other = { headers: {} }) {
    return instance({
      method: 'patch',
      baseURL: getURL(url).baseURL,
      url: getURL(url).url,
      headers: { ...other.headers },
      data,
      onUploadProgress: other.onUploadProgress,
      onDownloadProgress: other.onDownloadProgress,
    })
  },
  put(url, data, other = { headers: {} }) {
    return instance({
      method: 'put',
      baseURL: getURL(url).baseURL,
      url: getURL(url).url,
      headers: { ...other.headers },
      data,
      onUploadProgress: other.onUploadProgress,
      onDownloadProgress: other.onDownloadProgress,
    })
  },
  delete(url, data, other = { headers: {} }) {
    return instance({
      method: 'delete',
      baseURL: getURL(url).baseURL,
      url: getURL(url).url,
      headers: { ...other.headers },
      data,
      onUploadProgress: other.onUploadProgress,
      onDownloadProgress: other.onDownloadProgress,
    })
  },
}

export default api
