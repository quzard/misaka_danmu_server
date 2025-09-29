import {
  Button,
  Card,
  Col,
  Checkbox,
  Form,
  Input,
  List,
  message,
  Modal,
  Row,
  Switch,
  Space,
  Tag,
  Tooltip,
} from 'antd'
import { useEffect, useState, useRef } from 'react'
import {
  biliLogout,
  getbiliLoginQrcode,
  getbiliUserinfo,
  getScrapers,
  getSingleScraper,
  pollBiliLogin,
  setScrapers,
  setSingleScraper,
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
      {/* 保留你原有的列表项渲染逻辑 */}
      <div className="w-full flex items-center justify-between">
        {/* 左侧添加拖拽手柄 */}
        <div className="flex items-center gap-2">
          {/* 将attributes移到拖拽图标容器上，确保只有拖拽图标可触发拖拽 */}
          <div {...attributes} {...listeners} style={{ cursor: 'grab' }}>
            <MyIcon icon="drag" size={24} />
          </div>
          <div>{item.providerName}</div>
        </div>
        <div className="flex items-center justify-around gap-4">
          {item.providerName === 'bilibili' && !isMobile && (
            <div>
              {biliUserinfo.isLogin ? (
                <div className="flex items-center justify-start gap-2">
                  <img
                    className="w-6 h-6 rounded-full"
                    src={biliUserinfo.face}
                  />
                  <span>{biliUserinfo.uname}</span>
                </div>
              ) : (
                <span className="opacity-50">未登录</span>
              )}
            </div>
          )}
          <div onClick={handleConfig} className="cursor-pointer">
            <MyIcon icon="setting" size={24} />
          </div>
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
    </List.Item>
  )
}

export const Scrapers = () => {
  const [loading, setLoading] = useState(true)
  const [list, setList] = useState([])
  const [activeItem, setActiveItem] = useState(null)
  const dragOverlayRef = useRef(null)
  // 设置窗口
  const [open, setOpen] = useState(false)
  // 设置类型
  const [setname, setSetname] = useState('')
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [form] = Form.useForm()

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
        } catch (err) {}
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
      <Card loading={loading} title="弹幕搜索源">
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
      </Card>
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
      >
        <Form form={form} layout="vertical">
          <div className="mb-4">请为 {setname} 源填写以下配置信息。</div>
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
                  label={
                    <span>
                      跨域代理配置{' '}
                      <Tooltip title="JSON格式的代理配置，支持多个代理服务器">
                        <QuestionCircleOutlined className="cursor-pointer text-gray-400" />
                      </Tooltip>
                    </span>
                  }
                  rules={[
                    { required: true, message: '请输入代理配置' },
                    {
                      validator: (_, value) => {
                        if (!value) return Promise.resolve()
                        try {
                          JSON.parse(value)
                          return Promise.resolve()
                        } catch {
                          return Promise.reject(new Error('请输入有效的JSON格式'))
                        }
                      },
                    },
                  ]}
                  className="mb-6"
                >
                  <Input.TextArea rows={8} />
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
          <div className="flex items-center justify-start flex-wrap gap-2 mb-4">
            <Form.Item
              name={`scraper${setname.charAt(0).toUpperCase()}${setname.slice(1)}LogResponses`}
              label="记录原始响应"
              valuePropName="checked"
              className="min-w-[100px] shrink-0 !mb-0"
            >
              <Switch />
            </Form.Item>
            <div className="w-full">
              启用后，此源的所有API请求的原始响应将被记录到
              config/logs/scraper_responses.log 文件中，用于调试。
            </div>
          </div>
          {/* bilibili登录信息 */}
          {setname === 'bilibili' && (
            <div>
              {biliUserinfo.isLogin ? (
                <div className="text-center">
                  <div className="flex items-center justify-center gap-2 mb-4">
                    <img
                      className="w-10 h-10 rounded-full"
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
                <div className="text-center">
                  <div className="mb-4">当前未登录。</div>
                  <div className="flex items-center justify-center">
                    <Checkbox
                      checked={biliQrcodeChecked}
                      onChange={() => setBiliQrcodeChecked(v => !v)}
                    />
                    <span
                      className="ml-2 cursor-pointer"
                      onClick={() => setBiliQrcodeChecked(v => !v)}
                    >
                      我已阅读并同意以下免责声明
                    </span>
                  </div>
                  <div className="my-3">
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
                  <Button
                    disabled={!biliQrcodeChecked}
                    type="primary"
                    loading={biliQrcodeLoading}
                    onClick={handleBiliQrcode}
                  >
                    扫码登录
                  </Button>
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
      >
        <div className="text-center">
          <div className="relative w-[200px] h-[200px] mx-auto mb-3">
            <QRCodeCanvas
              value={biliQrcode.url}
              size={200}
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
          <div className="mb-3">请使用Bilibili手机客户端扫描二维码</div>
          <Button type="primary" danger onClick={cancelBiliLogin}>
            取消登录
          </Button>
        </div>
      </Modal>
    </div>
  )
}
