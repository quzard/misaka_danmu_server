import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  deleteTask,
  getTaskList,
  pauseTask,
  resumeTask,
  stopTask,
} from '@/apis'
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  List,
  message,
  Modal,
  Progress,
  Space,
  Tag,
  Tooltip,
  Dropdown,
} from 'antd'
import {
  CheckOutlined,
  DeleteOutlined,
  MinusOutlined,
  PauseOutlined,
  StepBackwardOutlined,
  StopOutlined,
  FilterOutlined,
  DownloadOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import classNames from 'classnames'
import { useModal } from '../../../ModalContext'
import { useMessage } from '../../../MessageContext'
import { useAtom } from 'jotai'
import { isMobileAtom } from '../../../../store'
// 移除useScroll导入，改用分页模式

export const ImportTask = () => {
  const [loading, setLoading] = useState(true)
  const [taskList, setTaskList] = useState([])
  const [selectList, setSelectList] = useState([])
  const timer = useRef()

  const [isMobile] = useAtom(isMobileAtom)

  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 100,
    total: 0,
  })

  const navigate = useNavigate()
  const modalApi = useModal()
  const messageApi = useMessage()

  const [canPause, isPause] = useMemo(() => {
    return [
      (selectList.every(item => item.status === '运行中') &&
        selectList.length > 0) ||
        (selectList.every(item => item.status === '已暂停') &&
          selectList.length > 0),
      selectList.every(item => item.status === '已暂停'),
    ]
  }, [selectList])

  const canStop = useMemo(() => {
    return selectList.some(item =>
      item.status === '运行中' || item.status === '已暂停'
    ) && selectList.length > 0
  }, [selectList])

  const canDelete = useMemo(() => {
    return (
      selectList.every(
        item =>
          item.status === '已完成' ||
          item.status === '失败' ||
          item.status === '排队中'
      ) && selectList.length > 0
    )
  }, [selectList])

  const [searchParams] = useSearchParams()
  const [queueFilter, setQueueFilter] = useState('all') // 队列类型过滤: all, download, management

  const [search, status] = useMemo(() => {
    return [
      searchParams.get('search') ?? '',
      searchParams.get('status') ?? 'in_progress',
    ]
  }, [searchParams])

  useEffect(() => {
    setPagination(n => ({
      ...n,
      pageSize: 100,
      current: 1,
    }))
  }, [search, status, queueFilter])



  /**
   * 轮询刷新当前页面任务列表
   */
  const pollTasks = useCallback(async () => {
    try {
      const res = await getTaskList({
        search,
        status,
        page: pagination.current,
        pageSize: pagination.pageSize,
      })

      let newData = res.data?.list || []

      // 前端过滤队列类型
      if (queueFilter !== 'all') {
        newData = newData.filter(task => task.queueType === queueFilter)
      }

      setTaskList(newData)


    } catch (error) {
      console.error('轮询获取数据失败:', error)
    }
  }, [search, status, pagination.current, pagination.pageSize, queueFilter])

  /**
   * 刷新任务列表
   */
  const refreshTasks = useCallback(async () => {
    try {
      setLoading(true)

      const res = await getTaskList({
        search,
        status,
        page: pagination.current,
        pageSize: pagination.pageSize,
      })

      const newData = res.data?.list || []
      setTaskList(newData)


      setLoading(false)
      setPagination(prev => ({
        ...prev,
        total: res.data?.total || 0,
      }))
    } catch (error) {
      console.error(error)
      setLoading(false)
    }
  }, [search, status, pagination.current, pagination.pageSize])

  /**
   * 处理暂停/恢复任务操作
   */
  const handlePause = async () => {
    if (isPause) {
      try {
        await Promise.all(
          selectList.map(it => resumeTask({ taskId: it.taskId }))
        )
        refreshTasks()
        setSelectList([])
      } catch (error) {
        message.error(`操作失败: ${error.message}`)
      }
    } else {
      try {
        await Promise.all(
          selectList.map(it => pauseTask({ taskId: it.taskId }))
        )
        refreshTasks()
        setSelectList([])
      } catch (error) {
        message.error(`操作失败: ${error.message}`)
      }
    }
  }

  /**
   * 处理中止任务操作
   */
  const handleStop = () => {
    console.log('handleStop clicked', selectList)

    let forceStop = false

    const StopConfirmContent = () => {
      const [force, setForce] = useState(false)

      useEffect(() => {
        forceStop = force
      }, [force])

      return (
        <div>
          <div>您确定要中止任务吗？</div>
          <div className="max-h-[310px] overflow-y-auto mt-3">
            {selectList.map((it, i) => (
              <div key={it.taskId}>
                {i + 1}、{it.title}
              </div>
            ))}
          </div>

          <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded">
            <label className="flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="mr-2"
              />
              <span className="text-sm">
                强制中止
                <span className="text-gray-500 ml-1">
                  (直接标记为失败状态，适用于卡住的任务)
                </span>
              </span>
            </label>
            {force && (
              <div className="mt-2 text-xs text-orange-600">
                ⚠️ 强制中止将直接标记任务为失败状态
              </div>
            )}
          </div>
        </div>
      )
    }

    modalApi.confirm({
      title: '中止任务',
      content: <StopConfirmContent />,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await Promise.all(
            selectList.map(it => stopTask({ taskId: it.taskId, force: forceStop }))
          )
          refreshTasks()
          setSelectList([])
          messageApi.success(forceStop ? '强制中止成功' : '中止成功')
        } catch (error) {
          messageApi.error(`中止任务失败: ${error.message}`)
          throw error
        }
      },
    })
  }

  /**
   * 处理删除任务操作
   */
  const handleDelete = () => {
    console.log('handleDelete clicked', selectList)

    const hasStuckTasks = selectList.some(task =>
      task.status === '运行中' || task.status === '已暂停'
    )

    let forceDelete = false

    const DeleteConfirmContent = () => {
      const [force, setForce] = useState(false)

      useEffect(() => {
        forceDelete = force
      }, [force])

      return (
        <div>
          <div>您确定要从历史记录中删除任务吗？</div>
          <div className="max-h-[310px] overflow-y-auto mt-3">
            {selectList.map((it, i) => (
              <div key={it.taskId}>
                {i + 1}、{it.title}
                {(it.status === '运行中' || it.status === '已暂停') && (
                  <span className="text-orange-500 ml-2">({it.status})</span>
                )}
              </div>
            ))}
          </div>

          <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded">
            <label className="flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
                className="mr-2"
              />
              <span className="text-sm">
                强制删除
                <span className="text-gray-500 ml-1">
                  (跳过中止逻辑，直接删除历史记录，适用于卡住的任务)
                </span>
              </span>
            </label>
            {force && (
              <div className="mt-2 text-xs text-orange-600">
                ⚠️ 强制删除将绕过正常的任务中止流程
              </div>
            )}
          </div>

          {hasStuckTasks && !force && (
            <div className="mt-3 p-2 bg-yellow-50 border border-yellow-200 rounded">
              <div className="text-sm text-yellow-700">
                💡 检测到运行中或暂停的任务，必须勾选"强制删除"才能删除
              </div>
            </div>
          )}
        </div>
      )
    }

    modalApi.confirm({
      title: '删除任务',
      content: <DeleteConfirmContent />,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          // 如果有卡住的任务但没有勾选强制删除，阻止执行
          if (hasStuckTasks && !forceDelete) {
            messageApi.warning('检测到运行中或暂停的任务，请勾选"强制删除"选项')
            return Promise.reject(new Error('需要强制删除'))
          }

          await Promise.all(
            selectList.map(it => deleteTask({ taskId: it.taskId, force: forceDelete }))
          )
          refreshTasks()
          setSelectList([])
          messageApi.success(forceDelete ? '强制删除成功' : '删除成功')
        } catch (error) {
          messageApi.error(`删除任务失败: ${error.message}`)
          throw error
        }
      },
    })
  }

  useEffect(() => {
    const isLoadMore = pagination.current > 1
    refreshTasks(isLoadMore)
    if (!isLoadMore) {
      setSelectList([])
    }
  }, [search, status, pagination.current, pagination.pageSize])

  useEffect(() => {
    // 清除之前的定时器
    clearInterval(timer.current)

    // 启动轮询定时器，每3秒刷新当前页面任务列表
    timer.current = setInterval(() => {
      pollTasks()
    }, 3000)

    return () => {
      clearInterval(timer.current)
    }
  }, [pollTasks])

  // 状态筛选菜单
  const statusMenu = {
    items: [
      { key: 'in_progress', label: '进行中' },
      { key: 'completed', label: '已完成' },
      { key: 'all', label: '全部' },
    ],
    onClick: ({ key }) => {
      navigate(`/task?search=${search}&status=${key}`, {
        replace: true,
      })
    },
  }

  const getStatusLabel = (status) => {
    switch (status) {
      case 'in_progress': return '进行中'
      case 'completed': return '已完成'
      case 'all': return '全部'
      default: return '进行中'
    }
  }

  // 队列类型筛选菜单
  const queueMenu = {
    items: [
      { key: 'all', label: '全部队列' },
      { key: 'download', label: '下载队列' },
      { key: 'management', label: '管理队列' },
    ],
    onClick: ({ key }) => {
      setQueueFilter(key)
    },
  }

  const getQueueLabel = (queue) => {
    switch (queue) {
      case 'all': return '全部队列'
      case 'download': return '下载队列'
      case 'management': return '管理队列'
      default: return '全部队列'
    }
  }

  // 获取队列类型图标
  const getQueueIcon = (queueType) => {
    return queueType === 'management' ? <SettingOutlined /> : <DownloadOutlined />
  }

  return (
    <div className="my-6">
      <Card
        loading={loading}
        title="任务管理器"
        extra={
          <div className='flex items-center justify-end gap-2 flex-wrap' style={{ maxWidth: '100%' }}>
            <Dropdown menu={statusMenu}>
              <Button icon={<FilterOutlined />} size="small">
                {getStatusLabel(status)}
              </Button>
            </Dropdown>
            <Dropdown menu={queueMenu}>
              <Button icon={<FilterOutlined />} size="small">
                {getQueueLabel(queueFilter)}
              </Button>
            </Dropdown>
            <Tooltip title="全选/取消全选">
              <Button
                type="default"
                shape="circle"
                size="small"
                icon={
                  selectList.length === taskList.length &&
                  !!selectList.length ? (
                    <CheckOutlined />
                  ) : (
                    <MinusOutlined />
                  )
                }
                onClick={() => {
                  if (
                    selectList.length === taskList.length &&
                    !!selectList.length
                  ) {
                    setSelectList([])
                  } else {
                    setSelectList(taskList)
                  }
                }}
              />
            </Tooltip>
            <Tooltip title="启用/暂停任务">
              <Button
                disabled={!canPause}
                type="default"
                shape="circle"
                size="small"
                icon={isPause ? <PauseOutlined /> : <StepBackwardOutlined />}
                onClick={handlePause}
              />
            </Tooltip>
            <Tooltip title="删除任务">
              <Button
                disabled={!canDelete}
                type="default"
                shape="circle"
                size="small"
                icon={<DeleteOutlined />}
                onClick={handleDelete}
              />
            </Tooltip>
            <Tooltip title="中止任务">
              <Button
                disabled={!canStop}
                type="default"
                shape="circle"
                size="small"
                icon={<StopOutlined />}
                onClick={handleStop}
              />
            </Tooltip>
            <Input.Search
              placeholder="按任务标题搜索"
              allowClear
              enterButton
              size="small"
              style={{ width: isMobile ? '100%' : '200px' }}
              onSearch={value => {
                navigate(`/task?search=${value}&status=${status}`, {
                  replace: true,
                })
              }}
            />
          </div>
        }
      >
        <div>
          {!!taskList?.length ? (
            <List
              itemLayout="vertical"
              size="small"
              dataSource={taskList}
              pagination={{
                ...pagination,
                showLessItems: true,
                align: 'center',
                onChange: (page, pageSize) => {
                  setPagination(n => {
                    return {
                      ...n,
                      current: page,
                      pageSize,
                    }
                  })
                },
                onShowSizeChange: (_, size) => {
                  setPagination(n => {
                    return {
                      ...n,
                      pageSize: size,
                    }
                  })
                },
                hideOnSinglePage: true,
              }}
              renderItem={(item, index) => {
                const isActive = selectList.some(
                  it => it.taskId === item.taskId
                )

                return (
                  <List.Item
                    key={index}
                    onClick={() => {
                      setSelectList(list => {
                        return list.map(it => it.taskId).includes(item.taskId)
                          ? list.filter(i => i.taskId !== item.taskId)
                          : [...list, item]
                      })
                    }}
                    style={{ padding: '16px 24px' }}
                  >
                    <div
                      className={classNames('relative w-full', {
                        'pl-9': isActive,
                      })}
                    >
                      {isActive && (
                        <Checkbox
                          checked={isActive}
                          className="absolute top-1/2 left-0 transform -translate-y-1/2"
                        />
                      )}

                      <div className="text-base mb-2 font-semibold">
                        <span style={{ marginRight: '8px', fontSize: '18px' }}>
                          {getQueueIcon(item.queueType)}
                        </span>
                        {item.title}
                      </div>
                      <div className="mb-3 text-gray-600">{item.description}</div>
                      <Progress
                        percent={item.progress}
                        status={item.status.includes('失败') && 'exception'}
                        strokeWidth={10}
                        showInfo={true}
                      />
                      <div style={{ marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <Tag
                          color={
                            item.status.includes('失败')
                              ? 'red'
                              : item.status.includes('运行中')
                                ? 'green'
                                : item.status.includes('已暂停')
                                  ? 'orange'
                                  : item.status.includes('已完成')
                                    ? 'blue'
                                    : 'default'
                          }
                        >
                          {item.status}
                        </Tag>
                        <Tag
                          color={item.queueType === 'management' ? 'cyan' : 'geekblue'}
                        >
                          <span style={{ marginRight: '4px' }}>
                            {getQueueIcon(item.queueType)}
                          </span>
                          {item.queueType === 'management' ? '管理队列' : '下载队列'}
                        </Tag>
                      </div>
                    </div>
                  </List.Item>
                )
              }}
            />
          ) : (
            <Empty description="没有符合条件的任务" />
          )}
        </div>
      </Card>
    </div>
  )
}
