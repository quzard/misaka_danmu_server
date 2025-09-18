import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  addSourceToAnime,
  deleteAnimeSource,
  deleteAnimeSourceSingle,
  fullSourceUpdate,
  getAnimeDetail,
  getAnimeLibrary,
  getAnimeSource,
  incrementalUpdate,
  setAnimeSource,
  toggleSourceFavorite,
  toggleSourceIncremental,
} from '../../apis'
import {
  Breadcrumb,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  message,
  Modal,
  Row,
  Space,
  Table,
  Tooltip,
} from 'antd'
import { DANDAN_TYPE_DESC_MAPPING } from '../../configs'
import { RoutePaths } from '../../general/RoutePaths'
import dayjs from 'dayjs'
import { MyIcon } from '@/components/MyIcon'
import classNames from 'classnames'
import { padStart } from 'lodash'
import { HomeOutlined } from '@ant-design/icons'
import { useModal } from '../../ModalContext'
import { useMessage } from '../../MessageContext'
import { AddSourceModal } from '../../components/AddSourceModal'
import { useDebounce } from '../../hooks/useDebounce'

export const AnimeDetail = () => {
  const { id } = useParams()
  const [loading, setLoading] = useState(true)
  const [sourceList, setSourceList] = useState([])
  const [animeDetail, setAnimeDetail] = useState({})
  const [libraryList, setLibraryList] = useState([])
  const [editOpen, setEditOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [selectedRows, setSelectedRows] = useState([])
  const [isAddSourceModalOpen, setIsAddSourceModalOpen] = useState(false)

  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 10,
    total: 0,
  })

  const navigate = useNavigate()
  const modalApi = useModal()
  const messageApi = useMessage()

  console.log(sourceList, 'sourceList')

  const totalEpisodeCount = useMemo(() => {
    return sourceList.reduce((total, item) => {
      return total + item.episodeCount
    }, 0)
  }, [sourceList])

  const getDetail = async () => {
    setLoading(true)
    try {
      const [detailRes, sourceRes] = await Promise.all([
        getAnimeDetail({
          animeId: Number(id),
        }),
        getAnimeSource({
          animeId: Number(id),
        }),
      ])
      setAnimeDetail(detailRes.data)
      setSourceList(sourceRes.data)
      setLoading(false)
    } catch (error) {
      navigate('/library')
    }
  }

  const handleAddSourceSuccess = () => {
    setIsAddSourceModalOpen(false)
    getDetail() // 添加成功后刷新数据源列表
  }

  const handleEditSource = async (init = true) => {
    try {
      const res = await getAnimeLibrary({
        keyword: keyword,
        page: pagination.current,
        pageSize: pagination.pageSize,
      })
      setLibraryList(res.data?.list || [])
      setPagination(prev => ({
        ...prev,
        total: res.data?.total || 0,
      }))
      if (init) {
        setEditOpen(true)
      }
    } catch (error) {
      messageApi.error('获取数据源失败')
    }
  }

  const handleKeywordChange = useDebounce(e => {
    setKeyword(e.target.value)
  }, 500)

  useEffect(() => {
    setPagination(n => {
      return {
        ...n,
        current: 1,
      }
    })
  }, [keyword])

  useEffect(() => {
    console.log(keyword, pagination.pageSize, pagination.current)
    handleEditSource(false)
  }, [keyword, pagination.pageSize, pagination.current])

  const handleConfirmSource = item => {
    modalApi.confirm({
      title: '关联数据源',
      zIndex: 1002,
      content: (
        <div>
          您确定要将当前作品的所有数据源关联到 "{item.title}" (ID:
          {item.animeId}) 吗？
          <br />
          此操作不可撤销！
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await setAnimeSource({
            sourceAnimeId: animeDetail.animeId,
            targetAnimeId: item.animeId,
          })
          messageApi.success('关联成功')
          setEditOpen(false)
          navigate(RoutePaths.LIBRARY)
        } catch (error) {
          messageApi.error(`关联失败:${error.message}`)
        }
      },
    })
  }

  const handleBatchDelete = () => {
    modalApi.confirm({
      title: '删除数据源',
      zIndex: 1002,
      content: (
        <div>
          您确定要删除选中的 {selectedRows.length} 个数据源吗？
          <br />
          此操作将在后台提交一个批量删除任务。
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await deleteAnimeSource({
            sourceIds: selectedRows?.map(it => it.sourceId),
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`提交批量删除任务失败:${error.message}`)
        }
      },
    })
  }

  const handleDeleteSingle = record => {
    modalApi.confirm({
      title: '删除数据源',
      zIndex: 1002,
      content: (
        <div>
          您确定要删除这个数据源吗？
          <br />
          此操作将在后台提交一个删除任务。
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await deleteAnimeSourceSingle({
            sourceId: record.sourceId,
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`提交删除任务失败:${error.message}`)
        }
      },
    })
  }

  const handleIncrementalUpdate = record => {
    modalApi.confirm({
      title: '增量刷新',
      zIndex: 1002,
      content: (
        <div>
          您确定要为 '{animeDetail.title}' 的这个数据源执行增量更新吗？
          <br />
          此操作将尝试获取下一集。
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await incrementalUpdate({
            sourceId: record.sourceId,
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`启动增量更新任务失败: ${error.message}`)
        }
      },
    })
  }

  const handleFullSourceUpdate = record => {
    modalApi.confirm({
      title: '全量刷新',
      zIndex: 1002,
      content: (
        <div>您确定要为 '{animeDetail.title}' 的这个数据源执行全量更新吗？</div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          const res = await fullSourceUpdate({
            sourceId: record.sourceId,
          })
          goTask(res)
        } catch (error) {
          messageApi.error(`启动刷新任务失败: ${error.message}`)
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
          {res.data?.message || '任务已提交'}
          <br />
          是否立即跳转到任务管理器查看进度？
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

  const operateWidth = sourceList?.every(it => it.providerName === 'custom')
    ? 90
    : 180
  const columns = [
    {
      title: '源提供方',
      dataIndex: 'providerName',
      key: 'providerName',
      width: 100,
    },
    {
      title: '媒体库ID',
      dataIndex: 'mediaId',
      key: 'mediaId',
      width: 200,
    },
    {
      title: '状态',
      width: 100,
      dataIndex: 'isFavorited',
      key: 'isFavorited',
      render: (_, record) => {
        return (
          <Space>
            {record.isFavorited && (
              <MyIcon
                icon="favorites-fill"
                size={20}
                className="text-yellow-300"
              />
            )}
            {record.incrementalRefreshEnabled && (
              <MyIcon icon="clock" size={20} className="text-red-400" />
            )}
          </Space>
        )
      },
    },

    {
      title: '收录时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 200,
      render: (_, record) => {
        return (
          <div>{dayjs(record.createdAt).format('YYYY-MM-DD HH:mm:ss')}</div>
        )
      },
    },
    {
      title: '操作',
      width: operateWidth,
      fixed: 'right',
      render: (_, record) => {
        return (
          <Space>
            <Tooltip title="精确标记源，请求弹幕时优先使用该源">
              <span
                className="cursor-pointer hover:text-primary"
                onClick={async () => {
                  try {
                    await toggleSourceFavorite({
                      sourceId: record.sourceId,
                    })
                    setSourceList(list => {
                      return list.map(it => {
                        if (it.sourceId === record.sourceId) {
                          return {
                            ...it,
                            isFavorited: !it.isFavorited,
                          }
                        } else {
                          return it
                        }
                      })
                    })
                  } catch (error) {
                    alert(`操作失败: ${error.message}`)
                  }
                }}
              >
                {record.isFavorited ? (
                  <MyIcon
                    icon="favorites-fill"
                    size={20}
                    className="text-yellow-300"
                  />
                ) : (
                  <MyIcon icon="favorites" size={20} />
                )}
              </span>
            </Tooltip>
            {record?.providerName !== 'custom' && (
              <Tooltip title="定时任务配合（任务管理器-定时任务-定时增量追更）使用，增量获取下一集">
                <span
                  className="cursor-pointer hover:text-primary"
                  onClick={async () => {
                    try {
                      await toggleSourceIncremental({
                        sourceId: record.sourceId,
                      })
                      setSourceList(list => {
                        return list.map(it => {
                          if (it.sourceId === record.sourceId) {
                            return {
                              ...it,
                              incrementalRefreshEnabled:
                                !it.incrementalRefreshEnabled,
                            }
                          } else {
                            return it
                          }
                        })
                      })
                    } catch (error) {
                      alert(`操作失败: ${error.message}`)
                    }
                  }}
                >
                  <MyIcon
                    icon="clock"
                    size={20}
                    className={classNames({
                      'text-red-400': record.incrementalRefreshEnabled,
                    })}
                  ></MyIcon>
                </span>
              </Tooltip>
            )}
            {record?.providerName !== 'custom' && (
              <Tooltip title="增量获取下一集">
                <span
                  className="cursor-pointer hover:text-primary"
                  onClick={() => handleIncrementalUpdate(record)}
                >
                  <MyIcon icon="zengliang" size={20}></MyIcon>
                </span>
              </Tooltip>
            )}
            <Tooltip title="分集列表">
              <span
                className="cursor-pointer hover:text-primary"
                onClick={() => {
                  navigate(`/episode/${record.sourceId}?animeId=${id}`)
                }}
              >
                <MyIcon icon="book" size={20}></MyIcon>
              </span>
            </Tooltip>
            {record?.providerName !== 'custom' && (
              <Tooltip title="执行全量更新(此操作会删除旧数据)">
                <span
                  className="cursor-pointer hover:text-primary"
                  onClick={() => handleFullSourceUpdate(record)}
                >
                  <MyIcon icon="refresh" size={20}></MyIcon>
                </span>
              </Tooltip>
            )}

            <Tooltip title="删除数据源">
              <span
                className="cursor-pointer hover:text-primary"
                onClick={() => {
                  handleDeleteSingle(record)
                }}
              >
                <MyIcon icon="delete" size={20}></MyIcon>
              </span>
            </Tooltip>
          </Space>
        )
      },
    },
  ]

  const rowSelection = {
    onChange: (_, selectedRows) => {
      console.log('selectedRows: ', selectedRows)
      setSelectedRows(selectedRows)
    },
  }

  useEffect(() => {
    getDetail()
  }, [])

  let imageSrc = animeDetail.localImagePath || animeDetail.imageUrl
  // 兼容旧的、错误的缓存路径
  if (imageSrc && imageSrc.startsWith('/images/')) {
    imageSrc = imageSrc.replace('/images/', '/data/images/')
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
            title: animeDetail.title,
          },
        ]}
      />
      <Card loading={loading} title={null}>
        <Row gutter={[12, 12]}>
          <Col md={20} xs={24}>
            <div className="flex items-center justify-start gap-4">
              {imageSrc && <img src={imageSrc} className="h-[100px]" />}
              <div>
                <div className="text-xl font-bold mb-3 break-all">
                  {animeDetail.title}（Season{' '}
                  {padStart(animeDetail.season, 2, '0')}）
                </div>
                <div className="flex items-center justify-start gap-2">
                  <span>总集数: {totalEpisodeCount}</span>|
                  <span>已关联 {sourceList.length} 个源</span>
                </div>
              </div>
            </div>
          </Col>
          <Col md={4} xs={24}>
            <div className="h-full flex items-center">
              <Button
                type="primary"
                block
                onClick={() => {
                  handleEditSource()
                }}
              >
                调整关联数据源
              </Button>
            </div>
          </Col>
        </Row>
        <div className="mt-6">
          <div className="flex items-center gap-4 mb-4">
            <Button
              onClick={() => {
                handleBatchDelete()
              }}
              type="primary"
              disabled={!selectedRows.length}
            >
              删除选中
            </Button>
            <Button
              onClick={() => {
                setIsAddSourceModalOpen(true)
              }}
            >
              添加数据源
            </Button>
          </div>
          {!!sourceList?.length ? (
            <Table
              rowSelection={{ type: 'checkbox', ...rowSelection }}
              pagination={false}
              size="small"
              dataSource={sourceList}
              columns={columns}
              rowKey={'sourceId'}
              scroll={{ x: '100%' }}
            />
          ) : (
            <Empty />
          )}
        </div>
      </Card>
      <Modal
        title={`为 "${animeDetail.title}"调整关联`}
        open={editOpen}
        footer={null}
        zIndex={110}
        onCancel={() => setEditOpen(false)}
      >
        <div>
          此操作会将 "{animeDetail.title}" (ID: {animeDetail.animeId})
          下的所有数据源移动到您选择的另一个作品条目下，然后删除原条目。
        </div>
        <div className="flex items-center justify-between my-4">
          <div className="text-base font-bold">选择目标作品</div>
          <div>
            <Input
              placeholder="搜索目标作品"
              onChange={e => handleKeywordChange(e)}
            />
          </div>
        </div>
        <List
          itemLayout="vertical"
          size="large"
          dataSource={libraryList}
          pagination={{
            ...pagination,
            align: 'center',
            showLessItems: true,
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
            return (
              <List.Item key={index}>
                <div className="flex justify-between items-center">
                  <div className="flex items-center justify-start">
                    <img width={60} alt="logo" src={item.imageUrl} />
                    <div className="ml-4">
                      <div className="text-base font-bold mb-2">
                        {item.title}（ID: {item.animeId}）
                      </div>
                      <div>
                        <span>季:{item.season}</span>
                        <span className="ml-3">
                          类型:{DANDAN_TYPE_DESC_MAPPING[item.type]}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div>
                    <Button
                      disabled={item.animeId === animeDetail.animeId}
                      type="primary"
                      onClick={() => {
                        handleConfirmSource(item)
                      }}
                    >
                      关联
                    </Button>
                  </div>
                </div>
              </List.Item>
            )
          }}
        />
      </Modal>
      <AddSourceModal
        open={isAddSourceModalOpen}
        animeId={id}
        onCancel={() => setIsAddSourceModalOpen(false)}
        onSuccess={handleAddSourceSuccess}
      />
    </div>
  )
}
