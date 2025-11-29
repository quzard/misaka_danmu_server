import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  batchManualImport,
  deleteAnimeEpisode,
  deleteAnimeEpisodeSingle,
  editEpisode,
  getAnimeDetail,
  getAnimeSource,
  getEpisodes,
  offsetEpisodes,
  manualImportEpisode,
  refreshEpisodeDanmaku,
  refreshEpisodesBulk,
  resetEpisode,
} from '../../apis'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Breadcrumb,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Space,
  Switch,
  Table,
  Tooltip,
  Upload,
  Tag,
  Typography,
} from 'antd'
import dayjs from 'dayjs'
import { MyIcon } from '@/components/MyIcon'
import {
  HomeOutlined,
  UploadOutlined,
  VerticalAlignMiddleOutlined,
} from '@ant-design/icons'
import { RoutePaths } from '../../general/RoutePaths'
import { useModal } from '../../ModalContext'
import { useMessage } from '../../MessageContext'
import { BatchImportModal } from '../../components/BatchImportModal'
import { isUrl } from '../../utils/data'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store'
import { ResponsiveTable } from '@/components/ResponsiveTable'

export const EpisodeDetail = () => {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const animeId = searchParams.get('animeId')
  const navigate = useNavigate()
  const isMobile = useAtomValue(isMobileAtom)
  const messageApi = useMessage()
  const modalApi = useModal()

  const [loading, setLoading] = useState(true)
  const [animeDetail, setAnimeDetail] = useState({})
  const [episodeList, setEpisodeList] = useState([])
  const [selectedRows, setSelectedRows] = useState([])
  const [sourceInfo, setSourceInfo] = useState({})
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 50,
    total: 0,
  })

  const [form] = Form.useForm()
  const [editOpen, setEditOpen] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [resetInfo, setResetInfo] = useState({})
  const [isBatchModalOpen, setIsBatchModalOpen] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const uploadRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [fileList, setFileList] = useState([])
  const [lastClickedIndex, setLastClickedIndex] = useState(null)

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSelectedRows([])
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const isXmlImport = useMemo(() => {
    return sourceInfo.providerName === 'custom'
  }, [sourceInfo])

  const getDetail = async () => {
    setLoading(true)
    try {
      // 如果 animeId 为 0 或无效，直接返回到库页面
      if (!animeId || Number(animeId) === 0) {
        messageApi.error('无效的作品ID')
        navigate('/library')
        return
      }

      const [detailRes, episodeRes, sourceRes] = await Promise.all([
        getAnimeDetail({
          animeId: Number(animeId),
        }),
        getEpisodes({
          sourceId: Number(id),
          page: pagination.current,
          pageSize: pagination.pageSize,
        }),
        getAnimeSource({
          animeId: Number(animeId),
        }),
      ])
      setAnimeDetail(detailRes.data)
      setEpisodeList(episodeRes.data?.list || [])
      setPagination(prev => ({
        ...prev,
        total: episodeRes.data?.total || 0,
      }))
      setSourceInfo({
        ...sourceRes?.data?.filter(it => it.sourceId === Number(id))?.[0],
        animeName: detailRes.data?.title,
      })
      setLoading(false)
    } catch (error) {
      messageApi.error('获取剧集详情失败')
      navigate(`/anime/${animeId}`)
    }
  }

  useEffect(() => {
    getDetail()
  }, [id, animeId, pagination.current, pagination.pageSize])

  const handleBatchImportSuccess = task => {
    setIsBatchModalOpen(false)
    // messageApi.success(
    //   `批量导入任务已提交 (ID: ${task.taskId})，请在任务中心查看进度。`
    // )
    goTask(task)
  }

  const columns = [
    {
      title: (
        <div className="flex items-center justify-center cursor-pointer" onClick={() => {
          if (selectedRows.length === episodeList.length && episodeList.length > 0) {
            setSelectedRows([])
          } else {
            setSelectedRows(episodeList)
          }
        }}>
          {selectedRows.length === episodeList.length && episodeList.length > 0 ? (
            <div className="w-4 h-4 bg-pink-400 rounded flex items-center justify-center">
              <span className="text-white text-xs">✓</span>
            </div>
          ) : (
            <div className="w-4 h-4 border border-gray-300 dark:border-gray-600 rounded"></div>
          )}
        </div>
      ),
      key: 'selection',
      width: 50,
      render: (_, record, index) => {
        const isSelected = selectedRows.some(row => row.episodeId === record.episodeId)
        return (
          <div
            className="cursor-pointer flex items-center justify-center"
            onClick={(e) => {
              const newSelected = [...selectedRows]
              if (e.shiftKey && lastClickedIndex !== null) {
                const start = Math.min(lastClickedIndex, index)
                const end = Math.max(lastClickedIndex, index)
                const range = episodeList.slice(start, end + 1)
                if (isSelected) {
                  // 如果当前已选，移除范围
                  setSelectedRows(selectedRows.filter(row => !range.some(r => r.episodeId === row.episodeId)))
                } else {
                  // 添加范围
                  const toAdd = range.filter(r => !selectedRows.some(s => s.episodeId === r.episodeId))
                  setSelectedRows([...selectedRows, ...toAdd])
                }
              } else {
                if (isSelected) {
                  setSelectedRows(selectedRows.filter(row => row.episodeId !== record.episodeId))
                } else {
                  setSelectedRows([...selectedRows, record])
                }
              }
              setLastClickedIndex(index)
            }}
          >
            {isSelected ? (
              <div className="w-4 h-4 bg-primary rounded flex items-center justify-center">
                <span className="text-white text-xs">✓</span>
              </div>
            ) : (
              <div className="w-4 h-4 border border-gray-300 dark:border-gray-600 rounded"></div>
            )}
          </div>
        )
      },
    },
    {
      title: 'ID',
      dataIndex: 'episodeId',
      key: 'episodeId',
      width: 150,
    },
    {
      title: '剧集名',
      dataIndex: 'title',
      key: 'title',
      width: 200,
    },
    {
      title: '集数',
      dataIndex: 'episodeIndex',
      key: 'episodeIndex',
      width: 80,
      sorter: {
        compare: (a, b) => a.episodeIndex - b.episodeIndex,
        multiple: 1,
      },
    },
    {
      title: '弹幕数',
      dataIndex: 'commentCount',
      key: 'commentCount',
      width: 80,
    },

    {
      title: '采集时间',
      dataIndex: 'fetchedAt',
      key: 'fetchedAt',
      width: 160,
      render: (_, record) => {
        return (
          <Typography.Text>{dayjs(record.fetchedAt).format('YYYY-MM-DD HH:mm:ss')}</Typography.Text>
        )
      },
    },
    {
      title: '官方链接',
      dataIndex: 'sourceUrl',
      key: 'sourceUrl',
      width: 100,
      render: (_, record) => {
        return (
          <div>
            {isUrl(record.sourceUrl) ? (
              <a
                href={record.sourceUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                跳转
              </a>
            ) : (
              '--'
            )}
          </div>
        )
      },
    },
    {
      title: '操作',
      width: isXmlImport ? 90 : 120,
      fixed: 'right',
      render: (_, record) => {
        return (
          <Space>
            <Tooltip title="编辑分集信息">
              <span
                className="cursor-pointer hover:text-primary text-gray-600 dark:text-gray-400"
                onClick={() => {
                  form.setFieldsValue({
                    ...record,
                    episodeId: record.episodeId,
                    originalEpisodeIndex: record.episodeIndex,
                  })
                  setIsEditing(true)
                  setEditOpen(true)
                }}
              >
                <MyIcon icon="edit" size={20} />
              </span>
            </Tooltip>
            {!isXmlImport && (
              <Tooltip title="刷新分集弹幕">
                <span
                  className="cursor-pointer hover:text-primary text-gray-600 dark:text-gray-400"
                  onClick={() => handleRefresh(record)}
                >
                  <MyIcon icon="refresh" size={20} />
                </span>
              </Tooltip>
            )}

            <Tooltip title="弹幕详情">
              <span
                className="cursor-pointer hover:text-primary text-gray-600 dark:text-gray-400"
                onClick={() => {
                  navigate(`/comment/${record.episodeId}?episodeId=${id}`)
                }}
              >
                <MyIcon icon="comment" size={20} />
              </span>
            </Tooltip>
            <Tooltip title="删除">
              <span
                className="cursor-pointer hover:text-primary text-gray-600 dark:text-gray-400"
                onClick={() => deleteEpisodeSingle(record)}
              >
                <MyIcon icon="delete" size={20} />
              </span>
            </Tooltip>
          </Space>
        )
      },
    },
  ]

  const rowSelection = {
    selectedRowKeys: selectedRows.map(r => r.episodeId),
    onChange: (selectedRowKeys, selectedRows) => {
      setSelectedRows(selectedRows)
    },
    onSelectAll: (selected, selectedRows, changeRows) => {
      if (selected) {
        setSelectedRows(episodeList)
      } else {
        setSelectedRows([])
      }
    }
  }

  const keepColumns = [
    {
      title: '集数',
      dataIndex: 'episodeIndex',
      key: 'episodeIndex',
      width: 60,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 200,
    },
    {
      title: '弹幕数',
      dataIndex: 'commentCount',
      key: 'commentCount',
      width: 60,
    },
  ]

  const handleBatchDelete = () => {
    modalApi.confirm({
      title: '删除分集',
      zIndex: 1002,
      content: (
        <div>
          <Typography.Text>您确定要删除选中的 {selectedRows.length} 个分集吗？</Typography.Text>
          <br />
          <Typography.Text>此操作将在后台提交一个批量删除任务。</Typography.Text>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await deleteAnimeEpisode({
            episodeIds: selectedRows?.map(it => it.episodeId),
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`提交批量删除任务失败:${error.message}`)
        }
      },
    })
  }

  const deleteEpisodeSingle = record => {
    modalApi.confirm({
      title: '删除分集',
      zIndex: 1002,
      content: (
        <div>
          <Typography.Text>您确定要删除分集 '{record.title}' 吗？</Typography.Text>
          <br />
          <Typography.Text>此操作将在后台提交一个批量删除任务。</Typography.Text>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await deleteAnimeEpisodeSingle({
            id: record.episodeId,
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`提交删除任务失败:${error.message}`)
        }
      },
    })
  }

  const handleRefresh = record => {
    modalApi.confirm({
      title: '刷新分集',
      zIndex: 1002,
      content: <Typography.Text>您确定要刷新分集 '{record.title}' 的弹幕吗？</Typography.Text>,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await refreshEpisodeDanmaku({
            id: record.episodeId,
          })
          messageApi.success(res.message || '刷新任务已开始。')
        } catch (error) {
          messageApi.error(`启动刷新任务失败:${error.message}`)
        }
      },
    })
  }

  const handleBatchRefresh = () => {
    if (!selectedRows.length) {
      messageApi.warning('请先选择要刷新的分集')
      return
    }

    modalApi.confirm({
      title: '批量刷新分集',
      zIndex: 1002,
      content: (
        <div>
          <Typography.Text>您确定要刷新选中的 {selectedRows.length} 个分集的弹幕吗？</Typography.Text>
          <br />
          <Typography.Text>此操作将在后台提交 {selectedRows.length} 个刷新任务。</Typography.Text>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const episodeIds = selectedRows.map(row => row.episodeId)
          const res = await refreshEpisodesBulk({ episodeIds })
          messageApi.success(res.message || '批量刷新任务已提交。')
        } catch (error) {
          messageApi.error(`提交批量刷新任务失败:${error.message}`)
        }
      },
    })
  }

  const goTask = res => {
    modalApi.confirm({
      title: '提示',
      zIndex: 1002,
      content: (
        <div>
          <Typography.Text>{res.data?.message || '任务已提交'}</Typography.Text>
          <br />
          <Typography.Text>是否立即跳转到任务管理器查看进度？</Typography.Text>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        navigate(`${RoutePaths.TASK}?status=all`)
      },
      onCancel: () => {
        getDetail()
        setSelectedRows([])
      },
    })
  }

  const handleSave = async () => {
    try {
      if (confirmLoading) return
      setConfirmLoading(true)
      const values = await form.validateFields()
      console.log(values, 'values')
      if (values.episodeId) {
        await editEpisode({
          ...values,
          sourceId: Number(id),
        })
      } else {
        await manualImportEpisode({
          ...values,
          sourceId: Number(id),
        })
      }
      getDetail()
      form.resetFields()
      setUploading(false)
      // 清空上传组件的内部文件列表
      setFileList([])
      messageApi.success('分集信息更新成功！')
    } catch (error) {
      console.log(error)
      messageApi.error(`更新失败: ${error.message || error?.detail || error}`)
    } finally {
      setConfirmLoading(false)
      setEditOpen(false)
    }
  }

  const handleOffset = () => {
    let offsetValue = 0
    modalApi.confirm({
      title: '集数偏移',
      icon: <VerticalAlignMiddleOutlined />,
      zIndex: 1002,
      content: (
        <div className="mt-4">
          <Typography.Text>请输入一个整数作为偏移量（可为负数）。</Typography.Text>
          <br />
          <Typography.Text className="text-gray-500 dark:text-gray-400 text-xs">
            例如：输入 12 会将第 1 集变为第 13 集。
          </Typography.Text>
          <InputNumber
            placeholder="输入偏移量, e.g., 12 or -5"
            onChange={value => (offsetValue = value)}
            style={{ width: '100%' }}
            autoFocus
          />
        </div>
      ),
      onOk: async () => {
        if (!offsetValue || !Number.isInteger(offsetValue)) {
          messageApi.warning('请输入一个有效的整数偏移量。')
          return
        }
        try {
          const res = await offsetEpisodes({
            episodeIds: selectedRows.map(it => it.episodeId),
            offset: offsetValue,
          })
          goTask(res)
        } catch (error) {
          messageApi.error(error?.detail || '提交任务失败')
        }
      },
      okText: '确认',
      cancelText: '取消',
    })
  }

  const handleResetEpisode = () => {
    modalApi.confirm({
      title: '重整集数',
      zIndex: 1002,
      content: (
        <div>
          <Typography.Text>
            您确定要为 '{animeDetail.title}'的这个数据源重整集数吗？
          </Typography.Text>
          <br />
          <Typography.Text>此操作会按当前顺序将集数重新编号为 1, 2, 3...</Typography.Text>
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await resetEpisode({
            sourceId: Number(id),
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`提交重整任务失败:${error.message}`)
        }
      },
    })
  }

  const handleResetMainEpisode = async () => {
    try {
      if (resetLoading) return
      setResetLoading(true)
      const episodeIds = resetInfo?.toDelete?.map(ep => Number(ep.episodeId))
      await deleteAnimeEpisode({
        episodeIds: episodeIds,
      })
      await resetEpisode({
        sourceId: Number(id),
      })
      messageApi.success('已提交：批量删除 + 重整集数 两个任务。')
    } catch (error) {
      messageApi.error(`提交任务失败: ${error.message}`)
    } finally {
      setResetInfo({})
      setResetOpen(false)
      setResetLoading(false)
    }
  }

  const handleUpload = async ({ file }) => {
    setUploading(true)

    try {
      // 创建文件读取器
      const reader = new FileReader()

      reader.onload = async e => {
        try {
          const xmlContent = e.target.result
          form.setFieldsValue({
            content: xmlContent,
          })
        } catch (error) {
          messageApi.error(`文件 ${file.name} 解析失败: ${error.message}`)
        }
      }

      reader.readAsText(file)
    } catch (error) {
      messageApi.error(`文件处理失败: ${error.message}`)
    } finally {
      setUploading(false)
    }
  }

  const handleChange = ({ file, fileList }) => {
    // 更新文件列表状态
    setFileList(fileList)

    if (file.status === 'uploading') {
      setUploading(true)
    }
    if (file.status === 'done' || file.status === 'error') {
      setUploading(false)
    }
  }

  const uploadProps = {
    accept: '.xml',
    multiple: false,
    showUploadList: false,
    beforeUpload: () => true,
    customRequest: handleUpload,
    onChange: handleChange,
    fileList: fileList,
  }

  return (
    <div className="my-6">
      <Breadcrumb
        className="!mb-4"
        items={[
          {
            title: (
              <Link to="/">
                <HomeOutlined />
              </Link>
            ),
          },
          {
            title: <Link to="/library">弹幕库</Link>,
          },
          {
            title: (
              <Link to={`/anime/${animeId}`}>
                {animeDetail.title?.length > 10
                  ? animeDetail.title.slice(0, 10) + '...'
                  : animeDetail.title}
              </Link>
            ),
          },
          {
            title: '分集列表',
          },
        ]}
      />
      <Card loading={loading} title={`分集列表: ${animeDetail?.title ?? ''}`}>
        <div className="mb-3 text-sm text-gray-600 dark:text-gray-400">
          💡 {isMobile ? '点击卡片可选中/取消选中分集，支持Shift多选' : '点击复选框或卡片可选中/取消选中分集，支持Shift多选'}，用于批量操作
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <Button
            onClick={() => {
              handleBatchDelete()
            }}
            type="primary"
            disabled={!selectedRows.length}
          >
            删除选中
          </Button>
          <div className="flex flex-wrap gap-2 sm:justify-end">
            <Button
              onClick={handleOffset}
              disabled={!selectedRows.length}
            >
              <Tooltip title="对所有选中的分集应用一个集数偏移量">
                <VerticalAlignMiddleOutlined />
                <span className="ml-1">集数偏移</span>
              </Tooltip>
            </Button>
            <Button
              onClick={() => {
                const validCounts = episodeList
                  .map(ep => Number(ep.commentCount))
                  .filter(n => Number.isFinite(n) && n >= 0)
                if (validCounts.length === 0) {
                  messageApi.error('所有分集的弹幕数不可用。')
                  return
                }
                const average =
                  validCounts.reduce((a, b) => a + b, 0) / validCounts.length
                const toDelete = episodeList.filter(
                  ep => Number(ep.commentCount) < average
                )
                const toKeep = episodeList.filter(
                  ep => Number(ep.commentCount) >= average
                )

                if (toDelete.length === 0) {
                  messageApi.error(
                    `未找到低于平均值 (${average.toFixed(2)}) 的分集。`
                  )
                  return
                }
                setResetInfo({
                  average,
                  toDelete,
                  toKeep,
                })
                setResetOpen(true)
              }}
              disabled={!episodeList.length}
            >
              正片重整
            </Button>
            <Button
              onClick={() => {
                handleResetEpisode()
              }}
              disabled={!episodeList.length}
            >
              重整集数
            </Button>
            <Button
              onClick={handleBatchRefresh}
              disabled={!selectedRows.length || isXmlImport}
            >
              <Tooltip title="批量刷新选中分集的弹幕">
                <MyIcon icon="refresh" size={16} />
                <span className="ml-1">批量刷新</span>
              </Tooltip>
            </Button>
            {isXmlImport && (
              <Button
                onClick={() => {
                  setIsBatchModalOpen(true)
                }}
              >
                批量导入
              </Button>
            )}
            <Button
              onClick={() => {
                form.resetFields()
                setIsEditing(false)
                setEditOpen(true)
              }}
              type="primary"
            >
              手动导入
            </Button>
          </div>
        </div>
        <div className="mb-4"></div>
        {!!episodeList?.length ? (
          <ResponsiveTable
            pagination={{
              ...pagination,
              showTotal: total => `共 ${total} 条数据`,
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
            size="small"
            dataSource={episodeList}
            columns={columns}
            rowKey={'episodeId'}
            tableProps={{ rowSelection, rowClassName: () => '' }}
            scroll={{ x: '100%' }}
            renderCard={(record) => {
              const isSelected = selectedRows.some(row => row.episodeId === record.episodeId);
              const index = episodeList.findIndex(ep => ep.episodeId === record.episodeId);
              return (
                <Card
                  size="small"
                  className={`hover:shadow-lg transition-all duration-300 mb-3 cursor-pointer relative ${isSelected ? 'shadow-lg ring-2 ring-pink-400/50 bg-pink-50/30 dark:bg-pink-900/10' : ''}`}
                  bodyStyle={{ padding: '12px' }}
                  onClick={(e) => {
                    // 如果点击的是按钮或链接，不触发选择
                    if (
                      e.target.closest('.ant-btn') ||
                      e.target.closest('a')
                    ) {
                      return
                    }

                    const currentIndex = episodeList.findIndex(ep => ep.episodeId === record.episodeId)
                    if (e.shiftKey && lastSelectedIndex !== null) {
                      const start = Math.min(lastSelectedIndex, currentIndex)
                      const end = Math.max(lastSelectedIndex, currentIndex)
                      const range = episodeList.slice(start, end + 1)
                      const newSelected = [...selectedRows]
                      range.forEach(ep => {
                        const isInSelected = newSelected.some(s => s.episodeId === ep.episodeId)
                        if (!isInSelected) {
                          newSelected.push(ep)
                        }
                      })
                      setSelectedRows(newSelected)
                    } else {
                      // 切换选中状态
                      if (isSelected) {
                        setSelectedRows(selectedRows.filter(row => row.episodeId !== record.episodeId))
                      } else {
                        setSelectedRows([...selectedRows, record])
                      }
                      setLastSelectedIndex(currentIndex)
                    }
                    setLastClickedIndex(index)
                  }}
                >
                  <div className="space-y-3 relative">
                    {isSelected && (
                      <div className="absolute -top-1 -right-1 w-3 h-3 bg-pink-400 rounded-full border-2 border-white dark:border-gray-800 z-10"></div>
                    )}
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <Tag color="blue" className="text-xs">
                              第{record.episodeIndex}集
                            </Tag>
                            <span className="text-sm font-medium text-gray-600 dark:text-gray-400">
                              ID: {record.episodeId}
                            </span>
                          </div>
                          <Button
                            size="small"
                            type="text"
                            danger
                            className="flex-shrink-0"
                            icon={<MyIcon icon="delete" size={16} />}
                            title="删除分集"
                            onClick={(e) => {
                              e.stopPropagation()
                              deleteEpisodeSingle(record)
                            }}
                          />
                        </div>
                        <Typography.Text className="font-semibold text-base mb-2 break-words">
                          {record.title}
                        </Typography.Text>
                        <div className="space-y-1">
                          <div className="flex items-center gap-4 text-sm">
                            <span className="flex items-center gap-1">
                              <MyIcon icon="comment" size={14} className="text-blue-500" />
                              <span className="text-gray-600 dark:text-gray-400">
                                {record.commentCount || 0} 条弹幕
                              </span>
                            </span>
                          </div>
                          {record.sourceUrl && isUrl(record.sourceUrl) && (
                            <div className="flex items-center gap-1">
                              <span className="text-xs text-gray-500 dark:text-gray-400">来源:</span>
                              <a
                                href={record.sourceUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-primary hover:text-primary-dark break-all"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {record.sourceUrl.length > 30 ? record.sourceUrl.substring(0, 30) + '...' : record.sourceUrl}
                              </a>
                            </div>
                          )}
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            采集时间: {dayjs(record.fetchedAt).format('YYYY-MM-DD HH:mm')}
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className="pt-1 border-t border-gray-200 dark:border-gray-700">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="small"
                          type="text"
                          icon={<MyIcon icon="edit" size={14} />}
                          title="编辑分集信息"
                          onClick={(e) => {
                            e.stopPropagation()
                            form.setFieldsValue({
                              ...record,
                              episodeId: record.episodeId,
                              originalEpisodeIndex: record.episodeIndex,
                              episodeIndex: Math.max(1, record.episodeIndex || 1),
                            })
                            setIsEditing(true)
                            setEditOpen(true)
                          }}
                        >
                          编辑
                        </Button>
                        {!isXmlImport && (
                          <Button
                            size="small"
                            type="text"
                            icon={<MyIcon icon="refresh" size={14} />}
                            title="刷新分集弹幕"
                            onClick={(e) => {
                              e.stopPropagation()
                              handleRefresh(record)
                            }}
                          >
                            刷新
                          </Button>
                        )}
                        <Button
                          size="small"
                          type="text"
                          icon={<MyIcon icon="comment" size={14} />}
                          title="查看弹幕详情"
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(`/comment/${record.episodeId}?episodeId=${id}`)
                          }}
                        >
                          弹幕
                        </Button>
                      </div>
                    </div>
                  </div>
                </Card>
              );
            }}
          />
        ) : (
          <Empty />
        )}
      </Card>
      <Modal
        title={isEditing ? '编辑分集信息' : '手动导入分集'}
        open={editOpen}
        onOk={handleSave}
        confirmLoading={confirmLoading}
        cancelText="取消"
        okText="确认"
        onCancel={() => {
          setEditOpen(false)
          setIsEditing(false)
          form.resetFields()
        }}
        zIndex={100}
      >
        <Form form={form} layout="horizontal">
          <Form.Item
            name="title"
            label="分集标题"
            rules={[{ required: true, message: '请输入分集标题' }]}
          >
            <Input placeholder="请输入分集标题" />
          </Form.Item>
          <Form.Item
            name="episodeIndex"
            label="集数"
            rules={[{ required: true, message: '请输入集数' }]}
          >
            <InputNumber
              style={{ width: '100%' }}
              placeholder="请输入分集集数"
              min={1}
            />
          </Form.Item>
          {isXmlImport ? (
            <>
              {!isEditing && (
                <>
                  <Form.Item
                    name="content"
                    label="弹幕XML内容"
                    rules={[
                      {
                        required: true,
                        message: `请输入弹幕XML内容`,
                      },
                    ]}
                  >
                    <Input.TextArea
                      rows={6}
                      placeholder="请在此处粘贴弹幕XML文件的内容"
                    />
                  </Form.Item>
                  <div className="text-right my-4">
                    <Upload
                      {...uploadProps}
                      ref={uploadRef}
                      loading={uploading}
                      disabled={uploading}
                    >
                      <Button type="primary" icon={<UploadOutlined />}>
                        选择文件导入XML
                      </Button>
                    </Upload>
                  </div>
                </>
              )}
            </>
          ) : (
            <Form.Item
              name="sourceUrl"
              label="官方链接"
              rules={[
                {
                  required: true,
                  message: `请输入官方链接`,
                },
              ]}
            >
              <Input placeholder="请输入官方链接" />
            </Form.Item>
          )}
          {isEditing && (
            <Form.Item
              name="danmakuFilePath"
              label="弹幕文件路径"
              tooltip="弹幕XML文件的存储路径，修改后会更新数据库记录（不会移动实际文件）"
            >
              <Input placeholder="例如: /app/config/danmaku/123/456.xml" />
            </Form.Item>
          )}
          <Form.Item name="episodeId" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="originalEpisodeIndex" hidden>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={`正片重整预览 - ${animeDetail.title}`}
        open={resetOpen}
        onOk={handleResetMainEpisode}
        confirmLoading={resetLoading}
        cancelText="取消"
        okText="确认执行"
        onCancel={() => setResetOpen(false)}
        zIndex={100}
      >
        <div>
          <Typography.Text className="mb-2">将基于平均弹幕数进行正片重整：</Typography.Text>
          <ul>
            <li>
              <Typography.Text>
                平均弹幕数：<strong>{resetInfo?.average?.toFixed(2)}</strong>
              </Typography.Text>
            </li>
            <li>
              <Typography.Text>
                预计删除分集：
                <span className="text-red-400 font-bold">
                  {resetInfo?.toDelete?.length}
                </span>{' '}
                / {episodeList.length}
              </Typography.Text>
            </li>
            <li>
              <Typography.Text>
                预计保留分集：
                <span className="text-green-500 font-bold">
                  {resetInfo?.toKeep?.length}
                </span>{' '}
                / {episodeList.length}
              </Typography.Text>
            </li>
          </ul>
        </div>
        <div className="my-4 text-sm font-semibold">
          <Typography.Text>预览将保留的分集（最多显示 80 条）</Typography.Text>
        </div>
        <Table
          pagination={false}
          size="small"
          dataSource={resetInfo?.toKeep?.slice(0, 80) ?? []}
          columns={keepColumns}
          rowKey={'episodeId'}
          scroll={{ x: '100%' }}
        />
      </Modal>
      <BatchImportModal
        open={isBatchModalOpen}
        sourceInfo={sourceInfo}
        onCancel={() => setIsBatchModalOpen(false)}
        onSuccess={handleBatchImportSuccess}
      />
    </div>
  )
}
