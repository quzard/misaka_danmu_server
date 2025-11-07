import { useState, useEffect } from 'react';
import { Card, Table, Button, Space, message, Popconfirm, Tag } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined, FolderOpenOutlined } from '@ant-design/icons';
import {
  getLocalWorks,
  getLocalShowSeasons,
  deleteLocalItem,
  batchDeleteLocalItems,
  importLocalItems
} from '../../../apis';
import MediaItemEditor from './MediaItemEditor';
import LocalEpisodeListModal from './LocalEpisodeListModal';

const LocalItemList = ({ refreshTrigger }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 100,
    total: 0,
  });
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [editingItem, setEditingItem] = useState(null);
  const [editorVisible, setEditorVisible] = useState(false);
  const [episodeModalVisible, setEpisodeModalVisible] = useState(false);
  const [currentSeason, setCurrentSeason] = useState(null);

  useEffect(() => {
    loadItems(pagination.current, pagination.pageSize);
  }, [refreshTrigger]);

  // 加载作品列表
  const loadItems = async (page = 1, pageSize = 100) => {
    setLoading(true);
    try {
      const res = await getLocalWorks({
        page,
        page_size: pageSize,
      });
      const data = res.data;

      // 构建树形结构
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
        // 电影节点 - 使用ids作为key
        result.push({
          ...work,
          key: JSON.stringify(work.ids),  // 使用JSON序列化的ids数组作为key
          isGroup: false,
        });
      } else if (work.type === 'tv_show') {
        // 电视剧组节点
        try {
          const seasonsRes = await getLocalShowSeasons(work.title);
          const seasons = seasonsRes.data || [];

          result.push({
            key: JSON.stringify(work.ids),  // 使用JSON序列化的ids数组作为key
            title: work.title,
            mediaType: 'tv_show',
            year: work.year,
            tmdbId: work.tmdbId,
            tvdbId: work.tvdbId,
            imdbId: work.imdbId,
            posterUrl: work.posterUrl,
            isGroup: true,
            seasonCount: work.seasonCount,
            episodeCount: work.episodeCount,
            children: seasons.map(s => ({
              key: JSON.stringify(s.ids),  // 使用JSON序列化的ids数组作为key
              title: `第 ${s.season} 季 (${s.episodeCount}集)`,
              season: s.season,
              episodeCount: s.episodeCount,
              year: s.year,
              posterUrl: s.posterUrl,
              mediaType: 'tv_season',
              showTitle: work.title,
              isGroup: true,
            })),
          });
        } catch (error) {
          console.error(`获取剧集 ${work.title} 的季度信息失败:`, error);
        }
      }
    }

    return result;
  };

  // 打开集列表
  const handleOpenEpisodes = (record) => {
    setCurrentSeason({
      title: record.showTitle,
      season: record.season,
    });
    setEpisodeModalVisible(true);
  };

  // 编辑
  const handleEdit = (record) => {
    setEditingItem(record);
    setEditorVisible(true);
  };

  // 删除
  const handleDelete = async (record) => {
    try {
      await deleteLocalItem(record.id);
      message.success('删除成功');
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('删除失败: ' + (error.message || '未知错误'));
    }
  };

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的项目');
      return;
    }

    try {
      // 将JSON字符串解析回ID数组
      const itemIds = selectedRowKeys.map(key => JSON.parse(key));
      await batchDeleteLocalItems(itemIds);
      message.success(`已删除 ${selectedRowKeys.length} 个项目`);
      setSelectedRowKeys([]);
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('批量删除失败: ' + (error.message || '未知错误'));
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

  // 批量导入
  const handleBatchImport = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要导入的项目');
      return;
    }

    // 分类收集要导入的项目
    const itemIds = [];
    const shows = [];
    const seasons = [];

    selectedRowKeys.forEach(key => {
      if (key.startsWith('movie-')) {
        // 电影(需要从后端获取ID)
        const item = findItemByKey(items, key);
        if (item && item.id) {
          itemIds.push(item.id);
        }
      } else {
        // 查找对应的item
        const item = findItemByKey(items, key);
        if (!item) return;

        if (item.mediaType === 'tv_season') {
          // 某一季
          seasons.push({
            title: item.showTitle,
            season: item.season
          });
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

      const res = await importLocalItems(payload);
      message.success(res.data.message || '导入任务已提交');
      setSelectedRowKeys([]);
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
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
                  // 删除整部剧集 - 使用record.key中的ids
                  const ids = JSON.parse(record.key);
                  batchDeleteLocalItems([ids])
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
                  importLocalItems({
                    shows: [{ title: record.title }]
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
                  // 删除该季度 - 使用record.key中的ids
                  const ids = JSON.parse(record.key);
                  batchDeleteLocalItems([ids])
                    .then(() => {
                      message.success(`成功删除第${record.season}季`);
                      loadItems(pagination.current, pagination.pageSize);
                    })
                    .catch(() => message.error('删除失败'));
                }}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除该季
                </Button>
              </Popconfirm>
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  // 导入该季度
                  importLocalItems({
                    seasons: [{
                      title: record.showTitle,
                      season: record.season
                    }]
                  })
                    .then((res) => {
                      message.success(res.data.message || '导入任务已提交');
                      loadItems(pagination.current, pagination.pageSize);
                    })
                    .catch(() => message.error('导入失败'));
                }}
              >
                导入该季
              </Button>
            </Space>
          );
        }

        // 电影操作
        if (record.mediaType === 'movie') {
          return (
            <Space size="small">
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
                编辑
              </Button>
              <Popconfirm title="确定要删除吗?" onConfirm={() => handleDelete(record)} okText="确定" cancelText="取消">
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            </Space>
          );
        }

        return null;
      },
    },
  ];

  return (
    <>
      <Card
        title="扫描结果"
        extra={
          <Space>
            <Button
              type="primary"
              icon={<ImportOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={handleBatchImport}
            >
              批量导入 ({selectedRowKeys.length})
            </Button>
            <Popconfirm
              title={`确定要删除选中的 ${selectedRowKeys.length} 个项目吗?`}
              onConfirm={handleBatchDelete}
              okText="确定"
              cancelText="取消"
              disabled={selectedRowKeys.length === 0}
            >
              <Button danger disabled={selectedRowKeys.length === 0}>
                批量删除 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个作品`,
            onChange: (page, pageSize) => loadItems(page, pageSize),
          }}
          rowSelection={{
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            getCheckboxProps: (record) => ({
              disabled: record.isGroup && record.mediaType === 'tv_show',
            }),
          }}
        />
      </Card>

      <MediaItemEditor
        visible={editorVisible}
        item={editingItem}
        isLocal={true}
        onClose={() => {
          setEditorVisible(false);
          setEditingItem(null);
        }}
        onSaved={() => {
          setEditorVisible(false);
          setEditingItem(null);
          loadItems(pagination.current, pagination.pageSize);
        }}
      />

      <LocalEpisodeListModal
        visible={episodeModalVisible}
        season={currentSeason}
        onClose={() => {
          setEpisodeModalVisible(false);
          setCurrentSeason(null);
        }}
        onRefresh={() => loadItems(pagination.current, pagination.pageSize)}
      />
    </>
  );
};

export default LocalItemList;

