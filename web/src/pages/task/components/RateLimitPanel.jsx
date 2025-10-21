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

            {/* 顶部卡片区 - 左右分栏 */}
            <Row gutter={16} className="!mb-6">
              {/* 左侧卡片 - 全局流控状态 */}
              <Col xs={24} lg={12}>
                <Card type="inner" title="🌐 全局流控状态">
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span><strong>全局限制:</strong></span>
                      <span>{status.globalRequestCount} / {status.globalLimit}</span>
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
                  <div style={{ marginBottom: 8 }}>
                    <Statistic
                      title="⏱️ 重置倒计时"
                      value={status.secondsUntilReset}
                      suffix="秒"
                    />
                  </div>
                </Card>
              </Col>

              {/* 右侧卡片 - 后备调用流控 */}
              <Col xs={24} lg={12}>
                <Card type="inner" title="🔄 后备调用流控">
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span><strong>后备限制:</strong></span>
                      <span>{status.fallback?.totalCount || 0} / {status.fallback?.totalLimit || 0}</span>
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
                  <div>
                    <div style={{ marginBottom: 8 }}>
                      <strong>📊 调用统计:</strong>
                    </div>
                    <div style={{ paddingLeft: 16 }}>
                      <div>• 匹配: {status.fallback?.matchCount || 0} 次</div>
                      <div>• 搜索: {status.fallback?.searchCount || 0} 次</div>
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
          </>
        )}
      </Card>
    </div>
  )
}
