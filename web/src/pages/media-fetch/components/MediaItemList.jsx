import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Space, Input, message, Checkbox, Popconfirm, Tag, List, Row, Col, Dropdown } from 'antd';
import { SearchOutlined, DeleteOutlined, EditOutlined, ImportOutlined, FolderOpenOutlined, AppstoreOutlined, TableOutlined, MoreOutlined } from '@ant-design/icons';
import { getMediaWorks, getShowSeasons, deleteMediaItem, batchDeleteMediaItems, importMediaItems } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';
import EpisodeListModal from './EpisodeListModal';

const { Search } = Input;

const MediaItemList = ({ serverId, refreshTrigger, selectedItems = [], onSelectionChange }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [searchText, setSearchText] = useState('');
  const [pagination, setPagination] = useState({ current: 1, pageSize: 100, total: 0 });
  const [editorVisible, setEditorVisible] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [episodeModalVisible, setEpisodeModalVisible] = useState(false);
  const [selectedShow, setSelectedShow] = useState(null);
  const [viewMode, setViewMode] = useState('table'); // 'table' or 'card'

  // 加载作品列表
  const loadItems = async (page = 1, pageSize = 100) => {
    setLoading(true);
    try {
      const res = await getMediaWorks({
        server_id: serverId,
        page,
        page_size: pageSize,
      });
      const data = res.data;

      // 构建树形结构(只包含作品和季度,不包含集)
      const treeData = await buildTreeData(data.list);
      setItems(treeData);
      setPagination({
        current: page,
        pageSize,
        total: data.total,
      });
    } catch (error) {
      message.error('加载作品列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 构建树形数据结构(作品 > 季度)
  const buildTreeData = async (worksList) => {
    const result = [];

    for (const work of worksList) {
      if (work.type === 'movie') {
        // 电影节点
        result.push({
          ...work,
          key: `movie-${work.id}`,
          isGroup: false,
        });
      } else if (work.type === 'tv_show') {
        // 电视剧组节点
        try {
          const seasonsRes = await getShowSeasons(work.title, work.serverId);
          const seasons = seasonsRes.data || [];

          result.push({
            key: `show-${work.title}`,
            title: work.title,
            mediaType: 'tv_show',
            year: work.year,
            tmdbId: work.tmdbId,
            tvdbId: work.tvdbId,
            imdbId: work.imdbId,
            posterUrl: work.posterUrl,
            serverId: work.serverId,
            isGroup: true,
            seasonCount: work.seasonCount,
            episodeCount: work.episodeCount,
            children: seasons.map(s => ({
              key: `season-${work.title}-S${s.season}`,
              title: `第 ${s.season} 季 (${s.episodeCount}集)`,
              season: s.season,
              episodeCount: s.episodeCount,
              year: s.year,
              posterUrl: s.posterUrl,
              mediaType: 'tv_season',
              serverId: work.serverId,
              showTitle: work.title,
              isGroup: true,
            })),
          });
        } catch (error) {
          console.error(`加载《${work.title}》季度信息失败:`, error);
          // 即使加载季度失败,也添加剧集组节点
          result.push({
            key: `show-${work.title}`,
            title: work.title,
            mediaType: 'tv_show',
            year: work.year,
            serverId: work.serverId,
            isGroup: true,
            children: [],
          });
        }
      }
    }

    return result;
  };

  useEffect(() => {
    if (serverId) {
      loadItems();
    }
  }, [serverId, refreshTrigger]);

  // 同步外部选中的项目
  useEffect(() => {
    setSelectedRowKeys(selectedItems);
  }, [selectedItems]);

  // 当选中状态改变时，通知外部组件
  const handleSelectionChange = (keys) => {
    setSelectedRowKeys(keys);
    if (onSelectionChange) {
      onSelectionChange(keys);
    }
  };

  // 处理表格变化
  const handleTableChange = (newPagination) => {
    loadItems(newPagination.current, newPagination.pageSize);
  };

  // 处理删除
  const handleDelete = async (record) => {
    if (record.isGroup) {
      message.warning('不能删除分组,请删除具体的项目');
      return;
    }

    try {
      await deleteMediaItem(record.id);
      message.success('删除成功');
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('删除失败');
      console.error(error);
    }
  };

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的项目');
      return;
    }

    // 分类收集要删除的项目
    const itemIds = [];
    const shows = [];
    const seasons = [];

    selectedRowKeys.forEach(key => {
      if (key.startsWith('movie-') || key.startsWith('episode-')) {
        // 直接删除的电影或剧集
        itemIds.push(parseInt(key.split('-')[1]));
      } else {
        // 查找对应的item
        const item = findItemByKey(items, key);
        if (!item) return;

        if (item.mediaType === 'tv_show') {
          // 整个剧集组
          shows.push({
            serverId: serverId,
            title: item.title
          });
        } else if (item.mediaType === 'tv_season') {
          // 某一季
          // 需要找到父级的title
          const parentKey = key.substring(0, key.lastIndexOf('-'));
          const parent = findItemByKey(items, parentKey);
          if (parent) {
            seasons.push({
              serverId: serverId,
              title: parent.title,
              season: item.season
            });
          }
        }
      }
    });

    if (itemIds.length === 0 && shows.length === 0 && seasons.length === 0) {
      message.warning('没有可删除的项目');
      return;
    }

    try {
      const payload = {};
      if (itemIds.length > 0) payload.itemIds = itemIds;
      if (shows.length > 0) payload.shows = shows;
      if (seasons.length > 0) payload.seasons = seasons;

      await batchDeleteMediaItems(payload);
      message.success('删除成功');
      setSelectedRowKeys([]);
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('批量删除失败');
      console.error(error);
    }
  };

  // 辅助函数:根据key查找item
  const findItemByKey = (list, key) => {
    for (const item of list) {
      if (item.key === key) return item;
      if (item.children) {
        const found = findItemByKey(item.children, key);
        if (found) return found;
      }
    }
    return null;
  };

  // 处理编辑
  const handleEdit = (record) => {
    if (record.isGroup) {
      message.warning('不能编辑分组');
      return;
    }
    setEditingItem(record);
    setEditorVisible(true);
  };

  const handleEditorSaved = () => {
    setEditorVisible(false);
    loadItems(pagination.current, pagination.pageSize);
  };

  // 处理导入
  const handleImport = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要导入的项目');
      return;
    }

    // 分类收集要导入的项目
    const itemIds = [];
    const shows = [];
    const seasons = [];

    selectedRowKeys.forEach(key => {
      if (key.startsWith('movie-') || key.startsWith('episode-')) {
        // 直接导入的电影或剧集
        itemIds.push(parseInt(key.split('-')[1]));
      } else {
        // 查找对应的item
        const item = findItemByKey(items, key);
        if (!item) return;

        if (item.mediaType === 'tv_show') {
          // 整个剧集组
          shows.push({
            serverId: serverId,
            title: item.title
          });
        } else if (item.mediaType === 'tv_season') {
          // 某一季
          // 需要找到父级的title
          const parentKey = key.substring(0, key.lastIndexOf('-'));
          const parent = findItemByKey(items, parentKey);
          if (parent) {
            seasons.push({
              serverId: serverId,
              title: parent.title,
              season: item.season
            });
          }
        }
      }
    });

    if (itemIds.length === 0 && shows.length === 0 && seasons.length === 0) {
      message.warning('没有可导入的项目');
      return;
    }

    try {
      const payload = {};
      if (itemIds.length > 0) payload.itemIds = itemIds;
      if (shows.length > 0) payload.shows = shows;
      if (seasons.length > 0) payload.seasons = seasons;

      const res = await importMediaItems(payload);
      const result = res.data;
      message.success(result.message || '导入任务已提交');
      setSelectedRowKeys([]);
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
  };

  // 打开分集列表弹窗
  const handleOpenEpisodes = (record) => {
    setSelectedShow({
      serverId: record.serverId,
      title: record.showTitle,
      season: record.season,
    });
    setEpisodeModalVisible(true);
  };

  // 表格列定义
  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: '30%',
      render: (title, record) => {
        // 季度节点显示为可点击链接
        if (record.mediaType === 'tv_season') {
          return (
            <Button
              type="link"
              icon={<FolderOpenOutlined />}
              onClick={() => handleOpenEpisodes(record)}
              style={{ padding: 0 }}
            >
              {title}
            </Button>
          );
        }
        return title;
      },
    },
    {
      title: '类型',
      dataIndex: 'mediaType',
      key: 'mediaType',
      width: '10%',
      render: (type) => {
        const typeMap = {
          movie: '电影',
          tv_series: '电视剧',
          tv_show: '电视剧',
          tv_season: '-',
        };
        return typeMap[type] || type;
      },
    },
    {
      title: '年份',
      dataIndex: 'year',
      key: 'year',
      width: '10%',
      render: (year) => year || '-',
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '10%',
      render: (isImported, record) => {
        if (record.isGroup) return '-';
        return isImported ? (
          <Tag color="success">已导入</Tag>
        ) : (
          <Tag>未导入</Tag>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '20%',
      render: (_, record) => {
        // 剧集组显示删除和导入整部按钮
        if (record.isGroup && record.mediaType === 'tv_show') {
          return (
            <Space size="small">
              <Popconfirm
                title={`确定要删除《${record.title}》的所有集吗?`}
                onConfirm={() => {
                  // 删除整部剧集
                  batchDeleteMediaItems({
                    shows: [{
                      serverId: serverId,
                      title: record.title
                    }]
                  })
                    .then(() => {
                      message.success(`成功删除《${record.title}》`);
                      loadItems(pagination.current, pagination.pageSize);
                    })
                    .catch(() => message.error('删除失败'));
                }}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除整部
                </Button>
              </Popconfirm>
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  // 导入整部剧集
                  importMediaItems({
                    shows: [{
                      serverId: serverId,
                      title: record.title
                    }]
                  })
                    .then((res) => {
                      message.success(res.data.message || '导入任务已提交');
                      loadItems(pagination.current, pagination.pageSize);
                    })
                    .catch(() => message.error('导入失败'));
                }}
              >
                导入整部
              </Button>
            </Space>
          );
        }

        // 季度显示删除和导入按钮
        if (record.mediaType === 'tv_season') {
          return (
            <Space size="small">
              <Popconfirm
                title={`确定要删除第${record.season}季的所有集吗?`}
                onConfirm={() => {
                  // 删除该季度
                  // 需要找到父级的title
                  const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
                  const parent = findItemByKey(items, parentKey);
                  if (parent) {
                    batchDeleteMediaItems({
                      seasons: [{
                        serverId: serverId,
                        title: parent.title,
                        season: record.season
                      }]
                    })
                      .then(() => {
                        message.success(`成功删除第${record.season}季`);
                        loadItems(pagination.current, pagination.pageSize);
                      })
                      .catch(() => message.error('删除失败'));
                  }
                }}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除整季
                </Button>
              </Popconfirm>
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  // 导入该季度
                  // 需要找到父级的title
                  const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
                  const parent = findItemByKey(items, parentKey);
                  if (parent) {
                    importMediaItems({
                      seasons: [{
                        serverId: serverId,
                        title: parent.title,
                        season: record.season
                      }]
                    })
                      .then((res) => {
                        message.success(res.data.message || '导入任务已提交');
                        loadItems(pagination.current, pagination.pageSize);
                      })
                      .catch(() => message.error('导入失败'));
                  }
                }}
              >
                导入整季
              </Button>
            </Space>
          );
        }

        // 电影显示导入、编辑和删除按钮
        if (record.mediaType === 'movie') {
          return (
            <Space size="small">
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  // 导入电影
                  importMediaItems({
                    itemIds: [record.id]
                  })
                    .then((res) => {
                      message.success(res.data.message || '导入任务已提交');
                      loadItems(pagination.current, pagination.pageSize);
                    })
                    .catch((error) => message.error('导入失败: ' + (error.message || '未知错误')));
                }}
              >
                导入
              </Button>
              <Button
                type="link"
                size="small"
                icon={<EditOutlined />}
                onClick={() => handleEdit(record)}
              >
                编辑
              </Button>
              <Popconfirm
                title="确定要删除吗?"
                onConfirm={() => handleDelete(record)}
                okText="确定"
                cancelText="取消"
              >
                <Button
                  type="link"
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                >
                  删除
                </Button>
              </Popconfirm>
            </Space>
          );
        }

        // 单集显示编辑和删除按钮
        return (
          <Space size="small">
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(record)}
            >
              编辑
            </Button>
            <Popconfirm
              title="确定要删除吗?"
              onConfirm={() => handleDelete(record)}
              okText="确定"
              cancelText="取消"
            >
              <Button
                type="link"
                size="small"
                danger
                icon={<DeleteOutlined />}
              >
                删除
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: handleSelectionChange,
    // 所有项都可以选择
  };

  // 渲染项目操作按钮 - 桌面端
  const renderItemActions = (record) => {
    // 剧集组显示删除和导入整部按钮
    if (record.isGroup && record.mediaType === 'tv_show') {
      return [
        <Popconfirm
          key="delete-show"
          title={`确定要删除《${record.title}》的所有集吗?`}
          onConfirm={() => {
            // 删除整部剧集
            batchDeleteMediaItems({
              shows: [{
                serverId: serverId,
                title: record.title
              }]
            })
              .then(() => {
                message.success(`成功删除《${record.title}》`);
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch(() => message.error('删除失败'));
          }}
          okText="确定"
          cancelText="取消"
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除整部
          </Button>
        </Popconfirm>,
        <Button
          key="import-show"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
            // 导入整部剧集
            importMediaItems({
              shows: [{
                serverId: serverId,
                title: record.title
              }]
            })
              .then((res) => {
                message.success(res.data.message || '导入任务已提交');
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch(() => message.error('导入失败'));
          }}
        >
          导入整部
        </Button>
      ];
    }

    // 季度显示删除和导入按钮
    if (record.mediaType === 'tv_season') {
      return [
        <Popconfirm
          key="delete-season"
          title={`确定要删除第${record.season}季的所有集吗?`}
          onConfirm={() => {
            // 删除该季度
            // 需要找到父级的title
            const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
            const parent = findItemByKey(items, parentKey);
            if (parent) {
              batchDeleteMediaItems({
                seasons: [{
                  serverId: serverId,
                  title: parent.title,
                  season: record.season
                }]
              })
                .then(() => {
                  message.success(`成功删除第${record.season}季`);
                  loadItems(pagination.current, pagination.pageSize);
                })
                .catch(() => message.error('删除失败'));
            }
          }}
          okText="确定"
          cancelText="取消"
        >
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除整季
          </Button>
        </Popconfirm>,
        <Button
          key="import-season"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
            // 导入该季度
            // 需要找到父级的title
            const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
            const parent = findItemByKey(items, parentKey);
            if (parent) {
              importMediaItems({
                seasons: [{
                  serverId: serverId,
                  title: parent.title,
                  season: record.season
                }]
              })
                .then((res) => {
                  message.success(res.data.message || '导入任务已提交');
                  loadItems(pagination.current, pagination.pageSize);
                })
                .catch(() => message.error('导入失败'));
            }
          }}
        >
          导入整季
        </Button>
      ];
    }

    // 电影显示导入、编辑和删除按钮
    if (record.mediaType === 'movie') {
      return [
        <Button
          key="import-movie"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
            // 导入电影
            importMediaItems({
              itemIds: [record.id]
            })
              .then((res) => {
                message.success(res.data.message || '导入任务已提交');
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch((error) => message.error('导入失败: ' + (error.message || '未知错误')));
          }}
        >
          导入
        </Button>,
        <Button
          key="edit-movie"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleEdit(record)}
        >
          编辑
        </Button>,
        <Popconfirm
          key="delete-movie"
          title="确定要删除吗?"
          onConfirm={() => handleDelete(record)}
          okText="确定"
          cancelText="取消"
        >
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
          >
            删除
          </Button>
        </Popconfirm>
      ];
    }

    // 单集显示编辑和删除按钮
    return [
      <Button
        key="edit-episode"
        type="link"
        size="small"
        icon={<EditOutlined />}
        onClick={() => handleEdit(record)}
      >
        编辑
      </Button>,
      <Popconfirm
        key="delete-episode"
        title="确定要删除吗?"
        onConfirm={() => handleDelete(record)}
        okText="确定"
        cancelText="取消"
      >
        <Button
          type="link"
          size="small"
          danger
          icon={<DeleteOutlined />}
        >
          删除
        </Button>
      </Popconfirm>
    ];
  };

  // 渲染移动端操作菜单
  const renderMobileActions = (record) => {
    const items = [];

    if (record.isGroup && record.mediaType === 'tv_show') {
      items.push(
        {
          key: 'import-show',
          icon: <ImportOutlined />,
          label: '导入整部',
          onClick: () => {
            importMediaItems({
              shows: [{
                serverId: serverId,
                title: record.title
              }]
            })
              .then((res) => {
                message.success(res.data.message || '导入任务已提交');
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch(() => message.error('导入失败'));
          }
        },
        {
          key: 'delete-show',
          icon: <DeleteOutlined />,
          label: '删除整部',
          danger: true,
          onClick: () => {
            // 这里会触发Popconfirm，但为了简化，我们直接执行
            batchDeleteMediaItems({
              shows: [{
                serverId: serverId,
                title: record.title
              }]
            })
              .then(() => {
                message.success(`成功删除《${record.title}》`);
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch(() => message.error('删除失败'));
          }
        }
      );
    } else if (record.mediaType === 'tv_season') {
      items.push(
        {
          key: 'import-season',
          icon: <ImportOutlined />,
          label: '导入整季',
          onClick: () => {
            const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
            const parent = findItemByKey(items, parentKey);
            if (parent) {
              importMediaItems({
                seasons: [{
                  serverId: serverId,
                  title: parent.title,
                  season: record.season
                }]
              })
                .then((res) => {
                  message.success(res.data.message || '导入任务已提交');
                  loadItems(pagination.current, pagination.pageSize);
                })
                .catch(() => message.error('导入失败'));
            }
          }
        },
        {
          key: 'delete-season',
          icon: <DeleteOutlined />,
          label: '删除整季',
          danger: true,
          onClick: () => {
            const parentKey = record.key.substring(0, record.key.lastIndexOf('-'));
            const parent = findItemByKey(items, parentKey);
            if (parent) {
              batchDeleteMediaItems({
                seasons: [{
                  serverId: serverId,
                  title: parent.title,
                  season: record.season
                }]
              })
                .then(() => {
                  message.success(`成功删除第${record.season}季`);
                  loadItems(pagination.current, pagination.pageSize);
                })
                .catch(() => message.error('删除失败'));
            }
          }
        }
      );
    } else if (record.mediaType === 'movie') {
      items.push(
        {
          key: 'import-movie',
          icon: <ImportOutlined />,
          label: '导入',
          onClick: () => {
            importMediaItems({
              itemIds: [record.id]
            })
              .then((res) => {
                message.success(res.data.message || '导入任务已提交');
                loadItems(pagination.current, pagination.pageSize);
              })
              .catch((error) => message.error('导入失败: ' + (error.message || '未知错误')));
          }
        },
        {
          key: 'edit-movie',
          icon: <EditOutlined />,
          label: '编辑',
          onClick: () => handleEdit(record)
        },
        {
          key: 'delete-movie',
          icon: <DeleteOutlined />,
          label: '删除',
          danger: true,
          onClick: () => handleDelete(record)
        }
      );
    } else {
      // 单集
      items.push(
        {
          key: 'edit-episode',
          icon: <EditOutlined />,
          label: '编辑',
          onClick: () => handleEdit(record)
        },
        {
          key: 'delete-episode',
          icon: <DeleteOutlined />,
          label: '删除',
          danger: true,
          onClick: () => handleDelete(record)
        }
      );
    }

    return (
      <Dropdown
        menu={{ items }}
        trigger={['click']}
        placement="bottomRight"
      >
        <Button 
          type="text" 
          icon={<MoreOutlined />} 
          size="middle"
          style={{ fontSize: '16px', width: '32px', height: '32px' }}
        />
      </Dropdown>
    );
  };

  return (
    <>
      <Card
        title={
          <div>
            <span className="desktop-only">媒体项列表</span>
            <span className="mobile-only">媒体列表</span>
          </div>
        }
        extra={
          <div className="desktop-only">
            <Space wrap>
              <Button
                icon={<TableOutlined />}
                type={viewMode === 'table' ? 'primary' : 'default'}
                onClick={() => setViewMode('table')}
                size="small"
              >
                表格
              </Button>
              <Button
                icon={<AppstoreOutlined />}
                type={viewMode === 'card' ? 'primary' : 'default'}
                onClick={() => setViewMode('card')}
                size="small"
              >
                卡片
              </Button>
              <Search
                placeholder="搜索标题"
                allowClear
                style={{ width: 200 }}
                onSearch={setSearchText}
              />
            </Space>
          </div>
        }
      >
        {/* 移动端头部布局 */}
        <div className="mobile-only" style={{ marginBottom: 20 }}>
          <Row gutter={[12, 12]} align="middle">
            <Col span={12}>
              <Button
                icon={<TableOutlined />}
                type={viewMode === 'table' ? 'primary' : 'default'}
                onClick={() => setViewMode('table')}
                size="large"
                block
                style={{ height: '44px', fontSize: '16px' }}
              >
                表格
              </Button>
            </Col>
            <Col span={12}>
              <Button
                icon={<AppstoreOutlined />}
                type={viewMode === 'card' ? 'primary' : 'default'}
                onClick={() => setViewMode('card')}
                size="large"
                block
                style={{ height: '44px', fontSize: '16px' }}
              >
                卡片
              </Button>
            </Col>
          </Row>
          <div style={{ marginTop: 16 }}>
            <Search
              placeholder="搜索标题"
              allowClear
              style={{ width: '100%', height: '44px' }}
              onSearch={setSearchText}
            />
          </div>
        </div>

        <Space style={{ marginBottom: 20, width: '100%' }} direction="vertical" size="middle">
          <Row gutter={[12, 12]} align="middle">
            <Col xs={24} sm={12} md={8}>
              <Checkbox
                indeterminate={selectedRowKeys.length > 0 && selectedRowKeys.length < items.length}
                checked={selectedRowKeys.length === items.length && items.length > 0}
                onChange={(e) => {
                  if (e.target.checked) {
                    // 全选所有项(包括剧集组、季度、单集、电影)
                    const allKeys = [];
                    const collectKeys = (list) => {
                      list.forEach(item => {
                        allKeys.push(item.key);
                        if (item.children) {
                          collectKeys(item.children);
                        }
                      });
                    };
                    collectKeys(items);
                    setSelectedRowKeys(allKeys);
                  } else {
                    setSelectedRowKeys([]);
                  }
                }}
              >
                全选 ({selectedRowKeys.length}/{items.length})
              </Checkbox>
            </Col>
            <Col xs={24} sm={12} md={16}>
              <Space wrap>
                {/* 批量操作按钮已移至LibraryScan组件 */}
              </Space>
            </Col>
          </Row>
        </Space>

        {viewMode === 'table' ? (
          <Table
            columns={columns}
            dataSource={items}
            loading={loading}
            rowSelection={rowSelection}
            pagination={pagination}
            onChange={handleTableChange}
            expandable={{
              defaultExpandAllRows: false,
            }}
            scroll={{ x: 800 }}
            size="small"
            className="desktop-only"
          />
        ) : (
          <List
            loading={loading}
            dataSource={items}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => `${range[0]}-${range[1]} 共 ${total} 项`,
            }}
            onChange={(page, pageSize) => loadItems(page, pageSize)}
            renderItem={(item) => (
              <List.Item
                key={item.key}
                actions={[
                  <div key="mobile-actions" className="mobile-only">
                    {renderMobileActions(item)}
                  </div>,
                  <div key="desktop-actions" className="desktop-only">
                    {renderItemActions(item)}
                  </div>
                ]}
                style={{ padding: '20px 0' }}
              >
                <List.Item.Meta
                  title={
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <Checkbox
                        checked={selectedRowKeys.includes(item.key)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedRowKeys([...selectedRowKeys, item.key]);
                          } else {
                            setSelectedRowKeys(selectedRowKeys.filter(key => key !== item.key));
                          }
                        }}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        {item.mediaType === 'tv_season' ? (
                          <Button
                            type="link"
                            icon={<FolderOpenOutlined />}
                            onClick={() => handleOpenEpisodes(item)}
                            style={{ padding: 0, height: 'auto', fontSize: '16px' }}
                          >
                            {item.title}
                          </Button>
                        ) : (
                          <div style={{ fontSize: '18px', fontWeight: 500, lineHeight: '1.4' }}>
                            {item.title}
                          </div>
                        )}
                        {item.year && (
                          <div style={{ marginTop: '6px', color: '#666', fontSize: '15px' }}>
                            {item.year}
                          </div>
                        )}
                      </div>
                    </div>
                  }
                  description={
                    <div>
                      <div style={{ marginTop: '8px', marginLeft: '36px' }} className="desktop-only">
                        <Space size="small" wrap>
                          <Tag size="small" color="blue">
                            {item.mediaType === 'movie' ? '电影' : 
                             item.mediaType === 'tv_show' ? '电视剧' : 
                             item.mediaType === 'tv_season' ? '季' : item.mediaType}
                          </Tag>
                          {!item.isGroup && (
                            <Tag size="small" color={item.isImported ? 'success' : 'default'}>
                              {item.isImported ? '已导入' : '未导入'}
                            </Tag>
                          )}
                          {item.seasonCount && (
                            <Tag size="small" color="purple">
                              共{item.seasonCount}季
                            </Tag>
                          )}
                          {item.episodeCount && (
                            <Tag size="small" color="orange">
                              {item.episodeCount}集
                            </Tag>
                          )}
                        </Space>
                      </div>
                      <div className="mobile-only" style={{ marginTop: '12px', marginLeft: '36px' }}>
                        <Space size="middle" wrap>
                          <Tag size="small" color="blue" style={{ fontSize: '13px', padding: '2px 8px' }}>
                            {item.mediaType === 'movie' ? '电影' : 
                             item.mediaType === 'tv_show' ? '电视剧' : 
                             item.mediaType === 'tv_season' ? '季' : item.mediaType}
                          </Tag>
                          {!item.isGroup && (
                            <Tag size="small" color={item.isImported ? 'success' : 'default'} style={{ fontSize: '13px', padding: '2px 8px' }}>
                              {item.isImported ? '已导入' : '未导入'}
                            </Tag>
                          )}
                          {item.seasonCount && (
                            <Tag size="small" color="purple" style={{ fontSize: '13px', padding: '2px 8px' }}>
                              共{item.seasonCount}季
                            </Tag>
                          )}
                          {item.episodeCount && (
                            <Tag size="small" color="orange" style={{ fontSize: '13px', padding: '2px 8px' }}>
                              {item.episodeCount}集
                            </Tag>
                          )}
                        </Space>
                      </div>
                    </div>
                  }
                />
                {item.children && item.children.length > 0 && (
                  <div>
                    {item.children.map((child) => (
                      <List.Item
                        key={child.key}
                        actions={[
                          <div key="mobile-actions-child" className="mobile-only">
                            {renderMobileActions(child)}
                          </div>,
                          <div key="desktop-actions-child" className="desktop-only">
                            {renderItemActions(child)}
                          </div>
                        ]}
                        style={{
                          padding: '16px 0 16px 48px',
                          borderLeft: '2px solid #f0f0f0',
                          marginLeft: '12px'
                        }}
                        className="desktop-child-item mobile-child-item"
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', width: '100%' }}>
                          <Checkbox
                            checked={selectedRowKeys.includes(child.key)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedRowKeys([...selectedRowKeys, child.key]);
                              } else {
                                setSelectedRowKeys(selectedRowKeys.filter(key => key !== child.key));
                              }
                            }}
                          />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <Button
                              type="link"
                              icon={<FolderOpenOutlined />}
                              onClick={() => handleOpenEpisodes(child)}
                              style={{ padding: 0, height: 'auto', fontSize: '16px' }}
                            >
                              {child.title}
                            </Button>
                          </div>
                        </div>
                      </List.Item>
                    ))}
                  </div>
                )}
              </List.Item>
            )}
          />
        )}
      </Card>

      <MediaItemEditor
        visible={editorVisible}
        item={editingItem}
        onClose={() => setEditorVisible(false)}
        onSaved={handleEditorSaved}
      />

      <EpisodeListModal
        visible={episodeModalVisible}
        onClose={() => {
          setEpisodeModalVisible(false);
          setSelectedShow(null);
        }}
        serverId={selectedShow?.serverId}
        title={selectedShow?.title}
        season={selectedShow?.season}
        onRefresh={() => loadItems(pagination.current, pagination.pageSize)}
      />
    </>
  );
};

export default MediaItemList;

