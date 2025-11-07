import { useState, useEffect } from 'react';
import { Modal, Table, Breadcrumb, message, Spin, Button, Space } from 'antd';
import { FolderOutlined, FileOutlined, HomeOutlined, ReloadOutlined } from '@ant-design/icons';
import { browseDirectory } from '../../../apis';

const DirectoryBrowser = ({ visible, onClose, onSelect }) => {
  const [loading, setLoading] = useState(false);
  const [currentPath, setCurrentPath] = useState('/');
  const [pathHistory, setPathHistory] = useState(['/']);
  const [files, setFiles] = useState([]);

  useEffect(() => {
    if (visible) {
      loadDirectory(currentPath);
    }
  }, [visible, currentPath]);

  const loadDirectory = async (path) => {
    setLoading(true);
    try {
      const response = await browseDirectory({
        storage: 'local',
        type: 'dir',
        path: path,
        name: ''
      }, 'name');
      
      // 只显示目录,不显示文件
      const dirs = response.data.filter(item => item.type === 'dir');
      setFiles(dirs);
    } catch (error) {
      message.error('加载目录失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleRowClick = (record) => {
    if (record.type === 'dir') {
      const newPath = record.path;
      setCurrentPath(newPath);
      setPathHistory([...pathHistory, newPath]);
    }
  };

  const handleBreadcrumbClick = (index) => {
    const newPath = pathHistory[index];
    setCurrentPath(newPath);
    setPathHistory(pathHistory.slice(0, index + 1));
  };

  const handleGoHome = () => {
    setCurrentPath('/');
    setPathHistory(['/']);
  };

  const handleRefresh = () => {
    loadDirectory(currentPath);
  };

  const handleSelect = () => {
    onSelect(currentPath);
    onClose();
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (text, record) => (
        <Space>
          {record.type === 'dir' ? <FolderOutlined /> : <FileOutlined />}
          <span>{text}</span>
        </Space>
      ),
    },
    {
      title: '修改时间',
      dataIndex: 'modify_time',
      key: 'modify_time',
      width: 200,
      render: (time) => time ? new Date(time).toLocaleString() : '-',
    },
  ];

  // 生成面包屑
  const breadcrumbItems = pathHistory.map((path, index) => ({
    title: index === 0 ? <HomeOutlined /> : path.split('/').pop() || path,
    onClick: () => handleBreadcrumbClick(index),
    style: { cursor: 'pointer' }
  }));

  return (
    <Modal
      title="选择目录"
      open={visible}
      onCancel={onClose}
      width={800}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="select" type="primary" onClick={handleSelect}>
          选择当前目录
        </Button>,
      ]}
    >
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        <Space>
          <Button icon={<HomeOutlined />} onClick={handleGoHome}>
            根目录
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh}>
            刷新
          </Button>
        </Space>

        <Breadcrumb items={breadcrumbItems} />

        <div style={{ padding: '8px', background: '#f5f5f5', borderRadius: '4px' }}>
          当前路径: {currentPath}
        </div>

        <Spin spinning={loading}>
          <Table
            columns={columns}
            dataSource={files}
            rowKey="path"
            pagination={false}
            onRow={(record) => ({
              onClick: () => handleRowClick(record),
              style: { cursor: 'pointer' },
            })}
            locale={{
              emptyText: '该目录下没有子目录'
            }}
            scroll={{ y: 400 }}
          />
        </Spin>
      </Space>
    </Modal>
  );
};

export default DirectoryBrowser;

