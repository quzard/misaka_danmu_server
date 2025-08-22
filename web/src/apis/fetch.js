import axios from 'axios'
import Cookies from 'js-cookie'
import { message } from 'antd'

const getURL = url => {
  return {
    baseURL:
      process.env.NODE_ENV === 'development' ? 'http://0.0.0.0:7768' : '/',
    url: url,
  }
}

const instance = axios.create({
  headers: {
    'Content-Type': 'application/json',
  },
})

instance.interceptors.request.use(
  async config => {
    const token = Cookies.get('token')
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
    // 新增：全局处理 401 未授权错误
    // 当任何API请求返回401时，说明token已失效
    if (error.response && error.response.status === 401) {
      // 清除过期的 token
      Cookies.remove('token')
      // 提示用户
      message.error('登录已过期，请重新登录。')
      // 延迟一小段时间后重定向到登录页，以确保用户能看到提示
      setTimeout(() => {
        window.location.href = '/login'
      }, 1500)
    }
    return Promise.reject(error.response?.data || {})
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
