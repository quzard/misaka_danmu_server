import {
  Button,
  Card,
  Checkbox,
  Dropdown,
  Form,
  Input,
  InputNumber,
  List,
  message,
  Modal,
  Row,
  Select,
  Spin,
  Switch,
  Space,
  Tag,
  Tooltip,
  Upload,
  Typography,
  Progress,
} from 'antd'
import { useEffect, useState, useRef } from 'react'
import Cookies from 'js-cookie'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import {
  biliLogout,
  getbiliLoginQrcode,
  getbiliUserinfo,
  getScrapers,
  getSingleScraper,
  pollBiliLogin,
  setScrapers,
  setSingleScraper,
  getResourceRepo,
  saveResourceRepo,
  getScraperVersions,
  loadScraperResources,
  backupScrapers,
  restoreScrapers,
  reloadScrapers,
  uploadScraperPackage,
  deleteScraperBackup,
  deleteCurrentScrapers,
  deleteAllScrapers,
  getScraperAutoUpdate,
  saveScraperAutoUpdate,
  getScraperFullReplace,
  saveScraperFullReplace,
  getScraperDefaultBlacklist,
  getCommonBlacklist,
} from '../../../apis'
import { MyIcon } from '@/components/MyIcon'
import {
  closestCorners,
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import {
  CloudOutlined,
  DesktopOutlined,
  KeyOutlined,
  LockOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'

import { QRCodeCanvas } from 'qrcode.react'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../../store'
import { useModal } from '../../../ModalContext'
import { useMessage } from '../../../MessageContext'

const SortableItem = ({
  item,
  biliUserinfo,
  index,
  handleChangeStatus,
  handleConfig,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: item.providerName, // 使用 providerName 作为唯一ID
    data: {
      item,
      index,
    },
  })

  const isMobile = useAtomValue(isMobileAtom)

  // 只保留必要的样式，移除会阻止滚动的touchAction
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    ...(isDragging && { cursor: 'grabbing' }),
  }

  return (
    <List.Item ref={setNodeRef} style={style}>
      <div className={`w-full flex ${isMobile ? 'gap-2' : 'items-center justify-between'}`}>
        {/* 左侧添加拖拽手柄 */}
        <div className="flex items-center gap-2">
          {/* 将attributes移到拖拽图标容器上，确保只有拖拽图标可触发拖拽 */}
          <div {...attributes} {...listeners} style={{ cursor: 'grab' }}>
            <MyIcon icon="drag" size={24} />
          </div>
          <div>{item.providerName}</div>
        </div>
        <div className={`flex ${isMobile ? 'ml-auto' : 'items-center justify-around'} gap-4`}>
          {item.providerName === 'bilibili' && (
            <div className={`flex ${isMobile ? 'items-center gap-2' : ''} ${isMobile ? 'text-center' : ''}`}>
              {biliUserinfo.isLogin ? (
                <div className={`flex ${isMobile ? 'flex-row items-center justify-center gap-2' : 'items-center justify-start gap-2'}`}>
                  <img
                    className="w-6 h-6 rounded-full"
                    src={biliUserinfo.face}
                  />
                  <span className={isMobile ? 'text-sm' : ''}>{biliUserinfo.uname}</span>
                </div>
              ) : (
                <span className="opacity-50 text-sm">未登录</span>
              )}
            </div>
          )}
          <div className={`flex ${isMobile ? 'justify-between items-center' : 'items-center justify-around'} gap-4`}>
            <div onClick={handleConfig} className="cursor-pointer">
              <MyIcon icon="setting" size={24} />
            </div>
            {item.version && (
              <Tag color="blue">{item.version}</Tag>
            )}
            {item.isEnabled ? (
              <Tag color="green">已启用</Tag>
            ) : (
              <Tag color="red">未启用</Tag>
            )}
            <Tooltip title="切换启用状态">
              <div onClick={handleChangeStatus}>
                <MyIcon icon="exchange" size={24} />
              </div>
            </Tooltip>
          </div>
        </div>
      </div>
    </List.Item>
  )
}

export const Scrapers = () => {
  const [loading, setLoading] = useState(true)
  const [list, setList] = useState([])
  const [activeItem, setActiveItem] = useState(null)
  const dragOverlayRef = useRef(null)
  const eventSourceRef = useRef(null)
  // 设置窗口
  const [open, setOpen] = useState(false)
  // 设置类型
  const [setname, setSetname] = useState('')
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [form] = Form.useForm()

  const isMobile = useAtomValue(isMobileAtom)

  // bili 相关
  const [biliQrcode, setBiliQrcode] = useState({})
  const [biliQrcodeStatus, setBiliQrcodeStatus] = useState('')
  const [biliQrcodeLoading, setBiliQrcodeLoading] = useState(false)
  const [biliUserinfo, setBiliUserinfo] = useState({})
  const [biliLoginOpen, setBiliLoginOpen] = useState(false)
  const [biliQrcodeChecked, setBiliQrcodeChecked] = useState(false)
  /** 扫码登录轮训 */
  const timer = useRef(0)
  // dandanplay auth mode
  const [dandanAuthMode, setDandanAuthMode] = useState('local') // 'local' or 'proxy'
  const [showAppSecret, setShowAppSecret] = useState(false)
  const [showDisclaimerModal, setShowDisclaimerModal] = useState(false)
  // 填充默认黑名单加载状态
  const [loadingDefaultBlacklist, setLoadingDefaultBlacklist] = useState(false)
  const [loadingCommonBlacklist, setLoadingCommonBlacklist] = useState(false)

  // 资源仓库相关
  const [resourceRepoUrl, setResourceRepoUrl] = useState('')
  const [loadingResources, setLoadingResources] = useState(false)
  const [versionInfo, setVersionInfo] = useState({
    localVersion: 'unknown',
    remoteVersion: null,
    officialVersion: null,
    hasUpdate: false
  })
  const [loadingVersions, setLoadingVersions] = useState(false)
  const [uploadingPackage, setUploadingPackage] = useState(false)
  const [sseConnected, setSseConnected] = useState(false)

  // 自动更新相关
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(false)
  const [autoUpdateLoading, setAutoUpdateLoading] = useState(false)

  // 全量替换相关
  const [fullReplaceEnabled, setFullReplaceEnabled] = useState(false)
  const [fullReplaceLoading, setFullReplaceLoading] = useState(false)

  // 下载进度相关
  const [downloadProgress, setDownloadProgress] = useState({
    visible: false,
    current: 0,
    total: 0,
    progress: 0,
    message: '',
    scraper: ''
  })
  const downloadAbortController = useRef(null)


  const modalApi = useModal()
  const messageApi = useMessage()

  const sensors = useSensors(
    useSensor(MouseSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        distance: 8,
        delay: 100,
      },
    })
  )

  useEffect(() => {
    getInfo()
    loadResourceRepoConfig()
    loadAutoUpdateConfig()
    loadFullReplaceConfig()

    // 建立 SSE 日志流, 根据相关事件自动刷新版本信息
    const token = Cookies.get('danmu_token')
    if (token) {
      const abortController = new AbortController()
      eventSourceRef.current = abortController

      fetchEventSource('/api/ui/logs/stream', {
        signal: abortController.signal,
        headers: {
          Authorization: `Bearer ${token}`,
        },
        onopen: async response => {
          if (response.ok) {
            setSseConnected(true)
          } else {
            setSseConnected(false)
            throw new Error(`连接失败: ${response.status}`)
          }
        },
        onmessage: event => {
          const data = event.data || ''
          if (!data) return

          // 监听与弹幕源加载/重载/还原相关的日志, 自动刷新版本信息
          if (
            data.includes('弹幕源') &&
            (data.includes('成功加载了') || data.includes('成功重载了') || data.includes('成功从备份重载了'))
          ) {
            loadVersionInfo()
          }
        },
        onerror: error => {
          console.error('版本信息 SSE 连接错误:', error)
          setSseConnected(false)
          throw error
        },
      }).catch(error => {
        if (error.name !== 'AbortError') {
          console.error('版本信息 SSE 流错误:', error)
        }
      })
    } else {
      console.warn('未找到 danmu_token, 跳过版本信息 SSE 监听')
    }

    // 清理函数:组件卸载时关闭SSE连接
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.abort()
        eventSourceRef.current = null
      }
      // 同时中断下载
      if (downloadAbortController.current) {
        downloadAbortController.current.abort()
        downloadAbortController.current = null
      }
    }
  }, [])

  const getInfo = async () => {
    try {
      setLoading(true)
      const [res1, res2] = await Promise.all([getScrapers(), getbiliUserinfo()])
      setList(res1.data ?? [])
      setBiliUserinfo(res2.data)
    } catch (error) {
    } finally {
      setLoading(false)
    }
  }

  const loadResourceRepoConfig = async () => {
    try {
      const res = await getResourceRepo()
      setResourceRepoUrl(res.data?.repoUrl || '')

      // 同时加载版本信息
      await loadVersionInfo()
    } catch (error) {
      console.error('加载资源仓库配置失败:', error)
    }
  }

  const loadVersionInfo = async () => {
    try {
      setLoadingVersions(true)
      const res = await getScraperVersions()
      setVersionInfo({
        localVersion: res.data?.localVersion || 'unknown',
        remoteVersion: res.data?.remoteVersion || null,
        officialVersion: res.data?.officialVersion || null,
        hasUpdate: res.data?.hasUpdate || false
      })
      return res.data
    } catch (error) {
      console.error('加载版本信息失败:', error)
      return null
    } finally {
      setLoadingVersions(false)
    }
  }

  // 加载自动更新配置（后端轮询，前端只控制开关）
  const loadAutoUpdateConfig = async () => {
    try {
      const res = await getScraperAutoUpdate()
      const enabled = res.data?.enabled || false
      setAutoUpdateEnabled(enabled)
    } catch (error) {
      console.error('加载自动更新配置失败:', error)
    }
  }

  // 切换自动更新状态（后端轮询，前端只控制开关）
  const handleAutoUpdateToggle = async (checked) => {
    try {
      setAutoUpdateLoading(true)
      await saveScraperAutoUpdate({ enabled: checked, interval: 15 })
      setAutoUpdateEnabled(checked)
      if (checked) {
        messageApi.success('已启用自动更新，后台每15分钟检查一次')
      } else {
        messageApi.success('已关闭自动更新')
      }
    } catch (error) {
      messageApi.error('保存自动更新配置失败')
    } finally {
      setAutoUpdateLoading(false)
    }
  }

  // 加载全量替换配置
  const loadFullReplaceConfig = async () => {
    try {
      const res = await getScraperFullReplace()
      const enabled = res.data?.enabled || false
      setFullReplaceEnabled(enabled)
    } catch (error) {
      console.error('加载全量替换配置失败:', error)
    }
  }

  // 切换全量替换状态
  const handleFullReplaceToggle = async (checked) => {
    try {
      setFullReplaceLoading(true)
      await saveScraperFullReplace({ enabled: checked })
      setFullReplaceEnabled(checked)
      if (checked) {
        messageApi.success('已启用全量替换模式，下次更新将从 Releases 下载压缩包')
      } else {
        messageApi.success('已关闭全量替换模式，将使用逐文件对比下载')
      }
    } catch (error) {
      messageApi.error('保存全量替换配置失败')
    } finally {
      setFullReplaceLoading(false)
    }
  }

  const handleLoadResources = async () => {
    if (!resourceRepoUrl.trim()) {
      messageApi.error('请输入资源仓库链接')
      return
    }

    try {
      setLoadingResources(true)

      // 保存配置
      await saveResourceRepo({ repoUrl: resourceRepoUrl })

      // 重置进度状态
      setDownloadProgress({
        visible: true,
        current: 0,
        total: 0,
        progress: 0,
        message: '正在连接资源仓库...',
        scraper: ''
      })

      // 使用 SSE 加载资源
      const token = Cookies.get('danmu_token')
      if (!token) {
        messageApi.error('未找到认证令牌')
        return
      }

      // 取消之前的下载
      if (downloadAbortController.current) {
        downloadAbortController.current.abort()
      }

      const abortController = new AbortController()
      downloadAbortController.current = abortController

      // 设置全局超时保护 (5分钟)
      const globalTimeout = setTimeout(() => {
        console.warn('下载超时,自动中断')
        abortController.abort()
        messageApi.error('下载超时,请检查网络连接')
        setDownloadProgress({
          visible: false,
          current: 0,
          total: 0,
          progress: 0,
          message: '',
          scraper: ''
        })
        setLoadingResources(false)
      }, 5 * 60 * 1000) // 5分钟

      // 标记是否已完成下载（用于忽略容器重启导致的连接断开错误）
      let downloadCompleted = false

      await fetchEventSource('/api/ui/scrapers/load-resources-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ repoUrl: resourceRepoUrl }),
        signal: abortController.signal,
        onopen: async response => {
          if (response.ok) {
            console.log('SSE 下载流已连接')
          } else {
            throw new Error(`连接失败: ${response.status}`)
          }
        },
        onmessage: event => {
          try {
            const data = JSON.parse(event.data)

            switch (data.type) {
              case 'info':
                setDownloadProgress(prev => ({
                  ...prev,
                  message: data.message
                }))
                break

              case 'compare_result':
                // 哈希比对完成，显示比对结果
                setDownloadProgress(prev => ({
                  ...prev,
                  message: `比对完成: ${data.to_download} 个需要下载, ${data.to_skip} 个已是最新${data.unsupported > 0 ? `, ${data.unsupported} 个不支持当前平台` : ''}`
                }))
                break

              case 'total':
                setDownloadProgress(prev => ({
                  ...prev,
                  total: data.total,
                  message: `开始下载 ${data.total} 个弹幕源...`
                }))
                break

              case 'progress':
                setDownloadProgress(prev => ({
                  ...prev,
                  current: data.current,
                  progress: data.progress,
                  scraper: data.scraper,
                  message: `正在下载 ${data.filename} (${data.current}/${data.total})`
                }))
                break

              case 'success':
                console.log(`成功下载: ${data.scraper}`)
                break

              case 'skip':
                // 不支持当前平台的源
                console.log(`跳过: ${data.scraper}`)
                break

              case 'skip_hash':
                // 哈希值相同，跳过下载（在新流程中这个事件不再发送，但保留兼容）
                console.log(`哈希相同跳过: ${data.scraper}`)
                break

              case 'failed':
                console.warn(`下载失败: ${data.scraper}`)
                break

              case 'complete':
                clearTimeout(globalTimeout) // 清除超时
                downloadCompleted = true // 标记下载已完成
                setDownloadProgress(prev => ({
                  ...prev,
                  progress: 100,
                  message: `下载完成! 成功: ${data.downloaded}, 跳过: ${data.skipped || 0}, 失败: ${data.failed}`
                }))

                // 根据实际下载数量显示不同的提示
                if (data.downloaded > 0) {
                  // 有文件被下载，可能会触发重启或热加载
                  if (data.full_replace) {
                    messageApi.success('全量替换完成，服务正在重启...')
                  } else {
                    messageApi.success('资源加载成功，正在应用更新...')
                  }
                } else {
                  // 没有文件被下载，所有源都是最新的
                  messageApi.success('所有弹幕源都是最新的')
                }

                // 延迟刷新页面
                const delay = data.downloaded > 0 ? 4000 : 1500
                setTimeout(() => {
                  setDownloadProgress({
                    visible: false,
                    current: 0,
                    total: 0,
                    progress: 0,
                    message: '',
                    scraper: ''
                  })
                  getInfo()
                  loadVersionInfo()
                  setLoadingResources(false)
                }, delay)
                break

              case 'container_restart_required':
                // 容器即将重启，标记为已完成，忽略后续连接断开错误
                downloadCompleted = true
                break

              case 'done':
                // SSE 流正常结束，标记为已完成
                downloadCompleted = true
                break

              case 'error':
                clearTimeout(globalTimeout) // 清除超时
                messageApi.error(data.message || '加载失败')
                setDownloadProgress({
                  visible: false,
                  current: 0,
                  total: 0,
                  progress: 0,
                  message: '',
                  scraper: ''
                })
                setLoadingResources(false)
                break
            }
          } catch (e) {
            console.error('解析 SSE 消息失败:', e)
          }
        },
        onerror: error => {
          console.error('SSE 下载流错误:', error)
          clearTimeout(globalTimeout) // 清除超时
          // 如果下载已完成，忽略连接断开错误（可能是容器重启导致）
          if (downloadCompleted) {
            console.log('下载已完成，忽略连接断开错误')
            // 抛出错误以停止 fetchEventSource 的自动重试
            throw new Error('下载已完成，停止重试')
          }
          if (error.name !== 'AbortError') {
            messageApi.error('下载连接出错')
            setDownloadProgress({
              visible: false,
              current: 0,
              total: 0,
              progress: 0,
              message: '',
              scraper: ''
            })
            setLoadingResources(false)
          }
          // 抛出错误以停止 fetchEventSource 的自动重试，防止连接断开后自动重新发起请求
          throw error
        },
      }).catch(error => {
        clearTimeout(globalTimeout) // 清除超时
        if (error.name !== 'AbortError') {
          console.error('SSE 流错误:', error)
        }
      })

    } catch (error) {
      messageApi.error(error.response?.data?.detail || '加载失败')
      setDownloadProgress({
        visible: false,
        current: 0,
        total: 0,
        progress: 0,
        message: '',
        scraper: ''
      })
      setLoadingResources(false)
    }
  }

  const handleUploadPackage = async (file) => {
    // 验证文件对象
    if (!file || !(file instanceof File)) {
      messageApi.error('无效的文件对象')
      return false
    }

    const formData = new FormData()
    formData.append('file', file)

    setUploadingPackage(true)

    try {
      // 传递配置对象,设置正确的 Content-Type
      const res = await uploadScraperPackage(formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      messageApi.success(res.data?.message || '上传成功')

      // 延迟刷新,等待后台重载完成
      setTimeout(async () => {
        try {
          await getInfo()
          await loadVersionInfo()
        } catch (error) {
          console.error('刷新信息失败:', error)
        }
      }, 2500) // 延迟2.5秒
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '上传失败')
    } finally {
      setUploadingPackage(false)
    }

    // 返回 false 阻止 Upload 组件的默认上传行为
    return false
  }

  const handleDragEnd = event => {
    const { active, over } = event

    // 拖拽无效或未改变位置
    if (!over || active.id === over.id) {
      setActiveItem(null)
      return
    }

    // 找到原位置和新位置
    const activeIndex = list.findIndex(item => item.providerName === active.id)
    const overIndex = list.findIndex(item => item.providerName === over.id)

    if (activeIndex !== -1 && overIndex !== -1) {
      // 1. 重新排列数组
      const newList = [...list]
      const [movedItem] = newList.splice(activeIndex, 1)
      newList.splice(overIndex, 0, movedItem)

      // 2. 重新计算所有项的display_order（从1开始连续编号）
      const updatedList = newList.map((item, index) => ({
        ...item,
        displayOrder: index + 1, // 排序值从1开始
      }))

      // 3. 更新状态
      setList(updatedList)
      setScrapers(updatedList)
      messageApi.success(
        `已更新排序，${movedItem.providerName} 移动到位置 ${overIndex + 1}`
      )
    }

    setActiveItem(null)
  }

  // 处理拖拽开始
  const handleDragStart = event => {
    const { active } = event
    // 找到当前拖拽的项
    const item = list.find(item => item.providerName === active.id)
    setActiveItem(item)
  }

  const handleChangeStatus = item => {
    const newList = list.map(it => {
      if (it.providerName === item.providerName) {
        return {
          ...it,
          isEnabled: !it.isEnabled,
        }
      } else {
        return it
      }
    })
    setList(newList)
    setScrapers(newList)
  }

  const handleConfig = async item => {
    const res = await getSingleScraper({
      name: item.providerName,
    })
    setOpen(true)
    setSetname(item.providerName)
    const setNameCapitalize = `${item.providerName.charAt(0).toUpperCase()}${item.providerName.slice(1)}`

    // 动态地为所有可配置字段设置表单初始值
    const dynamicInitialValues = {}
    if (item.configurableFields) {
      for (const [key, fieldInfo] of Object.entries(item.configurableFields)) {
        const camelKey = key.replace(/_([a-z])/g, g => g[1].toUpperCase())
        const config = parseFieldConfig(fieldInfo)
        let value = res.data?.[camelKey]

        // 如果是 boolean 类型，需要将字符串转换为真正的 boolean
        if (config.type === 'boolean') {
          if (typeof value === 'string') {
            value = value === 'true' || value === '1'
          } else if (typeof value === 'number') {
            value = value !== 0
          } else {
            value = Boolean(value)
          }
        }

        dynamicInitialValues[camelKey] = value
      }
    }

    form.setFieldsValue({
      [`scraper${setNameCapitalize}LogResponses`]:
        res.data?.[`scraper${setNameCapitalize}LogResponses`] ?? false,
      [`${item.providerName}EpisodeBlacklistRegex`]:
        res.data?.[`${item.providerName}EpisodeBlacklistRegex`] || '',
      useProxy: res.data?.useProxy ?? false,
      ...dynamicInitialValues,
    })

    // Dandanplay specific logic
    if (item.providerName === 'dandanplay') {
      // 如果配置了 App ID，则为本地模式，否则默认为代理模式
      if (res.data?.dandanplayAppId) {
        setDandanAuthMode('local')
      } else {
        setDandanAuthMode('proxy')
      }
    }
  }

  const handleSaveSingleScraper = async () => {
    try {
      setConfirmLoading(true)
      const values = await form.validateFields()
      const setNameCapitalize = `${setname.charAt(0).toUpperCase()}${setname.slice(1)}`

      // 根据当前模式，清空另一种模式的配置
      if (setname === 'dandanplay') {
        if (dandanAuthMode === 'local') {
          values.dandanplayProxyConfig = ''
        } else {
          values.dandanplayAppId = ''
          values.dandanplayAppSecret = ''
          values.dandanplayAppSecretAlt = ''
          values.dandanplayApiBaseUrl = ''
        }
        // dandanplay 不使用全局代理，移除该字段
        delete values.useProxy
      }

      await setSingleScraper({
        ...values,
        [`scraper${setNameCapitalize}LogResponses`]:
          values[`scraper${setNameCapitalize}LogResponses`],
        name: setname,
      })
      messageApi.success('保存成功')
    } catch (error) {
      console.error(error)
      messageApi.error('保存失败')
    } finally {
      setConfirmLoading(false)
      setOpen(false)
      form.resetFields()
    }
  }

  const startBiliLoginPoll = data => {
    timer.current = window.setInterval(() => {
      pollBiliLogin({
        qrcodeKey: data.qrcodeKey,
      })
        .then(res => {
          if (res.data.code === 86038) {
            clearInterval(timer.current)
            setBiliQrcodeStatus('expire')
          } else if (res.data.code === 86090) {
            setBiliQrcodeStatus('mobileConfirm')
          } else if (res.data.code === 0) {
            // 登录成功
            clearInterval(timer.current)
            setBiliLoginOpen(false)
            setOpen(false)
            getInfo()
          }
        })
        .catch(error => {
          setBiliQrcodeStatus('error')
          clearInterval(timer.current)
        })
    }, 1000)
  }

  useEffect(() => {
    return () => {
      clearInterval(timer.current)
    }
  }, [])

  const handleBiliQrcode = async () => {
    try {
      const res = await getbiliLoginQrcode()
      setBiliQrcode(res.data)
      setBiliQrcodeLoading(true)
      setBiliLoginOpen(true)
      startBiliLoginPoll(res.data)
      setBiliQrcodeStatus('')
    } catch (error) {
      messageApi.error('获取二维码失败')
    } finally {
      setBiliQrcodeLoading(false)
    }
  }

  const cancelBiliLogin = () => {
    setBiliLoginOpen(false)
    clearInterval(timer.current)
    setBiliQrcodeStatus('')
  }

  // 填充源默认分集黑名单
  const handleFillDefaultBlacklist = async () => {
    if (!setname) return
    try {
      setLoadingDefaultBlacklist(true)
      const res = await getScraperDefaultBlacklist(setname)
      if (res.data && res.data.defaultBlacklist) {
        form.setFieldValue(`${setname}EpisodeBlacklistRegex`, res.data.defaultBlacklist)
        messageApi.success('已填充源默认过滤规则')
      } else {
        messageApi.warning('该搜索源没有默认过滤规则')
      }
    } catch (error) {
      messageApi.error('获取源默认过滤规则失败')
    } finally {
      setLoadingDefaultBlacklist(false)
    }
  }

  // 填充通用分集黑名单
  const handleFillCommonBlacklist = async () => {
    if (!setname) return
    try {
      setLoadingCommonBlacklist(true)
      const res = await getCommonBlacklist()
      if (res.data && res.data.commonBlacklist) {
        form.setFieldValue(`${setname}EpisodeBlacklistRegex`, res.data.commonBlacklist)
        messageApi.success('已填充通用过滤规则')
      } else {
        messageApi.warning('未找到通用过滤规则')
      }
    } catch (error) {
      messageApi.error('获取通用过滤规则失败')
    } finally {
      setLoadingCommonBlacklist(false)
    }
  }

  const handleBiliLogout = () => {
    modalApi.confirm({
      title: '清除缓存',
      zIndex: 1002,
      content: <div>确定要注销当前的Bilibili登录吗？</div>,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await biliLogout()
          getInfo()
          setBiliQrcodeStatus('')
        } catch (err) { }
      },
    })
  }

  const renderDragOverlay = () => {
    if (!activeItem) return null

    return (
      <div ref={dragOverlayRef} style={{ width: '100%', maxWidth: '100%' }}>
        <List.Item
          style={{
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
            opacity: 0.9,
          }}
        >
          <div className="w-full flex items-center justify-between">
            <div className="flex items-center gap-2">
              <MyIcon icon="drag" size={24} />
              <div>{activeItem.providerName}</div>
            </div>
            <div className="flex items-center justify-around gap-4">
              <MyIcon icon="setting" size={24} />
              {activeItem.isEnabled ? (
                <Tag color="green">已启用</Tag>
              ) : (
                <Tag color="red">未启用</Tag>
              )}
            </div>
          </div>
        </List.Item>
      </div>
    )
  }

  // 解析字段配置（兼容多种格式）
  const parseFieldConfig = (fieldInfo) => {
    if (typeof fieldInfo === 'string') {
      // 旧格式：仅label
      return { label: fieldInfo, type: 'string', tooltip: '' }
    } else if (Array.isArray(fieldInfo)) {
      // 元组格式：[label, type, tooltip]
      return {
        label: fieldInfo[0],
        type: fieldInfo[1] || 'string',
        tooltip: fieldInfo[2] || '',
        placeholder: '',
        options: [],
        min: undefined,
        max: undefined,
        step: undefined,
        rows: 4,
      }
    } else {
      // 新格式：完整对象
      return {
        type: 'string',
        tooltip: '',
        placeholder: '',
        options: [],
        rows: 4,
        ...fieldInfo,
      }
    }
  }

  const renderDynamicFormItems = () => {
    const currentScraper = list.find(it => it.providerName === setname)
    if (!currentScraper || !currentScraper.configurableFields) {
      return null
    }

    return Object.entries(currentScraper.configurableFields).map(
      ([key, fieldInfo]) => {
        const config = parseFieldConfig(fieldInfo)
        const { label, type, tooltip, placeholder, options, min, max, step, rows } = config
        const camelKey = key.replace(/_([a-z])/g, g => g[1].toUpperCase())

        // 如果是 dandanplay，则跳过所有已在定制UI中处理的字段
        if (setname === 'dandanplay') {
          return null
        }

        // 跳过通用黑名单字段，因为它在下面有专门的渲染逻辑
        if (key.endsWith('_episode_blacklist_regex')) {
          return null
        }

        // 根据类型渲染对应的表单控件
        switch (type) {
          case 'boolean':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                valuePropName="checked"
                className="mb-4"
                tooltip={tooltip}
              >
                <Switch />
              </Form.Item>
            )

          case 'password':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <Input.Password placeholder={placeholder} />
              </Form.Item>
            )

          case 'number':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <InputNumber
                  min={min}
                  max={max}
                  step={step}
                  placeholder={placeholder}
                  style={{ width: '100%' }}
                />
              </Form.Item>
            )

          case 'select':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <Select placeholder={placeholder || '请选择'}>
                  {(options || []).map(opt => (
                    <Select.Option key={opt.value} value={opt.value}>
                      {opt.label}
                    </Select.Option>
                  ))}
                </Select>
              </Form.Item>
            )

          case 'textarea':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <Input.TextArea rows={rows} placeholder={placeholder} />
              </Form.Item>
            )

          case 'url':
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <Input
                  placeholder={placeholder || 'https://example.com'}
                />
              </Form.Item>
            )

          case 'string':
          default:
            // 为 gamer 的 cookie 提供更大的输入框
            if (key === 'gamerCookie') {
              return (
                <Form.Item
                  key={camelKey}
                  name={camelKey}
                  label={label}
                  className="mb-4"
                  tooltip={tooltip}
                >
                  <Input.TextArea rows={4} />
                </Form.Item>
              )
            }
            return (
              <Form.Item
                key={camelKey}
                name={camelKey}
                label={label}
                className="mb-4"
                tooltip={tooltip}
              >
                <Input placeholder={placeholder} />
              </Form.Item>
            )
        }
      }
    )
  }

  return (
    <div className="my-6">
      {/* 资源仓库配置卡片 */}
      <Card title="资源仓库" className="mb-4">
        <div className="space-y-4">
          <div>
            <div className="mb-2 text-sm text-gray-600">
              从资源仓库加载弹幕源文件,或上传离线包进行安装
            </div>
            <div className={`flex gap-2 ${isMobile ? 'flex-col' : 'flex-row'}`}>
              <Input
                placeholder="请输入GitHub仓库链接，例如：https://github.com/username/repo"
                value={resourceRepoUrl}
                onChange={(e) => setResourceRepoUrl(e.target.value)}
              />
              {isMobile ? (
                <>
                  <Button
                    type="primary"
                    loading={loadingResources}
                    onClick={handleLoadResources}
                    className="w-full"
                  >
                    加载资源
                  </Button>
                  <div className="flex gap-2 w-full">
                    <Button
                      onClick={async () => {
                        if (!resourceRepoUrl.trim()) {
                          messageApi.error('请输入资源仓库链接')
                          return
                        }
                        try {
                          await saveResourceRepo({ repoUrl: resourceRepoUrl })
                          messageApi.success('保存成功')
                          await loadVersionInfo()
                        } catch (error) {
                          messageApi.error(error.response?.data?.detail || '保存失败')
                        }
                      }}
                      className="flex-1"
                      style={{ flex: 1, height: '30px' }}
                    >
                      保存
                    </Button>
                    <Upload
                      beforeUpload={handleUploadPackage}
                      accept=".zip,.tar.gz,.tgz"
                      showUploadList={false}
                      disabled={uploadingPackage}
                      className="flex-1"
                      style={{ flex: 1, width: '100%' }}
                    >
                      <Button loading={uploadingPackage} disabled={uploadingPackage} className="w-full" style={{ width: '100%', minHeight: '10px', height: '30px' }}>
                        离线包上传
                      </Button>
                    </Upload>
                  </div>
                </>
              ) : (
                <>
                  <Button
                    onClick={async () => {
                      if (!resourceRepoUrl.trim()) {
                        messageApi.error('请输入资源仓库链接')
                        return
                      }
                      try {
                        await saveResourceRepo({ repoUrl: resourceRepoUrl })
                        messageApi.success('保存成功')
                        await loadVersionInfo()
                      } catch (error) {
                        messageApi.error(error.response?.data?.detail || '保存失败')
                      }
                    }}
                  >
                    保存
                  </Button>
                  <Button
                    type="primary"
                    loading={loadingResources}
                    onClick={handleLoadResources}
                  >
                    加载资源
                  </Button>
                  <Upload
                    beforeUpload={handleUploadPackage}
                    accept=".zip,.tar.gz,.tgz"
                    showUploadList={false}
                    disabled={uploadingPackage}
                  >
                    <Button loading={uploadingPackage} disabled={uploadingPackage}>
                      离线包上传
                    </Button>
                  </Upload>
                </>
              )}
            </div>
          </div>

          {/* 下载进度条 */}
          {downloadProgress.visible && (
            <div className="mt-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm text-gray-600">{downloadProgress.message}</span>
                <Button
                  size="small"
                  danger
                  onClick={() => {
                    if (downloadAbortController.current) {
                      downloadAbortController.current.abort()
                      downloadAbortController.current = null
                    }
                    setDownloadProgress({
                      visible: false,
                      current: 0,
                      total: 0,
                      progress: 0,
                      message: '',
                      scraper: ''
                    })
                    setLoadingResources(false)
                    messageApi.warning('已取消下载')
                  }}
                >
                  取消
                </Button>
              </div>
              <Progress
                percent={downloadProgress.progress}
                status={downloadProgress.progress === 100 ? 'success' : 'active'}
                strokeColor={{
                  '0%': '#108ee9',
                  '100%': '#87d068',
                }}
              />
            </div>
          )}

          {/* 版本信息 + 操作按钮（合并为一行） */}
          {(versionInfo.localVersion !== 'unknown' || versionInfo.remoteVersion || versionInfo.officialVersion) && (
            <div className={`flex ${isMobile ? 'flex-col gap-4' : 'items-center justify-between'} mb-4`}>
              <Card size="small" className={isMobile ? 'w-full' : ''}>
                <div className="flex flex-col gap-2">
                  {isMobile ? (
                    <div className="flex flex-col gap-2">
                      <div className="flex items-center justify-between">
                        {versionInfo.officialVersion && (
                          <>
                            <Typography.Text className="text-sm text-gray-600">主仓:</Typography.Text>
                            <Typography.Text code style={{ color: '#ce1ea2ff' }}>{versionInfo.officialVersion}</Typography.Text>
                          </>
                        )}
                        {versionInfo.remoteVersion && (
                          <>
                            <Typography.Text className="text-sm text-gray-600">远程:</Typography.Text>
                            <Typography.Text code style={{ color: '#52c41a' }}>{versionInfo.remoteVersion}</Typography.Text>
                          </>
                        )}
                      </div>
                      <div className="flex gap-3">
                        <div className="flex items-center gap-8">
                          <Typography.Text className="text-sm text-gray-600">本地:</Typography.Text>
                          <Typography.Text code style={{ color: '#1890ff' }}>{versionInfo.localVersion}</Typography.Text>
                        </div>
                        <div className="ml-auto">
                          <Button
                            type="text"
                            onClick={loadVersionInfo}
                            style={{
                              color: '#ff69b4',
                              width: 60,
                              position: 'relative',
                              padding: 0,
                            }}
                          >
                            {loadingVersions ? (
                              <>
                                <Spin
                                  size="small"
                                  style={{
                                    position: 'absolute',
                                    left: '50%',
                                    top: '50%',
                                    transform: 'translate(-50%, -50%)',
                                  }}
                                />
                                <span style={{ opacity: 0 }}>刷新</span>
                              </>
                            ) : '刷新'}
                          </Button>
                        </div>
                      </div>
                      {/* 移动端：自动更新和全量替换开关 */}
                      <div className="flex items-center justify-between mt-2">
                        <div className="flex items-center gap-2">
                          <Typography.Text className="text-sm text-gray-600">自动更新:</Typography.Text>
                          <Switch
                            size="small"
                            checked={autoUpdateEnabled}
                            loading={autoUpdateLoading}
                            checkedChildren="启用"
                            unCheckedChildren="关闭"
                            onChange={handleAutoUpdateToggle}
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <Tooltip title="启用后从 GitHub Releases 下载压缩包全量替换，适用于 .so 文件更新不生效的情况">
                            <Typography.Text className="text-sm text-gray-600" style={{ cursor: 'help' }}>全量替换:</Typography.Text>
                          </Tooltip>
                          <Switch
                            size="small"
                            checked={fullReplaceEnabled}
                            loading={fullReplaceLoading}
                            checkedChildren="启用"
                            unCheckedChildren="关闭"
                            onChange={handleFullReplaceToggle}
                          />
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-4">
                      {versionInfo.officialVersion && (
                        <div className="flex items-center gap-2">
                          <Typography.Text className="text-sm text-gray-600">主仓版本:</Typography.Text>
                          <Typography.Text code style={{ color: '#ce1ea2ff' }}>{versionInfo.officialVersion}</Typography.Text>
                        </div>
                      )}
                      {versionInfo.remoteVersion && (
                        <div className="flex items-center gap-2">
                          <Typography.Text className="text-sm text-gray-600">远程版本:</Typography.Text>
                          <Typography.Text code style={{ color: '#52c41a' }}>{versionInfo.remoteVersion}</Typography.Text>
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <Typography.Text className="text-sm text-gray-600">本地版本:</Typography.Text>
                        <Typography.Text code style={{ color: '#1890ff' }}>{versionInfo.localVersion}</Typography.Text>
                      </div>
                      <div className="flex items-center gap-2">
                        <Typography.Text className="text-sm text-gray-600">自动更新:</Typography.Text>
                        <Switch
                          size="small"
                          checked={autoUpdateEnabled}
                          loading={autoUpdateLoading}
                          checkedChildren="启用"
                          unCheckedChildren="关闭"
                          onChange={handleAutoUpdateToggle}
                        />
                      </div>
                      <div className="flex items-center gap-2">
                        <Tooltip title="启用后从 GitHub Releases 下载压缩包全量替换，适用于 .so 文件更新不生效的情况">
                          <Typography.Text className="text-sm text-gray-600" style={{ cursor: 'help' }}>全量替换:</Typography.Text>
                        </Tooltip>
                        <Switch
                          size="small"
                          checked={fullReplaceEnabled}
                          loading={fullReplaceLoading}
                          checkedChildren="启用"
                          unCheckedChildren="关闭"
                          onChange={handleFullReplaceToggle}
                        />
                      </div>
                      <Button
                        type="text"
                        onClick={loadVersionInfo}
                        style={{
                          color: '#ff69b4',
                          width: 60,
                          position: 'relative',
                          padding: 0,
                        }}
                      >
                        {loadingVersions ? (
                          <>
                            <Spin
                              size="small"
                              style={{
                                position: 'absolute',
                                left: '50%',
                                top: '50%',
                                transform: 'translate(-50%, -50%)',
                              }}
                            />
                            <span style={{ opacity: 0 }}>刷新</span>
                          </>
                        ) : '刷新'}
                      </Button>
                      {/* PC端：更新提示显示在刷新按钮右边 */}
                      {versionInfo.hasUpdate && (
                        <Typography.Text type="warning" style={{ marginLeft: 8 }}>🆙 有更新可用</Typography.Text>
                      )}
                    </div>
                  )}
                  {/* 移动端：更新提示显示在下一行 */}
                  {isMobile && versionInfo.hasUpdate && (
                    <div className="flex items-center gap-2">
                      <Typography.Text type="warning">🆙 有更新可用</Typography.Text>
                    </div>
                  )}
                </div>
              </Card>

              {/* 右侧：源操作按钮 —— 仅在 PC 端显示 */}
              {!isMobile && (
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: 'reload',
                        label: '重载当前源',
                        onClick: async () => {
                          try {
                            setLoading(true)
                            const res = await reloadScrapers()
                            messageApi.success(res.data?.message || '重载成功，正在后台重载...')
                            setTimeout(() => {
                              getInfo()
                              loadVersionInfo()
                            }, 2500)
                          } catch (error) {
                            messageApi.error(error.response?.data?.detail || '重载失败')
                          } finally {
                            setLoading(false)
                          }
                        }
                      },
                      {
                        key: 'backup',
                        label: '备份当前源',
                        onClick: async () => {
                          try {
                            const res = await backupScrapers()
                            messageApi.success(res.data?.message || '备份成功')
                          } catch (error) {
                            messageApi.error(error.response?.data?.detail || '备份失败')
                          }
                        }
                      },
                      {
                        key: 'restore',
                        label: '从备份中还原',
                        onClick: () => {
                          modalApi.confirm({
                            title: '还原弹幕源',
                            content: '确定要从备份还原弹幕源吗？这将覆盖当前的弹幕源文件。',
                            okText: '确认',
                            cancelText: '取消',
                            onOk: async () => {
                              try {
                                const res = await restoreScrapers()
                                messageApi.success(res.data?.message || '还原成功，正在后台重载...')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '还原失败')
                              }
                            },
                          })
                        }
                      },
                      { type: 'divider' },
                      {
                        key: 'deleteBackup',
                        label: '删除备份源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除备份',
                            content: '确定要删除所有备份文件吗？此操作不可恢复。',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteScraperBackup()
                                messageApi.success(res.data?.message || '删除备份成功')
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除备份失败')
                              }
                            },
                          })
                        }
                      },
                      {
                        key: 'deleteCurrent',
                        label: '删除当前源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除当前弹幕源',
                            content: '确定要删除所有当前弹幕源文件吗？此操作不可恢复。',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteCurrentScrapers()
                                messageApi.success(res.data?.message || '删除成功')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除失败')
                              }
                            },
                          })
                        }
                      },
                      {
                        key: 'deleteAll',
                        label: '删除当前&备份源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除所有弹幕源',
                            content: '确定要删除所有当前弹幕源和备份文件吗？此操作不可恢复！',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteAllScrapers()
                                messageApi.success(res.data?.message || '删除成功')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除失败')
                              }
                            },
                          })
                        }
                      },
                    ]
                  }}
                >
                  <Button type="primary">源操作</Button>
                </Dropdown>
              )}
            </div>
          )
          }

          {/* 移动端：源操作按钮 */}
          {
            isMobile && (
              <div className="flex gap-2 flex-wrap mb-4">
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: 'reload',
                        label: '重载当前源',
                        onClick: async () => {
                          try {
                            setLoading(true)
                            const res = await reloadScrapers()
                            messageApi.success(res.data?.message || '重载成功，正在后台重载...')
                            setTimeout(() => {
                              getInfo()
                              loadVersionInfo()
                            }, 2500)
                          } catch (error) {
                            messageApi.error(error.response?.data?.detail || '重载失败')
                          } finally {
                            setLoading(false)
                          }
                        }
                      },
                      {
                        key: 'backup',
                        label: '备份当前源',
                        onClick: async () => {
                          try {
                            const res = await backupScrapers()
                            messageApi.success(res.data?.message || '备份成功')
                          } catch (error) {
                            messageApi.error(error.response?.data?.detail || '备份失败')
                          }
                        }
                      },
                      {
                        key: 'restore',
                        label: '从备份中还原',
                        onClick: () => {
                          modalApi.confirm({
                            title: '还原弹幕源',
                            content: '确定要从备份还原弹幕源吗？这将覆盖当前的弹幕源文件。',
                            okText: '确认',
                            cancelText: '取消',
                            onOk: async () => {
                              try {
                                const res = await restoreScrapers()
                                messageApi.success(res.data?.message || '还原成功，正在后台重载...')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '还原失败')
                              }
                            },
                          })
                        }
                      },
                      { type: 'divider' },
                      {
                        key: 'deleteBackup',
                        label: '删除备份源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除备份',
                            content: '确定要删除所有备份文件吗？此操作不可恢复。',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteScraperBackup()
                                messageApi.success(res.data?.message || '删除备份成功')
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除备份失败')
                              }
                            },
                          })
                        }
                      },
                      {
                        key: 'deleteCurrent',
                        label: '删除当前源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除当前弹幕源',
                            content: '确定要删除所有当前弹幕源文件吗？此操作不可恢复。',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteCurrentScrapers()
                                messageApi.success(res.data?.message || '删除成功')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除失败')
                              }
                            },
                          })
                        }
                      },
                      {
                        key: 'deleteAll',
                        label: '删除当前&备份源',
                        danger: true,
                        onClick: () => {
                          modalApi.confirm({
                            title: '删除所有弹幕源',
                            content: '确定要删除所有当前弹幕源和备份文件吗？此操作不可恢复！',
                            okText: '确认删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: async () => {
                              try {
                                const res = await deleteAllScrapers()
                                messageApi.success(res.data?.message || '删除成功')
                                setTimeout(() => {
                                  getInfo()
                                  loadVersionInfo()
                                }, 2500)
                              } catch (error) {
                                messageApi.error(error.response?.data?.detail || '删除失败')
                              }
                            },
                          })
                        }
                      },
                    ]
                  }}
                >
                  <Button type="primary" className="flex-1 min-w-0">源操作</Button>
                </Dropdown>
              </div>
            )
          }
        </div >
      </Card >

      {/* 弹幕搜索源卡片 */}
      < Card loading={loading} title="弹幕搜索源" >
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            strategy={verticalListSortingStrategy}
            items={list.map(item => item.providerName)}
          >
            <List
              itemLayout="vertical"
              size="large"
              dataSource={list}
              renderItem={(item, index) => (
                <SortableItem
                  key={item.providerName}
                  item={item}
                  index={index}
                  biliUserinfo={biliUserinfo}
                  handleChangeStatus={() => handleChangeStatus(item)}
                  handleConfig={() => handleConfig(item)}
                />
              )}
            />
          </SortableContext>
          {/* 拖拽覆盖层 */}
          <DragOverlay>{renderDragOverlay()}</DragOverlay>
        </DndContext>
      </Card >
      <Modal
        title={`配置: ${setname}`}
        open={open}
        onOk={handleSaveSingleScraper}
        confirmLoading={confirmLoading}
        cancelText="取消"
        okText="确认"
        onCancel={() => setOpen(false)}
        destroyOnClose // 确保每次打开时都重新渲染
        forceRender // 确保表单项在Modal打开时就存在
        width={isMobile ? '95%' : '600px'}
        centered
      >
        <Form form={form} layout="vertical">
          {setname !== 'dandanplay' && (
            <Form.Item
              name="useProxy"
              label="使用代理"
              valuePropName="checked"
              className="mb-4"
            >
              <Switch />
            </Form.Item>
          )}

          {/* dandanplay specific */}
          {setname === 'dandanplay' && (
            <>
              <Form.Item label="认证方式" className="mb-6">
                <div className={`flex ${isMobile ? 'flex-col gap-2' : 'items-center gap-4'}`}>
                  <Switch
                    checkedChildren={
                      <Space>
                        <CloudOutlined />
                        跨域代理
                      </Space>
                    }
                    unCheckedChildren={
                      <Space>
                        <DesktopOutlined />
                        本地功能
                      </Space>
                    }
                    checked={dandanAuthMode === 'proxy'}
                    onChange={checked =>
                      setDandanAuthMode(checked ? 'proxy' : 'local')
                    }
                  />
                  <div className="text-sm text-gray-600">
                    {dandanAuthMode === 'local' ? '使用本地App ID和Secret进行认证' : '通过跨域代理使用API'}
                  </div>
                </div>
              </Form.Item>

              {dandanAuthMode === 'local' && (
                <>
                  <Form.Item
                    name="dandanplayAppId"
                    label={
                      <span>
                        App ID{' '}
                        <a
                          href="https://www.dandanplay.com/dev"
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <QuestionCircleOutlined className="cursor-pointer text-gray-400" />
                        </a>
                      </span>
                    }
                    rules={[{ required: true, message: '请输入App ID' }]}
                    className="mb-4"
                  >
                    <Input
                      prefix={<KeyOutlined className="text-gray-400" />}
                      placeholder="请输入App ID"
                    />
                  </Form.Item>

                  <Form.Item
                    name="dandanplayAppSecret"
                    label="App Secret"
                    rules={[{ required: true, message: '请输入App Secret' }]}
                    className="mb-4"
                  >
                    <Input.Password
                      prefix={<LockOutlined className="text-gray-400" />}
                      placeholder="请输入App Secret"
                    />
                  </Form.Item>

                  <Form.Item
                    name="dandanplayAppSecretAlt"
                    label="备用App Secret"
                    tooltip="可选的备用密钥，用于轮换使用以避免频率限制"
                    className="mb-4"
                  >
                    <Input.Password
                      prefix={<LockOutlined className="text-gray-400" />}
                      placeholder="请输入备用App Secret（可选）"
                    />
                  </Form.Item>

                  <Form.Item
                    name="dandanplayApiBaseUrl"
                    label="API基础URL"
                    tooltip="弹弹play API的基础URL，通常无需修改"
                    className="mb-4"
                  >
                    <Input placeholder="默认为 https://api.dandanplay.net" />
                  </Form.Item>
                </>
              )}

              {dandanAuthMode === 'proxy' && (
                <Form.Item
                  name="dandanplayProxyConfig"
                  label="跨域代理配置"
                  rules={[
                    { required: true, message: '请输入代理配置' },
                  ]}
                  className="mb-6"
                >
                  <Input.TextArea rows={isMobile ? 6 : 8} />
                </Form.Item>
              )}
            </>
          )}

          {/* 动态渲染表单项 */}
          {renderDynamicFormItems()}

          {/* 通用部分 分集标题黑名单 记录原始响应 */}
          <Form.Item
            name={`${setname}EpisodeBlacklistRegex`}
            label={
              <div className="flex items-center justify-between w-full">
                <span>分集标题黑名单 (正则)</span>
                <Space size="small">
                  <Button
                    type="link"
                    size="small"
                    loading={loadingCommonBlacklist}
                    onClick={handleFillCommonBlacklist}
                  >
                    填充通用规则
                  </Button>
                  <Button
                    type="link"
                    size="small"
                    loading={loadingDefaultBlacklist}
                    onClick={handleFillDefaultBlacklist}
                  >
                    填充源默认规则
                  </Button>
                </Space>
              </div>
            }
            className="mb-4"
          >
            <Input.TextArea rows={6} />
          </Form.Item>
          <div className={`flex ${isMobile ? 'flex-col gap-2' : 'items-center justify-start flex-wrap'} gap-2 mb-4`}>
            <Form.Item
              name={`scraper${setname.charAt(0).toUpperCase()}${setname.slice(1)}LogResponses`}
              label="记录原始响应"
              valuePropName="checked"
              className={isMobile ? "min-w-full !mb-0" : "min-w-[100px] shrink-0 !mb-0"}
            >
              <Switch />
            </Form.Item>
            <div className={`w-full ${isMobile ? 'text-sm' : ''}`}>
              启用后，此源的所有API请求的原始响应将被记录到
              config/logs/scraper_responses.log 文件中，用于调试。
            </div>
          </div>
          {/* bilibili登录信息 */}
          {setname === 'bilibili' && (
            <div className="text-center">
              {biliUserinfo.isLogin ? (
                <div className="text-center">
                  <div className={`flex ${isMobile ? 'flex-col items-center gap-2' : 'items-center justify-center gap-2'} mb-4`}>
                    <img
                      className={`${isMobile ? 'w-8 h-8' : 'w-10 h-10'} rounded-full`}
                      src={biliUserinfo.face}
                    />
                    <span>{biliUserinfo.uname}</span>
                    {biliUserinfo.vipStatus === 1 && (
                      <Tag
                        color={biliUserinfo.vipType === 2 ? '#f50' : '#2db7f5'}
                      >
                        {biliUserinfo.vipType === 2 ? '年度大会员' : '大会员'}
                      </Tag>
                    )}
                  </div>
                  <Button type="primary" danger onClick={handleBiliLogout}>
                    注销登录
                  </Button>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-4 w-full max-w-md mx-auto p-4">
                  <div className="flex flex-col items-center gap-4">
                    <Button
                      disabled={!biliQrcodeChecked}
                      type="primary"
                      loading={biliQrcodeLoading}
                      onClick={handleBiliQrcode}
                    >
                      扫码登录
                    </Button>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        checked={biliQrcodeChecked}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setShowDisclaimerModal(true);
                          } else {
                            setBiliQrcodeChecked(false);
                          }
                        }}
                      />
                      <span
                        className="cursor-pointer text-sm"
                        onClick={() => setShowDisclaimerModal(true)}
                      >
                        我已阅读并同意免责声明
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </Form>
      </Modal>
      <Modal
        title="bilibili扫码登录"
        open={biliLoginOpen}
        footer={null}
        onCancel={() => setBiliLoginOpen(false)}
        width={isMobile ? '90%' : '400px'}
        centered
      >
        <div className="text-center">
          <div className={`relative ${isMobile ? 'w-[150px] h-[150px]' : 'w-[200px] h-[200px]'} mx-auto mb-3`}>
            <QRCodeCanvas
              value={biliQrcode.url}
              size={isMobile ? 150 : 200}
              fgColor="#000"
              level="M"
            />

            {biliQrcodeStatus === 'expire' && (
              <div
                className="absolute left-0 top-0 w-full h-full p-3 flex items-center justify-center bg-black/80 cursor-pointer text-neutral-100"
                onClick={handleBiliQrcode}
              >
                二维码已失效
                <br />
                点击重新获取
              </div>
            )}
            {biliQrcodeStatus === 'mobileConfirm' && (
              <div className="absolute left-0 top-0 w-full h-full p-3 flex items-center justify-center bg-black/80 text-neutral-100">
                已扫描，请在
                <br />
                手机上确认登录
              </div>
            )}
            {biliQrcodeStatus === 'error' && (
              <div
                className="absolute left-0 top-0 w-full h-full p-3 flex items-center justify-center bg-black/80 cursor-pointer text-neutral-100"
                onClick={handleBiliQrcode}
              >
                轮询失败
                <br />
                点击重新获取
              </div>
            )}
          </div>
          <div className={`mb-3 ${isMobile ? 'text-sm px-2' : ''}`}>请使用Bilibili手机客户端扫描二维码</div>
          <Button type="primary" danger onClick={cancelBiliLogin}>
            取消登录
          </Button>
        </div>
      </Modal>
      <Modal
        title="免责声明"
        open={showDisclaimerModal}
        onOk={() => {
          setBiliQrcodeChecked(true)
          setShowDisclaimerModal(false)
        }}
        onCancel={() => setShowDisclaimerModal(false)}
        okText="同意"
        cancelText="取消"
      >
        <div className="text-sm text-left">
          登录接口由{' '}
          <a
            href="https://github.com/SocialSisterYi/bilibili-API-collect"
            target="_blank"
            rel="noopener noreferrer"
          >
            bilibili-API-collect
          </a>{' '}
          提供，为Blibili官方非公开接口。
          您的登录凭据将加密存储在您自己的数据库中。登录行为属用户个人行为，通过该登录获取数据同等于使用您的账号获取，由登录用户自行承担相关责任，与本工具无关。使用本接口登录等同于认同该声明。
        </div>
      </Modal>
    </div >
  )
}
