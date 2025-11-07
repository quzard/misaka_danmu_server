import { useState, useEffect } from 'react';
import { Card, Table, Button, Space, message, Popconfirm, Tag, List, Checkbox, Row, Col } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined, FolderOpenOutlined, TableOutlined, AppstoreOutlined } from '@ant-design/icons';
import {
  getLocalWorks,
  getLocalMovieFiles,
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
  const [viewMode, setViewMode] = useState('table'); // 添加视图模式状态

  // 检测是否为移动端
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 768);
      // 移动端默认使用卡片视图
      if (window.innerWidth <= 768) {
        setViewMode('card');
      }
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

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

  // 构建树形数据结构(作品 > 季度/文件)
  const buildTreeData = async (worksList) => {
    const result = [];

    for (const work of worksList) {
      if (work.type === 'movie') {
        // 电影节点 - 查询弹幕文件列表
        try {
          const filesRes = await getLocalMovieFiles(work.title, work.year);
          const files = filesRes.data?.list || [];

          result.push({
            key: JSON.stringify(work.ids),  // 使用JSON序列化的ids数组作为key
            title: work.title,
            mediaType: 'movie',
            year: work.year,
            tmdbId: work.tmdbId,
            tvdbId: work.tvdbId,
            imdbId: work.imdbId,
            posterUrl: work.posterUrl,
            isGroup: true,
            itemCount: work.itemCount,
            children: files.map(f => ({
              key: f.id,  // 文件使用id作为key
              title: f.filePath.split(/[/\\]/).pop(),  // 显示文件名
              filePath: f.filePath,
              year: f.year,
              tmdbId: f.tmdbId,
              tvdbId: f.tvdbId,
              imdbId: f.imdbId,
              posterUrl: f.posterUrl,
              mediaType: 'movie_file',
              movieTitle: work.title,
              isGroup: false,
              isImported: f.isImported,
            })),
          });
        } catch (error) {
          console.error(`加载电影文件失败: ${work.title}`, error);
          // 如果加载失败,仍然显示电影节点,但没有子节点
          result.push({
            ...work,
            key: JSON.stringify(work.ids),
            isGroup: false,
          });
        }
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
      // 查找对应的item
      const item = findItemByKey(items, key);
      if (!item) return;

      if (item.mediaType === 'movie_file') {
        // 电影文件
        if (item.id) {
          itemIds.push(item.id);
        }
      } else if (item.mediaType === 'tv_show') {
        // 整部剧集
        shows.push({
          title: item.title
        });
      } else if (item.mediaType === 'tv_season') {
        // 某一季
        seasons.push({
          title: item.showTitle,
          season: item.season
        });
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
      width: '40%', // 增加标题列宽度
      render: (title, record) => {
        // 季度节点显示为可点击链接
        if (record.mediaType === 'tv_season') {
          return (
            <Button
              type="link"
              icon={<FolderOpenOutlined />}
              onClick={() => handleOpenEpisodes(record)}
              style={{ padding: 0, fontSize: '14px' }} // 调整字体大小
            >
              {title}
            </Button>
          );
        }
        return <span style={{ fontSize: '14px' }}>{title}</span>; // 调整字体大小
      },
    },
    {
      title: '类型',
      dataIndex: 'mediaType',
      key: 'mediaType',
      width: '15%', // 调整列宽
      render: (type) => {
        const typeMap = {
          movie: '电影',
          tv_series: '电视剧',
          tv_show: '电视剧',
          tv_season: '-',
        };
        return <span style={{ fontSize: '12px' }}>{typeMap[type] || type}</span>; // 调整字体大小
      },
    },
    {
      title: '年份',
      dataIndex: 'year',
      key: 'year',
      width: '15%', // 调整列宽
      render: (year) => <span style={{ fontSize: '12px' }}>{year || '-'}</span>, // 调整字体大小
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '15%', // 调整列宽
      render: (isImported, record) => {
        if (record.isGroup) return '-';
        return isImported ? (
          <Tag color="success" style={{ fontSize: '12px' }}>已导入</Tag> // 调整字体大小
        ) : (
          <Tag style={{ fontSize: '12px' }}>未导入</Tag> // 调整字体大小
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: '15%', // 调整列宽
      render: (_, record) => {
        // 剧集组显示删除和导入整部按钮
        if (record.isGroup && record.mediaType === 'tv_show') {
          return (
            <Space size="small" direction="vertical"> {/* 垂直排列按钮 */}
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
                <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ fontSize: '12px' }}>
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
                style={{ fontSize: '12px' }}
              >
                导入整部
              </Button>
            </Space>
          );
        }

        // 季度显示删除和导入按钮
        if (record.mediaType === 'tv_season') {
          return (
            <Space size="small" direction="vertical"> {/* 垂直排列按钮 */}
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
                <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ fontSize: '12px' }}>
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
                style={{ fontSize: '12px' }}
              >
                导入该季
              </Button>
            </Space>
          );
        }

        // 电影操作
        if (record.mediaType === 'movie') {
          return (
            <Space size="small" direction="vertical"> {/* 垂直排列按钮 */}
              <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} style={{ fontSize: '12px' }}>
                编辑
              </Button>
              <Popconfirm title="确定要删除吗?" onConfirm={() => handleDelete(record)} okText="确定" cancelText="取消">
                <Button type="link" size="small" danger icon={<DeleteOutlined />} style={{ fontSize: '12px' }}>
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

  // 渲染卡片操作按钮
  const renderCardActions = (record) => {
    if (record.isGroup && record.mediaType === 'tv_show') {
      return [
        <Popconfirm
          key="delete-show"
          title={`确定要删除《${record.title}》的所有集吗?`}
          onConfirm={() => {
            batchDeleteLocalItems({
              shows: [{ title: record.title }]
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
      ];
    }

    if (record.mediaType === 'tv_season') {
      return [
        <Popconfirm
          key="delete-season"
          title={`确定要删除第${record.season}季的所有集吗?`}
          onConfirm={() => {
            batchDeleteLocalItems({
              seasons: [{
                title: record.showTitle,
                season: record.season
              }]
            })
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
        </Popconfirm>,
        <Button
          key="import-season"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
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
      ];
    }

    if (record.mediaType === 'movie') {
      return [
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
          <Button type="link" size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ];
    }

    return [];
  };

  // 渲染卡片项目
  const renderCardItem = (item) => (
    <List.Item
      key={item.key}
      actions={renderCardActions(item)}
      style={{ padding: '16px 0' }}
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
                <div style={{ fontSize: '16px', fontWeight: 500 }}>
                  {item.title}
                </div>
              )}
              {item.year && (
                <div style={{ marginTop: '4px', color: '#666', fontSize: '14px' }}>
                  {item.year}
                </div>
              )}
            </div>
          </div>
        }
        description={
          <div>
            <div style={{ marginTop: '8px', marginLeft: '36px' }}>
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
          </div>
        }
      />
      {item.children && item.children.length > 0 && (
        <div>
          {item.children.map((child) => (
            <List.Item
              key={child.key}
              actions={renderCardActions(child)}
              style={{
                padding: '12px 0 12px 48px',
                borderLeft: '2px solid #f0f0f0',
                marginLeft: '12px'
              }}
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
                    style={{ padding: 0, height: 'auto', fontSize: '14px' }}
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
  );

  return (
    <>
      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
            <span style={{ fontSize: '16px', fontWeight: 500 }}>扫描结果</span>
            {!isMobile && (
              <div style={{ display: 'flex', gap: '4px' }}>
                <Button
                  icon={<TableOutlined />}
                  type={viewMode === 'table' ? 'primary' : 'text'}
                  onClick={() => setViewMode('table')}
                  size="small"
                  style={{ 
                    minWidth: '32px', 
                    height: '32px', 
                    padding: '4px',
                    border: viewMode === 'table' ? undefined : 'none'
                  }}
                  title="表格视图"
                />
                <Button
                  icon={<AppstoreOutlined />}
                  type={viewMode === 'card' ? 'primary' : 'text'}
                  onClick={() => setViewMode('card')}
                  size="small"
                  style={{ 
                    minWidth: '32px', 
                    height: '32px', 
                    padding: '4px',
                    border: viewMode === 'card' ? undefined : 'none'
                  }}
                  title="卡片视图"
                />
              </div>
            )}
          </div>
        }
        extra={
          <Space direction="horizontal" size="small" wrap>
            <Button
              type="primary"
              icon={<ImportOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={handleBatchImport}
              size="small"
              style={{ 
                fontSize: '12px',
                minWidth: 'auto',
                height: '28px',
                padding: '0 8px'
              }}
            >
              导入 ({selectedRowKeys.length})
            </Button>
            <Popconfirm
              title={`确定要删除选中的 ${selectedRowKeys.length} 个项目吗?`}
              onConfirm={handleBatchDelete}
              okText="确定"
              cancelText="取消"
              disabled={selectedRowKeys.length === 0}
            >
              <Button
                danger
                disabled={selectedRowKeys.length === 0}
                size="small"
                style={{ 
                  fontSize: '12px',
                  minWidth: 'auto',
                  height: '28px',
                  padding: '0 8px'
                }}
              >
                删除 ({selectedRowKeys.length})
              </Button>
            </Popconfirm>
          </Space>
        }
        style={{ marginBottom: '16px' }}
      >
        {/* 全选复选框 */}
        <div style={{ marginBottom: '16px' }}>
          <Checkbox
            indeterminate={selectedRowKeys.length > 0 && selectedRowKeys.length < items.length}
            checked={selectedRowKeys.length === items.length && items.length > 0}
            onChange={(e) => {
              if (e.target.checked) {
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
        </div>

        {viewMode === 'table' ? (
          <Table
            columns={columns}
            dataSource={items}
            loading={loading}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
              onChange: (page, pageSize) => loadItems(page, pageSize),
              size: 'default',
              position: ['bottomCenter'],
            }}
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
              checkStrictly: false,
              getCheckboxProps: (record) => ({
                disabled: record.isGroup && record.mediaType === 'movie',
              }),
            }}
            size="small"
            scroll={{ x: 600 }}
          />
        ) : (
          <List
            loading={loading}
            dataSource={items}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
              onChange: (page, pageSize) => loadItems(page, pageSize),
              size: 'default',
              position: ['bottomCenter'],
            }}
            renderItem={renderCardItem}
          />
        )}
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

