import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Space, Input, message, Checkbox, Popconfirm, Tag } from 'antd';
import { SearchOutlined, DeleteOutlined, EditOutlined, ImportOutlined } from '@ant-design/icons';
import { getMediaItems, deleteMediaItem, batchDeleteMediaItems, importMediaItems } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';

const { Search } = Input;

const MediaItemList = ({ serverId, refreshTrigger }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [searchText, setSearchText] = useState('');
  const [pagination, setPagination] = useState({ current: 1, pageSize: 100, total: 0 });
  const [editorVisible, setEditorVisible] = useState(false);
  const [editingItem, setEditingItem] = useState(null);

  // 加载媒体项列表
  const loadItems = async (page = 1, pageSize = 100) => {
    setLoading(true);
    try {
      const res = await getMediaItems({
        server_id: serverId,
        page,
        page_size: pageSize,
      });
      const data = res.data;

      // 构建树形结构
      const treeData = buildTreeData(data.list);
      setItems(treeData);
      setPagination({
        current: page,
        pageSize,
        total: data.total,
      });
    } catch (error) {
      message.error('加载媒体项失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 构建树形数据结构
  const buildTreeData = (flatList) => {
    const movies = [];
    const tvShows = {};

    flatList.forEach(item => {
      if (item.mediaType === 'movie') {
        movies.push({
          ...item,
          key: `movie-${item.id}`,
        });
      } else if (item.mediaType === 'tv_series') {
        const showKey = `${item.title}`;
        if (!tvShows[showKey]) {
          tvShows[showKey] = {
            key: showKey,
            title: item.title,
            mediaType: 'tv_show',
            year: item.year,
            isGroup: true,
            children: {},
          };
        }

        const seasonKey = `${showKey}-S${item.season}`;
        if (!tvShows[showKey].children[seasonKey]) {
          tvShows[showKey].children[seasonKey] = {
            key: seasonKey,
            title: `第 ${item.season} 季`,
            season: item.season,
            mediaType: 'tv_season',
            isGroup: true,
            children: [],
          };
        }

        tvShows[showKey].children[seasonKey].children.push({
          ...item,
          key: `episode-${item.id}`,
          title: `第 ${item.episode} 集`,
        });
      }
    });

    // 转换为数组
    const result = [...movies];
    Object.values(tvShows).forEach(show => {
      show.children = Object.values(show.children).map(season => ({
        ...season,
        children: season.children.sort((a, b) => a.episode - b.episode),
      }));
      result.push(show);
    });

    return result;
  };

  useEffect(() => {
    if (serverId) {
      loadItems();
    }
  }, [serverId, refreshTrigger]);

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

  // 表格列定义
  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: '30%',
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

        // 单集和电影显示编辑和删除按钮
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
    onChange: setSelectedRowKeys,
    // 所有项都可以选择
  };

  return (
    <>
      <Card
        title="媒体项列表"
        extra={
          <Space>
            <Search
              placeholder="搜索标题"
              allowClear
              style={{ width: 200 }}
              onSearch={setSearchText}
            />
          </Space>
        }
      >
        <Space style={{ marginBottom: 16 }}>
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
            全选
          </Checkbox>
          <Popconfirm
            title="确定要删除选中的项目吗?"
            onConfirm={handleBatchDelete}
            okText="确定"
            cancelText="取消"
            disabled={selectedRowKeys.length === 0}
          >
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={selectedRowKeys.length === 0}
            >
              删除选中
            </Button>
          </Popconfirm>
          <Button
            type="primary"
            icon={<ImportOutlined />}
            onClick={handleImport}
            disabled={selectedRowKeys.length === 0}
          >
            导入选中
          </Button>
        </Space>

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
        />
      </Card>

      <MediaItemEditor
        visible={editorVisible}
        item={editingItem}
        onClose={() => setEditorVisible(false)}
        onSaved={handleEditorSaved}
      />
    </>
  );
};

export default MediaItemList;

