import React, { useState, useEffect } from 'react'
import { Card, Row, Col, Statistic, Button, Select, message, Spin, Empty } from 'antd'
import { ReloadOutlined, DeleteOutlined, DownloadOutlined } from '@ant-design/icons'
import { getAIMetrics, clearAICache } from '@/apis'

const { Option } = Select

const AIMetrics = () => {
  const [loading, setLoading] = useState(false)
  const [metricsData, setMetricsData] = useState(null)
  const [timeRange, setTimeRange] = useState(24)
  const [clearing, setClearing] = useState(false)

  // 加载统计数据
  const loadMetrics = async () => {
    try {
      setLoading(true)
      const res = await getAIMetrics(timeRange)
      setMetricsData(res.data)
    } catch (error) {
      console.error('加载AI统计失败:', error)
      message.error(`加载失败: ${error?.message || '未知错误'}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMetrics()
  }, [timeRange])

  // 清空缓存
  const handleClearCache = async () => {
    try {
      setClearing(true)
      await clearAICache()
      message.success('AI缓存已清空')
      loadMetrics() // 重新加载统计
    } catch (error) {
      console.error('清空缓存失败:', error)
      message.error(`清空失败: ${error?.message || '未知错误'}`)
    } finally {
      setClearing(false)
    }
  }

  if (loading && !metricsData) {
    return (
      <div style={{ textAlign: 'center', padding: '50px' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!metricsData) {
    return <Empty description="暂无数据" />
  }

  const { ai_stats, cache_stats } = metricsData

  return (
    <div>
      {/* 操作栏 */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <span>时间范围:</span>
          <Select value={timeRange} onChange={setTimeRange} style={{ width: 150 }}>
            <Option value={1}>最近1小时</Option>
            <Option value={24}>最近24小时</Option>
            <Option value={168}>最近7天</Option>
            <Option value={720}>最近30天</Option>
          </Select>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Button icon={<ReloadOutlined />} onClick={loadMetrics} loading={loading}>
            刷新统计
          </Button>
          <Button 
            icon={<DeleteOutlined />} 
            onClick={handleClearCache} 
            loading={clearing}
            danger
          >
            清空缓存
          </Button>
        </div>
      </div>

      {/* 调用统计 */}
      <Card title="📞 调用统计" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col xs={24} sm={12} md={6}>
            <Statistic
              title="总调用次数"
              value={ai_stats?.total_calls || 0}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic
              title="成功次数"
              value={Math.round((ai_stats?.total_calls || 0) * (ai_stats?.success_rate || 0))}
              valueStyle={{ color: '#3f8600' }}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic
              title="失败次数"
              value={Math.round((ai_stats?.total_calls || 0) * (1 - (ai_stats?.success_rate || 0)))}
              valueStyle={{ color: '#cf1322' }}
            />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic
              title="成功率"
              value={(ai_stats?.success_rate || 0) * 100}
              precision={1}
              suffix="%"
              valueStyle={{ color: ((ai_stats?.success_rate || 0) * 100) >= 90 ? '#3f8600' : '#faad14' }}
            />
          </Col>
        </Row>
      </Card>

      {/* Token 统计 */}
      <Card title="📝 Token 统计" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col xs={24} sm={12} md={8}>
            <Statistic
              title="总 Token 数"
              value={ai_stats?.total_tokens || 0}
            />
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Statistic
              title="平均响应时间"
              value={((ai_stats?.avg_duration_ms || 0) / 1000).toFixed(2)}
              suffix="s"
            />
          </Col>
          <Col xs={24} sm={12} md={8}>
            <Statistic
              title="缓存命中率"
              value={(ai_stats?.cache_hit_rate || 0) * 100}
              precision={1}
              suffix="%"
              valueStyle={{ color: ((ai_stats?.cache_hit_rate || 0) * 100) >= 30 ? '#3f8600' : '#faad14' }}
            />
          </Col>
        </Row>
      </Card>

      {/* 缓存统计 */}
      {cache_stats && (
        <Card title="💾 缓存统计">
          <Row gutter={16}>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="缓存命中次数"
                value={cache_stats.hits || 0}
              />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="缓存未命中"
                value={cache_stats.misses || 0}
              />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="缓存命中率"
                value={cache_stats.hit_rate || 0}
                precision={1}
                suffix="%"
                valueStyle={{ color: (cache_stats.hit_rate || 0) >= 30 ? '#3f8600' : '#faad14' }}
              />
            </Col>
            <Col xs={24} sm={12} md={6}>
              <Statistic
                title="缓存大小"
                value={`${cache_stats.size || 0} / ${cache_stats.max_size || 1000}`}
              />
            </Col>
          </Row>
        </Card>
      )}
    </div>
  )
}

export default AIMetrics

