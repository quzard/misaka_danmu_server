import { useState, useEffect } from 'react';
import { Modal, Table, Button, Space, message, Popconfirm, Radio, Select } from 'antd';
import { DeleteOutlined, EditOutlined, ImportOutlined } from '@ant-design/icons';
import { getLocalMovieFiles, deleteLocalItem, importLocalItems, addSourceToAnime } from '../../../apis';
import MediaItemEditor from './MediaItemEditor';

// 来源标签选项(仅用于显示)
const SOURCE_LABELS = [
  { value: 'unknown', label: '未知来源' },
  { value: 'bilibili', label: 'Bilibili' },
  { value: 'tencent', label: '腾讯视频' },
  { value: 'iqiyi', label: '爱奇艺' },
  { value: 'youku', label: '优酷' },
  { value: 'mgtv', label: '芒果TV' },
  { value: 'renren', label: '人人视频' },
];

// 从文件名识别来源标签
const detectSourceLabelFromFilename = (filename) => {
  const lowerFilename = filename.toLowerCase();
  if (lowerFilename.includes('bilibili') || lowerFilename.includes('哔哩')) {
    return 'bilibili';
  }
  if (lowerFilename.includes('iqiyi') || lowerFilename.includes('爱奇艺')) {
    return 'iqiyi';
  }
  if (lowerFilename.includes('tencent') || lowerFilename.includes('腾讯')) {
    return 'tencent';
  }
  if (lowerFilename.includes('youku') || lowerFilename.includes('优酷')) {
    return 'youku';
  }
  if (lowerFilename.includes('mgtv') || lowerFilename.includes('芒果')) {
    return 'mgtv';
  }
  if (lowerFilename.includes('renren') || lowerFilename.includes('人人')) {
    return 'renren';
  }
  return 'unknown';
};

// 生成mediaId: custom_{sourceLabel}
const generateMediaId = (sourceLabel) => {
  return `custom_${sourceLabel}`;
};

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
  // 文件来源配置: { fileId: { sourceLabel: 'bilibili', mediaId: 'custom_bilibili' } }
  const [fileSourceConfig, setFileSourceConfig] = useState({});

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

      // 初始化文件来源配置
      const sourceConfig = {};
      if (data.list && data.list.length > 0) {
        data.list.forEach((file) => {
          const filename = file.filePath.split(/[/\\]/).pop();
          const detectedLabel = detectSourceLabelFromFilename(filename);
          sourceConfig[file.id] = {
            sourceLabel: detectedLabel,
            mediaId: generateMediaId(detectedLabel),
          };
        });
        setFileSourceConfig(sourceConfig);

        // 自动选择第一个未导入的文件,如果没有则选择第一个
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

    const config = fileSourceConfig[selectedFileId];
    if (!config) {
      message.error('文件配置丢失');
      return;
    }

    try {
      // 使用高级导入API,provider固定为custom,mediaId为custom_{sourceLabel}
      const res = await importLocalItems({
        items: [{
          itemId: selectedFileId,
          provider: 'custom',
          mediaId: config.mediaId,
        }]
      });
      message.success(res.data.message || '导入任务已提交');
      onClose();
      onRefresh?.();
    } catch (error) {
      message.error('导入失败: ' + (error.message || '未知错误'));
    }
  };

  // 更新文件的来源标签
  const handleSourceLabelChange = (fileId, sourceLabel) => {
    setFileSourceConfig(prev => ({
      ...prev,
      [fileId]: {
        sourceLabel,
        mediaId: generateMediaId(sourceLabel),
      }
    }));
  };

  const columns = [
    {
      title: '选择',
      key: 'select',
      width: '6%',
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
      width: '35%',
      ellipsis: true,
    },
    {
      title: '来源标签',
      key: 'sourceLabel',
      width: '15%',
      render: (_, record) => {
        const config = fileSourceConfig[record.id];
        return (
          <Select
            value={config?.sourceLabel || 'unknown'}
            onChange={(value) => handleSourceLabelChange(record.id, value)}
            options={SOURCE_LABELS}
            style={{ width: '100%' }}
            size="small"
          />
        );
      },
    },
    {
      title: 'NFO路径',
      dataIndex: 'nfoPath',
      key: 'nfoPath',
      width: '25%',
      ellipsis: true,
      render: (path) => path || '-',
    },
    {
      title: '状态',
      dataIndex: 'isImported',
      key: 'isImported',
      width: '10%',
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

