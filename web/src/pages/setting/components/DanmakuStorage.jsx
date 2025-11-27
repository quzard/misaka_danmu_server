import React, { useState, useEffect, useMemo } from 'react';
import { Form, Input, Switch, Button, Space, message, Popconfirm, Card, Divider, Typography, Select, Radio, Row, Col, Tabs } from 'antd';
import { FolderOpenOutlined, RocketOutlined, CheckCircleOutlined, SettingOutlined, FileOutlined } from '@ant-design/icons';
import { getConfig, setConfig, browseDirectory, createFolder, deleteFolder } from '@/apis';
import DirectoryBrowser from '../../media-fetch/components/DirectoryBrowser';
import Cookies from 'js-cookie';
import {
  FullFileBrowser,
  setChonkyDefaults,
  ChonkyActions,
  FileHelper,
  defineFileAction
} from 'chonky';
import { ChonkyIconFA } from 'chonky-icon-fontawesome';

const { Text } = Typography;
const { Option } = Select;
const { TabPane } = Tabs;

// 设置Chonky默认配置
setChonkyDefaults({
  iconComponent: ChonkyIconFA,
});

// 中文化的文件操作
const ChineseActions = {
  EnableListView: defineFileAction({
    ...ChonkyActions.EnableListView,
    button: {
      name: '列表视图',
      toolbar: true,
      contextMenu: false,
    },
  }),
  EnableGridView: defineFileAction({
    ...ChonkyActions.EnableGridView,
    button: {
      name: '网格视图',
      toolbar: true,
      contextMenu: false,
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
  CreateFolder: defineFileAction({
    ...ChonkyActions.CreateFolder,
    button: {
      name: '新建文件夹',
      toolbar: false,
      contextMenu: true,
      icon: 'folder',
    },
  }),
  DeleteFolder: defineFileAction({
    id: 'delete_folder',
    requiresSelection: true,
    fileFilter: (file) => FileHelper.isDirectory(file),
    button: {
      name: '删除文件夹',
      toolbar: false,
      contextMenu: true,
      icon: 'trash',
    },
  }),
};

// 模板定义
const TEMPLATES = {
  movie: [
    { label: '按标题分组', value: '${title}/${episodeId}', desc: '${title}/${episodeId}' },
    { label: '标题+年份', value: '${title} (${year})/${episodeId}', desc: '${title} (${year})/${episodeId}' },
    { label: '扁平结构', value: '${episodeId}', desc: '${episodeId}' },
  ],
  tv: [
    { label: '按番剧ID分组', value: '${animeId}/${episodeId}', desc: '${animeId}/${episodeId}' },
    { label: '按标题+季度分组', value: '${title}/Season ${season}/${episodeId}', desc: '${title}/Season ${season}/${episodeId}' },
    { label: 'Plex风格', value: '${title}/${title} - S${season:02d}E${episode:02d}', desc: '${title}/${title} - S${season:02d}E${episode:02d}' },
    { label: '扁平结构', value: '${episodeId}', desc: '${episodeId}' },
  ]
};

const DanmakuStorage = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [customDanmakuPathEnabled, setCustomDanmakuPathEnabled] = useState(false);

  // 电影配置
  const [movieDanmakuDirectoryPath, setMovieDanmakuDirectoryPath] = useState('/app/config/danmaku/movies');
  const [movieDanmakuFilenameTemplate, setMovieDanmakuFilenameTemplate] = useState('${title}/${episodeId}');
  const [moviePreviewPath, setMoviePreviewPath] = useState('');

  // 电视配置
  const [tvDanmakuDirectoryPath, setTvDanmakuDirectoryPath] = useState('/app/config/danmaku/tv');
  const [tvDanmakuFilenameTemplate, setTvDanmakuFilenameTemplate] = useState('${animeId}/${episodeId}');
  const [tvPreviewPath, setTvPreviewPath] = useState('');

  // 模板选择器状态
  const [selectedType, setSelectedType] = useState('movie');
  const [selectedTemplate, setSelectedTemplate] = useState('${title}/${episodeId}');

  // 目录浏览器状态
  const [browserVisible, setBrowserVisible] = useState(false);
  const [browserTarget, setBrowserTarget] = useState(''); // 'movie' or 'tv'

  // 文件管理状态
  const [activeTab, setActiveTab] = useState('config');
  const [fileManagerPath, setFileManagerPath] = useState('/app/config/danmaku');
  const [fileManagerFiles, setFileManagerFiles] = useState([]);
  const [fileManagerLoading, setFileManagerLoading] = useState(false);
  const [createFolderVisible, setCreateFolderVisible] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const [isMobile, setIsMobile] = useState(false);

  // 检测是否为移动端
  useEffect(() => {
    const checkIsMobile = () => {
      setIsMobile(window.innerWidth <= 768);
    };
    checkIsMobile();
    window.addEventListener('resize', checkIsMobile);
    return () => window.removeEventListener('resize', checkIsMobile);
  }, []);

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 更新路径预览
  useEffect(() => {
    updatePreview();
  }, [customDanmakuPathEnabled, movieDanmakuDirectoryPath, movieDanmakuFilenameTemplate, tvDanmakuDirectoryPath, tvDanmakuFilenameTemplate]);

  // 当选择类型改变时，更新默认模板
  useEffect(() => {
    const defaultTemplate = selectedType === 'movie' ? '${title}/${episodeId}' : '${animeId}/${episodeId}';
    setSelectedTemplate(defaultTemplate);
  }, [selectedType]);

  const loadConfig = async () => {
    try {
      setLoading(true);

      // 加载配置
      const enabledRes = await getConfig('customDanmakuPathEnabled');
      const movieDirRes = await getConfig('movieDanmakuDirectoryPath');
      const movieTemplateRes = await getConfig('movieDanmakuFilenameTemplate');
      const tvDirRes = await getConfig('tvDanmakuDirectoryPath');
      const tvTemplateRes = await getConfig('tvDanmakuFilenameTemplate');

      const enabled = enabledRes?.data?.value === 'true';
      const movieDir = movieDirRes?.data?.value || '/app/config/danmaku/movies';
      const movieTemplate = movieTemplateRes?.data?.value || '${title}/${episodeId}';
      const tvDir = tvDirRes?.data?.value || '/app/config/danmaku/tv';
      const tvTemplate = tvTemplateRes?.data?.value || '${animeId}/${episodeId}';

      setCustomDanmakuPathEnabled(enabled);
      setMovieDanmakuDirectoryPath(movieDir);
      setMovieDanmakuFilenameTemplate(movieTemplate);
      setTvDanmakuDirectoryPath(tvDir);
      setTvDanmakuFilenameTemplate(tvTemplate);

      form.setFieldsValue({
        customDanmakuPathEnabled: enabled,
        movieDanmakuDirectoryPath: movieDir,
        movieDanmakuFilenameTemplate: movieTemplate,
        tvDanmakuDirectoryPath: tvDir,
        tvDanmakuFilenameTemplate: tvTemplate,
      });
    } catch (error) {
      message.error('加载配置失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const updatePreview = () => {
    if (!customDanmakuPathEnabled) {
      setMoviePreviewPath('/app/config/danmaku/160/25000160010001.xml (默认路径)');
      setTvPreviewPath('/app/config/danmaku/160/25000160010001.xml (默认路径)');
      return;
    }

    // 电影示例数据
    const movieExampleContext = {
      animeId: '160',
      episodeId: '25000160010001',
      title: '铃芽之旅',
      season: '1',
      episode: '1',
      year: '2022',
      provider: 'bilibili',
      sourceId: '192'
    };

    // 电视示例数据
    const tvExampleContext = {
      animeId: '160',
      episodeId: '25000160010001',
      title: '葬送的芙莉莲',
      season: '1',
      episode: '1',
      year: '2023',
      provider: 'bilibili',
      sourceId: '192'
    };

    // 生成电影预览
    let moviePreview = movieDanmakuFilenameTemplate;
    moviePreview = moviePreview.replace(/\$\{(\w+):(\w+)\}/g, (match, varName, format) => {
      const value = movieExampleContext[varName];
      if (value && format.endsWith('d')) {
        const num = parseInt(value);
        const width = parseInt(format.match(/\d+/)?.[0] || '0');
        return num.toString().padStart(width, '0');
      }
      return value || match;
    });
    moviePreview = moviePreview.replace(/\$\{(\w+)\}/g, (match, varName) => {
      return movieExampleContext[varName] || match;
    });
    const movieDir = movieDanmakuDirectoryPath.replace(/[\/\\]+$/, '');
    const movieFilename = moviePreview.replace(/^[\/\\]+/, '');
    const movieFullPath = `${movieDir}/${movieFilename}${movieFilename.endsWith('.xml') ? '' : '.xml'}`;
    setMoviePreviewPath(movieFullPath);

    // 生成电视预览
    let tvPreview = tvDanmakuFilenameTemplate;
    tvPreview = tvPreview.replace(/\$\{(\w+):(\w+)\}/g, (match, varName, format) => {
      const value = tvExampleContext[varName];
      if (value && format.endsWith('d')) {
        const num = parseInt(value);
        const width = parseInt(format.match(/\d+/)?.[0] || '0');
        return num.toString().padStart(width, '0');
      }
      return value || match;
    });
    tvPreview = tvPreview.replace(/\$\{(\w+)\}/g, (match, varName) => {
      return tvExampleContext[varName] || match;
    });
    const tvDir = tvDanmakuDirectoryPath.replace(/[\/\\]+$/, '');
    const tvFilename = tvPreview.replace(/^[\/\\]+/, '');
    const tvFullPath = `${tvDir}/${tvFilename}${tvFilename.endsWith('.xml') ? '' : '.xml'}`;
    setTvPreviewPath(tvFullPath);
  };

  const handleSave = async () => {
    try {
      setLoading(true);

      // 保存配置
      await setConfig('customDanmakuPathEnabled', customDanmakuPathEnabled ? 'true' : 'false');
      await setConfig('movieDanmakuDirectoryPath', movieDanmakuDirectoryPath);
      await setConfig('movieDanmakuFilenameTemplate', movieDanmakuFilenameTemplate);
      await setConfig('tvDanmakuDirectoryPath', tvDanmakuDirectoryPath);
      await setConfig('tvDanmakuFilenameTemplate', tvDanmakuFilenameTemplate);

      message.success('配置保存成功');
    } catch (error) {
      message.error('配置保存失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleBatchRename = async () => {
    message.info('批量重命名功能开发中...');
  };

  const handleMigrateDirectory = async () => {
    message.info('迁移弹幕目录功能开发中...');
  };

  // 应用模板
  const applyTemplate = () => {
    if (!selectedTemplate) {
      message.warning('请选择一个模板');
      return;
    }

    if (selectedType === 'movie') {
      setMovieDanmakuFilenameTemplate(selectedTemplate);
      form.setFieldValue('movieDanmakuFilenameTemplate', selectedTemplate);
      message.success('已应用电影模板');
    } else {
      setTvDanmakuFilenameTemplate(selectedTemplate);
      form.setFieldValue('tvDanmakuFilenameTemplate', selectedTemplate);
      message.success('已应用电视模板');
    }
  };

  // 打开目录浏览器
  const handleBrowseDirectory = (target) => {
    setBrowserTarget(target);
    setBrowserVisible(true);
  };

  // 选择目录
  const handleSelectDirectory = (path) => {
    if (browserTarget === 'movie') {
      setMovieDanmakuDirectoryPath(path);
      form.setFieldValue('movieDanmakuDirectoryPath', path);
      message.success(`已选择电影存储目录: ${path}`);
    } else if (browserTarget === 'tv') {
      setTvDanmakuDirectoryPath(path);
      form.setFieldValue('tvDanmakuDirectoryPath', path);
      message.success(`已选择电视存储目录: ${path}`);
    }
    setBrowserVisible(false);
  };

  // ==================== 文件管理功能 ====================

  // 转换文件列表为Chonky格式
  const convertToChonkyFiles = (files) => {
    return files.map(file => ({
      id: file.path,
      name: file.name,
      isDir: file.type === 'dir',
      modDate: file.modify_time ? new Date(file.modify_time) : null,
      size: file.size || 0,
    }));
  };

  // 创建文件夹链（面包屑导航）
  const createFolderChain = (path) => {
    const parts = path.split('/').filter(Boolean);
    const chain = [{ id: '/', name: '根目录', isDir: true }];
    let currentPath = '';
    for (const part of parts) {
      currentPath += '/' + part;
      chain.push({ id: currentPath, name: part, isDir: true });
    }
    return chain;
  };

  // 加载目录内容
  const loadFileManagerDirectory = async (path) => {
    setFileManagerLoading(true);
    try {
      const token = Cookies.get('danmu_token');
      if (!token) {
        message.error('请先登录');
        return;
      }
      const normalizedPath = path.replace(/^\/+/, '/');
      const requestData = {
        id: normalizedPath || 'root',
        storage: 'local',
        type: 'dir',
        path: normalizedPath,
        name: ''
      };
      const response = await browseDirectory(requestData, 'name');
      const chonkyFiles = convertToChonkyFiles(response.data);
      setFileManagerFiles(chonkyFiles);
    } catch (error) {
      console.error('加载目录失败:', error);
      message.error('加载目录失败：' + (error.response?.data?.detail || error.message));
    } finally {
      setFileManagerLoading(false);
    }
  };

  // 当切换到文件管理Tab或路径变化时加载目录
  useEffect(() => {
    if (activeTab === 'files') {
      loadFileManagerDirectory(fileManagerPath);
    }
  }, [activeTab, fileManagerPath]);

  // 文件夹链
  const folderChain = useMemo(() => createFolderChain(fileManagerPath), [fileManagerPath]);

  // 创建文件夹
  const handleCreateFolder = async () => {
    if (!newFolderName.trim()) {
      message.warning('请输入文件夹名称');
      return;
    }
    try {
      await createFolder({ parentPath: fileManagerPath, folderName: newFolderName.trim() });
      message.success('文件夹创建成功');
      setCreateFolderVisible(false);
      setNewFolderName('');
      loadFileManagerDirectory(fileManagerPath);
    } catch (error) {
      message.error('创建文件夹失败：' + (error.response?.data?.detail || error.message));
    }
  };

  // 删除文件夹
  const handleDeleteFolder = async (folderPath) => {
    try {
      await deleteFolder({ folderPath });
      message.success('文件夹删除成功');
      loadFileManagerDirectory(fileManagerPath);
    } catch (error) {
      message.error('删除文件夹失败：' + (error.response?.data?.detail || error.message));
    }
  };

  // 处理文件操作
  const handleFileAction = (data) => {
    // 处理选择文件/文件夹
    if (data.id === ChonkyActions.ChangeSelection.id) {
      // 不需要特殊处理
    }
    // 处理双击进入文件夹
    if (data.id === ChonkyActions.OpenFiles.id) {
      const { targetFile } = data.payload;
      if (targetFile && FileHelper.isDirectory(targetFile)) {
        const normalizedPath = targetFile.id.replace(/^\/+/, '/');
        setFileManagerPath(normalizedPath);
      }
    }
    // 处理点击面包屑导航
    else if (data.id === ChonkyActions.OpenParentFolder.id) {
      const { targetFile } = data.payload;
      if (targetFile) {
        const normalizedPath = targetFile.id.replace(/^\/+/, '/');
        setFileManagerPath(normalizedPath);
      }
    }
    // 处理创建文件夹
    else if (data.id === ChineseActions.CreateFolder.id) {
      setCreateFolderVisible(true);
    }
    // 处理删除文件夹
    else if (data.id === 'delete_folder') {
      const selectedFiles = data.state.selectedFilesForAction;
      if (selectedFiles && selectedFiles.length > 0) {
        const folder = selectedFiles[0];
        if (FileHelper.isDirectory(folder)) {
          handleDeleteFolder(folder.id);
        }
      }
    }
  };

  // 中文国际化
  const createChineseI18n = () => ({
    locale: 'zh-CN',
    formatters: {
      formatFileModDate: (_, file) => {
        if (!file || !file.modDate) return '未知';
        const date = new Date(file.modDate);
        return date.toLocaleDateString('zh-CN') + ' ' + date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      },
      formatFileSize: (_, file) => {
        if (!file || file.size === undefined || file.size === null) return '';
        if (file.isDir) return '';
        const size = file.size;
        if (size < 1024) return size + ' B';
        if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB';
        if (size < 1024 * 1024 * 1024) return (size / (1024 * 1024)).toFixed(1) + ' MB';
        return (size / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
      },
    },
  });

  return (
    <Card title="弹幕存储设置">
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="存储配置" key="config">
          <Form
            form={form}
            layout="vertical"
            style={{ maxWidth: 1000 }}
          >
            {/* 启用自定义弹幕路径 */}
        <Form.Item
          label="启用自定义弹幕路径"
          name="customDanmakuPathEnabled"
        >
          <div>
            <Switch
              checked={customDanmakuPathEnabled}
              onChange={async (checked) => {
                setCustomDanmakuPathEnabled(checked);
                form.setFieldValue('customDanmakuPathEnabled', checked);
                // 自动保存开关状态
                try {
                  await setConfig('customDanmakuPathEnabled', checked ? 'true' : 'false');
                  message.success(checked ? '已启用自定义弹幕路径' : '已禁用自定义弹幕路径');
                } catch (error) {
                  message.error('保存失败');
                  console.error(error);
                  // 恢复原状态
                  setCustomDanmakuPathEnabled(!checked);
                  form.setFieldValue('customDanmakuPathEnabled', !checked);
                }
              }}
            />
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              启用后将使用下方配置的自定义路径和命名模板
            </div>
          </div>
        </Form.Item>

        {/* 快速模板选择器 */}
        <Card
          title={
            <Space>
              <RocketOutlined />
              快速应用模板
            </Space>
          }
          size="small"
          style={{ marginBottom: '24px' }}
        >
          <div style={{ marginBottom: '16px' }}>
            <Row gutter={[16, 24]}>
              <Col xs={24} sm={8} style={{ marginBottom: '16px' }}>
                <div style={{ marginBottom: '12px', fontWeight: 500, color: '#666' }}>内容类型</div>
                <Select
                  value={selectedType}
                  onChange={setSelectedType}
                  disabled={!customDanmakuPathEnabled}
                  placeholder="选择类型"
                  style={{ width: '100%' }}
                >
                  <Option value="movie">🎬 电影/剧场版</Option>
                  <Option value="tv">📺 电视节目</Option>
                </Select>
              </Col>
              <Col xs={24} sm={10} style={{ marginBottom: '16px' }}>
                <div style={{ marginBottom: '12px', fontWeight: 500, color: '#666' }}>命名模板</div>
                <Select
                  value={selectedTemplate}
                  onChange={setSelectedTemplate}
                  placeholder="选择一个模板"
                  disabled={!customDanmakuPathEnabled}
                  style={{ width: '100%' }}
                >
                  {TEMPLATES[selectedType].map((tpl) => (
                    <Option key={tpl.value} value={tpl.value}>
                      {tpl.label}
                    </Option>
                  ))}
                </Select>
              </Col>
              <Col xs={24} sm={6}>
                <div style={{ marginBottom: '12px', fontWeight: 500, color: '#666' }}>操作</div>
                <Button
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  onClick={applyTemplate}
                  disabled={!customDanmakuPathEnabled || !selectedTemplate}
                  block
                  style={{ height: '32px' }}
                >
                  应用模板
                </Button>
              </Col>
            </Row>
          </div>

          <div style={{
            padding: '12px',
            background: 'linear-gradient(135deg, #f6f9fc 0%, #e9ecef 100%)',
            borderRadius: '6px',
            border: '1px solid #e1e8ed'
          }}>
            <div style={{ color: '#666', fontSize: '13px', lineHeight: '1.5' }}>
              <strong>💡 提示：</strong>选择内容类型和命名模板后，点击"应用模板"按钮将自动填充到对应的命名模板字段中，让配置更加便捷高效。
            </div>
          </div>
        </Card>

        <Divider orientation="left">
          <Space>
            🎬 电影/剧场版配置
          </Space>
        </Divider>

        {/* 电影存储目录 */}
        <Form.Item
          label="电影存储目录"
          name="movieDanmakuDirectoryPath"
        >
          <div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Input
                value={movieDanmakuDirectoryPath}
                onChange={(e) => {
                  setMovieDanmakuDirectoryPath(e.target.value);
                  form.setFieldValue('movieDanmakuDirectoryPath', e.target.value);
                }}
                placeholder="/app/config/danmaku/movies"
                disabled={!customDanmakuPathEnabled}
                style={{ flex: 1 }}
              />
              <Button
                icon={<FolderOpenOutlined />}
                onClick={() => handleBrowseDirectory('movie')}
                disabled={!customDanmakuPathEnabled}
              >
                浏览
              </Button>
            </div>
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              电影/剧场版弹幕文件的根目录
            </div>
          </div>
        </Form.Item>

        {/* 电影命名模板 */}
        <Form.Item
          label="电影命名模板"
          name="movieDanmakuFilenameTemplate"
        >
          <div>
            <Input
              value={movieDanmakuFilenameTemplate}
              onChange={(e) => {
                setMovieDanmakuFilenameTemplate(e.target.value);
                form.setFieldValue('movieDanmakuFilenameTemplate', e.target.value);
              }}
              placeholder="${title}/${episodeId}"
              disabled={!customDanmakuPathEnabled}
            />
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              支持变量: {'${animeId}'}, {'${episodeId}'}, {'${title}'}, {'${year}'}, {'${provider}'}
            </div>
            <div style={{ color: '#999', fontSize: '12px' }}>
              支持子目录: {'${title}'}/<wbr/>{'${episodeId}'}
            </div>
            <div style={{ color: '#999', fontSize: '12px' }}>
              .xml后缀会自动拼接,无需在模板中添加
            </div>
          </div>
        </Form.Item>

        {/* 电影路径预览 */}
        <Form.Item label={
          <Space>
            👀 电影路径预览
          </Space>
        }>
          <div style={{
            padding: '16px',
            background: 'linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)',
            borderRadius: '8px',
            border: '1px solid #dee2e6',
            fontFamily: 'JetBrains Mono, Consolas, monospace',
            fontSize: '13px',
            wordBreak: 'break-all',
            color: '#495057'
          }}>
            {moviePreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: '#6c757d', fontSize: '12px', marginTop: '8px' }}>
            📝 示例: 铃芽之旅 (2022)
          </div>
        </Form.Item>

        <Divider orientation="left">
          <Space>
            📺 电视节目配置
          </Space>
        </Divider>

        {/* 电视存储目录 */}
        <Form.Item
          label="电视存储目录"
          name="tvDanmakuDirectoryPath"
        >
          <div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Input
                value={tvDanmakuDirectoryPath}
                onChange={(e) => {
                  setTvDanmakuDirectoryPath(e.target.value);
                  form.setFieldValue('tvDanmakuDirectoryPath', e.target.value);
                }}
                placeholder="/app/config/danmaku/tv"
                disabled={!customDanmakuPathEnabled}
                style={{ flex: 1 }}
              />
              <Button
                icon={<FolderOpenOutlined />}
                onClick={() => handleBrowseDirectory('tv')}
                disabled={!customDanmakuPathEnabled}
              >
                浏览
              </Button>
            </div>
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              电视节目弹幕文件的根目录
            </div>
          </div>
        </Form.Item>

        {/* 电视命名模板 */}
        <Form.Item
          label="电视命名模板"
          name="tvDanmakuFilenameTemplate"
        >
          <div>
            <Input
              value={tvDanmakuFilenameTemplate}
              onChange={(e) => {
                setTvDanmakuFilenameTemplate(e.target.value);
                form.setFieldValue('tvDanmakuFilenameTemplate', e.target.value);
              }}
              placeholder="${animeId}/${episodeId}"
              disabled={!customDanmakuPathEnabled}
            />
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              支持变量: {'${animeId}'}, {'${episodeId}'}, {'${title}'}, {'${season:02d}'}, {'${episode:02d}'}
            </div>
            <div style={{ color: '#999', fontSize: '12px' }}>
              支持子目录: {'${animeId}'}/<wbr/>{'${episodeId}'}
            </div>
            <div style={{ color: '#999', fontSize: '12px' }}>
              .xml后缀会自动拼接,无需在模板中添加
            </div>
          </div>
        </Form.Item>

        {/* 电视路径预览 */}
        <Form.Item label={
          <Space>
            👀 电视路径预览
          </Space>
        }>
          <div style={{
            padding: '16px',
            background: 'linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%)',
            borderRadius: '8px',
            border: '1px solid #dee2e6',
            fontFamily: 'JetBrains Mono, Consolas, monospace',
            fontSize: '13px',
            wordBreak: 'break-all',
            color: '#495057'
          }}>
            {tvPreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: '#6c757d', fontSize: '12px', marginTop: '8px' }}>
            📝 示例: 葬送的芙莉莲 S01E01
          </div>
        </Form.Item>

        {/* 操作按钮 */}
        <Card
          title={
            <Space>
              操作面板
            </Space>
          }
          size="small"
          style={{ marginTop: '24px' }}
        >
          <div className="flex flex-col gap-3">
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={handleSave}
              loading={loading}
              size="large"
              block
              style={{
                height: '48px',
                fontSize: '16px',
                fontWeight: 500
              }}
            >
              保存配置
            </Button>

            <div className="flex flex-col sm:flex-row gap-3">
              <Button
                icon={<FolderOpenOutlined />}
                onClick={handleBatchRename}
                disabled={!customDanmakuPathEnabled || loading}
                size="large"
                block
                style={{ flex: 1, height: '44px' }}
              >
                批量重命名
              </Button>

              <Popconfirm
                title="确定要迁移弹幕目录吗?"
                description="此操作会移动所有弹幕文件到新目录"
                onConfirm={handleMigrateDirectory}
                disabled={!customDanmakuPathEnabled || loading}
              >
                <Button
                  danger
                  icon={<RocketOutlined />}
                  disabled={!customDanmakuPathEnabled || loading}
                  size="large"
                  block
                  style={{ flex: 1, height: '44px' }}
                >
                  迁移目录
                </Button>
              </Popconfirm>
            </div>
          </div>
        </Card>
          </Form>
        </TabPane>

        {/* 文件管理 Tab */}
        <TabPane tab="文件管理" key="files">
          <div style={{
            height: 'calc(100vh - 280px)',
            minHeight: '500px',
            position: 'relative',
            overflow: 'hidden',
            border: '1px solid var(--color-border)',
            borderRadius: '8px'
          }}>
            {fileManagerLoading ? (
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
                <span>加载中...</span>
              </div>
            ) : (
              <FullFileBrowser
                files={fileManagerFiles}
                folderChain={folderChain}
                fileActions={[
                  ...(isMobile ? [
                    ChonkyActions.OpenFiles,
                    ChineseActions.CreateFolder,
                    ChineseActions.DeleteFolder,
                  ] : [
                    ChineseActions.EnableListView,
                    ChineseActions.EnableGridView,
                    ChineseActions.SortFilesByName,
                    ChineseActions.SortFilesByDate,
                    ChineseActions.CreateFolder,
                    ChineseActions.DeleteFolder,
                  ]),
                ]}
                onFileAction={handleFileAction}
                i18n={createChineseI18n()}
                defaultFileViewActionId={ChonkyActions.EnableListView.id}
                disableSelection={false}
                disableDragAndDrop={true}
              />
            )}
          </div>

          {/* 创建文件夹对话框 */}
          <div style={{ display: createFolderVisible ? 'block' : 'none' }}>
            <Card
              title="新建文件夹"
              size="small"
              style={{
                position: 'absolute',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
                zIndex: 1000,
                width: '300px',
                boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
              }}
              extra={
                <Button size="small" onClick={() => { setCreateFolderVisible(false); setNewFolderName(''); }}>
                  关闭
                </Button>
              }
            >
              <Input
                placeholder="请输入文件夹名称"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onPressEnter={handleCreateFolder}
              />
              <div style={{ marginTop: '12px', textAlign: 'right' }}>
                <Space>
                  <Button onClick={() => { setCreateFolderVisible(false); setNewFolderName(''); }}>取消</Button>
                  <Button type="primary" onClick={handleCreateFolder}>创建</Button>
                </Space>
              </div>
            </Card>
          </div>
        </TabPane>
      </Tabs>

      {/* 目录浏览器（用于存储配置中选择目录） */}
      <DirectoryBrowser
        visible={browserVisible}
        onClose={() => setBrowserVisible(false)}
        onSelect={handleSelectDirectory}
      />
    </Card>
  );
};

export default DanmakuStorage;

