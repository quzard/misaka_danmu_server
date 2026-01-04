import { useState, useEffect } from 'react'
import { Modal, Spin, Tag, Badge, Typography, Collapse, Timeline, Button } from 'antd'
import { getReleaseHistory } from '../apis'
import { useMessage } from '../MessageContext'
import dayjs from 'dayjs'

const { Text } = Typography

export const ReleaseHistoryModal = ({ open, onClose }) => {
  const [loading, setLoading] = useState(false)
  const [releaseHistory, setReleaseHistory] = useState([])
  const messageApi = useMessage()

  useEffect(() => {
    if (open && releaseHistory.length === 0) {
      loadReleaseHistory()
    }
  }, [open])

  const loadReleaseHistory = async () => {
    setLoading(true)
    try {
      const res = await getReleaseHistory(30)
      setReleaseHistory(res.data.releases || [])
    } catch (error) {
      console.error('加载历史版本失败:', error)
      messageApi.error('加载历史版本失败')
    } finally {
      setLoading(false)
    }
  }

  const latestVersion = releaseHistory.length > 0 ? releaseHistory[0].version : null

  return (
    <Modal
      title={
        <div className="flex items-center gap-2">
          <span>更新日志</span>
          {latestVersion && (
            <Tag color="green">最新版本: v{latestVersion}</Tag>
          )}
        </div>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
      styles={{ body: { maxHeight: '70vh', overflowY: 'auto' } }}
    >
      <Spin spinning={loading}>
        {releaseHistory.length > 0 ? (
          <Timeline
            className="mt-4"
            items={releaseHistory.map((release, index) => ({
              color: index === 0 ? 'green' : 'gray',
              children: (
                <Collapse
                  size="small"
                  defaultActiveKey={index === 0 ? [release.version] : []}
                  items={[{
                    key: release.version,
                    label: (
                      <div className="flex items-center gap-2 flex-wrap">
                        <Tag color={index === 0 ? 'green' : 'default'}>
                          v{release.version}
                        </Tag>
                        {release.publishedAt && (
                          <Text type="secondary" className="text-xs">
                            {dayjs(release.publishedAt).format('YYYY-MM-DD HH:mm')}
                          </Text>
                        )}
                        {index === 0 && <Badge status="processing" text="最新" />}
                      </div>
                    ),
                    children: (
                      <div className="max-h-[300px] overflow-y-auto">
                        <pre className="whitespace-pre-wrap text-sm m-0 bg-gray-50 dark:bg-gray-800 p-3 rounded">
                          {release.changelog || '暂无更新说明'}
                        </pre>
                        {release.releaseUrl && (
                          <Button
                            type="link"
                            size="small"
                            href={release.releaseUrl}
                            target="_blank"
                            className="mt-2 p-0"
                          >
                            查看 GitHub Release
                          </Button>
                        )}
                      </div>
                    )
                  }]}
                />
              )
            }))}
          />
        ) : (
          !loading && <div className="text-center text-gray-500 py-8">暂无版本信息</div>
        )}
      </Spin>
    </Modal>
  )
}

export default ReleaseHistoryModal

