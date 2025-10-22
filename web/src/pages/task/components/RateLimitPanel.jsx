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

            {/* 顶部状态卡片 */}
            <Card type="inner" className="!mb-4">
              <Row gutter={16}>
                <Col xs={24} sm={12}>
                  <Statistic
                    title="流控状态"
                    value={status.enabled ? '已启用' : '已禁用'}
                    valueStyle={{ color: status.enabled ? '#3f8600' : '#cf1322' }}
                  />
                </Col>
                <Col xs={24} sm={12}>
                  <Statistic.Countdown
                    title="重置倒计时"
                    value={Date.now() + status.secondsUntilReset * 1000}
                    format="HH:mm:ss"
                  />
                </Col>
              </Row>
            </Card>

            {/* 中间卡片区 - 左右分栏 */}
            <Row gutter={16} className="!mb-6">
              {/* 左侧卡片 - 弹幕下载流控 */}
              <Col xs={24} lg={12}>
                <Card type="inner" title="🌐 弹幕下载流控" style={{ height: '100%' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <span><strong>弹幕下载详情:</strong></span>
                        <span>{status.globalRequestCount} 次 / {status.globalLimit} 次</span>
                      </div>
                      <Progress
                        percent={status.globalLimit > 0 ? (status.globalRequestCount / status.globalLimit) * 100 : 0}
                        status={
                          status.globalLimit > 0 && (status.globalRequestCount / status.globalLimit) * 100 >= 100
                            ? 'exception'
                            : status.globalLimit > 0 && (status.globalRequestCount / status.globalLimit) * 100 >= 80
                              ? 'normal'
                              : 'success'
                        }
                        strokeColor={
                          status.globalLimit > 0 && (status.globalRequestCount / status.globalLimit) * 100 >= 100
                            ? '#ff4d4f'
                            : status.globalLimit > 0 && (status.globalRequestCount / status.globalLimit) * 100 >= 80
                              ? '#faad14'
                              : '#52c41a'
                        }
                      />
                    </div>
                    {/* 占位元素,保持与右侧卡片高度一致 */}
                    <div style={{ height: '32px' }}></div>
                  </div>
                </Card>
              </Col>

              {/* 右侧卡片 - 后备调用流控 */}
              <Col xs={24} lg={12}>
                <Card type="inner" title="🔄 后备调用流控" style={{ height: '100%' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <span><strong>后备流控详情:</strong></span>
                        <span>{status.fallback?.totalCount || 0} 次 / {status.fallback?.totalLimit || 0} 次</span>
                      </div>
                      <Progress
                        percent={status.fallback?.totalLimit > 0 ? (status.fallback.totalCount / status.fallback.totalLimit) * 100 : 0}
                        status={
                          status.fallback?.totalLimit > 0 && (status.fallback.totalCount / status.fallback.totalLimit) * 100 >= 100
                            ? 'exception'
                            : status.fallback?.totalLimit > 0 && (status.fallback.totalCount / status.fallback.totalLimit) * 100 >= 80
                              ? 'normal'
                              : 'success'
                        }
                        strokeColor={
                          status.fallback?.totalLimit > 0 && (status.fallback.totalCount / status.fallback.totalLimit) * 100 >= 100
                            ? '#ff4d4f'
                            : status.fallback?.totalLimit > 0 && (status.fallback.totalCount / status.fallback.totalLimit) * 100 >= 80
                              ? '#faad14'
                              : '#52c41a'
                        }
                      />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginTop: '12px', height: '32px' }}>
                      <strong>📊 调用统计:</strong>
                      <span>匹配: {status.fallback?.matchCount || 0} 次</span>
                      <span>搜索: {status.fallback?.searchCount || 0} 次</span>
                    </div>
                  </div>
                </Card>
              </Col>
            </Row>

            {/* 底部表格区 - 各源流控详情 */}
            <Card type="inner" title="各源流控详情" className={status.verificationFailed ? 'opacity-50' : ''}>
              <Table
                columns={[
                  {
                    title: '源名称',
                    dataIndex: 'providerName',
                    key: 'providerName',
                    width: 100,
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
          </>
        )}
      </Card>
    </div>
  )
}
