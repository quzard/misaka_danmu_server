import React, { useState, useEffect, useMemo } from 'react';
import { Form, Input, Switch, Button, Space, message, Popconfirm, Card, Divider, Typography, Select, Radio, Row, Col, Tabs, Table, Modal, Tag, Progress, Checkbox, Tooltip } from 'antd';
import { FolderOpenOutlined, RocketOutlined, CheckCircleOutlined, SettingOutlined, FileOutlined, SwapOutlined, EditOutlined, SyncOutlined, DeleteOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import { getConfig, setConfig, browseDirectory, createFolder, deleteFolder, getAnimeLibrary, batchMigrateDanmaku, batchRenameDanmaku, applyDanmakuTemplate } from '@/apis';
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

  // 迁移与重命名状态
  const [libraryItems, setLibraryItems] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryTotal, setLibraryTotal] = useState(0);
  const [libraryPage, setLibraryPage] = useState(1);
  const [libraryPageSize, setLibraryPageSize] = useState(10);
  const [libraryKeyword, setLibraryKeyword] = useState('');
  const [libraryTypeFilter, setLibraryTypeFilter] = useState('all');
  const [selectedRowKeys, setSelectedRowKeys] = useState([]);
  const [selectedRows, setSelectedRows] = useState([]);
  // Modal状态
  const [migrateModalVisible, setMigrateModalVisible] = useState(false);
  const [renameModalVisible, setRenameModalVisible] = useState(false);
  const [templateModalVisible, setTemplateModalVisible] = useState(false);
  const [operationLoading, setOperationLoading] = useState(false);
  // 迁移配置
  const [migrateTargetPath, setMigrateTargetPath] = useState('/app/config/danmaku');
  const [migrateKeepStructure, setMigrateKeepStructure] = useState(true);
  const [migrateConflictAction, setMigrateConflictAction] = useState('skip');
  // 重命名配置
  const [renameMode, setRenameMode] = useState('prefix');
  const [renamePrefix, setRenamePrefix] = useState('');
  const [renameSuffix, setRenameSuffix] = useState('');
  const [renameRegexPattern, setRenameRegexPattern] = useState('');
  const [renameRegexReplace, setRenameRegexReplace] = useState('');
  // 模板转换配置
  const [templateTarget, setTemplateTarget] = useState('tv');

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

  // ==================== 迁移与重命名功能 ====================

  // 加载弹幕库条目
  const loadLibraryItems = async (page = 1, keyword = '', typeFilter = 'all') => {
    setLibraryLoading(true);
    try {
      const params = {
        page,
        pageSize: libraryPageSize,
      };
      if (keyword) params.keyword = keyword;

      const response = await getAnimeLibrary(params);
      let items = response.data?.list || [];

      // 类型过滤
      if (typeFilter !== 'all') {
        items = items.filter(item => {
          if (typeFilter === 'movie') return item.type === 'movie';
          if (typeFilter === 'tv') return item.type === 'tv_series' || item.type === 'ova';
          return true;
        });
      }

      setLibraryItems(items);
      setLibraryTotal(response.data?.total || 0);
      setLibraryPage(page);
    } catch (error) {
      console.error('加载弹幕库失败:', error);
      message.error('加载弹幕库失败');
    } finally {
      setLibraryLoading(false);
    }
  };

  // 当切换到迁移与重命名tab时加载数据
  useEffect(() => {
    if (activeTab === 'migrate') {
      loadLibraryItems(1, libraryKeyword, libraryTypeFilter);
    }
  }, [activeTab]);

  // 搜索处理
  const handleLibrarySearch = () => {
    setSelectedRowKeys([]);
    setSelectedRows([]);
    loadLibraryItems(1, libraryKeyword, libraryTypeFilter);
  };

  // 刷新列表
  const handleLibraryRefresh = () => {
    setSelectedRowKeys([]);
    setSelectedRows([]);
    loadLibraryItems(libraryPage, libraryKeyword, libraryTypeFilter);
  };

  // 表格选择配置
  const rowSelection = {
    selectedRowKeys,
    onChange: (keys, rows) => {
      setSelectedRowKeys(keys);
      setSelectedRows(rows);
    },
  };

  // 计算选中条目的总弹幕文件数
  const selectedEpisodeCount = useMemo(() => {
    return selectedRows.reduce((sum, item) => sum + (item.episodeCount || 0), 0);
  }, [selectedRows]);

  // 表格列定义
  const libraryColumns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (text, record) => (
        <Space>
          <span>{text}</span>
          {record.season > 1 && <Tag color="blue">S{record.season}</Tag>}
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (type) => {
        const typeMap = {
          'movie': { text: '电影', color: 'orange' },
          'tv_series': { text: 'TV', color: 'blue' },
          'ova': { text: 'OVA', color: 'purple' },
          'other': { text: '其他', color: 'default' },
        };
        const config = typeMap[type] || typeMap['other'];
        return <Tag color={config.color}>{config.text}</Tag>;
      },
    },
    {
      title: '集数',
      dataIndex: 'episodeCount',
      key: 'episodeCount',
      width: 70,
      render: (count) => count ? `${count}集` : '-',
    },
    {
      title: '弹幕数',
      dataIndex: 'sourceCount',
      key: 'sourceCount',
      width: 90,
      render: (count) => count ? count.toLocaleString() : '-',
    },
    {
      title: '收录时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 100,
      render: (date) => date ? new Date(date).toLocaleDateString('zh-CN') : '-',
    },
  ];

  // 打开迁移Modal
  const handleOpenMigrateModal = () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要迁移的条目');
      return;
    }
    setMigrateModalVisible(true);
  };

  // 打开重命名Modal
  const handleOpenRenameModal = () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要重命名的条目');
      return;
    }
    setRenameModalVisible(true);
  };

  // 打开模板转换Modal
  const handleOpenTemplateModal = () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要转换的条目');
      return;
    }
    setTemplateModalVisible(true);
  };

  // 执行迁移操作
  const handleExecuteMigrate = async () => {
    if (!migrateTargetPath) {
      message.warning('请输入目标目录');
      return;
    }
    setOperationLoading(true);
    try {
      const result = await batchMigrateDanmaku({
        animeIds: selectedRowKeys,
        targetPath: migrateTargetPath,
        keepStructure: migrateKeepStructure,
        conflictAction: migrateConflictAction,
      });
      if (result.success) {
        message.success(`迁移完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`迁移部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setMigrateModalVisible(false);
      setSelectedRowKeys([]);
      setSelectedRows([]);
      loadLibraryItems(libraryPage, libraryKeyword, libraryTypeFilter);
    } catch (error) {
      message.error('迁移失败: ' + (error.message || '未知错误'));
    } finally {
      setOperationLoading(false);
    }
  };

  // 执行重命名操作
  const handleExecuteRename = async () => {
    if (renameMode === 'prefix' && !renamePrefix && !renameSuffix) {
      message.warning('请输入前缀或后缀');
      return;
    }
    if (renameMode === 'regex' && !renameRegexPattern) {
      message.warning('请输入正则表达式匹配模式');
      return;
    }
    setOperationLoading(true);
    try {
      const result = await batchRenameDanmaku({
        animeIds: selectedRowKeys,
        mode: renameMode,
        prefix: renamePrefix,
        suffix: renameSuffix,
        regexPattern: renameRegexPattern,
        regexReplace: renameRegexReplace,
      });
      if (result.success) {
        message.success(`重命名完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`重命名部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setRenameModalVisible(false);
      setSelectedRowKeys([]);
      setSelectedRows([]);
      loadLibraryItems(libraryPage, libraryKeyword, libraryTypeFilter);
    } catch (error) {
      message.error('重命名失败: ' + (error.message || '未知错误'));
    } finally {
      setOperationLoading(false);
    }
  };

  // 执行模板转换操作
  const handleExecuteTemplate = async () => {
    setOperationLoading(true);
    try {
      const result = await applyDanmakuTemplate({
        animeIds: selectedRowKeys,
        templateType: templateTarget,
      });
      if (result.success) {
        message.success(`模板应用完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`模板应用部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setTemplateModalVisible(false);
      setSelectedRowKeys([]);
      setSelectedRows([]);
      loadLibraryItems(libraryPage, libraryKeyword, libraryTypeFilter);
    } catch (error) {
      message.error('模板应用失败: ' + (error.message || '未知错误'));
    } finally {
      setOperationLoading(false);
    }
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
    messages: {
      // 内置操作翻译
      'chonky.actionOpen': '打开所选',
      'chonky.actionSelectAll': '全选文件',
      'chonky.actionClearSelection': '清除选择',
      'chonky.actionOpenSelection': '打开所选',
      'chonky.actionSelectAllFiles': '全选文件',
      // 工具栏和状态文本
      'chonky.toolbar.searchPlaceholder': '搜索文件...',
      'chonky.toolbar.visibleFileCount': '{fileCount} 个文件',
      'chonky.toolbar.selectedFileCount': '已选择 {fileCount} 个',
      'chonky.toolbar.hiddenFileCount': '{fileCount} 个隐藏文件',
      // 文件浏览器菜单
      'chonky.contextMenu.browserMenuShortcut': '浏览器菜单: Alt + 右键',
      // 空文件夹提示
      'chonky.folderEmpty': '文件夹为空',
      'chonky.loading': '加载中...',
    },
  });

  return (
    <Card>
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

        {/* 迁移与重命名 Tab */}
        <TabPane tab="迁移与重命名" key="migrate">
          {/* 筛选条件 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Space wrap>
              <span>类型:</span>
              <Select
                value={libraryTypeFilter}
                onChange={(v) => { setLibraryTypeFilter(v); setSelectedRowKeys([]); setSelectedRows([]); }}
                style={{ width: 100 }}
              >
                <Option value="all">全部</Option>
                <Option value="movie">电影</Option>
                <Option value="tv">TV/OVA</Option>
              </Select>
              <Input.Search
                placeholder="搜索标题..."
                value={libraryKeyword}
                onChange={(e) => setLibraryKeyword(e.target.value)}
                onSearch={handleLibrarySearch}
                style={{ width: 200 }}
                allowClear
              />
              <Button icon={<ReloadOutlined />} onClick={handleLibraryRefresh}>
                刷新
              </Button>
            </Space>
          </Card>

          {/* 条目列表 */}
          <Table
            rowKey="animeId"
            columns={libraryColumns}
            dataSource={libraryItems}
            rowSelection={rowSelection}
            loading={libraryLoading}
            pagination={{
              current: libraryPage,
              pageSize: libraryPageSize,
              total: libraryTotal,
              showSizeChanger: true,
              showTotal: (total) => `共 ${total} 个条目`,
              onChange: (page, pageSize) => {
                setLibraryPageSize(pageSize);
                loadLibraryItems(page, libraryKeyword, libraryTypeFilter);
              },
            }}
            size="small"
            scroll={{ y: 'calc(100vh - 500px)' }}
          />

          {/* 选择状态栏 */}
          <Card size="small" style={{ marginTop: 16, marginBottom: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
              <Space>
                <Tag color={selectedRows.length > 0 ? 'blue' : 'default'}>
                  已选择 {selectedRows.length} 个条目
                </Tag>
                {selectedRows.length > 0 && (
                  <Tag color="cyan">含 {selectedEpisodeCount} 个弹幕文件</Tag>
                )}
              </Space>
              <Space>
                <Button size="small" onClick={() => {
                  const allKeys = libraryItems.map(item => item.animeId);
                  setSelectedRowKeys(allKeys);
                  setSelectedRows(libraryItems);
                }}>
                  全选当页
                </Button>
                <Button size="small" onClick={() => { setSelectedRowKeys([]); setSelectedRows([]); }}>
                  清空选择
                </Button>
              </Space>
            </div>
          </Card>

          {/* 批量操作按钮 */}
          <Card size="small">
            <Space wrap>
              <Tooltip title="将选中条目的弹幕文件迁移到新目录">
                <Button
                  icon={<SwapOutlined />}
                  onClick={handleOpenMigrateModal}
                  disabled={selectedRows.length === 0}
                >
                  迁移到...
                </Button>
              </Tooltip>
              <Tooltip title="批量重命名选中条目的弹幕文件">
                <Button
                  icon={<EditOutlined />}
                  onClick={handleOpenRenameModal}
                  disabled={selectedRows.length === 0}
                >
                  批量重命名
                </Button>
              </Tooltip>
              <Tooltip title="按新的存储模板重新组织弹幕文件">
                <Button
                  type="primary"
                  icon={<SyncOutlined />}
                  onClick={handleOpenTemplateModal}
                  disabled={selectedRows.length === 0}
                >
                  应用新模板
                </Button>
              </Tooltip>
            </Space>
          </Card>

          {/* 迁移Modal */}
          <Modal
            title="批量迁移"
            open={migrateModalVisible}
            onCancel={() => setMigrateModalVisible(false)}
            onOk={handleExecuteMigrate}
            confirmLoading={operationLoading}
            okText="确认迁移"
            width={600}
          >
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>目标目录:</div>
              <Input
                value={migrateTargetPath}
                onChange={(e) => setMigrateTargetPath(e.target.value)}
                placeholder="/app/config/danmaku/new"
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <Checkbox
                checked={migrateKeepStructure}
                onChange={(e) => setMigrateKeepStructure(e.target.checked)}
              >
                保持原目录结构
              </Checkbox>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>冲突处理:</div>
              <Select
                value={migrateConflictAction}
                onChange={setMigrateConflictAction}
                style={{ width: 200 }}
              >
                <Option value="skip">跳过</Option>
                <Option value="overwrite">覆盖</Option>
                <Option value="rename">重命名</Option>
              </Select>
            </div>
            <Divider />
            <div style={{ color: '#666' }}>
              将迁移 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
            </div>
          </Modal>

          {/* 重命名Modal */}
          <Modal
            title="批量重命名"
            open={renameModalVisible}
            onCancel={() => setRenameModalVisible(false)}
            onOk={handleExecuteRename}
            confirmLoading={operationLoading}
            okText="确认重命名"
            width={600}
          >
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>重命名规则:</div>
              <Radio.Group value={renameMode} onChange={(e) => setRenameMode(e.target.value)}>
                <Radio value="prefix">添加前后缀</Radio>
                <Radio value="regex">正则替换</Radio>
              </Radio.Group>
            </div>
            {renameMode === 'prefix' ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  addonBefore="添加前缀"
                  value={renamePrefix}
                  onChange={(e) => setRenamePrefix(e.target.value)}
                  placeholder="例如: 弹幕_"
                />
                <Input
                  addonBefore="添加后缀"
                  value={renameSuffix}
                  onChange={(e) => setRenameSuffix(e.target.value)}
                  placeholder="例如: _backup (在.xml之前)"
                />
              </Space>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  addonBefore="匹配模式"
                  value={renameRegexPattern}
                  onChange={(e) => setRenameRegexPattern(e.target.value)}
                  placeholder="正则表达式，例如: (\d+)\.xml"
                />
                <Input
                  addonBefore="替换为"
                  value={renameRegexReplace}
                  onChange={(e) => setRenameRegexReplace(e.target.value)}
                  placeholder="例如: Episode_$1.xml"
                />
              </Space>
            )}
            <Divider />
            <div style={{ color: '#666' }}>
              将重命名 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
            </div>
          </Modal>

          {/* 模板转换Modal */}
          <Modal
            title="应用新模板"
            open={templateModalVisible}
            onCancel={() => setTemplateModalVisible(false)}
            onOk={handleExecuteTemplate}
            confirmLoading={operationLoading}
            okText="确认应用"
            width={600}
          >
            <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
              <Text type="secondary">💡 将选中条目的弹幕文件按新的存储模板重新组织命名</Text>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>目标模板:</div>
              <Select
                value={templateTarget}
                onChange={setTemplateTarget}
                style={{ width: '100%' }}
              >
                <Option value="tv">电视节目模板: {'${title}/Season ${season}/${title} - S${season}E${episode}.xml'}</Option>
                <Option value="movie">电影模板: {'${title}/${title}.xml'}</Option>
                <Option value="id">ID模板: {'${animeId}/${episodeId}.xml'}</Option>
              </Select>
            </div>
            <Divider />
            <div style={{ color: '#666' }}>
              将转换 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
            </div>
          </Modal>
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

