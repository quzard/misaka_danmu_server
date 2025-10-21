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
            此面板实时显示全局、弹幕下载和后备调用的速率限制状态。
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

            {/* 全局限制 */}
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

            {/* 左右分栏布局 */}
            <Row gutter={16}>
              {/* 左侧：弹幕下载流控 */}
              <Col xs={24} lg={12}>
                <Card
                  type="inner"
                  title="弹幕下载流控"
                  className={status.verificationFailed ? 'opacity-50' : ''}
                >
                  <Table
                    columns={[
                      {
                        title: '源名称',
                        dataIndex: 'providerName',
                        key: 'providerName',
                        width: 100,
                      },
                      {
                        title: '直接下载',
                        dataIndex: 'directCount',
                        key: 'directCount',
                        width: 80,
                        align: 'center',
                      },
                      {
                        title: '后备调用',
                        dataIndex: 'fallbackCount',
                        key: 'fallbackCount',
                        width: 80,
                        align: 'center',
                      },
                      {
                        title: '总计/配额',
                        key: 'usage',
                        width: 100,
                        align: 'center',
                        render: (_, record) =>
                          `${record.requestCount} / ${record.quota}`,
                      },
                      {
                        title: '状态',
                        key: 'status',
                        width: 80,
                        align: 'center',
                        render: (_, record) => {
                          if (record.quota === '∞') return '正常'
                          const percent = (record.requestCount / record.quota) * 100
                          if (percent >= 100) return '🔴 已满'
                          if (percent >= 80) return '🟡 接近'
                          return '🟢 正常'
                        },
                      },
                    ]}
                    dataSource={status.providers}
                    rowKey="providerName"
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>

              {/* 右侧：后备调用流控 */}
              <Col xs={24} lg={12}>
                <Card
                  type="inner"
                  title="后备调用流控"
                  className={status.verificationFailed ? 'opacity-50' : ''}
                >
                  <Row gutter={[16, 16]}>
                    <Col span={12}>
                      <Statistic
                        title="后备匹配"
                        value={status.fallback?.matchCount || 0}
                        suffix={`/ ${status.fallback?.totalLimit || 50}`}
                      />
                    </Col>
                    <Col span={12}>
                      <Statistic
                        title="后备搜索"
                        value={status.fallback?.searchCount || 0}
                        suffix={`/ ${status.fallback?.totalLimit || 50}`}
                      />
                    </Col>
                    <Col span={24}>
                      <Statistic
                        title="总计"
                        value={status.fallback?.totalCount || 0}
                        suffix={`/ ${status.fallback?.totalLimit || 50}`}
                      />
                    </Col>
                    <Col span={24}>
                      <Progress
                        percent={
                          status.fallback?.totalLimit > 0
                            ? (status.fallback.totalCount / status.fallback.totalLimit) * 100
                            : 0
                        }
                        status={
                          status.fallback?.totalCount >= status.fallback?.totalLimit
                            ? 'exception'
                            : status.fallback?.totalCount >= status.fallback?.totalLimit * 0.8
                              ? 'normal'
                              : 'success'
                        }
                      />
                    </Col>
                    <Col span={24}>
                      <Statistic.Timer
                        title="重置倒计时"
                        value={Date.now() + status.secondsUntilReset * 1000}
                        format="HH:mm:ss"
                        type="countdown"
                      />
                    </Col>
                  </Row>
                </Card>
              </Col>
            </Row>
          </>
        )}
      </Card>
    </div>
  )
}
