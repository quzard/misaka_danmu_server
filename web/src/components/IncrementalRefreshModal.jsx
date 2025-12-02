import React, { useEffect, useState, useMemo } from 'react'
import { Modal, Drawer, Input, Switch, Radio, Button, Checkbox, Collapse, Tag, Spin, Empty, Space, message, Alert } from 'antd'
import { SyncOutlined, ClockCircleOutlined, WarningOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../store/index.js'
import {
  getIncrementalRefreshSources,
  getIncrementalRefreshTaskStatus,
  batchToggleIncrementalRefresh,
  batchSetFavorite,
  toggleSourceIncremental,
  toggleSourceFavorite,
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

  // 加载数据
  const fetchData = async () => {
    setLoading(true)
    try {
      const [sourcesRes, statusRes] = await Promise.all([
        getIncrementalRefreshSources(),
        getIncrementalRefreshTaskStatus(),
      ])
      setAnimeGroups(sourcesRes?.data || [])
      setTaskStatus(statusRes?.data || null)
    } catch (error) {
      message.error('加载数据失败: ' + error.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      fetchData()
      setSelectedSourceIds([])
      setSearchKeyword('')
    }
  }, [open])

  // 过滤后的数据
  const filteredGroups = useMemo(() => {
    if (!searchKeyword.trim()) return animeGroups
    const keyword = searchKeyword.toLowerCase()
    return animeGroups
      .map(group => ({
        ...group,
        sources: group.sources.filter(
          s => group.animeTitle.toLowerCase().includes(keyword) || s.providerName.toLowerCase().includes(keyword)
        ),
      }))
      .filter(group => group.sources.length > 0)
  }, [animeGroups, searchKeyword])

  // 统计信息
  const stats = useMemo(() => {
    const allSources = animeGroups.flatMap(g => g.sources)
    return {
      total: allSources.length,
      refreshEnabled: allSources.filter(s => s.incrementalRefreshEnabled).length,
      favorited: allSources.filter(s => s.isFavorited).length,
      failed: allSources.filter(s => s.incrementalRefreshFailures > 0).length,
    }
  }, [animeGroups])

  // 切换单个源的追更状态
  const handleToggleRefresh = async (sourceId) => {
    try {
      await toggleSourceIncremental({ sourceId })
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
    }
  }

  // 切换单个源的标记状态
  const handleToggleFavorite = async (sourceId) => {
    try {
      await toggleSourceFavorite({ sourceId })
      fetchData()
    } catch (error) {
      message.error('操作失败: ' + error.message)
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
          className="mb-4"
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
              <Tag className="ml-2">{taskStatus.cronExpression}</Tag>
            )}
          </span>
        }
        description={
          taskStatus.nextRunTime && taskStatus.enabled
            ? `下次执行：${dayjs(taskStatus.nextRunTime).format('YYYY-MM-DD HH:mm:ss')}`
            : null
        }
        showIcon
        className="mb-4"
      />
    )
  }

  // 渲染源列表项
  const renderSourceItem = (source, animeTitle) => (
    <div key={source.sourceId} className="flex items-center gap-4 py-3 px-4 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg border-b border-gray-100 dark:border-gray-700 last:border-b-0">
      <Checkbox
        checked={selectedSourceIds.includes(source.sourceId)}
        onChange={(e) => handleCheckboxChange(source.sourceId, e.target.checked)}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium">{source.providerName}</span>
          <Tag color="blue" size="small">追到 第{source.episodeCount}集</Tag>
          {source.incrementalRefreshEnabled && (
            <Tag color="green" size="small">追更中</Tag>
          )}
          {source.incrementalRefreshFailures > 0 && (
            <Tag color="error" size="small">失败 {source.incrementalRefreshFailures} 次</Tag>
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

      {/* 统计信息 */}
      <div className="mb-3 flex flex-wrap gap-2">
        <Tag>共 {stats.total} 个源</Tag>
        <Tag color="blue">追更中 {stats.refreshEnabled} 个</Tag>
        <Tag color="green">已标记 {stats.favorited} 个</Tag>
        {stats.failed > 0 && <Tag color="red">失败 {stats.failed} 个</Tag>}
      </div>

      {/* 搜索框 */}
      <Input.Search
        placeholder="搜索番剧或源名称..."
        value={searchKeyword}
        onChange={(e) => setSearchKeyword(e.target.value)}
        allowClear
        className="mb-3"
      />

      {/* 源列表 */}
      <div className="flex-1 overflow-auto" style={{ maxHeight: isMobile ? 'calc(100vh - 350px)' : 400 }}>
        {loading ? (
          <div className="flex justify-center py-8"><Spin /></div>
        ) : filteredGroups.length === 0 ? (
          <Empty description="暂无数据" />
        ) : (
          <Collapse
            defaultActiveKey={filteredGroups.slice(0, 3).map(g => g.animeId)}
            items={filteredGroups.map(group => ({
              key: group.animeId,
              label: (
                <div className="flex items-center gap-2">
                  <span className="font-medium">{group.animeTitle}</span>
                  <Tag size="small">{group.sources.length} 个源</Tag>
                </div>
              ),
              children: group.sources.map(source => renderSourceItem(source, group.animeTitle)),
            }))}
          />
        )}
      </div>

      {/* 批量操作按钮 */}
      <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-600 flex items-center flex-wrap gap-3">
        <span className="text-gray-500 text-sm">
          已选 <span className="font-medium text-blue-500">{selectedSourceIds.length}</span> 项：
        </span>
        <Space size="small" wrap>
          <Button onClick={handleBatchEnableRefresh} loading={operationLoading} disabled={selectedSourceIds.length === 0}>
            批量开启追更
          </Button>
          <Button onClick={handleBatchDisableRefresh} loading={operationLoading} disabled={selectedSourceIds.length === 0}>
            批量关闭追更
          </Button>
          <Button onClick={handleBatchSetFavorite} loading={operationLoading} disabled={selectedSourceIds.length === 0}>
            批量设为标记
          </Button>
        </Space>
      </div>
    </div>
  )

  // 响应式渲染
  if (isMobile) {
    return (
      <Drawer
        title="追更与标记管理"
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
      title="追更与标记管理"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={700}
    >
      {renderContent()}
    </Modal>
  )
}
