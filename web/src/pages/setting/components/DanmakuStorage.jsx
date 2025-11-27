import React, { useState, useEffect, useMemo } from 'react';
import { Form, Input, Switch, Button, Space, message, Card, Divider, Typography, Select, Radio, Row, Col, Tabs, Table, Modal, Tag, Progress, Checkbox, Tooltip } from 'antd';
import { FolderOpenOutlined, CheckCircleOutlined, SettingOutlined, FileOutlined, SwapOutlined, EditOutlined, SyncOutlined, DeleteOutlined, SearchOutlined, ReloadOutlined } from '@ant-design/icons';
import { getConfig, setConfig, getAnimeLibrary, previewMigrateDanmaku, batchMigrateDanmaku, previewRenameDanmaku, batchRenameDanmaku, previewDanmakuTemplate, applyDanmakuTemplate } from '@/apis';
import DirectoryBrowser from '../../media-fetch/components/DirectoryBrowser';

const { Text } = Typography;
const { Option } = Select;
const { TabPane } = Tabs;

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

  // Tab状态
  const [activeTab, setActiveTab] = useState('config');
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
  const [migratePreviewData, setMigratePreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  // 重命名配置
  const [renameMode, setRenameMode] = useState('prefix');
  const [renamePrefix, setRenamePrefix] = useState('');
  const [renameSuffix, setRenameSuffix] = useState('');
  const [renameRegexPattern, setRenameRegexPattern] = useState('');
  const [renameRegexReplace, setRenameRegexReplace] = useState('');
  const [renamePreviewData, setRenamePreviewData] = useState(null);
  const [renamePreviewLoading, setRenamePreviewLoading] = useState(false);
  // 模板转换配置
  const [templateTarget, setTemplateTarget] = useState('tv');
  const [customTemplate, setCustomTemplate] = useState('');  // 自定义模板
  const [templatePreviewData, setTemplatePreviewData] = useState(null);
  const [templatePreviewLoading, setTemplatePreviewLoading] = useState(false);

  // 可用的模板变量定义
  const templateVariables = [
    { name: '${title}', desc: '作品标题', example: '葬送的芙莉莲' },
    { name: '${titleBase}', desc: '标准化标题（去除季度信息，如"第X季"、"第X期"等）', example: '葬送的芙莉莲' },
    { name: '${season}', desc: '季度号', example: '1' },
    { name: '${season:02d}', desc: '季度号（补零到2位）', example: '01' },
    { name: '${episode}', desc: '分集号', example: '12' },
    { name: '${episode:02d}', desc: '分集号（补零到2位）', example: '12' },
    { name: '${episode:03d}', desc: '分集号（补零到3位）', example: '012' },
    { name: '${year}', desc: '年份', example: '2024' },
    { name: '${provider}', desc: '数据源提供商', example: 'dandanplay' },
    { name: '${animeId}', desc: '作品ID', example: '227' },
    { name: '${episodeId}', desc: '分集ID', example: '25000227010001' },
    { name: '${sourceId}', desc: '数据源ID', example: '1' },
  ];

  // 预设模板选项
  const presetTemplates = [
    { value: 'tv', label: '电视节目模板', template: '${title}/Season ${season}/${title} - S${season}E${episode}' },
    { value: 'movie', label: '电影模板', template: '${title}/${title}' },
    { value: 'id', label: 'ID模板', template: '${animeId}/${episodeId}' },
    { value: 'plex', label: 'Plex风格', template: '${title}/${title} - S${season:02d}E${episode:02d}' },
    { value: 'emby', label: 'Emby风格', template: '${title}/${title} S${season:02d}/${title} S${season:02d}E${episode:02d}' },
    { value: 'titleBase', label: '标准化标题', template: '${titleBase}/Season ${season}/${titleBase} - S${season}E${episode}' },
  ];

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
  const handleOpenMigrateModal = async () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要迁移的条目');
      return;
    }
    setMigratePreviewData(null); // 清空预览数据
    setMigrateModalVisible(true);
    // 打开时自动预览
    if (migrateTargetPath) {
      setPreviewLoading(true);
      try {
        const response = await previewMigrateDanmaku({
          animeIds: selectedRowKeys,
          targetPath: migrateTargetPath,
          keepStructure: migrateKeepStructure,
        });
        setMigratePreviewData(response.data);
      } catch (error) {
        message.error('预览失败: ' + (error.message || '未知错误'));
      } finally {
        setPreviewLoading(false);
      }
    }
  };

  // 预览迁移
  const handlePreviewMigrate = async () => {
    if (!migrateTargetPath) {
      message.warning('请输入目标目录');
      return;
    }
    setPreviewLoading(true);
    try {
      const response = await previewMigrateDanmaku({
        animeIds: selectedRowKeys,
        targetPath: migrateTargetPath,
        keepStructure: migrateKeepStructure,
      });
      setMigratePreviewData(response.data);
    } catch (error) {
      message.error('预览失败: ' + (error.message || '未知错误'));
    } finally {
      setPreviewLoading(false);
    }
  };

  // 重命名预览函数
  const fetchRenamePreview = async (mode, prefix, suffix, regexPattern, regexReplace) => {
    setRenamePreviewLoading(true);
    try {
      const response = await previewRenameDanmaku({
        animeIds: selectedRowKeys,
        mode,
        prefix: prefix || '',
        suffix: suffix || '',
        regexPattern: regexPattern || '',
        regexReplace: regexReplace || '',
      });
      setRenamePreviewData(response.data);
    } catch (error) {
      message.error('预览失败: ' + (error.message || '未知错误'));
    } finally {
      setRenamePreviewLoading(false);
    }
  };

  // 打开重命名Modal
  const handleOpenRenameModal = async () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要重命名的条目');
      return;
    }
    setRenamePreviewData(null);
    setRenameModalVisible(true);
    // 打开时自动预览（显示原始文件名）
    await fetchRenamePreview(renameMode, renamePrefix, renameSuffix, renameRegexPattern, renameRegexReplace);
  };

  // 打开模板转换Modal
  const handleOpenTemplateModal = async () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要转换的条目');
      return;
    }
    setTemplatePreviewData(null);
    setTemplateModalVisible(true);
    // 打开时自动预览
    setTemplatePreviewLoading(true);
    try {
      const response = await previewDanmakuTemplate({
        animeIds: selectedRowKeys,
        templateType: templateTarget,
      });
      setTemplatePreviewData(response.data);
    } catch (error) {
      message.error('预览失败: ' + (error.message || '未知错误'));
    } finally {
      setTemplatePreviewLoading(false);
    }
  };

  // 预览应用模板
  const handlePreviewTemplate = async () => {
    setTemplatePreviewLoading(true);
    try {
      const response = await previewDanmakuTemplate({
        animeIds: selectedRowKeys,
        templateType: templateTarget,
      });
      setTemplatePreviewData(response.data);
    } catch (error) {
      message.error('预览失败: ' + (error.message || '未知错误'));
    } finally {
      setTemplatePreviewLoading(false);
    }
  };

  // 执行迁移操作
  const handleExecuteMigrate = async () => {
    if (!migrateTargetPath) {
      message.warning('请输入目标目录');
      return;
    }
    setOperationLoading(true);
    try {
      const response = await batchMigrateDanmaku({
        animeIds: selectedRowKeys,
        targetPath: migrateTargetPath,
        keepStructure: migrateKeepStructure,
        conflictAction: migrateConflictAction,
      });
      const result = response.data;
      if (result.success) {
        message.success(`迁移完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`迁移部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setMigrateModalVisible(false);
      setMigratePreviewData(null);
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
      const response = await batchRenameDanmaku({
        animeIds: selectedRowKeys,
        mode: renameMode,
        prefix: renamePrefix,
        suffix: renameSuffix,
        regexPattern: renameRegexPattern,
        regexReplace: renameRegexReplace,
      });
      const result = response.data;
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
      const response = await applyDanmakuTemplate({
        animeIds: selectedRowKeys,
        templateType: templateTarget,
      });
      const result = response.data;
      if (result.success) {
        message.success(`模板应用完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`模板应用部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setTemplateModalVisible(false);
      setTemplatePreviewData(null);
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
  const handleSelectDirectory = async (path) => {
    if (browserTarget === 'movie') {
      setMovieDanmakuDirectoryPath(path);
      form.setFieldValue('movieDanmakuDirectoryPath', path);
      message.success(`已选择电影存储目录: ${path}`);
    } else if (browserTarget === 'tv') {
      setTvDanmakuDirectoryPath(path);
      form.setFieldValue('tvDanmakuDirectoryPath', path);
      message.success(`已选择电视存储目录: ${path}`);
    } else if (browserTarget === 'migrate') {
      // 迁移目录选择后自动预览
      setMigrateTargetPath(path);
      setBrowserVisible(false);
      // 自动执行预览
      setPreviewLoading(true);
      try {
        const response = await previewMigrateDanmaku({
          animeIds: selectedRowKeys,
          targetPath: path,
          keepStructure: migrateKeepStructure,
        });
        setMigratePreviewData(response.data);
      } catch (error) {
        message.error('预览失败: ' + (error.message || '未知错误'));
      } finally {
        setPreviewLoading(false);
      }
      return; // 提前返回，不再执行下面的 setBrowserVisible
    }
    setBrowserVisible(false);
  };

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

        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          onClick={handleSave}
          loading={loading}
          size="large"
          block
          style={{
            marginTop: '24px',
            height: '48px',
            fontSize: '16px',
            fontWeight: 500
          }}
        >
          保存配置
        </Button>
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
            onCancel={() => { setMigrateModalVisible(false); setMigratePreviewData(null); }}
            onOk={handleExecuteMigrate}
            confirmLoading={operationLoading}
            okText="确认迁移"
            width={700}
          >
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>目标目录:</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input
                  value={migrateTargetPath}
                  onChange={(e) => { setMigrateTargetPath(e.target.value); setMigratePreviewData(null); }}
                  placeholder="/app/config/danmaku/new"
                  style={{ flex: 1 }}
                />
                <Button
                  type="primary"
                  icon={<FolderOpenOutlined />}
                  onClick={() => handleBrowseDirectory('migrate')}
                >
                  浏览
                </Button>
              </div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Checkbox
                checked={migrateKeepStructure}
                onChange={(e) => { setMigrateKeepStructure(e.target.checked); setMigratePreviewData(null); }}
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

            {/* 预览区域 */}
            {migratePreviewData && (
              <>
                <Divider orientation="left">迁移预览</Divider>
                <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                  {migratePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 12, padding: 8, background: '#fafafa', borderRadius: 4 }}>
                      <div style={{ fontWeight: 500, marginBottom: 4 }}>
                        {item.animeTitle} {item.episodeIndex ? `第${item.episodeIndex}集` : ''}
                      </div>
                      <div style={{ fontSize: 13, color: '#666' }}>
                        <div style={{ marginBottom: 4 }}>
                          <Text type="secondary">原路径: </Text>
                          <Text code style={{ fontSize: 13 }}>{item.oldPath}</Text>
                        </div>
                        <div>
                          <Text type="secondary">新路径: </Text>
                          <Text code style={{ fontSize: 13, color: '#52c41a' }}>{item.newPath}</Text>
                        </div>
                        {!item.exists && (
                          <Tag color="warning" style={{ marginTop: 4 }}>文件不存在</Tag>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 8, color: '#666' }}>
                  共 <strong>{migratePreviewData.totalCount}</strong> 个文件将被迁移
                </div>
              </>
            )}

            {!migratePreviewData && (
              <>
                <Divider />
                <div style={{ color: '#666' }}>
                  将迁移 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    <Text type="secondary">点击"预览"按钮查看详细迁移路径</Text>
                  </div>
                </div>
              </>
            )}
          </Modal>

          {/* 重命名Modal */}
          <Modal
            title="批量重命名"
            open={renameModalVisible}
            onCancel={() => setRenameModalVisible(false)}
            onOk={handleExecuteRename}
            confirmLoading={operationLoading}
            okText="确认重命名"
            width={700}
          >
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>重命名规则:</div>
              <Radio.Group
                value={renameMode}
                onChange={(e) => {
                  const newMode = e.target.value;
                  setRenameMode(newMode);
                  // 切换模式时重新预览
                  fetchRenamePreview(newMode, renamePrefix, renameSuffix, renameRegexPattern, renameRegexReplace);
                }}
              >
                <Radio value="prefix">添加前后缀</Radio>
                <Radio value="regex">正则替换</Radio>
              </Radio.Group>
            </div>
            {renameMode === 'prefix' ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  addonBefore="添加前缀"
                  value={renamePrefix}
                  onChange={(e) => {
                    setRenamePrefix(e.target.value);
                    fetchRenamePreview(renameMode, e.target.value, renameSuffix, renameRegexPattern, renameRegexReplace);
                  }}
                  placeholder="例如: 弹幕_"
                />
                <Input
                  addonBefore="添加后缀"
                  value={renameSuffix}
                  onChange={(e) => {
                    setRenameSuffix(e.target.value);
                    fetchRenamePreview(renameMode, renamePrefix, e.target.value, renameRegexPattern, renameRegexReplace);
                  }}
                  placeholder="例如: _backup (在.xml之前)"
                />
              </Space>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                <Input
                  addonBefore="匹配模式"
                  value={renameRegexPattern}
                  onChange={(e) => {
                    setRenameRegexPattern(e.target.value);
                    fetchRenamePreview(renameMode, renamePrefix, renameSuffix, e.target.value, renameRegexReplace);
                  }}
                  placeholder="正则表达式，例如: (\d+)"
                />
                <Input
                  addonBefore="替换为"
                  value={renameRegexReplace}
                  onChange={(e) => {
                    setRenameRegexReplace(e.target.value);
                    fetchRenamePreview(renameMode, renamePrefix, renameSuffix, renameRegexPattern, e.target.value);
                  }}
                  placeholder="例如: Episode_$1"
                />
              </Space>
            )}

            {/* 预览区域 */}
            <Divider orientation="left">重命名预览</Divider>
            {renamePreviewLoading ? (
              <div style={{ textAlign: 'center', padding: 20, color: '#666' }}>
                正在加载预览...
              </div>
            ) : renamePreviewData ? (
              <>
                <div style={{ maxHeight: 250, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                  {renamePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 8, padding: 6, background: '#fafafa', borderRadius: 4 }}>
                      <div style={{ fontSize: 13 }}>
                        <Text code style={{ fontSize: 13 }}>{item.oldName}</Text>
                        <span style={{ margin: '0 8px', color: '#999' }}>→</span>
                        <Text code style={{ fontSize: 13, color: item.error ? '#ff4d4f' : '#52c41a' }}>{item.newName}</Text>
                        {!item.exists && <Tag color="warning" style={{ marginLeft: 8 }}>文件不存在</Tag>}
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 8, color: '#666' }}>
                  共 <strong>{renamePreviewData.totalCount}</strong> 个文件将被重命名
                </div>
              </>
            ) : (
              <div style={{ color: '#666' }}>
                将重命名 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
              </div>
            )}
          </Modal>

          {/* 模板转换Modal */}
          <Modal
            title="应用新模板"
            open={templateModalVisible}
            onCancel={() => setTemplateModalVisible(false)}
            onOk={handleExecuteTemplate}
            confirmLoading={operationLoading}
            okText="确认应用"
            width={isMobile ? '95%' : 1350}
          >
            <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
              <Text type="secondary">💡 将选中条目的弹幕文件按新的存储模板重新组织命名</Text>
            </div>

            {/* 可用参数按钮组 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8, color: '#666' }}>可用参数（点击插入）:</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {templateVariables.map((v) => (
                  <Tooltip
                    key={v.name}
                    title={<div><div>{v.desc}</div><div style={{ color: '#aaa', marginTop: 4 }}>示例: {v.example}</div></div>}
                    placement="top"
                  >
                    <Button
                      size="small"
                      type="dashed"
                      onClick={() => {
                        const newTemplate = customTemplate + v.name;
                        setCustomTemplate(newTemplate);
                        setTemplateTarget('custom');
                      }}
                      style={{ fontFamily: 'monospace', fontSize: 12 }}
                    >
                      {v.name}
                    </Button>
                  </Tooltip>
                ))}
              </div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ marginBottom: 8 }}>目标模板:</div>
              <Row gutter={12}>
                <Col span={isMobile ? 24 : 8}>
                  <Select
                    value={templateTarget}
                    onChange={async (v) => {
                      setTemplateTarget(v);
                      if (v !== 'custom') {
                        const preset = presetTemplates.find(p => p.value === v);
                        if (preset) {
                          setCustomTemplate(preset.template);
                        }
                        // 选择预设模板后自动预览
                        setTemplatePreviewLoading(true);
                        try {
                          const response = await previewDanmakuTemplate({
                            animeIds: selectedRowKeys,
                            templateType: v,
                          });
                          setTemplatePreviewData(response.data);
                        } catch (error) {
                          message.error('预览失败: ' + (error.message || '未知错误'));
                        } finally {
                          setTemplatePreviewLoading(false);
                        }
                      }
                    }}
                    style={{ width: '100%', marginBottom: isMobile ? 8 : 0 }}
                  >
                    {presetTemplates.map(p => (
                      <Option key={p.value} value={p.value}>{p.label}</Option>
                    ))}
                    <Option value="custom">自定义模板</Option>
                  </Select>
                </Col>
                <Col span={isMobile ? 24 : 16}>
                  <Input
                    value={customTemplate}
                    onChange={(e) => {
                      setCustomTemplate(e.target.value);
                      setTemplateTarget('custom');
                    }}
                    placeholder="输入自定义模板，如: ${title}/Season ${season}/${title} - S${season}E${episode}"
                    style={{ fontFamily: 'monospace' }}
                  />
                </Col>
              </Row>
              <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                当前模板: <Text code style={{ fontSize: 12 }}>{customTemplate || presetTemplates.find(p => p.value === templateTarget)?.template || ''}.xml</Text>
              </div>
            </div>

            {/* 预览区域 */}
            {templatePreviewData && (
              <>
                <Divider orientation="left">转换预览</Divider>
                <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                  {templatePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 12, padding: 8, background: '#fafafa', borderRadius: 4 }}>
                      <div style={{ fontWeight: 500, marginBottom: 4 }}>
                        {item.animeTitle} {item.episodeIndex ? `第${item.episodeIndex}集` : ''}
                      </div>
                      <div style={{ fontSize: 13, color: '#666' }}>
                        <div style={{ marginBottom: 4 }}>
                          <Text type="secondary">原路径: </Text>
                          <Text code style={{ fontSize: 13 }}>{item.oldPath}</Text>
                        </div>
                        <div>
                          <Text type="secondary">新路径: </Text>
                          <Text code style={{ fontSize: 13, color: '#52c41a' }}>{item.newPath}</Text>
                        </div>
                        {!item.exists && (
                          <Tag color="warning" style={{ marginTop: 4 }}>文件不存在</Tag>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 8, color: '#666' }}>
                  共 <strong>{templatePreviewData.totalCount}</strong> 个文件将被转换
                </div>
              </>
            )}

            {!templatePreviewData && !templatePreviewLoading && (
              <>
                <Divider />
                <div style={{ color: '#666' }}>
                  将转换 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    <Text type="secondary">选择模板后将自动显示预览</Text>
                  </div>
                </div>
              </>
            )}
            {templatePreviewLoading && (
              <div style={{ textAlign: 'center', padding: 20, color: '#666' }}>
                正在加载预览...
              </div>
            )}
          </Modal>
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

