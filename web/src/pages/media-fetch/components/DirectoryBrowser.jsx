import { useState, useEffect, useMemo } from 'react';
import { Modal, Button, Space, Typography, message } from 'antd';
import { FolderOpenOutlined } from '@ant-design/icons';
import {
  FullFileBrowser,
  setChonkyDefaults,
  ChonkyActions,
  FileHelper,
  defineFileAction
} from 'chonky';
import { ChonkyIconFA } from 'chonky-icon-fontawesome';
import { browseDirectory } from '../../../apis';
import './DirectoryBrowser.css';

// 定义中文文件操作
const ChineseActions = {
  EnableListView: defineFileAction({
    ...ChonkyActions.EnableListView,
    button: {
      name: '列表视图',
      toolbar: true,
      contextMenu: false,
      icon: ChonkyActions.EnableListView.button?.icon || 'list',
    },
  }),
  EnableGridView: defineFileAction({
    ...ChonkyActions.EnableGridView,
    button: {
      name: '网格视图',
      toolbar: true,
      contextMenu: false,
      icon: ChonkyActions.EnableGridView.button?.icon || 'th',
    },
  }),
  SortFilesByName: defineFileAction({
    ...ChonkyActions.SortFilesByName,
    button: {
      name: '按名称排序',
      toolbar: true,
      contextMenu: false,
    },
  }),
  SortFilesByDate: defineFileAction({
    ...ChonkyActions.SortFilesByDate,
    button: {
      name: '按日期排序',
      toolbar: true,
      contextMenu: false,
    },
  }),
  SortFilesBySize: defineFileAction({
    ...ChonkyActions.SortFilesBySize,
    button: {
      name: '按大小排序',
      toolbar: true,
      contextMenu: false,
    },
  }),
  CreateFolder: defineFileAction({
    ...ChonkyActions.CreateFolder,
    button: {
      name: '新建文件夹',
      toolbar: false,
      contextMenu: true,
      icon: 'folder', // 尝试简单的folder图标
    },
  }),
};

// 设置Chonky默认配置
setChonkyDefaults({
  iconComponent: ChonkyIconFA,
});

// 定义中文国际化配置
const createChineseI18n = (isMobile) => ({
  locale: 'zh',
  formatters: {
    formatFileModDate: (intl, file) => {
      const safeModDate = FileHelper.getModDate(file);
      if (safeModDate) {
        return `${intl.formatDate(safeModDate)}, ${intl.formatTime(safeModDate)}`;
      } else {
        return null;
      }
    },
    formatFileSize: (intl, file) => {
      if (!file || typeof file.size !== 'number') return null;
      return `大小: ${file.size}`;
    },
  },
  messages: {
    // Chonky UI 翻译字符串
    'chonky.toolbar.searchPlaceholder': '搜索',
    'chonky.toolbar.visibleFileCount': `{fileCount, plural,
      one {# 个文件}
      other {# 个文件}
    }`,
    'chonky.toolbar.hiddenFileCount': `{fileCount, plural,
      =0 {}
      one {# 已隐藏}
      other {# 已隐藏}
    }`,
    'chonky.fileList.nothingToShow': '这里空空如也！',
    'chonky.contextMenu.browserMenuShortcut': 'Alt+鼠标右键：显示浏览器菜单',
    'chonky.contextMenu.multipleSelection': '已选择 {count} 项',
    'chonky.contextMenu.emptySelection': '未选择任何项目',

    // 文件操作翻译字符串 - 电脑端隐藏actions和options按钮组
    [`chonky.actionGroups.Actions`]: isMobile ? '操作' : '',
    [`chonky.actionGroups.Options`]: isMobile ? '选项' : '',
    [`chonky.actions.${ChonkyActions.OpenParentFolder.id}.button.name`]: '打开上级文件夹',
    [`chonky.actions.${ChonkyActions.CreateFolder.id}.button.name`]: '新建文件夹',
    [`chonky.actions.${ChonkyActions.CreateFolder.id}.button.tooltip`]: '创建新文件夹',
    [`chonky.actions.${ChonkyActions.OpenSelection.id}.button.name`]: '打开选中项',
    [`chonky.actions.${ChonkyActions.EnableListView.id}.button.name`]: '列表视图',
    [`chonky.actions.${ChonkyActions.EnableGridView.id}.button.name`]: '网格视图',
    [`chonky.actions.${ChonkyActions.SortFilesByName.id}.button.name`]: '按名称排序',
    [`chonky.actions.${ChonkyActions.SortFilesByDate.id}.button.name`]: '按日期排序',
    [`chonky.actions.${ChonkyActions.SortFilesBySize.id}.button.name`]: '按大小排序',
    [`chonky.actions.${ChonkyActions.ToggleHiddenFiles.id}.button.name`]: '隐藏文件',
    [`chonky.actions.${ChonkyActions.ToggleShowFoldersFirst.id}.button.name`]: '文件夹优先',
  },
});

const { Text } = Typography;

// 将API返回的数据转换为Chonky格式
const convertToChonkyFiles = (apiFiles) => {
  return apiFiles.map(item => {
    const modDate = item.modify_time ? new Date(item.modify_time) : new Date();

    return {
      id: item.path,
      name: item.name,
      isDir: item.type === 'dir',
      modDate: modDate,
      ...(item.type !== 'dir' && { size: item.size || 0 }), // 只为文件设置大小，文件夹不设置大小
    };
  });
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
  const [isMobile, setIsMobile] = useState(false);
  const [createFolderVisible, setCreateFolderVisible] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  // 检测是否为移动端
  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    
    checkIsMobile();
    window.addEventListener('resize', checkIsMobile);
    
    return () => {
      window.removeEventListener('resize', checkIsMobile);
    };
  }, []);

  // 移动端简化日期显示
  useEffect(() => {
    if (isMobile && visible && files.length > 0) {
      const formatTimeElements = () => {
        const timeElements = document.querySelectorAll('.chonky-fileEntry > div:nth-child(2)');
        timeElements.forEach(el => {
          const text = el.textContent;
          if (text && text.includes(',')) {
            try {
              const date = new Date(text);
              if (!isNaN(date.getTime())) {
                const month = date.getMonth() + 1;
                const day = date.getDate();
                const hour = date.getHours();
                const minute = date.getMinutes();
                el.textContent = `${month}-${day} ${hour}:${minute.toString().padStart(2, '0')}`;
              }
            } catch (e) {
              // 忽略解析错误
            }
          }
        });
      };
      setTimeout(formatTimeElements, 100);
    }
  }, [isMobile, visible, files]);

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

      // 显示所有文件和文件夹
      const allFiles = response.data;
      const chonkyFiles = convertToChonkyFiles(allFiles);
      setFiles(chonkyFiles);
    } catch (error) {
      message.error('加载目录失败：' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 处理创建文件夹
  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) {
      message.warning('请输入文件夹名称');
      return;
    }

    try {
      // 这里暂时使用提示，实际应该调用创建目录的API
      message.info(`创建文件夹 "${newFolderName}" 的功能正在开发中`);
      setCreateFolderVisible(false);
      setNewFolderName('');
      // 重新加载目录
      await loadDirectory(currentPath);
    } catch (error) {
      message.error('创建文件夹失败：' + (error.message || '未知错误'));
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
      className="DirectoryBrowser-modal"
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
      width={isMobile ? "95vw" : "60vw"}
      style={{
        margin: isMobile ? '1vh 2.5vw 2vh' : '2vh 20vw 4vh',
        top: isMobile ? '1vh' : '2vh',
        height: isMobile ? '96vh' : '94vh',
        maxWidth: 'none',
        paddingBottom: 0,
        borderRadius: '12px',
        overflow: 'hidden'
      }}
      styles={{
        body: {
          padding: 0,
          height: isMobile ? 'calc(96vh - 100px)' : 'calc(94vh - 120px)',
          overflow: 'hidden',
          background: 'var(--color-bg)'
        }
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
          fileActions={[
            // 两端都保留现有按钮，同时都添加创建文件夹功能
            ...(isMobile ? [
              // 手机端保留默认的下拉菜单，并添加创建文件夹
              ChonkyActions.OpenFiles,
              ChineseActions.CreateFolder,
            ] : [
              // 电脑端保留自定义中文按钮
              ChineseActions.EnableListView,
              ChineseActions.EnableGridView,
              ChineseActions.SortFilesByName,
              ChineseActions.SortFilesByDate,
              ChineseActions.SortFilesBySize,
              ChineseActions.CreateFolder,
            ]),
          ]}
          // 电脑端完全禁用默认action，手机端显示默认action
          disableDefaultFileActions={!isMobile}
          onFileAction={(data) => {
            // 处理双击进入文件夹
            if (data.id === ChonkyActions.OpenFiles.id) {
              const { targetFile } = data.payload;
              if (targetFile && FileHelper.isDirectory(targetFile)) {
                setCurrentPath(targetFile.id);
              }
            }
            // 处理创建文件夹
            else if (data.id === ChineseActions.CreateFolder.id) {
              setCreateFolderVisible(true);
            }
          }}
          i18n={createChineseI18n(isMobile)}
          defaultFileViewActionId={ChonkyActions.EnableListView.id}
          disableSelection={true}
          disableDragAndDrop={true}
        />

        {/* 创建文件夹对话框 */}
        <Modal
          title="新建文件夹"
          open={createFolderVisible}
          onOk={handleCreateFolder}
          onCancel={() => {
            setCreateFolderVisible(false);
            setNewFolderName('');
          }}
          okText="创建"
          cancelText="取消"
          width={400}
        >
          <div style={{ marginTop: '16px' }}>
            <Typography.Text>在当前目录创建新文件夹：</Typography.Text>
            <div style={{ marginTop: '12px' }}>
              <Typography.Text type="secondary" style={{ fontSize: '12px' }}>
                当前路径: {currentPath}
              </Typography.Text>
            </div>
            <div style={{ marginTop: '16px' }}>
              <input
                type="text"
                placeholder="请输入文件夹名称"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px 12px',
                  border: '1px solid #d9d9d9',
                  borderRadius: '6px',
                  fontSize: '14px',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
                onKeyPress={(e) => {
                  if (e.key === 'Enter') {
                    handleCreateFolder();
                  }
                }}
              />
            </div>
          </div>
        </Modal>
      </div>
    </Modal>
  );
};

export default DirectoryBrowser;

