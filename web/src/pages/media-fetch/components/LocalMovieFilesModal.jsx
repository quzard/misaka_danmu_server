import { useState, useEffect } from 'react';
import { Modal, Table, Button, Space, message, Popconfirm, Radio } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined } from '@ant-design/icons';
import { getLocalMovieFiles, deleteLocalItem, importLocalItems } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';

const LocalMovieFilesModal = ({ visible, movie, onClose, onRefresh }) => {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 100,
    total: 0,
  });
  const [editorVisible, setEditorVisible] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [selectedFileId, setSelectedFileId] = useState(null);

  useEffect(() => {
    if (visible && movie) {
      loadFiles(pagination.current, pagination.pageSize);
    }
  }, [visible, movie]);

  const loadFiles = async (page, pageSize) => {
    if (!movie) return;

    setLoading(true);
    try {
      const res = await getLocalMovieFiles(movie.title, movie.year, page, pageSize);
      const data = res.data;
      setFiles(data.list || []);
      setPagination({
        current: page,
        pageSize: pageSize,
        total: data.total || 0,
      });
      
      // 自动选择第一个未导入的文件,如果没有则选择第一个
      if (data.list && data.list.length > 0) {
        const firstNotImported = data.list.find(f => !f.isImported);
        setSelectedFileId(firstNotImported ? firstNotImported.id : data.list[0].id);
      }
    } catch (error) {
      message.error('加载文件列表失败: ' + (error.message || '未知错误'));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteLocalItem(id);
      message.success('删除成功');
      loadFiles(pagination.current, pagination.pageSize);
      onRefresh?.();
    } catch (error) {
      message.error('删除失败: ' + (error.message || '未知错误'));
    }
  };

  const handleEdit = (record) => {
    setEditingItem(record);
    setEditorVisible(true);
  };

  const handleImport = async () => {
    if (!selectedFileId) {
      message.warning('请选择要导入的文件');
      return;
    }

    try {
      const res = await importLocalItems({ itemIds: [selectedFileId] });
      message.success(res.data.message || '导入任务已提交');
      onClose();
      onRefresh?.();
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
    }
  };

  const columns = [
    {
      title: '选择',
      key: 'select',
      width: '8%',
      render: (_, record) => (
        <Radio
          checked={selectedFileId === record.id}
          onChange={() => setSelectedFileId(record.id)}
        />
      ),
    },
    {
      title: '文件路径',
      dataIndex: 'filePath',
      key: 'filePath',
      width: '50%',
      ellipsis: true,
    },
    {
      title: 'NFO路径',
      dataIndex: 'nfoPath',
      key: 'nfoPath',
      width: '30%',
      ellipsis: true,
      render: (path) => path || '-',
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '12%',
      render: (imported) => (imported ? '已导入' : '未导入'),
    },
  ];

  return (
    <>
      <Modal
        title={movie ? `${movie.title}${movie.year ? ` (${movie.year})` : ''} - 选择弹幕文件` : '选择弹幕文件'}
        open={visible}
        onCancel={onClose}
        width={1000}
        footer={[
          <Button key="cancel" onClick={onClose}>
            取消
          </Button>,
          <Button
            key="import"
            type="primary"
            icon={<ImportOutlined />}
            onClick={handleImport}
            disabled={!selectedFileId}
          >
            导入选中的文件
          </Button>,
        ]}
      >
        <Table
          columns={columns}
          dataSource={files}
          loading={loading}
          rowKey="id"
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 个文件`,
            onChange: (page, pageSize) => loadFiles(page, pageSize),
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
          loadFiles(pagination.current, pagination.pageSize);
          onRefresh?.();
        }}
      />
    </>
  );
};

export default LocalMovieFilesModal;

