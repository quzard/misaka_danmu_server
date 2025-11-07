import { useState, useEffect, useMemo } from 'react';
import { Modal, Button, Space, Typography, message } from 'antd';
import { FolderOpenOutlined } from '@ant-design/icons';
import {
  FullFileBrowser,
  setChonkyDefaults,
  ChonkyActions,
  FileHelper
} from 'chonky';
import { ChonkyIconFA } from 'chonky-icon-fontawesome';
import { browseDirectory } from '../../../apis';
import './DirectoryBrowser.css';

// 设置Chonky默认配置
setChonkyDefaults({
  iconComponent: ChonkyIconFA,
  defaultFileViewActionId: ChonkyActions.EnableListView.id, // 默认列表视图
  disableDefaultFileActions: [
    ChonkyActions.UploadFiles.id,
    ChonkyActions.DownloadFiles.id,
    ChonkyActions.DeleteFiles.id,
    ChonkyActions.CreateFolder.id,
    ChonkyActions.CopyFiles.id,
    ChonkyActions.MoveFiles.id,
    ChonkyActions.OpenFiles.id, // 禁用双击打开
  ]
});

const { Text } = Typography;

// 将API返回的数据转换为Chonky格式
const convertToChonkyFiles = (apiFiles) => {
  return apiFiles.map(item => ({
    id: item.path,
    name: item.name,
    isDir: item.type === 'dir',
    modDate: item.modify_time ? new Date(item.modify_time) : new Date(),
    size: item.size || 0,
  }));
};

// 创建文件夹链
const createFolderChain = (currentPath) => {
  if (!currentPath || currentPath === '/') {
    return [{ id: '/', name: '根目录', isDir: true }];
  }

  const parts = currentPath.split('/').filter(p => p);
  const chain = [{ id: '/', name: '根目录', isDir: true }];

  let currentId = '/';
  for (const part of parts) {
    currentId = currentId === '/' ? `/${part}` : `${currentId}/${part}`;
    chain.push({
      id: currentId,
      name: part,
      isDir: true,
    });
  }

  return chain;
};

const DirectoryBrowser = ({ visible, onClose, onSelect }) => {
  const [loading, setLoading] = useState(false);
  const [currentPath, setCurrentPath] = useState('/');
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
      const chonkyFiles = convertToChonkyFiles(dirs);
      setFiles(chonkyFiles);
    } catch (error) {
      message.error('加载目录失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 创建文件夹链
  const folderChain = useMemo(() => createFolderChain(currentPath), [currentPath]);

  // 选择当前目录
  const handleSelectCurrent = () => {
    onSelect(currentPath);
    onClose();
  };

  return (
    <Modal
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <FolderOpenOutlined style={{ color: '#1890ff' }} />
          <span>选择目录</span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      width="95vw"
      style={{
        margin: 0,
        height: '90vh',
        maxWidth: 'none'
      }}
      bodyStyle={{
        padding: 0,
        height: 'calc(90vh - 120px)',
        overflow: 'hidden'
      }}
      footer={
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text type="secondary" style={{ fontSize: '12px' }}>
            当前目录: <Text strong>{currentPath || '/'}</Text>
          </Text>
          <Space>
            <Button onClick={onClose}>
              取消
            </Button>
            <Button onClick={handleSelectCurrent}>
              选择当前目录
            </Button>
          </Space>
        </div>
      }
    >
      <div style={{
        height: '100%',
        position: 'relative'
      }}>
        <FullFileBrowser
          files={files}
          folderChain={folderChain}
          onFileAction={(data) => {
            // 处理双击进入文件夹
            if (data.id === ChonkyActions.OpenFiles.id) {
              const { targetFile } = data.payload;
              if (targetFile && FileHelper.isDirectory(targetFile)) {
                setCurrentPath(targetFile.id);
              }
            }
          }}
          defaultFileViewActionId={ChonkyActions.EnableListView.id}
          disableSelection={true}
          disableDragAndDrop={true}
          darkMode={false}
          disableDefaultFileActions={[
            ChonkyActions.UploadFiles.id,
            ChonkyActions.DownloadFiles.id,
            ChonkyActions.DeleteFiles.id,
            ChonkyActions.CreateFolder.id,
            ChonkyActions.CopyFiles.id,
            ChonkyActions.MoveFiles.id,
            ChonkyActions.ToggleHiddenFiles.id,
            ChonkyActions.EnableGridView.id,
          ]}
        />
      </div>
    </Modal>
  );
};

export default DirectoryBrowser;

