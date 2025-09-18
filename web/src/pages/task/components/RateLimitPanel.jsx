import { useEffect, useState, useRef } from 'react'
import { getRateLimitStatus } from '../../../apis/index.js'
import {
  Card,
  Table,
  Typography,
  Progress,
  Row,
  Col,
  Statistic,
  Alert,
} from 'antd'

const { Title, Paragraph } = Typography

const periodLabelMap = {
  second: '秒',
  minute: '分钟',
  hour: '小时',
  day: '天',
}

export const RateLimitPanel = () => {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef()

  const fetchStatus = async () => {
    try {
      const res = await getRateLimitStatus()
      setStatus(res.data)
      if (loading) setLoading(false)
    } catch (error) {
      console.error('获取流控状态失败:', error)
      if (loading) setLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
    timer.current = setInterval(fetchStatus, 5000) // Refresh every 5 seconds
    return () => {
      clearInterval(timer.current)
    }
  }, [])

  return (
    <div className="my-6">
      <Card loading={loading}>
        <Typography>
          <Title level={4}>流控状态面板</Title>
          <Paragraph>
            此面板实时显示全局和各源的弹幕下载速率限制状态。特定源的配额包含在全局限制内。
          </Paragraph>
        </Typography>
        {status && (
          <>
            {status.verificationFailed && (
              <Alert
                message="严重安全警告"
                description="流控配置文件验证失败或缺失。为保证安全，所有弹幕下载请求已被自动阻止。"
                type="error"
                showIcon
                className="!mb-4"
              />
            )}
            <Card type="inner" title="全局限制" className="!mb-6">
              <Row gutter={[16, 16]} align="middle">
                <Col xs={24} sm={12} md={8}>
                  <Statistic
                    title="全局状态"
                    value={
                      status.verificationFailed
                        ? '验证失败 (已锁定)'
                        : status.globalEnabled
                          ? '已启用'
                          : '已禁用'
                    }
                    valueStyle={{
                      color: status.verificationFailed
                        ? 'var(--color-red-600)'
                        : undefined,
                    }}
                  />
                </Col>
                <Col xs={24} sm={12} md={8}>
                  <Statistic
                    title={`全局使用量 (每${periodLabelMap[status.globalPeriod] || status.globalPeriod})`}
                    value={status.globalRequestCount}
                    suffix={`/ ${status.globalLimit}`}
                    className={status.verificationFailed ? 'opacity-50' : ''}
                  />
                </Col>
                <Col xs={24} sm={24} md={8}>
                  <Statistic.Timer
                    title="重置倒计时"
                    value={Date.now() + status.secondsUntilReset * 1000}
                    format="HH:mm:ss"
                    type="countdown"
                    className={status.verificationFailed ? 'opacity-50' : ''}
                  />
                </Col>
                <Col span={24}>
                  <Progress
                    percent={status.globalLimit > 0 ? (status.globalRequestCount / status.globalLimit) * 100 : 0}
                    showInfo={false}
                    className={status.verificationFailed ? 'opacity-50' : ''}
                  />
                </Col>
              </Row>
            </Card>
            <Card
              type="inner"
              title="各源配额使用情况"
              className={status.verificationFailed ? 'opacity-50' : ''}
            >
              <Table
                columns={[
                  {
                    title: '搜索源',
                    dataIndex: 'providerName',
                    key: 'providerName',
                  },
                  {
                    title: '使用情况 (已用 / 配额)',
                    key: 'usage',
                    render: (_, record) =>
                      `${record.requestCount} / ${record.quota}`,
                  },
                ]}
                dataSource={status.providers}
                rowKey="providerName"
                pagination={false}
              />
            </Card>
          </>
        )}
      </Card>
    </div>
  )
}
