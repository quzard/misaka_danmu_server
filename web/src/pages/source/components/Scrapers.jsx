import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  List,
  message,
  Modal,
  Row,
  Spin,
  Switch,
  Space,
  Tag,
  Tooltip,
  Upload,
  Typography,
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
    } catch (error) {
      console.error('加载版本信息失败:', error)
    } finally {
      setLoadingVersions(false)
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

      // 加载资源
      await loadScraperResources({ repoUrl: resourceRepoUrl })

      messageApi.success('资源加载成功,服务正在重启...')

      // 延迟刷新页面
      setTimeout(() => {
        getInfo()
        loadVersionInfo()
      }, 2500)
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '加载失败')
    } finally {
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
      for (const key of Object.keys(item.configurableFields)) {
        const camelKey = key.replace(/_([a-z])/g, g => g[1].toUpperCase())
        dynamicInitialValues[camelKey] = res.data?.[camelKey]
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

  const renderDynamicFormItems = () => {
    const currentScraper = list.find(it => it.providerName === setname)
    if (!currentScraper || !currentScraper.configurableFields) {
      return null
    }

    return Object.entries(currentScraper.configurableFields).map(
      ([key, fieldInfo]) => {
        // 兼容旧的字符串格式和新的元组格式
        const [label, type, tooltip] =
          typeof fieldInfo === 'string'
            ? [fieldInfo, 'string', '']
            : fieldInfo
        const camelKey = key.replace(/_([a-z])/g, g => g[1].toUpperCase())

        // 如果是 dandanplay，则跳过所有已在定制UI中处理的字段
        if (setname === 'dandanplay') {
          return null
        }

        // 跳过通用黑名单字段，因为它在下面有专门的渲染逻辑
        if (key.endsWith('_episode_blacklist_regex')) {
          return null
        }

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
          case 'string':
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
                <Input />
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
                <Input.Password />
              </Form.Item>
            )
          default:
            return null
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
                      {sseConnected && <Tag color="default">自动监听</Tag>}
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
                  )}
                  {versionInfo.hasUpdate && (
                    <div className="flex items-center gap-2">
                      <Typography.Text type="warning">有更新可用</Typography.Text>
                    </div>
                  )}
                </div>
              </Card>

              {/* 右侧：操作按钮组 —— 仅在 PC 端显示 */}
              {!isMobile && (
                <div className="flex gap-2">
                  <Button
                    onClick={async () => {
                      try {
                        const res = await backupScrapers()
                        messageApi.success(res.data?.message || '备份成功')
                      } catch (error) {
                        messageApi.error(error.response?.data?.detail || '备份失败')
                      }
                    }}
                  >
                    备份当前弹幕源
                  </Button>
                  <Button
                    onClick={() => {
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
                    }}
                  >
                    从备份还原
                  </Button>
                  <Button
                    type="primary"
                    onClick={async () => {
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
                    }}
                  >
                    重载弹幕源
                  </Button>
                </div>
              )}
            </div>
          )
          }

          {/* 移动端：单独显示按钮 */}
          {
            isMobile && (
              <div className="flex gap-2 flex-wrap mb-4">
                <Button
                  onClick={async () => {
                    try {
                      const res = await backupScrapers()
                      messageApi.success(res.data?.message || '备份成功')
                    } catch (error) {
                      messageApi.error(error.response?.data?.detail || '备份失败')
                    }
                  }}
                  className="flex-1 min-w-0"
                  style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}
                >
                  备份
                </Button>
                <Button
                  onClick={() => {
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
                  }}
                  className="flex-1 min-w-0"
                  style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}
                >
                  还原
                </Button>
                <Button
                  type="primary"
                  onClick={async () => {
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
                  }}
                  className="flex-1 min-w-0"
                  style={{ whiteSpace: 'normal', wordBreak: 'break-word' }}
                >
                  重载
                </Button>
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
            label="分集标题黑名单 (正则)"
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
