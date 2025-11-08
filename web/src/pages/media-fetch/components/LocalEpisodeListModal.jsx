import { useState, useEffect } from 'react';
import { Modal, Table, Button, Space, message, Popconfirm } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined } from '@ant-design/icons';
import { getLocalSeasonEpisodes, deleteLocalItem, importLocalItems } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';

const LocalEpisodeListModal = ({ visible, season, onClose, onRefresh }) => {
  const [episodes, setEpisodes] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 100,
    total: 0,
  });
  const [editingItem, setEditingItem] = useState(null);
  const [editorVisible, setEditorVisible] = useState(false);

  useEffect(() => {
    if (visible && season) {
      loadEpisodes(1, pagination.pageSize);
    }
  }, [visible, season]);

  const loadEpisodes = async (page = 1, pageSize = 100) => {
    if (!season) return;

    setLoading(true);
    try {
      const res = await getLocalSeasonEpisodes(season.title, season.season, page, pageSize);
      const data = res.data;
      setEpisodes(data.list);
      setPagination({
        current: page,
        pageSize,
        total: data.total,
      });
    } catch (error) {
      message.error('加载分集列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleEdit = (record) => {
    setEditingItem(record);
    setEditorVisible(true);
  };

  const handleDelete = async (record) => {
    try {
      await deleteLocalItem(record.id);
      message.success('删除成功');
      loadEpisodes(pagination.current, pagination.pageSize);
      onRefresh?.();
    } catch (error) {
      message.error('删除失败: ' + (error.message || '未知错误'));
    }
  };

  const handleImport = async (record) => {
    try {
      const res = await importLocalItems({ itemIds: [record.id] });
      message.success(res.data.message || '导入任务已提交');
      loadEpisodes(pagination.current, pagination.pageSize);
      onRefresh?.();
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
    }
  };

  const columns = [
    {
      title: '集数',
      dataIndex: 'episode',
      key: 'episode',
      width: '15%',
      render: (ep) => `第 ${ep} 集`,
    },
    {
      title: '文件路径',
      dataIndex: 'filePath',
      key: 'filePath',
      width: '37.5%',
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '15%',
      render: (imported) => (imported ? '已导入' : '未导入'),
    },
    {
      title: '操作',
      key: 'action',
      width: '20%',
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<ImportOutlined />}
            onClick={() => handleImport(record)}
            disabled={record.isImported}
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
      ),
    },
  ];

  return (
    <>
      <Modal
        title={season ? `${season.title} - 第 ${season.season} 季` : '分集列表'}
        open={visible}
        onCancel={onClose}
        footer={null}
        width={1000}
      >
        <Table
          columns={columns}
          dataSource={episodes}
          loading={loading}
          rowKey="id"
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 集`,
            onChange: (page, pageSize) => loadEpisodes(page, pageSize),
          }}
        />
      </Modal>

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
          loadEpisodes(pagination.current, pagination.pageSize);
          onRefresh?.();
        }}
      />
    </>
  );
};

export default LocalEpisodeListModal;

