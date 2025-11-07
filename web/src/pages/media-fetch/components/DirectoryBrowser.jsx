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
  const [selectedFiles, setSelectedFiles] = useState([]);

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
      message.error('加载目录失败：' + (error.message || '未知错误'));
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
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          fontSize: '16px',
          fontWeight: 600,
          color: 'var(--color-text)'
        }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'var(--color-primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'white'
          }}>
            <FolderOpenOutlined style={{ fontSize: '16px' }} />
          </div>
          <span>目录浏览器</span>
        </div>
      }
      open={visible}
      onCancel={onClose}
      width="95vw"
      style={{
        margin: '2vh 2.5vw 4vh',
        top: '2vh',
        height: '94vh',
        maxWidth: 'none',
        paddingBottom: 0,
        borderRadius: '12px',
        overflow: 'hidden'
      }}
      bodyStyle={{
        padding: 0,
        height: 'calc(94vh - 120px)',
        overflow: 'hidden',
        background: 'var(--color-bg)'
      }}
      footer={
        <div style={{
          display: 'flex',
          justifyContent: 'flex-end',
          alignItems: 'center',
          gap: '12px',
          padding: '12px 24px',
          background: 'var(--color-card)',
          borderTop: '1px solid var(--color-border)',
          borderRadius: '0 0 12px 12px'
        }}>
          <Button
            onClick={onClose}
            style={{
              borderRadius: '6px',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
              padding: '6px 16px',
              height: '32px',
              fontSize: '14px'
            }}
          >
            取消
          </Button>
          <Button
            type="primary"
            onClick={handleSelectCurrent}
            style={{
              borderRadius: '6px',
              background: 'var(--color-primary)',
              border: 'none',
              fontWeight: 500,
              padding: '6px 16px',
              height: '32px',
              fontSize: '14px'
            }}
          >
            选择此目录
          </Button>
        </div>
      }
      destroyOnClose
      maskClosable={false}
      centered={false}
    >
      <div style={{
        height: '100%',
        position: 'relative',
        overflow: 'hidden'
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

