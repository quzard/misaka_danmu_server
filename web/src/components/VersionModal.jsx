import { useState, useEffect } from 'react'
import { Modal, Button, Tag, Spin, Badge, Typography, Divider, Alert } from 'antd'
import { SyncOutlined, RocketOutlined, CheckCircleOutlined, CloseCircleOutlined, HistoryOutlined } from '@ant-design/icons'
import { checkAppUpdate, getDockerStatus, restartService } from '../apis'
import { useMessage } from '../MessageContext'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import Cookies from 'js-cookie'
import ReleaseHistoryModal from './ReleaseHistoryModal'

const { Text, Paragraph, Title } = Typography

export const VersionModal = ({ open, onClose, currentVersion }) => {
  const [loading, setLoading] = useState(false)
  const [updateInfo, setUpdateInfo] = useState(null)
  const [dockerStatus, setDockerStatus] = useState(null)
  const [updating, setUpdating] = useState(false)
  const [updateLogs, setUpdateLogs] = useState([])
  const [updateComplete, setUpdateComplete] = useState(false)
  const [updateError, setUpdateError] = useState(null)
  const [releaseHistoryOpen, setReleaseHistoryOpen] = useState(false)
  const messageApi = useMessage()

  // 加载更新信息和 Docker 状态
  useEffect(() => {
    if (open) {
      loadData()
    }
  }, [open])

  const loadData = async () => {
    setLoading(true)
    try {
      const [updateRes, dockerRes] = await Promise.all([
        checkAppUpdate(),
        getDockerStatus()
      ])
      setUpdateInfo(updateRes.data)
      setDockerStatus(dockerRes.data)
    } catch (error) {
      console.error('加载数据失败:', error)
    } finally {
      setLoading(false)
    }
  }



  // 开始更新
  const handleUpdate = async () => {
    if (!dockerStatus?.canUpdate) {
      messageApi.error('Docker 套接字 不可用，无法执行更新')
      return
    }

    setUpdating(true)
    setUpdateLogs([])
    setUpdateComplete(false)
    setUpdateError(null)

    const token = Cookies.get('danmu_token')
    
    try {
      await fetchEventSource('/api/ui/update/stream', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
        onmessage(event) {
          try {
            const data = JSON.parse(event.data)
            setUpdateLogs(prev => [...prev, data.status])
            
            if (data.event === 'DONE' || data.event === 'UP_TO_DATE') {
              setUpdateComplete(true)
              setUpdating(false)
            } else if (data.event === 'ERROR') {
              setUpdateError(data.status)
              setUpdating(false)
            }
          } catch (e) {
            console.error('解析更新消息失败:', e)
          }
        },
        onerror(err) {
          console.error('更新流错误:', err)
          setUpdateError('连接中断')
          setUpdating(false)
        },
        onclose() {
          setUpdating(false)
        }
      })
    } catch (error) {
      console.error('更新失败:', error)
      setUpdateError(error.message || '更新失败')
      setUpdating(false)
    }
  }

  // 重启服务
  const handleRestart = async () => {
    try {
      const res = await restartService()
      messageApi.success(res.data.message)
      onClose()
    } catch (error) {
      messageApi.error('重启失败: ' + (error.message || '未知错误'))
    }
  }

  // 渲染更新日志
  const renderChangelog = () => {
    if (!updateInfo?.changelog) return null
    
    return (
      <div className="max-h-[300px] overflow-y-auto bg-gray-50 dark:bg-gray-800 rounded-lg p-4 mt-4">
        <Title level={5}>更新日志</Title>
        <Paragraph>
          <pre className="whitespace-pre-wrap text-sm">{updateInfo.changelog}</pre>
        </Paragraph>
      </div>
    )
  }

  return (
    <Modal
      title="版本信息"
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
    >
      <Spin spinning={loading}>
        <div className="space-y-4">
          {/* 当前版本 */}
          <div className="flex items-center justify-between">
            <Text>当前版本</Text>
            <Tag color="blue">{currentVersion}</Tag>
          </div>

          {/* 最新版本 */}
          {updateInfo && (
            <div className="flex items-center justify-between">
              <Text>最新版本</Text>
              <div className="flex items-center gap-2">
                {updateInfo.hasUpdate ? (
                  <Tag color="green">{updateInfo.latestVersion}</Tag>
                ) : (
                  <Tag>{updateInfo.latestVersion || '检查中...'}</Tag>
                )}
                {updateInfo.hasUpdate && <Badge status="processing" text="有新版本" />}
              </div>
            </div>
          )}

          {/* Docker 状态 */}
          <Divider />
          <div className="flex items-center justify-between">
            <Text>Docker 状态</Text>
            {dockerStatus?.socketAvailable ? (
              <Tag icon={<CheckCircleOutlined />} color="success">已连接</Tag>
            ) : (
              <Tag icon={<CloseCircleOutlined />} color="default">未连接</Tag>
            )}
          </div>

          {!dockerStatus?.socketAvailable && (
            <Alert
              type="info"
              showIcon
              message="Docker 套接字 未映射"
              description="如需使用一键更新功能，请在 docker-compose.yml 中添加 /var/run/docker.sock:/var/run/docker.sock 路径映射"
            />
          )}

          {/* 更新日志 */}
          {renderChangelog()}

          {/* 更新进度 */}
          {(updating || updateLogs.length > 0) && (
            <div className="mt-4">
              <Divider>更新进度</Divider>
              <div className="bg-gray-900 text-green-400 rounded-lg p-4 max-h-[200px] overflow-y-auto font-mono text-sm">
                {updateLogs.map((log, index) => (
                  <div key={index}>{log}</div>
                ))}
                {updating && <Spin size="small" className="ml-2" />}
              </div>
            </div>
          )}

          {/* 更新结果 */}
          {updateComplete && (
            <Alert
              type="success"
              showIcon
              message="更新完成"
              description="容器将在后台重启，请稍后刷新页面"
            />
          )}

          {updateError && (
            <Alert
              type="error"
              showIcon
              message="更新失败"
              description={updateError}
            />
          )}

          {/* 操作按钮 */}
          <Divider />
          <div className="flex justify-between">
            <Button
              onClick={() => setReleaseHistoryOpen(true)}
              icon={<HistoryOutlined />}
            >
              更新日志
            </Button>
            <div className="flex gap-2">
              <Button onClick={() => loadData()} icon={<SyncOutlined />}>
                刷新
              </Button>
              {updateInfo?.hasUpdate && dockerStatus?.canUpdate && (
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  onClick={handleUpdate}
                  loading={updating}
                  disabled={updateComplete}
                >
                  开始更新
                </Button>
              )}
              {updateInfo?.releaseUrl && (
                <Button
                  href={updateInfo.releaseUrl}
                  target="_blank"
                >
                  查看 Release
                </Button>
              )}
            </div>
          </div>
        </div>
      </Spin>

      {/* 更新日志弹窗 */}
      <ReleaseHistoryModal
        open={releaseHistoryOpen}
        onClose={() => setReleaseHistoryOpen(false)}
      />
    </Modal>
  )
}

export default VersionModal

