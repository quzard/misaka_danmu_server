import { useState, useEffect } from 'react';
import { Card, Table, Button, Space, message, Popconfirm, Tag, Segmented, Input, Checkbox, Typography, List, Pagination, InputNumber, Popover } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined, FolderOpenOutlined, TableOutlined, AppstoreOutlined, ReloadOutlined, CalendarOutlined } from '@ant-design/icons';

const { Search } = Input;
const { Text } = Typography;
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
  const [allItems, setAllItems] = useState([]); // 缓存所有数据
  const [currentPageItems, setCurrentPageItems] = useState([]); // 当前页显示的数据
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 40,
    total: 0,
  });
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [editingItem, setEditingItem] = useState(null);
  const [editorVisible, setEditorVisible] = useState(false);
  const [episodeModalVisible, setEpisodeModalVisible] = useState(false);
  const [currentSeason, setCurrentSeason] = useState(null);
  const [viewMode, setViewMode] = useState('table'); // 添加视图模式状态
  const [mediaTypeFilter, setMediaTypeFilter] = useState('all'); // 添加类型过滤状态
  const [searchText, setSearchText] = useState(''); // 添加搜索状态
  const [isDataLoaded, setIsDataLoaded] = useState(false); // 添加数据加载标志
  const [yearFrom, setYearFrom] = useState();
  const [yearTo, setYearTo] = useState();

  // 检测是否为移动端
  const [isMobile, setIsMobile] = useState(false);

  // 初始加载数据
  useEffect(() => {
    if (!isDataLoaded) {
      loadItems(pagination.current, pagination.pageSize); // 使用缓存
    }
  }, [isDataLoaded]); // 只在组件首次加载时执行

  // 监听refreshTrigger变化，自动刷新数据
  useEffect(() => {
    if (refreshTrigger > 0) {
      refreshData();
    }
  }, [refreshTrigger]);

  useEffect(() => {
    if (isDataLoaded) {
      loadItems(1, pagination.pageSize, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [yearFrom, yearTo]);

  useEffect(() => {
    const checkMobile = () => {
      const mobile = window.innerWidth <= 768;
      setIsMobile(mobile);
      // 移动端默认使用卡片视图和20条每页
      if (mobile) {
        setViewMode('card');
        setPagination(prev => ({
          ...prev,
          pageSize: 20
        }));
      } else {
        // 桌面端恢复默认设置
        setPagination(prev => ({
          ...prev,
          pageSize: 50
        }));
      }
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // 处理筛选和搜索的客户端过滤
  useEffect(() => {
    if (allItems.length > 0 && isDataLoaded) {
      const filteredData = getFilteredData();
      
      // 计算当前页的数据
      const startIndex = (pagination.current - 1) * pagination.pageSize;
      const endIndex = startIndex + pagination.pageSize;
      const pageData = filteredData.slice(startIndex, endIndex);
      setCurrentPageItems(pageData);
      
      // 更新分页总数
      setPagination(prev => ({
        ...prev,
        total: filteredData.length
      }));
    }
  }, [mediaTypeFilter, searchText, allItems, isDataLoaded]);

  // 加载作品列表
  const loadItems = async (page = 1, pageSize = 50, forceRefresh = false) => {
    const hasYearFilter = yearFrom !== undefined && yearFrom !== null && yearFrom !== '' || yearTo !== undefined && yearTo !== null && yearTo !== '';
    // 检查缓存
    const cacheKey = 'localItemsCache';
    const cacheTimestampKey = 'localItemsCacheTimestamp';
    const cacheExpiry = 5 * 60 * 1000; // 5分钟缓存

    if (!forceRefresh && !hasYearFilter) {
      try {
        const cachedData = localStorage.getItem(cacheKey);
        const cachedTimestamp = localStorage.getItem(cacheTimestampKey);

        if (cachedData && cachedTimestamp) {
          const age = Date.now() - parseInt(cachedTimestamp);
          if (age < cacheExpiry) {
            const parsedData = JSON.parse(cachedData);
            setAllItems(parsedData);
            setIsDataLoaded(true);
            return; // 使用缓存数据
          }
        }
      } catch (error) {
        console.warn('读取缓存失败:', error);
      }
    }

    setLoading(true);
    try {
      const params = {
        page,
        page_size: pageSize,
      };

      if (yearFrom !== undefined && yearFrom !== null && yearFrom !== '') {
        params.year_from = yearFrom;
      }
      if (yearTo !== undefined && yearTo !== null && yearTo !== '') {
        params.year_to = yearTo;
      }

      const res = await getLocalWorks(params);
      const data = res.data;

      // 构建树形数据结构
      const treeData = await buildTreeData(data.list);

      // 缓存数据到localStorage
      try {
        localStorage.setItem(cacheKey, JSON.stringify(treeData));
        localStorage.setItem(cacheTimestampKey, Date.now().toString());
      } catch (error) {
        console.warn('保存缓存失败:', error);
      }

      // 缓存所有数据
      setAllItems(treeData);
      setIsDataLoaded(true); // 标记数据已加载
    } catch (error) {
      message.error('加载作品列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 客户端分页函数
  const handlePaginationChange = (page, pageSize) => {
    const newPagination = {
      ...pagination,
      current: page,
      pageSize: pageSize
    };
    setPagination(newPagination);
    
    // 根据当前筛选条件计算当前页的数据
    const filteredData = getFilteredData();
    const startIndex = (page - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    const pageData = filteredData.slice(startIndex, endIndex);
    
    setCurrentPageItems(pageData);
  };

  // 获取当前筛选后的数据
  const getFilteredData = () => {
    if (mediaTypeFilter !== 'all') {
      if (mediaTypeFilter === 'movie') {
        return allItems.filter(item => item.mediaType === 'movie');
      } else if (mediaTypeFilter === 'tv_series') {
        return allItems.filter(item =>
          item.mediaType === 'tv_season' || item.mediaType === 'tv_show'
        );
      }
    } else if (searchText) {
      const searchLower = searchText.toLowerCase();
      return allItems.filter(item =>
        item.title?.toLowerCase().includes(searchLower) ||
        item.workTitle?.toLowerCase().includes(searchLower) ||
        item.fileName?.toLowerCase().includes(searchLower) ||
        item.displayPath?.toLowerCase().includes(searchLower)
      );
    }
    return allItems;
  };

  // 刷新数据（重新扫描）
  const refreshData = async () => {
    setIsDataLoaded(false); // 重置加载标志，允许重新加载
    await loadItems(pagination.current, pagination.pageSize, true); // 强制刷新
  };

  // 构建树形数据结构(作品 -> 文件/季度)
  const buildTreeData = async (worksList) => {
    const result = [];

    for (const work of worksList) {
      if (work.type === 'movie') {
        // 电影 - 查询弹幕文件列表
        try {
          const filesRes = await getLocalMovieFiles(work.title, work.year);
          const files = filesRes.data?.list || [];

          // 创建电影作品节点
          result.push({
            key: `movie-${work.title}${work.year ? `-${work.year}` : ''}`,
            title: work.title,
            year: work.year,
            tmdbId: work.tmdbId,
            tvdbId: work.tvdbId,
            imdbId: work.imdbId,
            posterUrl: work.posterUrl,
            mediaType: 'movie',
            isGroup: true,
            // 子节点:弹幕文件
            children: files.map(f => ({
              key: `file-${f.id}`,
              id: f.id,
              title: f.filePath.split(/[/\\]/).pop(), // 文件名
              filePath: f.filePath,
              workTitle: work.title,
              year: f.year || work.year,
              tmdbId: f.tmdbId || work.tmdbId,
              tvdbId: f.tvdbId || work.tvdbId,
              imdbId: f.imdbId || work.imdbId,
              posterUrl: f.posterUrl || work.posterUrl,
              mediaType: 'movie_file',
              isImported: f.isImported,
              isGroup: false,
            }))
          });
        } catch (error) {
          console.error(`加载电影文件失败: ${work.title}`, error);
          // 即使加载失败,也添加作品节点
          result.push({
            key: `movie-${work.title}${work.year ? `-${work.year}` : ''}`,
            title: work.title,
            year: work.year,
            mediaType: 'movie',
            isGroup: true,
            children: [],
          });
        }
      } else if (work.type === 'tv_show') {
        // 电视剧 - 查询季度信息
        try {
          const seasonsRes = await getLocalShowSeasons(work.title);
          const seasons = seasonsRes.data || [];

          // 创建电视剧作品节点
          result.push({
            key: `show-${work.title}`,
            title: work.title,
            year: work.year,
            tmdbId: work.tmdbId,
            tvdbId: work.tvdbId,
            imdbId: work.imdbId,
            posterUrl: work.posterUrl,
            mediaType: 'tv_show',
            isGroup: true,
            // 子节点:季度
            children: seasons.map(s => ({
              key: `season-${work.title}-S${s.season}`,
              title: `第 ${s.season} 季`,
              showTitle: work.title,
              season: s.season,
              year: s.year || work.year,
              tmdbId: work.tmdbId,
              tvdbId: work.tvdbId,
              imdbId: work.imdbId,
              posterUrl: s.posterUrl || work.posterUrl,
              mediaType: 'tv_season',
              episodeCount: s.episodeCount,
              isGroup: false,
              ids: s.ids || [],
            }))
          });
        } catch (error) {
          console.error(`获取剧集 ${work.title} 的季度信息失败:`, error);
          // 即使加载失败,也添加作品节点
          result.push({
            key: `show-${work.title}`,
            title: work.title,
            year: work.year,
            mediaType: 'tv_show',
            isGroup: true,
            children: [],
          });
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
      refreshData();
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
      // 从选中的 keys 中提取所有 IDs
      const allIds = [];

      selectedRowKeys.forEach(key => {
        // 在 currentPageItems 和 allItems 中查找对应的项目
        const findItem = (items) => {
          for (const item of items) {
            if (item.key === key) {
              return item;
            }
            if (item.children) {
              const found = item.children.find(child => child.key === key);
              if (found) return found;
            }
          }
          return null;
        };

        const item = findItem(currentPageItems) || findItem(allItems);
        if (!item) return;

        // 根据不同类型提取 IDs
        if (item.isGroup && item.mediaType === 'tv_show') {
          // 电视剧作品组 - 收集所有季度的 IDs
          const seasonIds = item.children?.flatMap(child => child.ids || []) || [];
          allIds.push(...seasonIds);
        } else if (item.isGroup && item.mediaType === 'movie') {
          // 电影作品组 - 收集所有文件的 IDs
          const fileIds = item.children?.map(child => child.id).filter(id => id) || [];
          allIds.push(...fileIds);
        } else if (item.mediaType === 'tv_season') {
          // 季度 - 使用 ids 数组
          if (item.ids && item.ids.length > 0) {
            allIds.push(...item.ids);
          }
        } else if (item.mediaType === 'movie_file') {
          // 电影文件 - 使用 id
          if (item.id) {
            allIds.push(item.id);
          }
        }
      });

      if (allIds.length === 0) {
        message.warning('没有可删除的项目');
        return;
      }

      await batchDeleteLocalItems(allIds);
      message.success(`已删除 ${allIds.length} 个项目`);
      setSelectedRowKeys([]);
      refreshData();
    } catch (error) {
      message.error('批量删除失败: ' + (error.message || '未知错误'));
      console.error('批量删除错误:', error);
    }
  };

  // 获取分页配置
  const getPaginationConfig = (isTable = false) => ({
    ...pagination,
    showSizeChanger: true,
    showQuickJumper: false,
    onChange: handlePaginationChange,
    size: 'small',
    position: isTable ? ['bottomCenter'] : undefined,
    pageSizeOptions: ['10', '20', '50', '100', '200'],
    selectProps: { showSearch: false },
    style: isTable ? {
      marginTop: '16px',
      textAlign: 'center'
    } : {
      justifyContent: 'center'
    }
  });

  // 统一的筛选选项配置
  const filterOptions = [
    { label: '全部', value: 'all' },
    { label: '电影', value: 'movie' },
    { label: isMobile ? '电视' : '电视节目', value: 'tv_series' }
  ];

  const segmentedStyle = {
    backgroundColor: 'var(--color-card)',
    border: '1px solid var(--color-border)'
  };

  // 通用导入函数
  const handleImport = async (type, data) => {
    try {
      const res = await importLocalItems(data);
      message.success(res.data.message || '导入任务已提交');
      refreshData();
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
  };

  // 单个文件导入
  const handleImportSingleFile = async (record) => {
    if (!record.id) {
      message.error('文件ID不存在');
      return;
    }

    // 从文件名识别来源标签
    const filename = record.filePath.split(/[/\\]/).pop();
    const lowerFilename = filename.toLowerCase();
    let sourceLabel = 'unknown';

    if (lowerFilename.includes('bilibili') || lowerFilename.includes('哔哩')) {
      sourceLabel = 'bilibili';
    } else if (lowerFilename.includes('iqiyi') || lowerFilename.includes('爱奇艺')) {
      sourceLabel = 'iqiyi';
    } else if (lowerFilename.includes('tencent') || lowerFilename.includes('腾讯')) {
      sourceLabel = 'tencent';
    } else if (lowerFilename.includes('youku') || lowerFilename.includes('优酷')) {
      sourceLabel = 'youku';
    } else if (lowerFilename.includes('mgtv') || lowerFilename.includes('芒果')) {
      sourceLabel = 'mgtv';
    } else if (lowerFilename.includes('renren') || lowerFilename.includes('人人')) {
      sourceLabel = 'renren';
    }

    const mediaId = `custom_${sourceLabel}`;

    await handleImport('文件', {
      items: [{
        itemId: record.id,
        provider: 'custom',
        mediaId: mediaId,
      }]
    });
  };

  // 递归查找item的辅助函数
  const findItemByKey = (items, key) => {
    for (const item of items) {
      if (item.key === key) {
        return item;
      }
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
      // 递归查找对应的item
      const item = findItemByKey(allItems, key);
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

      await handleImport('批量', payload);
      setSelectedRowKeys([]);
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
        // 只有tv_season显示为可点击链接(电影不显示)
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
      width: '10%',
      render: (type, record) => {
        const typeMap = {
          movie: '电影',
          movie_file: '弹幕文件',
          tv_series: '电视节目',
          tv_show: '电视节目',
          tv_season: '季度',
        };
        // 如果是作品组,显示作品类型
        if (record.isGroup) {
          return <span style={{ fontSize: '12px' }}>{typeMap[type] || type}</span>;
        }
        return <span style={{ fontSize: '12px' }}>{typeMap[type] || type}</span>;
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
      width: '10%', // 调小状态列宽
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
      width: '20%', // 调大操作列宽
      render: (_, record) => {
        // 剧集组显示删除和导入整部按钮
        if (record.isGroup && record.mediaType === 'tv_show') {
          return (
            <Space size="small">
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  handleImport('剧集', {
                    shows: [{ title: record.title }]
                  });
                }}
              >
                导入整部
              </Button>
              <Popconfirm
                title={`确定要删除《${record.title}》的所有集吗?`}
                onConfirm={() => {
                  // 删除整部剧集 - 收集所有季度的IDs
                  const allIds = record.children?.flatMap(child => child.ids || []) || [];
                  if (allIds.length === 0) {
                    message.warning('该剧集没有可删除的项目');
                    return;
                  }
                  batchDeleteLocalItems(allIds)
                    .then(() => {
                      message.success(`成功删除《${record.title}》`);
                      refreshData();
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
            </Space>
          );
        }

        // 季度显示删除和导入按钮
        if (record.mediaType === 'tv_season') {
          return (
            <Space size="small">
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => {
                  handleImport('季度', {
                    seasons: [{
                      title: record.showTitle,
                      season: record.season
                    }]
                  });
                }}
              >
                导入整季
              </Button>
              <Popconfirm
                title={`确定要删除第${record.season}季的所有集吗?`}
                onConfirm={() => {
                  // 删除该季度 - 使用record.ids
                  if (record.ids && record.ids.length > 0) {
                    batchDeleteLocalItems(record.ids)
                      .then(() => {
                        message.success(`成功删除第${record.season}季`);
                        refreshData();
                      })
                      .catch(() => message.error('删除失败'));
                  } else {
                    message.warning('该季度没有可删除的项目');
                  }
                }}
                okText="确定"
                cancelText="取消"
              >
                <Button type="link" size="small" danger icon={<DeleteOutlined />}>
                  删除整季
                </Button>
              </Popconfirm>
            </Space>
          );
        }

        // 电影作品组操作
        if (record.isGroup && record.mediaType === 'movie') {
          return null; // 电影作品组不显示操作按钮
        }

        // 电影文件操作
        if (record.mediaType === 'movie_file') {
          return (
            <Space size="small">
              <Button
                type="link"
                size="small"
                icon={<ImportOutlined />}
                onClick={() => handleImportSingleFile(record)}
              >
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

        return null;
      },
    },
  ];

  // 渲染卡片操作按钮 (移动端 - 垂直排列,顺序:导入-编辑-删除)
  const renderCardActions = (record, excludeDelete = false, showText = true) => {
    if (record.isGroup && record.mediaType === 'tv_show') {
      const actions = [
        <Button
          key="import-show"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
            handleImport('剧集', {
              shows: [{ title: record.title }]
            });
          }}
        >
          {showText && '导入整部'}
        </Button>
      ];

      if (!excludeDelete) {
        actions.push(
          <Popconfirm
            key="delete-show"
            title={`确定要删除《${record.title}》的所有集吗?`}
            onConfirm={() => {
              // 删除整部剧集 - 收集所有季度的IDs
              const allIds = record.children?.flatMap(child => child.ids || []) || [];
              if (allIds.length === 0) {
                message.warning('该剧集没有可删除的项目');
                return;
              }
              batchDeleteLocalItems(allIds)
                .then(() => {
                  message.success(`成功删除《${record.title}》`);
                  refreshData();
                })
                .catch(() => message.error('删除失败'));
            }}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              {showText && '删除整部'}
            </Button>
          </Popconfirm>
        );
      }

      return actions;
    }

    if (record.mediaType === 'tv_season' || record.mediaType === 'tv_series') {
      const actions = [
        <Button
          key="import-season"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => {
            handleImport('季度', {
              seasons: [{
                title: record.showTitle,
                season: record.season
              }]
            });
          }}
        >
          {showText && '导入整季'}
        </Button>
      ];

      if (!excludeDelete) {
        actions.push(
          <Popconfirm
            key="delete-season"
            title={`确定要删除第${record.season}季的所有集吗?`}
            onConfirm={() => {
              // 删除该季度 - 使用record.ids
              if (record.ids && record.ids.length > 0) {
                batchDeleteLocalItems(record.ids)
                  .then(() => {
                    message.success(`成功删除第${record.season}季`);
                    refreshData();
                  })
                  .catch(() => message.error('删除失败'));
              } else {
                message.warning('该季度没有可删除的项目');
              }
            }}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              {showText && '删除整季'}
            </Button>
          </Popconfirm>
        );
      }

      return actions;
    }

    // 电影作品组节点,不显示操作按钮
    if (record.isGroup && record.mediaType === 'movie') {
      return [];
    }

    // 电影文件,显示导入、编辑、删除按钮 (顺序:导入-编辑-删除)
    if (record.mediaType === 'movie_file') {
      const actions = [
        <Button
          key="import-movie"
          type="link"
          size="small"
          icon={<ImportOutlined />}
          onClick={() => handleImportSingleFile(record)}
        >
          {showText && '导入'}
        </Button>,
        <Button
          key="edit-movie"
          type="link"
          size="small"
          icon={<EditOutlined />}
          onClick={() => handleEdit(record)}
        >
          {showText && '编辑'}
        </Button>
      ];

      if (!excludeDelete) {
        actions.push(
          <Popconfirm
            key="delete-movie"
            title="确定要删除吗?"
            onConfirm={() => handleDelete(record)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              {showText && '删除'}
            </Button>
          </Popconfirm>
        );
      }

      return actions;
    }

    return [];
  };



  return (
    <>
      <Card
        title={
          <div>
            <span className="desktop-only">本地扫描</span>
            <span className="mobile-only">本地扫描</span>
          </div>
        }
          extra={
            isMobile ? null : (
              <Space>
                <Segmented
                  value={mediaTypeFilter}
                  onChange={setMediaTypeFilter}
                  options={filterOptions}
                  style={segmentedStyle}
                />
                <Popover
                  trigger="click"
                  placement="bottomRight"
                  content={
                    <Space direction="vertical" size="small">
                      <Space size="small" align="center">
                        <InputNumber
                          placeholder="起始年份"
                          value={yearFrom}
                          onChange={setYearFrom}
                          min={1900}
                          max={2100}
                          controls={false}
                          style={{ width: 100 }}
                        />
                        <span>~</span>
                        <InputNumber
                          placeholder="结束年份"
                          value={yearTo}
                          onChange={setYearTo}
                          min={1900}
                          max={2100}
                          controls={false}
                          style={{ width: 100 }}
                        />
                      </Space>
                      {(yearFrom || yearTo) && (
                        <Button
                          type="link"
                          size="small"
                          onClick={() => {
                            setYearFrom(undefined);
                            setYearTo(undefined);
                          }}
                          style={{ padding: 0 }}
                        >
                          清空筛选
                        </Button>
                      )}
                    </Space>
                  }
                >
                  <Button
                    icon={<CalendarOutlined />}
                    size="small"
                  >
                    {yearFrom || yearTo
                      ? `年份: ${yearFrom || '?'}~${yearTo || '?'}`
                      : '年份'}
                  </Button>
                </Popover>
                <Popconfirm
                  title={`确定要删除选中的 ${selectedRowKeys.length} 个项目吗?`}
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
                onClick={handleBatchImport}
                disabled={selectedRowKeys.length === 0}
              >
                导入选中
              </Button>
            </Space>
          )
        }
        style={{ marginBottom: '16px' }}
      >
        {/* 移动端顶部操作区域 */}
        {isMobile && (
          <div style={{ marginBottom: '16px' }}>
            <div style={{ marginBottom: '12px' }}>
              <Segmented
                value={mediaTypeFilter}
                onChange={setMediaTypeFilter}
                options={filterOptions}
                block
                style={segmentedStyle}
              />
            </div>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <Popconfirm
                title={`确定要删除选中的 ${selectedRowKeys.length} 个项目吗?`}
                onConfirm={handleBatchDelete}
                okText="确定"
                cancelText="取消"
                disabled={selectedRowKeys.length === 0}
              >
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  disabled={selectedRowKeys.length === 0}
                  size="small"
                >
                  删除选中
                </Button>
              </Popconfirm>
              <Button
                type="primary"
                icon={<ImportOutlined />}
                onClick={handleBatchImport}
                disabled={selectedRowKeys.length === 0}
                size="small"
              >
                导入选中
              </Button>
            </div>
          </div>
        )}
        {/* 扫描列表标题 */}
        <div style={{ marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="desktop-only">扫描列表</span>
            <span className="mobile-only">扫描列表</span>
            <Button
              icon={<ReloadOutlined />}
              size="small"
              onClick={() => refreshData()}
              loading={loading}
            >
              刷新
            </Button>
          </div>
          <Space wrap>
            {!isMobile && (
              <>
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
                  type={viewMode === 'list' ? 'primary' : 'default'}
                  onClick={() => setViewMode('list')}
                  size="small"
                >
                  卡片
                </Button>
              </>
            )}
            <Search
              placeholder="搜索标题"
              allowClear
              style={isMobile ? { width: '100%', minWidth: '120px' } : { width: 200 }}
              onSearch={setSearchText}
            />
          </Space>
        </div>

        {(!isMobile && viewMode === 'table') ? (
          <Table
            columns={columns}
            dataSource={currentPageItems}
            loading={loading}
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
              checkStrictly: false,
            }}
            pagination={getPaginationConfig(true)}
            expandable={{
              defaultExpandAllRows: false,
            }}
            scroll={{ x: 800 }}
            size="small"
            className="desktop-only"
          />
        ) : (
          <>
            <List
              loading={loading}
              dataSource={currentPageItems}
              renderItem={(item) => {
                // 作品组节点
                if (item.isGroup) {
                  return (
                    <div key={item.key} style={{ marginBottom: 16 }}>
                      {/* 作品标题 */}
                      <div style={{
                        padding: '12px 16px',
                        background: 'var(--color-hover)',
                        borderRadius: '8px 8px 0 0',
                        borderBottom: '1px solid var(--color-border)'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                          <Checkbox
                            checked={selectedRowKeys.includes(item.key)}
                            indeterminate={
                              !selectedRowKeys.includes(item.key) &&
                              item.children?.some(child => selectedRowKeys.includes(child.key))
                            }
                            onChange={(e) => {
                              if (e.target.checked) {
                                // 选中父节点时,同时选中所有子节点
                                const childKeys = item.children?.map(child => child.key) || [];
                                setSelectedRowKeys([...new Set([...selectedRowKeys, item.key, ...childKeys])]);
                              } else {
                                // 取消选中父节点时,同时取消所有子节点
                                const childKeys = item.children?.map(child => child.key) || [];
                                setSelectedRowKeys(selectedRowKeys.filter(key => key !== item.key && !childKeys.includes(key)));
                              }
                            }}
                          />
                          <div style={{ flex: 1 }}>
                            <div style={{ fontSize: 16, fontWeight: 600 }}>
                              {item.title}
                              {item.year && <span style={{ marginLeft: 8, color: 'var(--color-text-secondary)', fontWeight: 400 }}>({item.year})</span>}
                            </div>
                            <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>
                              <Tag size="small" color={item.mediaType === 'movie' ? 'blue' : 'purple'}>
                                {item.mediaType === 'movie' ? '电影' : '电视节目'}
                              </Tag>
                              <span style={{ marginLeft: 8 }}>
                                {item.children?.length || 0} {item.mediaType === 'movie' ? '个文件' : '季'}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* 子项列表 */}
                      {item.children && item.children.length > 0 && (
                        <div style={{
                          background: 'var(--color-card)',
                          borderRadius: '0 0 8px 8px',
                          border: '1px solid var(--color-border)',
                          borderTop: 'none'
                        }}>
                          {item.children.map((child, index) => (
                            <div
                              key={child.key}
                              style={{
                                padding: '12px 16px 12px 48px',
                                borderBottom: index < item.children.length - 1 ? '1px solid var(--color-border)' : 'none'
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                <Checkbox
                                  checked={selectedRowKeys.includes(child.key)}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      // 选中子节点
                                      const newKeys = [...selectedRowKeys, child.key];
                                      // 检查是否所有子节点都被选中,如果是则自动选中父节点
                                      const allChildrenSelected = item.children?.every(c =>
                                        newKeys.includes(c.key)
                                      );
                                      if (allChildrenSelected && !newKeys.includes(item.key)) {
                                        newKeys.push(item.key);
                                      }
                                      setSelectedRowKeys(newKeys);
                                    } else {
                                      // 取消选中子节点时,同时取消父节点
                                      setSelectedRowKeys(selectedRowKeys.filter(key => key !== child.key && key !== item.key));
                                    }
                                  }}
                                />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ fontSize: 14 }}>
                                    {child.mediaType === 'tv_season' ? (
                                      <Button
                                        type="link"
                                        icon={<FolderOpenOutlined />}
                                        onClick={() => handleOpenEpisodes(child)}
                                        style={{ padding: 0, height: 'auto' }}
                                      >
                                        {child.title}
                                      </Button>
                                    ) : (
                                      child.title
                                    )}
                                  </div>
                                  <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>
                                    <Space size="small" wrap>
                                      <Tag size="small" color={child.mediaType === 'movie_file' ? 'cyan' : 'orange'}>
                                        {child.mediaType === 'movie_file' ? '弹幕文件' : `${child.episodeCount}集`}
                                      </Tag>
                                      {child.isImported !== undefined && (
                                        <Tag size="small" color={child.isImported ? 'success' : 'default'}>
                                          {child.isImported ? '已导入' : '未导入'}
                                        </Tag>
                                      )}
                                    </Space>
                                  </div>
                                </div>
                                <div className="mobile-only">{renderCardActions(child, false, false)}</div>
                                <div className="desktop-only">{renderCardActions(child, false, true)}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                }

                // 非分组节点(不应该出现在这里,但保留兼容性)
                return (
                  <List.Item
                    key={item.key}
                    actions={[
                      <div key="mobile-actions" className="mobile-only">{renderCardActions(item, false, false)}</div>,
                      <div key="desktop-actions" className="desktop-only">{renderCardActions(item, false, true)}</div>
                    ]}
                    style={{ padding: '12px 0' }}
                  >
                    <List.Item.Meta
                      title={
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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
                            <div style={{ fontSize: 16, fontWeight: 500 }}>
                              {item.title}
                            </div>
                          </div>
                        </div>
                      }
                      description={null}
                    />
                  </List.Item>
                );
              }}
            />
            {/* 自定义分页控件 */}
            <div style={{ textAlign: 'center', marginTop: '8px' }}>
              <Pagination
                {...getPaginationConfig(false)}
              />
            </div>
          </>
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
          refreshData();
        }}
      />

      <LocalEpisodeListModal
        visible={episodeModalVisible}
        season={currentSeason}
        onClose={() => {
          setEpisodeModalVisible(false);
          setCurrentSeason(null);
        }}
        onRefresh={() => refreshData()}
      />
    </>
  );
};

export default LocalItemList;

