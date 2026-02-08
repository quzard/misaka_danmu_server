import React, { useState, useEffect } from 'react';
import { Modal, Table, Button, Space, Input, message, Checkbox, Popconfirm, Tag } from 'antd';
import { SearchOutlined, DeleteOutlined, EditOutlined, ImportOutlined } from '@ant-design/icons';
import { getSeasonEpisodes, deleteMediaItem, batchDeleteMediaItems, importMediaItems } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';

const { Search } = Input;

const EpisodeListModal = ({ visible, onClose, serverId, title, season, onRefresh }) => {
  const [episodes, setEpisodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [searchText, setSearchText] = useState('');
  const [pagination, setPagination] = useState({ current: 1, pageSize: 100, total: 0 });
  const [editorVisible, setEditorVisible] = useState(false);
  const [editingItem, setEditingItem] = useState(null);

  // 加载分集列表
  const loadEpisodes = async (page = 1, pageSize = 100) => {
    if (!serverId || !title || season === null || season === undefined) return;
    
    setLoading(true);
    try {
      const res = await getSeasonEpisodes(title, season, serverId, page, pageSize);
      const data = res.data;
      
      setEpisodes(data.list || []);
      setPagination({
        current: page,
        pageSize,
        total: data.total || 0,
      });
    } catch (error) {
      message.error('加载分集列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (visible) {
      loadEpisodes();
      setSelectedRowKeys([]);
      setSearchText('');
    }
  }, [visible, serverId, title, season]);

  // 处理表格变化
  const handleTableChange = (newPagination) => {
    loadEpisodes(newPagination.current, newPagination.pageSize);
  };

  // 处理删除
  const handleDelete = async (record) => {
    try {
      await deleteMediaItem(record.id);
      message.success('删除成功');
      loadEpisodes(pagination.current, pagination.pageSize);
      if (onRefresh) onRefresh();
    } catch (error) {
      message.error('删除失败');
      console.error(error);
    }
  };

  // 批量删除
  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的集');
      return;
    }

    try {
      await batchDeleteMediaItems({ itemIds: selectedRowKeys });
      message.success('删除成功');
      setSelectedRowKeys([]);
      loadEpisodes(pagination.current, pagination.pageSize);
      if (onRefresh) onRefresh();
    } catch (error) {
      message.error('批量删除失败');
      console.error(error);
    }
  };

  // 处理编辑
  const handleEdit = (record) => {
    setEditingItem(record);
    setEditorVisible(true);
  };

  const handleEditorSaved = () => {
    setEditorVisible(false);
    loadEpisodes(pagination.current, pagination.pageSize);
    if (onRefresh) onRefresh();
  };

  // 批量导入
  const handleBatchImport = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要导入的集');
      return;
    }

    try {
      const res = await importMediaItems({ itemIds: selectedRowKeys });
      message.success(res.data.message || '导入任务已提交');
      setSelectedRowKeys([]);
      loadEpisodes(pagination.current, pagination.pageSize);
      if (onRefresh) onRefresh();
    } catch (error) {
      message.error('批量导入失败');
      console.error(error);
    }
  };

  // 过滤数据
  const filteredEpisodes = episodes.filter(ep => {
    if (!searchText) return true;
    const searchLower = searchText.toLowerCase();
    return (
      ep.title?.toLowerCase().includes(searchLower) ||
      ep.episode?.toString().includes(searchText) ||
      ep.tmdbId?.toLowerCase().includes(searchLower) ||
      ep.tvdbId?.toLowerCase().includes(searchLower) ||
      ep.imdbId?.toLowerCase().includes(searchLower)
    );
  });

  const columns = [
    {
      title: '集数',
      dataIndex: 'episode',
      key: 'episode',
      width: '10%',
      sorter: (a, b) => a.episode - b.episode,
      render: (episode) => `第 ${episode} 集`,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: '25%',
    },
    {
      title: 'TMDB ID',
      dataIndex: 'tmdbId',
      key: 'tmdbId',
      width: '15%',
      render: (tmdbId) => tmdbId || '-',
    },
    {
      title: 'TVDB ID',
      dataIndex: 'tvdbId',
      key: 'tvdbId',
      width: '15%',
      render: (tvdbId) => tvdbId || '-',
    },
    {
      title: 'IMDB ID',
      dataIndex: 'imdbId',
      key: 'imdbId',
      width: '15%',
      render: (imdbId) => imdbId || '-',
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '10%',
      render: (isImported) => {
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
      width: '16%',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button
            type="link"
            size="small"
            icon={<ImportOutlined />}
            onClick={() => {
              importMediaItems({ itemIds: [record.id] })
                .then((res) => {
                  message.success(res.data.message || '导入任务已提交');
                  loadEpisodes(pagination.current, pagination.pageSize);
                  if (onRefresh) onRefresh();
                })
                .catch(() => message.error('导入失败'));
            }}
          >
            导入
          </Button>
          <Popconfirm
            title="确定要删除这一集吗?"
            onConfirm={() => handleDelete(record)}
            okText="确定"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const rowSelection = {
    selectedRowKeys,
    onChange: (newSelectedRowKeys) => {
      setSelectedRowKeys(newSelectedRowKeys);
    },
  };

  return (
    <>
      <Modal
        title={`《${title}》- 第 ${season} 季`}
        open={visible}
        onCancel={onClose}
        width={1200}
        footer={[
          <Button key="close" onClick={onClose}>
            关闭
          </Button>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {/* 搜索和操作栏 */}
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Search
              placeholder="搜索集数、标题、ID..."
              allowClear
              style={{ width: 300 }}
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              prefix={<SearchOutlined />}
            />
            <Space>
              <Button
                type="primary"
                icon={<ImportOutlined />}
                onClick={handleBatchImport}
                disabled={selectedRowKeys.length === 0}
              >
                批量导入 ({selectedRowKeys.length})
              </Button>
              <Popconfirm
                title={`确定要删除选中的 ${selectedRowKeys.length} 集吗?`}
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
                  批量删除 ({selectedRowKeys.length})
                </Button>
              </Popconfirm>
            </Space>
          </Space>

          {/* 表格 */}
          <Table
            rowSelection={rowSelection}
            columns={columns}
            dataSource={filteredEpisodes}
            rowKey="id"
            loading={loading}
            pagination={{
              ...pagination,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (total) => `共 ${total} 集`,
            }}
            onChange={handleTableChange}
            size="small"
          />
        </Space>
      </Modal>

      {/* 编辑弹窗 */}
      {editorVisible && (
        <MediaItemEditor
          visible={editorVisible}
          item={editingItem}
          onClose={() => setEditorVisible(false)}
          onSaved={handleEditorSaved}
        />
      )}
    </>
  );
};

export default EpisodeListModal;

