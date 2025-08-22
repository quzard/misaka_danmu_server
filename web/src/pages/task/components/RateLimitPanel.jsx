import { Card, Col, Progress, Row, Spin, Tooltip, Typography } from 'antd'
import { useEffect, useState, useRef } from 'react'
import { getRateLimitStatus } from '@/apis'
import { QuestionCircleOutlined } from '@ant-design/icons'

const { Title, Text } = Typography

// 辅助函数：将秒格式化为易读的字符串
const formatSeconds = seconds => {
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (remainingSeconds === 0) return `${minutes}分钟`
  return `${minutes}分${remainingSeconds}秒`
}

const RateLimitCard = ({ title, status }) => {
  if (!status || !status.limit || status.limit <= 0) {
    return null // 如果限制未启用或无效，则不渲染卡片
  }

  const percent = (status.count / status.limit) * 100
  const periodHours = (status.periodSeconds / 3600).toFixed(1).replace('.0', '')
  const limitText = `${status.limit} 次 / ${periodHours} 小时`

  return (
    <Col xs={24} sm={12} md={8} lg={6}>
      <Card title={title} size="small" className="text-center">
        <Progress
          type="circle"
          percent={percent}
          format={() => `${status.count}/${status.limit}`}
        />
        <Text type="secondary" className="block mt-2">
          {limitText}
        </Text>
        <Text type="secondary" className="block mt-1">
          将于 {formatSeconds(status.resetsInSeconds)} 后重置
        </Text>
      </Card>
    </Col>
  )
}

export const RateLimitPanel = () => {
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState(null)
  const timerRef = useRef(null)

  const fetchStatus = async () => {
    try {
      const res = await getRateLimitStatus()
      setStatus(res.data)
    } catch (error) {
      console.error('获取流控状态失败:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    timerRef.current = setInterval(fetchStatus, 5000) // 每5秒刷新一次
    return () => clearInterval(timerRef.current)
  }, [])

  if (loading) {
    return <div className="text-center p-10"><Spin /></div>
  }

  return (
    <div className="my-6">
      <Card>
        <Title level={4} className="!mb-4">
          全局流控状态
          <Tooltip title="全局流控限制所有源在指定周期内的总下载次数。周期从该周期内的第一次下载开始计算。">
            <QuestionCircleOutlined className="ml-2 text-gray-400 cursor-help" />
          </Tooltip>
        </Title>
        <Row gutter={[16, 16]}>
          <RateLimitCard title="全局" status={status?.globalStatus} />
        </Row>

        <Title level={4} className="!mt-8 !mb-4">
          各源流控状态
        </Title>
        <Row gutter={[16, 16]}>
          {status?.providerStatus && Object.entries(status.providerStatus).map(([provider, providerStatus]) => (
            <RateLimitCard key={provider} title={provider.charAt(0).toUpperCase() + provider.slice(1)} status={providerStatus} />
          ))}
        </Row>
      </Card>
    </div>
  )
}
