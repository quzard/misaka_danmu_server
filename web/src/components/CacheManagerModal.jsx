import { useState, useEffect, useCallback } from 'react'
import { Modal, Table, Button, Input, Select, Space, Tag, Popconfirm, message, Statistic, Row, Col, Card } from 'antd'
import { DeleteOutlined, ReloadOutlined, ClearOutlined, SearchOutlined, DatabaseOutlined } from '@ant-design/icons'
import { getCacheStats, getCacheList, clearCache, deleteCacheKey } from '@/apis'

const REGION_COLORS = {
  search: 'blue',
  metadata: 'green',
  episodes: 'orange',
  comments: 'purple',
  default: 'default',
}

export default function CacheManagerModal({ open, onClose }) {
  const [stats, setStats] = useState({ total: 0, regions: {} })
  const [keys, setKeys] = useState([])
  const [loading, setLoading] = useState(false)
  const [region, setRegion] = useState('search')
  const [search, setSearch] = useState('')
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })

  const fetchStats = useCallback(async () => {
    try {
      const res = await getCacheStats()
      setStats(res.data)
    } catch { /* ignore */ }
  }, [])

  const fetchKeys = useCallback(async (page = 1, size = 20) => {
    setLoading(true)
    try {
      const res = await getCacheList({ region, search: search || undefined, page, pageSize: size })
      setKeys(res.data.keys || [])
      setPagination(prev => ({ ...prev, current: page, pageSize: size, total: res.data.total }))
    } catch { /* ignore */ }
    setLoading(false)
  }, [region, search])

  useEffect(() => {
    if (open) {
      fetchStats()
      fetchKeys(1)
    }
  }, [open, region])

  const handleSearch = () => fetchKeys(1)

  const handleDeleteKey = async (key) => {
    try {
      await deleteCacheKey(key, region)
      message.success('已删除')
      fetchStats()
      fetchKeys(pagination.current)
    } catch {
      message.error('删除失败')
    }
  }

  const handleClearRegion = async (r) => {
    try {
      const res = await clearCache(r)
      message.success(`已清除 ${res.data.cleared} 条缓存`)
      fetchStats()
      fetchKeys(1)
    } catch {
      message.error('清除失败')
    }
  }

  const handleClearAll = async () => {
    try {
      const res = await clearCache(undefined)
      message.success(`已清除全部 ${res.data.cleared} 条缓存`)
      fetchStats()
      fetchKeys(1)
    } catch {
      message.error('清除失败')
    }
  }

  const columns = [
    {
      title: 'Key',
      dataIndex: 'key',
      ellipsis: true,
    },
    {
      title: '操作',
      width: 80,
      render: (_, record) => (
        <Popconfirm title="确认删除？" onConfirm={() => handleDeleteKey(record.key)} okText="确定" cancelText="取消">
          <Button type="link" danger size="small" icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  const tableData = keys.map(k => ({ key: k }))
  const regionOptions = Object.keys(stats.regions || {}).length > 0
    ? Object.entries(stats.regions).map(([r, count]) => ({ label: `${r} (${count})`, value: r }))
    : [{ label: 'search', value: 'search' }, { label: 'metadata', value: 'metadata' }, { label: 'episodes', value: 'episodes' }, { label: 'comments', value: 'comments' }, { label: 'default', value: 'default' }]

  return (
    <Modal
      title={<><DatabaseOutlined /> 缓存管理</>}
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnClose
    >
      {/* 统计卡片 */}
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="总计" value={stats.total} /></Card>
        </Col>
        {Object.entries(stats.regions || {}).map(([r, count]) => (
          <Col span={6} key={r}>
            <Card size="small">
              <Statistic title={<Tag color={REGION_COLORS[r] || 'default'}>{r}</Tag>} value={count} />
            </Card>
          </Col>
        ))}
      </Row>

      {/* 工具栏 */}
      <Space style={{ marginBottom: 12 }} wrap>
        <Select value={region} onChange={v => { setRegion(v); setSearch('') }} options={regionOptions} style={{ width: 180 }} />
        <Input placeholder="搜索 key" value={search} onChange={e => setSearch(e.target.value)} onPressEnter={handleSearch} prefix={<SearchOutlined />} style={{ width: 200 }} allowClear />
        <Button icon={<SearchOutlined />} onClick={handleSearch}>搜索</Button>
        <Button icon={<ReloadOutlined />} onClick={() => { fetchStats(); fetchKeys(1) }}>刷新</Button>
        <Popconfirm title={`清除 ${region} 区域全部缓存？`} onConfirm={() => handleClearRegion(region)} okText="确定" cancelText="取消">
          <Button icon={<ClearOutlined />} danger>清除当前区域</Button>
        </Popconfirm>
        <Popconfirm title="清除所有区域的全部缓存？" onConfirm={handleClearAll} okText="确定" cancelText="取消">
          <Button danger type="primary" icon={<ClearOutlined />}>清除全部</Button>
        </Popconfirm>
      </Space>

      {/* 缓存列表 */}
      <Table
        columns={columns}
        dataSource={tableData}
        loading={loading}
        size="small"
        pagination={{
          ...pagination,
          showSizeChanger: true,
          showTotal: t => `共 ${t} 条`,
          onChange: (page, size) => fetchKeys(page, size),
        }}
      />
    </Modal>
  )
}
