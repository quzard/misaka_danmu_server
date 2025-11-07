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
        // 电影节点
        result.push({
          ...work,
          key: `movie-${work.title}`,
          isGroup: false,
        });
      } else if (work.type === 'tv_show') {
        // 电视剧组节点
        try {
          const seasonsRes = await getLocalShowSeasons(work.title);
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
      await batchDeleteLocalItems(selectedRowKeys);
      message.success(`已删除 ${selectedRowKeys.length} 个项目`);
      setSelectedRowKeys([]);
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('批量删除失败: ' + (error.message || '未知错误'));
    }
  };

  // 导入
  const handleImport = async (record) => {
    try {
      const payload = {};
      if (record.mediaType === 'movie') {
        // 电影: 导入单个项目(需要从后端获取ID)
        message.warning('电影导入功能待实现');
        return;
      } else if (record.mediaType === 'tv_show') {
        // 电视剧组: 导入所有集
        payload.shows = [{ title: record.title }];
      } else if (record.mediaType === 'tv_season') {
        // 季度: 导入该季所有集
        payload.seasons = [{ title: record.showTitle, season: record.season }];
      }

      const res = await importLocalItems(payload);
      message.success(res.data.message || '导入任务已提交');
      loadItems(pagination.current, pagination.pageSize);
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
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
      title: 'TMDB ID',
      dataIndex: 'tmdbId',
      key: 'tmdbId',
      width: '10%',
      render: (id) => id || '-',
    },
    {
      title: '统计',
      key: 'stats',
      width: '15%',
      render: (_, record) => {
        if (record.mediaType === 'tv_show') {
          return `${record.seasonCount || 0}季 / ${record.episodeCount || 0}集`;
        } else if (record.mediaType === 'tv_season') {
          return `${record.episodeCount || 0}集`;
        }
        return '-';
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '25%',
      render: (_, record) => {
        // 电影操作
        if (record.mediaType === 'movie') {
          return (
            <Space size="small">
              <Button type="link" size="small" icon={<ImportOutlined />} onClick={() => handleImport(record)}>
                导入
              </Button>
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

        // 电视剧组和季度操作
        return (
          <Space size="small">
            <Button type="link" size="small" icon={<ImportOutlined />} onClick={() => handleImport(record)}>
              导入
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <>
      <Card
        title="扫描结果"
        extra={
          <Space>
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

