import React, { useEffect, useState, useCallback } from 'react'
import { Modal, Drawer, Input, Switch, Button, Checkbox, Collapse, Tag, Spin, Empty, Space, message, Alert, Dropdown, Pagination, Popover, Popconfirm } from 'antd'
import { SyncOutlined, ClockCircleOutlined, WarningOutlined, CheckCircleOutlined, CloseCircleOutlined, DownOutlined, SearchOutlined, DeleteOutlined } from '@ant-design/icons'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../store/index.js'
import {
  getIncrementalRefreshSources,
  getIncrementalRefreshTaskStatus,
  batchToggleIncrementalRefresh,
  batchSetFavorite,
  batchUnsetFavorite,
  toggleSourceIncremental,
  toggleSourceFavorite,
  deleteAnimeSource,
} from '../apis'
import dayjs from 'dayjs'

/**
 * 追更与标记管理弹窗组件
 */
export const IncrementalRefreshModal = ({ open, onCancel, onSuccess }) => {
  const isMobile = useAtomValue(isMobileAtom)
  const [loading, setLoading] = useState(false)
  const [taskStatus, setTaskStatus] = useState(null)
  const [animeGroups, setAnimeGroups] = useState([])
  const [searchKeyword, setSearchKeyword] = useState('')
  const [selectedSourceIds, setSelectedSourceIds] = useState([])
  const [operationLoading, setOperationLoading] = useState(false)

  // 分页和过滤状态
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [favoriteFilter, setFavoriteFilter] = useState('all')
  const [refreshFilter, setRefreshFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [stats, setStats] = useState({ total: 0, totalSources: 0, refreshEnabled: 0, favorited: 0, maxFailures: 10 })

  // 加载数据
  const fetchData = useCallback(async (params = {}) => {
    setLoading(true)
    try {
      const [sourcesRes, statusRes] = await Promise.all([
        getIncrementalRefreshSources({
          page: params.page ?? page,
          pageSize: params.pageSize ?? pageSize,
          keyword: params.keyword ?? searchKeyword,
          favoriteFilter: params.favoriteFilter ?? favoriteFilter,
          refreshFilter: params.refreshFilter ?? refreshFilter,
          typeFilter: params.typeFilter ?? typeFilter,
        }),
        getIncrementalRefreshTaskStatus(),
      ])
      const data = sourcesRes?.data || {}
      setAnimeGroups(data.list || [])
      setStats({
        total: data.total || 0,
        totalSources: data.totalSources || 0,
        refreshEnabled: data.refreshEnabled || 0,
        favorited: data.favorited || 0,
        maxFailures: data.maxFailures || 10,
      })
      setTaskStatus(statusRes?.data || null)
    } catch (error) {
      message.error('加载数据失败: ' + error.message)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, searchKeyword, favoriteFilter, refreshFilter, typeFilter])

  useEffect(() => {
    if (open) {
      setPage(1)
      setFavoriteFilter('all')
      setRefreshFilter('all')
      setTypeFilter('all')
      setSearchKeyword('')
      setSelectedSourceIds([])
      fetchData({ page: 1, keyword: '', favoriteFilter: 'all', refreshFilter: 'all', typeFilter: 'all' })
    }
  }, [open])

  // 搜索处理（防抖）
  const handleSearch = (value) => {
    setSearchKeyword(value)
    setPage(1)
    fetchData({ page: 1, keyword: value })
  }

  // 过滤器变更处理
  const handleFavoriteFilterChange = (filter) => {
    setFavoriteFilter(filter)
    setPage(1)
    fetchData({ page: 1, favoriteFilter: filter })
  }

  const handleRefreshFilterChange = (filter) => {
    setRefreshFilter(filter)
    setPage(1)
    fetchData({ page: 1, refreshFilter: filter })
  }

  const handleTypeFilterChange = (filter) => {
    setTypeFilter(filter)
    setPage(1)
    fetchData({ page: 1, typeFilter: filter })
  }

  // 分页变更
  const handlePageChange = (newPage) => {
    setPage(newPage)
    fetchData({ page: newPage })
  }

  // 每页数量变更
  const handlePageSizeChange = (newSize) => {
    setPageSize(newSize)
    setPage(1)
    fetchData({ page: 1, pageSize: newSize })
  }

  // 切换单个源的追更状态（本地乐观更新）
  const handleToggleRefresh = async (sourceId) => {
    // 找到源所属的番剧
    const group = animeGroups.find(g => g.sources.some(s => s.sourceId === sourceId))
    if (!group) return

    const source = group.sources.find(s => s.sourceId === sourceId)
    const newState = !source.incrementalRefreshEnabled

    // 乐观更新本地状态
    setAnimeGroups(prev => prev.map(g => {
      if (g.animeId !== group.animeId) return g
      return {
        ...g,
        sources: g.sources.map(s => {
          if (s.sourceId === sourceId) {
            return { ...s, incrementalRefreshEnabled: newState }
          }
          // 互斥：开启一个源时关闭同组其他源
          if (newState) {
            return { ...s, incrementalRefreshEnabled: false }
          }
          return s
        })
      }
    }))

    try {
      await toggleSourceIncremental({ sourceId })
    } catch (error) {
      message.error('操作失败: ' + error.message)
      fetchData() // 失败时重新获取数据恢复状态
    }
  }

  // 切换单个源的标记状态（本地乐观更新）
  const handleToggleFavorite = async (sourceId) => {
    // 找到源所属的番剧
    const group = animeGroups.find(g => g.sources.some(s => s.sourceId === sourceId))
    if (!group) return

    const source = group.sources.find(s => s.sourceId === sourceId)
    const newState = !source.isFavorited

    // 乐观更新本地状态
    setAnimeGroups(prev => prev.map(g => {
      if (g.animeId !== group.animeId) return g
      return {
        ...g,
        sources: g.sources.map(s => {
          if (s.sourceId === sourceId) {
            return { ...s, isFavorited: newState }
          }
          // 互斥：开启一个源时关闭同组其他源
          if (newState) {
            return { ...s, isFavorited: false }
          }
          return s
        })
      }
    }))

    try {
      await toggleSourceFavorite({ sourceId })
    } catch (error) {
      message.error('操作失败: ' + error.message)
      fetchData() // 失败时重新获取数据恢复状态
    }
  }

  // 批量开启追更
  const handleBatchEnableRefresh = async () => {
    if (selectedSourceIds.length === 0) {
      message.warning('请先选择源')
      return
    }
    setOperationLoading(true)
    try {
      await batchToggleIncrementalRefresh({ sourceIds: selectedSourceIds, enabled: true })
      message.success('批量开启成功')
      setSelectedSourceIds([])
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    } finally {
      setOperationLoading(false)
    }
  }

  // 批量关闭追更
  const handleBatchDisableRefresh = async () => {
    if (selectedSourceIds.length === 0) {
      message.warning('请先选择源')
      return
    }
    setOperationLoading(true)
    try {
      await batchToggleIncrementalRefresh({ sourceIds: selectedSourceIds, enabled: false })
      message.success('批量关闭成功')
      setSelectedSourceIds([])
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    } finally {
      setOperationLoading(false)
    }
  }

  // 批量设置标记
  const handleBatchSetFavorite = async () => {
    if (selectedSourceIds.length === 0) {
      message.warning('请先选择源')
      return
    }
    setOperationLoading(true)
    try {
      await batchSetFavorite({ sourceIds: selectedSourceIds })
      message.success('批量标记成功')
      setSelectedSourceIds([])
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    } finally {
      setOperationLoading(false)
    }
  }

  // 批量取消标记
  const handleBatchUnsetFavorite = async () => {
    if (selectedSourceIds.length === 0) {
      message.warning('请先选择源')
      return
    }
    setOperationLoading(true)
    try {
      await batchUnsetFavorite({ sourceIds: selectedSourceIds })
      message.success('批量取消标记成功')
      setSelectedSourceIds([])
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    } finally {
      setOperationLoading(false)
    }
  }

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedSourceIds.length === 0) {
      message.warning('请先选择源')
      return
    }
    setOperationLoading(true)
    try {
      await deleteAnimeSource({ sourceIds: selectedSourceIds, deleteFiles: true })
      message.success(`批量删除任务已提交，共 ${selectedSourceIds.length} 个源`)
      setSelectedSourceIds([])
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    } finally {
      setOperationLoading(false)
    }
  }

  // 全选当前页
  const handleSelectAll = () => {
    const allSourceIds = animeGroups.flatMap(g => g.sources.map(s => s.sourceId))
    setSelectedSourceIds(allSourceIds)
  }

  // 取消全选
  const handleDeselectAll = () => {
    setSelectedSourceIds([])
  }

  // 选择框变化
  const handleCheckboxChange = (sourceId, checked) => {
    setSelectedSourceIds(prev =>
      checked ? [...prev, sourceId] : prev.filter(id => id !== sourceId)
    )
  }

  // 渲染定时任务状态
  const renderTaskStatus = () => {
    if (!taskStatus) return null

    if (!taskStatus.exists) {
      return (
        <Alert
          type="warning"
          icon={<WarningOutlined />}
          message="增量追更定时任务未配置"
          description="请在设置中配置增量追更定时任务，否则追更功能不会自动执行。"
          showIcon
          style={{ marginBottom: 24 }}
        />
      )
    }

    return (
      <Alert
        type={taskStatus.enabled ? 'success' : 'warning'}
        icon={taskStatus.enabled ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
        message={
          <span>
            增量追更定时任务：{taskStatus.enabled ? '已启用' : '已禁用'}
            {taskStatus.cronExpression && (
              <Tag className="ml-4">{taskStatus.cronExpression}</Tag>
            )}
          </span>
        }
        description={
          taskStatus.nextRunTime && taskStatus.enabled
            ? `下次执行：${dayjs(taskStatus.nextRunTime).format('YYYY-MM-DD HH:mm:ss')}`
            : null
        }
        showIcon
        style={{ marginBottom: 24 }}
      />
    )
  }

  // 渲染源列表项
  const renderSourceItem = (source, animeTitle) => (
    <div key={source.sourceId} className="source-item flex items-center gap-4 py-3 px-4 rounded-lg border-b border-gray-100 dark:border-gray-700 last:border-b-0 hover:bg-gray-100 dark:hover:bg-gray-700">
      <Checkbox
        checked={selectedSourceIds.includes(source.sourceId)}
        onChange={(e) => handleCheckboxChange(source.sourceId, e.target.checked)}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium">{source.providerName}</span>
          <Tag color="blue" size="small">当前 第{source.episodeCount}集</Tag>
          {source.incrementalRefreshEnabled && (
            <>
              <Tag color="green" size="small">追更中</Tag>
              <Tag color={source.incrementalRefreshFailures > 0 ? 'error' : 'default'} size="small">
                失败 {source.incrementalRefreshFailures}/{stats.maxFailures}
              </Tag>
            </>
          )}
          {source.isFavorited && (
            <Tag color="gold" size="small">★ 已标记</Tag>
          )}
        </div>
        {source.lastRefreshLatestEpisodeAt && (
          <div className="text-xs text-gray-400 mt-1">
            上次追更：{dayjs(source.lastRefreshLatestEpisodeAt).format('YYYY-MM-DD HH:mm')}
          </div>
        )}
      </div>
      <Space size="small">
        <Switch
          checkedChildren="追更"
          unCheckedChildren="追更"
          checked={source.incrementalRefreshEnabled}
          onChange={() => handleToggleRefresh(source.sourceId)}
        />
        <Switch
          checkedChildren="标记"
          unCheckedChildren="标记"
          checked={source.isFavorited}
          onChange={() => handleToggleFavorite(source.sourceId)}
        />
      </Space>
    </div>
  )

  // 渲染内容
  const renderContent = () => (
    <div className="flex flex-col h-full">
      {/* 定时任务状态 */}
      {renderTaskStatus()}

      {/* 统计信息和过滤器 */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-2">
          <Tag>共 {stats.totalSources} 个源</Tag>
          <Tag color="blue">追更中 {stats.refreshEnabled} 个</Tag>
          <Tag color="green">已标记 {stats.favorited} 个</Tag>
        </div>
        <Space size="small">
          <Dropdown
            menu={{
              items: [
                { key: 'all', label: '全部' },
                { key: 'movie', label: '电影' },
                { key: 'tv_series', label: '电视节目' },
              ],
              selectedKeys: [typeFilter],
              onClick: ({ key }) => handleTypeFilterChange(key),
            }}
            trigger={['click']}
          >
            <Button size="small">
              类型: {typeFilter === 'all' ? '全部' : typeFilter === 'movie' ? '电影' : '电视节目'} <DownOutlined />
            </Button>
          </Dropdown>
          <Dropdown
            menu={{
              items: [
                { key: 'all', label: '全部' },
                { key: 'enabled', label: '已追更' },
                { key: 'disabled', label: '未追更' },
              ],
              selectedKeys: [refreshFilter],
              onClick: ({ key }) => handleRefreshFilterChange(key),
            }}
            trigger={['click']}
          >
            <Button size="small">
              追更: {refreshFilter === 'all' ? '全部' : refreshFilter === 'enabled' ? '已追更' : '未追更'} <DownOutlined />
            </Button>
          </Dropdown>
          <Dropdown
            menu={{
              items: [
                { key: 'all', label: '全部' },
                { key: 'favorited', label: '已标记' },
                { key: 'unfavorited', label: '未标记' },
              ],
              selectedKeys: [favoriteFilter],
              onClick: ({ key }) => handleFavoriteFilterChange(key),
            }}
            trigger={['click']}
          >
            <Button size="small">
              标记: {favoriteFilter === 'all' ? '全部' : favoriteFilter === 'favorited' ? '已标记' : '未标记'} <DownOutlined />
            </Button>
          </Dropdown>
          {!isMobile && (
            <Popover
              content={
                <div style={{ width: 220 }}>
                  <Input
                    placeholder="搜索番剧或源名称..."
                    allowClear
                    value={searchKeyword}
                    onChange={(e) => setSearchKeyword(e.target.value)}
                    onPressEnter={(e) => handleSearch(e.target.value)}
                    autoFocus
                  />
                </div>
              }
              title="搜索"
              trigger="click"
              placement="bottom"
            >
              <Button size="small" icon={<SearchOutlined />}>
                {searchKeyword ? `搜索: ${searchKeyword.length > 4 ? searchKeyword.slice(0, 4) + '...' : searchKeyword}` : '搜索'}
              </Button>
            </Popover>
          )}
        </Space>
      </div>

      {/* 源列表 */}
      <div className="flex-1 overflow-auto" style={{ maxHeight: isMobile ? 'calc(100vh - 400px)' : 350 }}>
        {loading ? (
          <div className="flex justify-center py-8"><Spin /></div>
        ) : animeGroups.length === 0 ? (
          <Empty description="暂无数据" />
        ) : (
          <Collapse
            defaultActiveKey={animeGroups.slice(0, 3).map(g => g.animeId)}
            items={animeGroups.map(group => ({
              key: group.animeId,
              label: (
                <div className="flex items-center gap-2">
                  <Tag size="small" color={group.animeType === 'movie' ? 'purple' : 'blue'}>
                    {group.animeType === 'movie' ? '电影' : '电视节目'}
                  </Tag>
                  <span className="font-medium">{group.animeTitle}</span>
                  <Tag size="small">{group.sources.length} 个源</Tag>
                </div>
              ),
              children: group.sources.map(source => renderSourceItem(source, group.animeTitle)),
            }))}
          />
        )}
      </div>

      {/* 分页 */}
      {stats.total > pageSize && (
        <div className="mt-3 flex justify-center items-center gap-3">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={stats.total}
            onChange={handlePageChange}
            showSizeChanger={false}
            showQuickJumper={stats.total > pageSize * 3}
            size="small"
          />
          <Dropdown
            menu={{
              items: [
                { key: '10', label: '10 条/页' },
                { key: '20', label: '20 条/页' },
                { key: '50', label: '50 条/页' },
                { key: '100', label: '100 条/页' },
              ],
              selectedKeys: [String(pageSize)],
              onClick: ({ key }) => handlePageSizeChange(Number(key)),
            }}
            trigger={['click']}
          >
            <Button size="small">
              {pageSize} 条/页 <DownOutlined />
            </Button>
          </Dropdown>
        </div>
      )}

      {/* 批量操作按钮 */}
      <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-600">
        {/* 第一行：已选数量 + 搜索（移动端） */}
        <div className="flex items-center gap-2 mb-2">
          <span className="text-gray-500 text-sm">
            已选 <span className="font-medium text-blue-500">{selectedSourceIds.length}</span> 项
          </span>
          {isMobile && (
            <Popover
              content={
                <div style={{ width: 220 }}>
                  <Input
                    placeholder="搜索番剧或源名称..."
                    allowClear
                    value={searchKeyword}
                    onChange={(e) => setSearchKeyword(e.target.value)}
                    onPressEnter={(e) => handleSearch(e.target.value)}
                    autoFocus
                  />
                </div>
              }
              title="搜索"
              trigger="click"
              placement="top"
            >
              <Button size="small" icon={<SearchOutlined />} className="ml-auto">
                {searchKeyword ? `搜索: ${searchKeyword.length > 4 ? searchKeyword.slice(0, 4) + '...' : searchKeyword}` : '搜索'}
              </Button>
            </Popover>
          )}
        </div>
        {/* 移动端：分两行显示按钮 */}
        {isMobile ? (
          <div className="space-y-2">
            {/* 第一行：操作 + 批量删除 */}
            <div className="flex gap-2">
              <Dropdown
                menu={{
                  items: [
                    { key: 'selectAll', label: '全选当前页', onClick: handleSelectAll },
                    { key: 'deselectAll', label: '取消全选', onClick: handleDeselectAll },
                  ],
                }}
                trigger={['click']}
              >
                <Button size="small" className="flex-1">
                  操作 <DownOutlined />
                </Button>
              </Dropdown>
              <Popconfirm
                title={`确定要删除选中的 ${selectedSourceIds.length} 个源吗?`}
                description="此操作将删除源及其关联的弹幕文件"
                onConfirm={handleBatchDelete}
                okText="确定"
                cancelText="取消"
                disabled={selectedSourceIds.length === 0}
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  loading={operationLoading}
                  disabled={selectedSourceIds.length === 0}
                  className="flex-1"
                >
                  批量删除
                </Button>
              </Popconfirm>
            </div>
            {/* 第二行：批量追更 + 批量标记 */}
            <div className="flex gap-2">
              <Dropdown
                menu={{
                  items: [
                    { key: 'enable', label: '批量开启', onClick: handleBatchEnableRefresh, disabled: selectedSourceIds.length === 0 },
                    { key: 'disable', label: '批量关闭', onClick: handleBatchDisableRefresh, disabled: selectedSourceIds.length === 0 },
                  ],
                }}
                trigger={['click']}
                disabled={operationLoading}
              >
                <Button size="small" loading={operationLoading} className="flex-1">
                  批量追更 <DownOutlined />
                </Button>
              </Dropdown>
              <Dropdown
                menu={{
                  items: [
                    { key: 'set', label: '批量开启', onClick: handleBatchSetFavorite, disabled: selectedSourceIds.length === 0 },
                    { key: 'unset', label: '批量关闭', onClick: handleBatchUnsetFavorite, disabled: selectedSourceIds.length === 0 },
                  ],
                }}
                trigger={['click']}
                disabled={operationLoading}
              >
                <Button size="small" loading={operationLoading} className="flex-1">
                  批量标记 <DownOutlined />
                </Button>
              </Dropdown>
            </div>
          </div>
        ) : (
          /* 桌面端：一行显示所有按钮 */
          <Space size="small" wrap>
            <Dropdown
              menu={{
                items: [
                  { key: 'selectAll', label: '全选当前页', onClick: handleSelectAll },
                  { key: 'deselectAll', label: '取消全选', onClick: handleDeselectAll },
                ],
              }}
              trigger={['click']}
            >
              <Button size="small">
                操作 <DownOutlined />
              </Button>
            </Dropdown>
            <Dropdown
              menu={{
                items: [
                  { key: 'enable', label: '批量开启', onClick: handleBatchEnableRefresh, disabled: selectedSourceIds.length === 0 },
                  { key: 'disable', label: '批量关闭', onClick: handleBatchDisableRefresh, disabled: selectedSourceIds.length === 0 },
                ],
              }}
              trigger={['click']}
              disabled={operationLoading}
            >
              <Button size="small" loading={operationLoading}>
                批量追更 <DownOutlined />
              </Button>
            </Dropdown>
            <Dropdown
              menu={{
                items: [
                  { key: 'set', label: '批量开启', onClick: handleBatchSetFavorite, disabled: selectedSourceIds.length === 0 },
                  { key: 'unset', label: '批量关闭', onClick: handleBatchUnsetFavorite, disabled: selectedSourceIds.length === 0 },
                ],
              }}
              trigger={['click']}
              disabled={operationLoading}
            >
              <Button size="small" loading={operationLoading}>
                批量标记 <DownOutlined />
              </Button>
            </Dropdown>
            <Popconfirm
              title={`确定要删除选中的 ${selectedSourceIds.length} 个源吗?`}
              description="此操作将删除源及其关联的弹幕文件"
              onConfirm={handleBatchDelete}
              okText="确定"
              cancelText="取消"
              disabled={selectedSourceIds.length === 0}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={operationLoading}
                disabled={selectedSourceIds.length === 0}
              >
                批量删除
              </Button>
            </Popconfirm>
          </Space>
        )}
      </div>
    </div>
  )

  // 响应式渲染
  if (isMobile) {
    return (
      <Drawer
        title="批量管理"
        placement="bottom"
        onClose={onCancel}
        open={open}
        height="85vh"
      >
        {renderContent()}
      </Drawer>
    )
  }

  return (
    <Modal
      title="批量管理"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={700}
    >
      {renderContent()}
    </Modal>
  )
}
