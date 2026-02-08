import { useState, useEffect, useCallback, useMemo } from 'react'
import { List, Button, Tag, Space, Card, Checkbox, Empty, Tooltip, Input, Modal } from 'antd'
import { DeleteOutlined, CheckOutlined, MinusOutlined, PlayCircleOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getWebhookTasks, deleteWebhookTasks, runWebhookTasksNow, clearAllWebhookTasks } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { useModal } from '../../../ModalContext'

const getStatusTagType = status => {
  if (status === 'pending') return 'processing'
  if (status === 'submitted') return 'success'
  if (status === 'failed') return 'error'
  return 'default'
}

const translateStatus = status => {
  const statusMap = {
    pending: '待处理',
    submitted: '已提交',
    processing: '处理中',
    failed: '失败',
  }
  return statusMap[status] || status
}

export const WebhookTasks = () => {
  const [loading, setLoading] = useState(true)
  const [taskList, setTaskList] = useState([])
  const [selectedTasks, setSelectedTasks] = useState([])
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })
  const [searchTerm, setSearchTerm] = useState('')
  const [searchModalVisible, setSearchModalVisible] = useState(false)
  const [tempSearchTerm, setTempSearchTerm] = useState('')
  const messageApi = useMessage()
  const modalApi = useModal()

  const fetchTasks = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await getWebhookTasks({
        search: searchTerm,
        page: pagination.current,
        pageSize: pagination.pageSize,
      })
      setTaskList(data.list || [])
      setPagination(prev => ({ ...prev, total: data.total || 0 }))
    } catch (error) {
      messageApi.error('获取 Webhook 任务列表失败')
    } finally {
      setLoading(false)
    }
  }, [messageApi, pagination.current, pagination.pageSize, searchTerm])

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const handleSelectionChange = (task, checked) => {
    setSelectedTasks(prev =>
      checked ? [...prev, task] : prev.filter(t => t.id !== task.id)
    )
  }

  const handleSelectAll = () => {
    if (selectedTasks.length === taskList.length) {
      setSelectedTasks([])
    } else {
      setSelectedTasks(taskList)
    }
  }

  const handleBulkDelete = () => {
    modalApi.confirm({
      title: '批量删除任务',
      content: `确定要删除选中的 ${selectedTasks.length} 个任务吗？`,
      onOk: async () => {
        try {
          const ids = selectedTasks.map(task => task.id)
          await deleteWebhookTasks({ ids })
          messageApi.success('批量删除成功')
          setSelectedTasks([])
          fetchTasks()
        } catch (error) {
          messageApi.error('批量删除失败')
        }
      },
    })
  }

  const handleRunNow = () => {
    modalApi.confirm({
      title: '立即执行任务',
      content: `确定要立即执行选中的 ${selectedTasks.length} 个待处理任务吗？`,
      onOk: async () => {
        try {
          const ids = selectedTasks.map(task => task.id)
          await runWebhookTasksNow({ ids })
          messageApi.success('任务已提交执行')
          setSelectedTasks([])
          // 刷新列表以更新状态
          fetchTasks()
        } catch (error) {
          messageApi.error('提交执行失败')
        }
      },
    })
  }

  const handleClearAll = () => {
    modalApi.confirm({
      title: '清空所有任务',
      content: `确定要清空所有 ${pagination.total} 个待处理任务吗？此操作不可撤销！`,
      okType: 'danger',
      onOk: async () => {
        try {
          const { data } = await clearAllWebhookTasks()
          messageApi.success(data.message || '清空成功')
          setSelectedTasks([])
          fetchTasks()
        } catch (error) {
          messageApi.error('清空失败')
        }
      },
    })
  }

  const selectedTaskIds = useMemo(() => new Set(selectedTasks.map(t => t.id)), [
    selectedTasks,
  ])

  return (
    <div className="my-6">
      <Card
        loading={loading}
        title="Webhook 任务列表"
        extra={
          <Space>
            <Tooltip title="全选/取消全选">
              <Button
                type="default"
                shape="circle"
                icon={
                  selectedTasks.length === taskList.length &&
                  !!selectedTasks.length ? (
                    <CheckOutlined />
                  ) : (
                    <MinusOutlined />
                  )
                }
                onClick={handleSelectAll}
              />
            </Tooltip>
            <Tooltip title="立即执行选中任务">
              <Button
                type="primary"
                shape="circle"
                icon={<PlayCircleOutlined />}
                disabled={selectedTasks.length === 0}
                onClick={handleRunNow}
              />
            </Tooltip>
            <Tooltip title="批量删除">
              <Button
                danger
                type="primary"
                shape="circle"
                icon={<DeleteOutlined />}
                disabled={selectedTasks.length === 0}
                onClick={handleBulkDelete}
              />
            </Tooltip>
            <Tooltip title="清空所有任务">
              <Button
                danger
                type="primary"
                shape="circle"
                icon={<ClearOutlined />}
                disabled={pagination.total === 0}
                onClick={handleClearAll}
              />
            </Tooltip>
            <Tooltip title="搜索任务">
              <Button
                type="default"
                shape="circle"
                icon={<SearchOutlined />}
                onClick={() => {
                  setTempSearchTerm(searchTerm)
                  setSearchModalVisible(true)
                }}
              />
            </Tooltip>
          </Space>
        }
      >
        <div>
          {taskList.length > 0 ? (
            <List
              itemLayout="vertical"
              size="small"
              dataSource={taskList}
              pagination={{
                ...pagination,
                align: 'center',
                showSizeChanger: true,
                pageSizeOptions: ['20', '50', '100'],
                onChange: (page, pageSize) => {
                  setPagination(prev => ({ ...prev, current: page, pageSize }))
                },
              }}
              renderItem={item => {
                const isSelected = selectedTaskIds.has(item.id)
                return (
                  <List.Item
                    key={item.id}
                    onClick={() => handleSelectionChange(item, !isSelected)}
                    className="!cursor-pointer hover:!bg-gray-100"
                    extra={
                      <Tag color={getStatusTagType(item.status)}>
                        {translateStatus(item.status)}
                      </Tag>
                    }
                  >
                    <div className="relative pl-8">
                      <Checkbox
                        checked={isSelected}
                        className="absolute top-1/2 left-0 transform -translate-y-1/2"
                      />
                      <div className="text-base mb-1">{item.taskTitle}</div>
                      <div className="text-gray-500 text-sm">
                        <span>来源: {item.webhookSource}</span>
                        <span className="mx-2">|</span>
                        <span>
                          接收于: {dayjs(item.receptionTime).format('YYYY-MM-DD HH:mm:ss')}
                        </span>
                        <span className="mx-2">|</span>
                        <span>
                          计划于: {dayjs(item.executeTime).format('YYYY-MM-DD HH:mm:ss')}
                        </span>
                      </div>
                    </div>
                  </List.Item>
                )
              }}
            />
          ) : (
            <Empty description="没有待处理的 Webhook 任务" />
          )}
        </div>
      </Card>

      {/* 搜索模态框 */}
      <Modal
        title="搜索任务"
        open={searchModalVisible}
        onCancel={() => setSearchModalVisible(false)}
        onOk={() => {
          setSearchTerm(tempSearchTerm)
          setPagination(prev => ({ ...prev, current: 1 }))
          setSearchModalVisible(false)
        }}
        okText="搜索"
        cancelText="取消"
      >
        <div className="py-4">
          <Input
            placeholder="请输入任务标题关键词"
            value={tempSearchTerm}
            onChange={(e) => setTempSearchTerm(e.target.value)}
            onPressEnter={() => {
              setSearchTerm(tempSearchTerm)
              setPagination(prev => ({ ...prev, current: 1 }))
              setSearchModalVisible(false)
            }}
            allowClear
            autoFocus
          />
          {searchTerm && (
            <div className="mt-2 text-sm text-gray-500">
              当前搜索: "{searchTerm}"
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}