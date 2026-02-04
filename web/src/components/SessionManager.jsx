import { useState, useEffect } from 'react'
import { Modal, Card, Button, Spin, Empty, Tag, Popconfirm, Tooltip } from 'antd'
import {
  DesktopOutlined,
  MobileOutlined,
  ClockCircleOutlined,
  GlobalOutlined,
  DeleteOutlined,
  ExclamationCircleOutlined,
  SafetyCertificateOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import { getUserSessions, revokeSession, revokeOtherSessions } from '../apis/index.js'
import { useMessage } from '../MessageContext'
import dayjs from 'dayjs'

/**
 * 解析 User-Agent 获取设备/浏览器信息
 */
const parseUserAgent = (ua) => {
  if (!ua) return { browser: '未知浏览器', os: '未知系统', isMobile: false }

  const isMobile = /Mobile|Android|iPhone|iPad/i.test(ua)

  // 解析浏览器
  let browser = '未知浏览器'
  if (ua.includes('Edg/')) browser = 'Edge'
  else if (ua.includes('Chrome/')) browser = 'Chrome'
  else if (ua.includes('Firefox/')) browser = 'Firefox'
  else if (ua.includes('Safari/') && !ua.includes('Chrome')) browser = 'Safari'
  else if (ua.includes('Opera') || ua.includes('OPR/')) browser = 'Opera'

  // 解析操作系统
  let os = '未知系统'
  if (ua.includes('Windows')) os = 'Windows'
  else if (ua.includes('Mac OS')) os = 'macOS'
  else if (ua.includes('Linux')) os = 'Linux'
  else if (ua.includes('Android')) os = 'Android'
  else if (ua.includes('iPhone') || ua.includes('iPad')) os = 'iOS'

  return { browser, os, isMobile }
}

/**
 * 格式化时间显示
 */
const formatTime = (time) => {
  if (!time) return '-'
  return dayjs(time).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 计算过期状态
 */
const getExpireStatus = (expiresAt, isRevoked) => {
  if (isRevoked) return { text: '已撤销', color: 'red' }
  if (!expiresAt) return { text: '永不过期', color: 'green' }
  const now = dayjs()
  const expire = dayjs(expiresAt)
  if (expire.isBefore(now)) return { text: '已过期', color: 'red' }
  const diff = expire.diff(now, 'day')
  if (diff < 1) return { text: `${expire.diff(now, 'hour')}小时后过期`, color: 'orange' }
  return { text: `${diff}天后过期`, color: 'blue' }
}

const SessionManager = ({ open, onClose }) => {
  const [loading, setLoading] = useState(false)
  const [sessions, setSessions] = useState([])
  const [currentJti, setCurrentJti] = useState(null)
  const [revoking, setRevoking] = useState(null)
  const messageApi = useMessage()

  const fetchSessions = async () => {
    try {
      setLoading(true)
      const res = await getUserSessions()
      setSessions(res.data.sessions || [])
      setCurrentJti(res.data.currentJti)
    } catch (error) {
      messageApi.error('获取会话列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchSessions()
    }
  }, [open])

  const handleRevokeSession = async (sessionId) => {
    try {
      setRevoking(sessionId)
      await revokeSession(sessionId)
      messageApi.success('已踢出该设备')
      fetchSessions()
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '操作失败')
    } finally {
      setRevoking(null)
    }
  }

  const handleRevokeOthers = async () => {
    try {
      setRevoking('all')
      const res = await revokeOtherSessions()
      messageApi.success(`已踢出 ${res.data.revokedCount} 个其他设备`)
      fetchSessions()
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '操作失败')
    } finally {
      setRevoking(null)
    }
  }

  // 过滤出有效会话（未撤销且未过期）
  const activeSessions = sessions.filter(s => !s.isRevoked && (!s.expiresAt || dayjs(s.expiresAt).isAfter(dayjs())))
  const otherActiveSessions = activeSessions.filter(s => s.jti !== currentJti)

  // 底部按钮
  const footerContent = otherActiveSessions.length > 0 && !loading ? (
    <div className="flex justify-end">
      <Popconfirm
        title="确定踢出所有其他设备？"
        description={`将踢出 ${otherActiveSessions.length} 个其他设备`}
        onConfirm={handleRevokeOthers}
        okText="确定"
        cancelText="取消"
        icon={<ExclamationCircleOutlined style={{ color: 'red' }} />}
      >
        <Button
          type="primary"
          danger
          loading={revoking === 'all'}
        >
          踢出所有其他设备
        </Button>
      </Popconfirm>
    </div>
  ) : null

  return (
    <Modal
      title="会话管理"
      open={open}
      onCancel={onClose}
      footer={footerContent}
      width={700}
      styles={{ body: { maxHeight: '60vh', overflowY: 'auto' } }}
    >
      <div className="mb-4 text-gray-500 text-sm">
        管理您的登录会话，可以查看所有已登录的设备并踢出可疑设备。
      </div>

      {loading ? (
        <div className="flex justify-center py-8">
          <Spin size="large" />
        </div>
      ) : activeSessions.length === 0 ? (
        <Empty description="暂无活跃会话" />
      ) : (
        <div className="space-y-3">
          {activeSessions.map((session) => {
            const { browser, os, isMobile } = parseUserAgent(session.userAgent)
            const expireStatus = getExpireStatus(session.expiresAt, session.isRevoked)
            const isCurrent = session.jti === currentJti
            const isWhitelist = session.isWhitelist

            return (
              <Card
                key={session.id}
                size="small"
                className={`${isCurrent ? 'border-blue-400 border-2' : ''} ${isWhitelist ? 'bg-green-50 dark:bg-green-900/20' : ''}`}
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2 flex-wrap">
                      {isWhitelist ? (
                        <Tooltip title="IP白名单免登录会话">
                          <SafetyCertificateOutlined className="text-green-500" />
                        </Tooltip>
                      ) : (
                        isMobile ? <MobileOutlined /> : <DesktopOutlined />
                      )}
                      <span className="font-medium">{browser} / {os}</span>
                      {isWhitelist && <Tag color="green" icon={<SafetyCertificateOutlined />}>白名单</Tag>}
                      {isCurrent && <Tag color="blue">当前会话</Tag>}
                      <Tag color={expireStatus.color}>{expireStatus.text}</Tag>
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 space-y-1">
                      <div className="flex items-center gap-1">
                        <GlobalOutlined />
                        <span>IP: {session.ipAddress || '未知'}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="ml-3.5">UA: {session.userAgent || '未知'}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <ClockCircleOutlined />
                        <span>登录时间: {formatTime(session.createdAt)}</span>
                      </div>
                    </div>
                  </div>
                  {!isCurrent && (
                    <Popconfirm
                      title="确定踢出此设备？"
                      description={isWhitelist ? "白名单会话踢出后，同IP同浏览器访问会自动重建" : "该设备将需要重新登录"}
                      onConfirm={() => handleRevokeSession(session.id)}
                      okText="确定"
                      cancelText="取消"
                    >
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        loading={revoking === session.id}
                      >
                        踢出
                      </Button>
                    </Popconfirm>
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </Modal>
  )
}

export default SessionManager

