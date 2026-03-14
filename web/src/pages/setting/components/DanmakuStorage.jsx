import { useState, useEffect, useMemo, useRef } from 'react';
import { Form, Input, Switch, Button, Space, message, Card, Divider, Typography, Select, Row, Col, Tabs, Table, Modal, Tag, Checkbox, Tooltip, Collapse, Popover } from 'antd';
import { FolderOpenOutlined, CheckCircleOutlined, FileOutlined, SwapOutlined, EditOutlined, SyncOutlined, DeleteOutlined, SearchOutlined, ReloadOutlined, RocketOutlined } from '@ant-design/icons';
import { getConfig, setConfig, getAnimeLibrary, previewMigrateDanmaku, batchMigrateDanmaku, previewRenameDanmaku, batchRenameDanmaku, previewDanmakuTemplate, applyDanmakuTemplate, getTemplateVariables, getDanmakuLikesFetchEnabled, setDanmakuLikesFetchEnabled } from '@/apis';
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

  // 设置分页状态
  const [likesFetchEnabled, setLikesFetchEnabled] = useState(true);

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
  // 重命名配置 - 多规则系统
  const [renameRules, setRenameRules] = useState([]);
  const [selectedRuleType, setSelectedRuleType] = useState('replace');
  const [ruleParams, setRuleParams] = useState({});
  const [renamePreviewData, setRenamePreviewData] = useState(null);
  const [renamePreviewLoading, setRenamePreviewLoading] = useState(false);
  const [isRenamePreviewMode, setIsRenamePreviewMode] = useState(false);
  const [renameOriginalItems, setRenameOriginalItems] = useState([]); // 保存原始文件名列表
  // 模板转换配置
  const [templateTarget, setTemplateTarget] = useState('tv');
  const [customTemplate, setCustomTemplate] = useState('');  // 自定义模板
  const [templatePreviewData, setTemplatePreviewData] = useState(null);
  const [templatePreviewLoading, setTemplatePreviewLoading] = useState(false);

  // 从后端获取的模板变量（统一列表）
  const [templateVariables, setTemplateVariables] = useState([]);

  // 电影/电视配置Tab切换
  const [activeConfigTab, setActiveConfigTab] = useState('movie');
  // 快速模板弹窗
  const [quickTemplateModalVisible, setQuickTemplateModalVisible] = useState(false);
  const [quickTemplateType, setQuickTemplateType] = useState('movie'); // 'movie' or 'tv'

  // 输入框引用，用于插入变量到光标位置
  const movieTemplateInputRef = useRef(null);
  const tvTemplateInputRef = useRef(null);

  // 预设模板选项
  const presetTemplates = [
    { value: 'tv', label: '电视节目模板', template: '${title}/Season ${season}/${title} - S${season}E${episode}' },
    { value: 'movie', label: '电影模板', template: '${title}/${title}' },
    { value: 'id', label: 'ID模板', template: '${animeId}/${episodeId}' },
    { value: 'plex', label: 'Plex风格', template: '${title}/${title} - S${season:02d}E${episode:02d}' },
    { value: 'emby', label: 'Emby风格', template: '${title}/${title} S${season:02d}/${title} S${season:02d}E${episode:02d}' },
    { value: 'titleBase', label: '标准化标题', template: '${titleBase}/Season ${season}/${titleBase} - S${season}E${episode}' },
    { value: 'custom_movie', label: '自定义模板-电影', template: movieDanmakuFilenameTemplate || '${title}/${episodeId}' },
    { value: 'custom_tv', label: '自定义模板-电视节目', template: tvDanmakuFilenameTemplate || '${animeId}/${episodeId}' },
  ];

  // 多规则重命名 - 规则类型配置
  const ruleTypeOptions = [
    { value: 'replace', label: '替换' },
    { value: 'regex', label: '正则' },
    { value: 'insert', label: '插入' },
    { value: 'delete', label: '删除' },
    { value: 'serialize', label: '序列化' },
    { value: 'case', label: '大小写' },
    { value: 'strip', label: '清理' },
  ];

  // 应用单条规则到文件名
  const applyRenameRule = (filename, rule, index) => {
    if (!rule.enabled) return filename;
    try {
      switch (rule.type) {
        case 'replace':
          return rule.params.caseSensitive
            ? filename.split(rule.params.search || '').join(rule.params.replace || '')
            : filename.replace(new RegExp((rule.params.search || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), rule.params.replace || '');
        case 'regex':
          return filename.replace(new RegExp(rule.params.pattern || '', 'g'), rule.params.replace || '');
        case 'insert':
          if (rule.params.position === 'start') return (rule.params.text || '') + filename;
          if (rule.params.position === 'end') return filename + (rule.params.text || '');
          const pos = parseInt(rule.params.index) || 0;
          return filename.slice(0, pos) + (rule.params.text || '') + filename.slice(pos);
        case 'delete':
          const deleteMode = rule.params.mode || 'text';

          switch (deleteMode) {
            case 'text':
              // 删除指定文本
              return rule.params.caseSensitive
                ? filename.split(rule.params.text || '').join('')
                : filename.replace(new RegExp((rule.params.text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), '');

            case 'first':
              // 删除前N个字符
              const firstCount = parseInt(rule.params.count) || 0;
              return filename.slice(firstCount);

            case 'last':
              // 删除后N个字符
              const lastCount = parseInt(rule.params.count) || 0;
              return filename.slice(0, -lastCount || undefined);

            case 'toText':
              // 从开头删除到指定文本（包含该文本）
              const toText = rule.params.text || '';
              if (!toText) return filename;
              const toIndex = rule.params.caseSensitive
                ? filename.indexOf(toText)
                : filename.toLowerCase().indexOf(toText.toLowerCase());
              return toIndex >= 0 ? filename.slice(toIndex + toText.length) : filename;

            case 'fromText':
              // 从指定文本删除到结尾（包含该文本）
              const fromText = rule.params.text || '';
              if (!fromText) return filename;
              const fromIndex = rule.params.caseSensitive
                ? filename.indexOf(fromText)
                : filename.toLowerCase().indexOf(fromText.toLowerCase());
              return fromIndex >= 0 ? filename.slice(0, fromIndex) : filename;

            case 'range':
              // 删除指定范围（从位置X删除Y个字符）
              const from = parseInt(rule.params.from) || 0;
              const count = parseInt(rule.params.count) || 0;
              return filename.slice(0, from) + filename.slice(from + count);

            default:
              return filename;
          }
        case 'serialize':
          const start = parseInt(rule.params.start) || 1;
          const step = parseInt(rule.params.step) || 1;
          const digits = parseInt(rule.params.digits) || 2;
          const num = String(start + index * step).padStart(digits, '0');
          const serialized = (rule.params.prefix || '') + num + (rule.params.suffix || '');
          if (rule.params.position === 'start') return serialized + filename;
          if (rule.params.position === 'end') return filename + serialized;
          return serialized;
        case 'case':
          if (rule.params.mode === 'upper') return filename.toUpperCase();
          if (rule.params.mode === 'lower') return filename.toLowerCase();
          if (rule.params.mode === 'title') return filename.charAt(0).toUpperCase() + filename.slice(1).toLowerCase();
          return filename;
        case 'strip':
          let result = filename;
          if (rule.params.trimSpaces) result = result.trim();
          if (rule.params.trimDuplicateSpaces) result = result.replace(/\s+/g, ' ');
          if (rule.params.chars) result = result.split(rule.params.chars).join('');
          return result;
        default:
          return filename;
      }
    } catch (e) {
      message.error(`规则 "${ruleTypeOptions.find(r => r.value === rule.type)?.label}" 执行错误: ${e.message}`);
      return filename;
    }
  };

  // 应用所有规则到文件名
  const applyAllRenameRules = (filename, index) => {
    return renameRules.reduce((name, rule) => applyRenameRule(name, rule, index), filename);
  };

  // 添加规则
  const handleAddRenameRule = () => {
    // 验证必填参数
    if (selectedRuleType === 'replace' && !ruleParams.search) {
      message.warning('请输入要查找的文本');
      return;
    }
    if (selectedRuleType === 'regex' && !ruleParams.pattern) {
      message.warning('请输入正则表达式');
      return;
    }
    if (selectedRuleType === 'insert') {
      if (!ruleParams.text) {
        message.warning('请输入要插入的文本');
        return;
      }
      if (ruleParams.position === 'index' && ruleParams.index === undefined) {
        message.warning('请输入插入位置');
        return;
      }
    }
    if (selectedRuleType === 'delete') {
      const mode = ruleParams.mode || 'text';
      if ((mode === 'text' || mode === 'toText' || mode === 'fromText') && !ruleParams.text) {
        message.warning('请输入文本');
        return;
      }
      if ((mode === 'first' || mode === 'last' || mode === 'range') && !ruleParams.count) {
        message.warning('请输入字符数');
        return;
      }
      if (mode === 'range' && ruleParams.from === undefined) {
        message.warning('请输入起始位置');
        return;
      }
    }

    const newRule = {
      id: Date.now().toString(),
      type: selectedRuleType,
      enabled: true,
      params: { ...ruleParams }
    };
    setRenameRules(prev => [...prev, newRule]);
    setRuleParams({});
    message.success('规则已添加');
  };

  // 删除规则
  const handleDeleteRenameRule = (ruleId) => {
    setRenameRules(prev => prev.filter(r => r.id !== ruleId));
  };

  // 切换规则启用状态
  const handleToggleRenameRule = (ruleId) => {
    setRenameRules(prev => prev.map(r => r.id === ruleId ? { ...r, enabled: !r.enabled } : r));
  };

  // 监听规则变化，自动更新预览
  useEffect(() => {
    if (!isRenamePreviewMode || !renameModalVisible || renameOriginalItems.length === 0) return;

    // 使用从后端获取的原始文件名列表计算新名称
    const previewItems = renameOriginalItems.map((item, index) => {
      const oldName = item.oldName;
      const baseName = oldName.replace(/\.[^/.]+$/, '');
      const ext = oldName.includes('.') ? '.' + oldName.split('.').pop() : '';
      const newBaseName = applyAllRenameRules(baseName, index);
      return {
        oldName: oldName,
        newName: newBaseName + ext,
        episodeId: item.episodeId,
        oldPath: item.oldPath
      };
    });
    setRenamePreviewData({ totalCount: previewItems.length, previewItems: previewItems.slice(0, 20) });
  }, [renameRules, isRenamePreviewMode, renameModalVisible, renameOriginalItems]);

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

  // 监听自定义模板变化，自动预览（防抖）
  const templatePreviewTimerRef = useRef(null);
  useEffect(() => {
    // 只在模板 Modal 打开且是自定义模式时才触发预览
    if (!templateModalVisible || templateTarget !== 'custom' || !customTemplate) {
      return;
    }

    // 清除之前的定时器
    if (templatePreviewTimerRef.current) {
      clearTimeout(templatePreviewTimerRef.current);
    }

    // 防抖：300ms 后调用预览 API
    templatePreviewTimerRef.current = setTimeout(async () => {
      setTemplatePreviewLoading(true);
      try {
        const response = await previewDanmakuTemplate({
          animeIds: selectedRowKeys,
          templateType: 'custom',
          customTemplate: customTemplate,
        });
        setTemplatePreviewData(response.data);
      } catch (error) {
        message.error('预览失败: ' + (error.message || '未知错误'));
      } finally {
        setTemplatePreviewLoading(false);
      }
    }, 300);

    return () => {
      if (templatePreviewTimerRef.current) {
        clearTimeout(templatePreviewTimerRef.current);
      }
    };
  }, [customTemplate, templateTarget, templateModalVisible, selectedRowKeys]);

  // 监听迁移配置变化，自动预览（防抖）
  const migratePreviewTimerRef = useRef(null);
  useEffect(() => {
    // 只在迁移 Modal 打开且有目标路径时才触发预览
    if (!migrateModalVisible || !migrateTargetPath || selectedRowKeys.length === 0) {
      return;
    }

    // 清除之前的定时器
    if (migratePreviewTimerRef.current) {
      clearTimeout(migratePreviewTimerRef.current);
    }

    // 防抖：300ms 后调用预览 API
    migratePreviewTimerRef.current = setTimeout(async () => {
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
    }, 300);

    return () => {
      if (migratePreviewTimerRef.current) {
        clearTimeout(migratePreviewTimerRef.current);
      }
    };
  }, [migrateTargetPath, migrateKeepStructure, migrateModalVisible, selectedRowKeys]);

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

      // 获取模板变量列表
      try {
        const varsRes = await getTemplateVariables();
        if (varsRes?.data) {
          setTemplateVariables(varsRes.data);
        }
      } catch (e) {
        console.warn('获取模板变量失败，使用默认值', e);
      }

      // 获取点赞开关
      try {
        const likesFetchRes = await getDanmakuLikesFetchEnabled();
        setLikesFetchEnabled(likesFetchRes?.data?.value !== 'false');
      } catch (e) {
        console.warn('获取点赞开关失败', e);
      }
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
      title: '铃芽之旅 第二季',
      titleBase: '铃芽之旅',  // 电影标题通常不含季度信息
      season: '1',
      episode: '1',
      year: '2022',
      provider: 'bilibili',
      sourceId: '192',
      tmdbId: '1022789',
    };

    // 电视示例数据
    const tvExampleContext = {
      animeId: '160',
      episodeId: '25000160010001',
      title: '葬送的芙莉莲 第二季',
      titleBase: '葬送的芙莉莲',  // 标准化标题，去除季度信息
      season: '1',
      episode: '1',
      year: '2023',
      provider: 'bilibili',
      sourceId: '192',
      tmdbId: '209867',
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
    // 检测目录路径使用的分隔符，保持一致
    const sep = movieDir.includes('\\') ? '\\' : '/';
    const movieFullPath = `${movieDir}${sep}${movieFilename.replace(/[\/\\]/g, sep)}${movieFilename.endsWith('.xml') ? '' : '.xml'}`;
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
    const tvSep = tvDir.includes('\\') ? '\\' : '/';
    const tvFullPath = `${tvDir}${tvSep}${tvFilename.replace(/[\/\\]/g, tvSep)}${tvFilename.endsWith('.xml') ? '' : '.xml'}`;
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
      // 类型过滤：传递给后端处理，而不是前端过滤
      if (typeFilter !== 'all') params.type = typeFilter;

      const response = await getAnimeLibrary(params);
      const items = response.data?.list || [];

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

  // 打开重命名Modal
  const handleOpenRenameModal = async () => {
    if (selectedRows.length === 0) {
      message.warning('请先选择要重命名的条目');
      return;
    }
    // 重置多规则状态
    setRenameRules([]);
    setSelectedRuleType('replace');
    setRuleParams({});
    setRenamePreviewLoading(true);
    setRenameModalVisible(true);
    setIsRenamePreviewMode(true);

    // 调用后端API获取原始文件名列表
    try {
      const response = await previewRenameDanmaku({
        animeIds: selectedRowKeys,
        mode: 'prefix',
        prefix: '',
        suffix: '',
        regexPattern: '',
        regexReplace: '',
      });
      const items = response.data?.previewItems || [];
      // 保存原始文件名列表，用于后续规则计算
      setRenameOriginalItems(items);
      // 初始预览显示原始文件名
      const previewItems = items.map(item => ({
        oldName: item.oldName,
        newName: item.oldName, // 初始时新名称等于旧名称
        episodeId: item.episodeId,
        oldPath: item.oldPath
      }));
      setRenamePreviewData({ totalCount: items.length, previewItems: previewItems.slice(0, 20) });
    } catch (error) {
      message.error('获取文件列表失败: ' + (error.message || '未知错误'));
      setRenamePreviewData(null);
      setRenameOriginalItems([]);
    } finally {
      setRenamePreviewLoading(false);
    }
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
        customTemplate: templateTarget === 'custom' ? customTemplate : undefined,
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
        customTemplate: templateTarget === 'custom' ? customTemplate : undefined,
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

  // 执行重命名操作 - 使用多规则系统
  const handleExecuteRename = async () => {
    if (renameRules.length === 0) {
      message.warning('请先添加重命名规则');
      return;
    }

    if (renameOriginalItems.length === 0) {
      message.warning('没有找到需要重命名的文件');
      return;
    }

    // 使用从后端获取的原始文件名列表计算新名称
    const directRenames = renameOriginalItems.map((item, index) => {
      const oldName = item.oldName;
      const baseName = oldName.replace(/\.[^/.]+$/, '');
      const ext = oldName.includes('.') ? '.' + oldName.split('.').pop() : '';
      const newBaseName = applyAllRenameRules(baseName, index);
      return {
        episodeId: item.episodeId,
        newName: newBaseName + ext
      };
    });

    setOperationLoading(true);
    try {
      const response = await batchRenameDanmaku({
        animeIds: selectedRowKeys,
        mode: 'direct',
        directRenames: directRenames,
      });
      const result = response.data;
      if (result.success) {
        message.success(`重命名完成: 成功 ${result.successCount} 个，跳过 ${result.skippedCount} 个`);
      } else {
        message.warning(`重命名部分完成: 成功 ${result.successCount} 个，失败 ${result.failedCount} 个，跳过 ${result.skippedCount} 个`);
      }
      setRenameModalVisible(false);
      setRenameRules([]);
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
        customTemplate: templateTarget === 'custom' ? customTemplate : undefined,
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

        {/* 可折叠变量区域 */}
        <Collapse
          defaultActiveKey={['variables']}
          style={{ marginBottom: '24px' }}
          items={[
            {
              key: 'variables',
              label: (
                <Space>
                  <span>📂 可用变量</span>
                  <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>
                    (点击插入到光标处)
                  </span>
                </Space>
              ),
              children: (
                <div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '12px' }}>
                    {(templateVariables || []).map((v) => (
                      <Tooltip
                        key={v.name}
                        title={<div><div>{v.desc}</div><div style={{ color: '#aaa', marginTop: 4 }}>示例: {v.example}</div></div>}
                        placement="top"
                        trigger={isMobile ? 'click' : 'hover'}
                      >
                        <Button
                          size="small"
                          type="dashed"
                          disabled={!customDanmakuPathEnabled}
                          onClick={() => {
                            // 根据当前激活的Tab插入到对应的输入框光标处
                            const inputRef = activeConfigTab === 'movie' ? movieTemplateInputRef : tvTemplateInputRef;
                            const currentValue = activeConfigTab === 'movie' ? movieDanmakuFilenameTemplate : tvDanmakuFilenameTemplate;
                            const setValue = activeConfigTab === 'movie' ? setMovieDanmakuFilenameTemplate : setTvDanmakuFilenameTemplate;
                            const fieldName = activeConfigTab === 'movie' ? 'movieDanmakuFilenameTemplate' : 'tvDanmakuFilenameTemplate';

                            if (inputRef.current && inputRef.current.input) {
                              const input = inputRef.current.input;
                              const start = input.selectionStart || 0;
                              const end = input.selectionEnd || 0;
                              const newValue = currentValue.slice(0, start) + v.name + currentValue.slice(end);
                              setValue(newValue);
                              form.setFieldValue(fieldName, newValue);
                              // 设置光标位置
                              setTimeout(() => {
                                input.focus();
                                input.setSelectionRange(start + v.name.length, start + v.name.length);
                              }, 0);
                            } else {
                              // 如果无法获取光标，则追加到末尾
                              const newValue = currentValue + v.name;
                              setValue(newValue);
                              form.setFieldValue(fieldName, newValue);
                            }
                          }}
                          style={{ fontFamily: 'monospace', fontSize: '12px' }}
                        >
                          {v.name}
                        </Button>
                      </Tooltip>
                    ))}
                  </div>
                  <div style={{ color: 'var(--color-text-secondary)', fontSize: '12px' }}>
                    💡 电影模板中使用季/集变量时将输出为空
                  </div>
                </div>
              )
            }
          ]}
        />

        {/* 电影/电视配置Tabs */}
        <Tabs
          activeKey={activeConfigTab}
          onChange={setActiveConfigTab}
          items={[
            {
              key: 'movie',
              label: <span>🎬 电影/剧场版</span>,
              children: (
                <div>

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
          label="命名模板"
          name="movieDanmakuFilenameTemplate"
        >
          <div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Input
                ref={movieTemplateInputRef}
                value={movieDanmakuFilenameTemplate}
                onChange={(e) => {
                  setMovieDanmakuFilenameTemplate(e.target.value);
                  form.setFieldValue('movieDanmakuFilenameTemplate', e.target.value);
                }}
                placeholder="${title}/${episodeId}"
                disabled={!customDanmakuPathEnabled}
                style={{ flex: 1 }}
              />
              <Button
                icon={<FileOutlined />}
                onClick={() => {
                  setQuickTemplateType('movie');
                  setQuickTemplateModalVisible(true);
                }}
                disabled={!customDanmakuPathEnabled}
              >
                快速模板
              </Button>
            </div>
            <div style={{ color: 'var(--color-text-secondary)', fontSize: '12px', marginTop: '8px' }}>
              💡 支持子目录如 {'${title}/${episodeId}'}，.xml后缀会自动拼接
            </div>
          </div>
        </Form.Item>

        {/* 电影路径预览 */}
        <Form.Item label={
          <Space>
            👀 路径预览
          </Space>
        }>
          <div style={{
            padding: '16px',
            background: 'var(--color-hover)',
            borderRadius: '8px',
            border: '1px solid var(--color-border)',
            fontFamily: 'JetBrains Mono, Consolas, monospace',
            fontSize: '13px',
            wordBreak: 'break-all',
            color: 'var(--color-text)'
          }}>
            {moviePreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: 'var(--color-text-secondary)', fontSize: '12px', marginTop: '8px' }}>
            📝 示例: 铃芽之旅 (2022)
          </div>
        </Form.Item>
                </div>
              )
            },
            {
              key: 'tv',
              label: <span>📺 电视节目</span>,
              children: (
                <div>
        {/* 电视存储目录 */}
        <Form.Item
          label="存储目录"
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
          label="命名模板"
          name="tvDanmakuFilenameTemplate"
        >
          <div>
            <div style={{ display: 'flex', gap: '8px' }}>
              <Input
                ref={tvTemplateInputRef}
                value={tvDanmakuFilenameTemplate}
                onChange={(e) => {
                  setTvDanmakuFilenameTemplate(e.target.value);
                  form.setFieldValue('tvDanmakuFilenameTemplate', e.target.value);
                }}
                placeholder="${animeId}/${episodeId}"
                disabled={!customDanmakuPathEnabled}
                style={{ flex: 1 }}
              />
              <Button
                icon={<FileOutlined />}
                onClick={() => {
                  setQuickTemplateType('tv');
                  setQuickTemplateModalVisible(true);
                }}
                disabled={!customDanmakuPathEnabled}
              >
                快速模板
              </Button>
            </div>
            <div style={{ color: 'var(--color-text-secondary)', fontSize: '12px', marginTop: '8px' }}>
              💡 支持子目录如 {'${animeId}/${episodeId}'}，.xml后缀会自动拼接
            </div>
          </div>
        </Form.Item>

        {/* 电视路径预览 */}
        <Form.Item label={
          <Space>
            👀 路径预览
          </Space>
        }>
          <div style={{
            padding: '16px',
            background: 'var(--color-hover)',
            borderRadius: '8px',
            border: '1px solid var(--color-border)',
            fontFamily: 'JetBrains Mono, Consolas, monospace',
            fontSize: '13px',
            wordBreak: 'break-all',
            color: 'var(--color-text)'
          }}>
            {tvPreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: 'var(--color-text-secondary)', fontSize: '12px', marginTop: '8px' }}>
            📝 示例: 葬送的芙莉莲 S01E01
          </div>
        </Form.Item>
                </div>
              )
            }
          ]}
        />

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
              <Popover
                trigger="click"
                placement="bottom"
                content={(
                  <div style={{ width: 250 }}>
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Input
                        placeholder="搜索标题..."
                        value={libraryKeyword}
                        onChange={(e) => setLibraryKeyword(e.target.value)}
                        onPressEnter={handleLibrarySearch}
                        prefix={<SearchOutlined />}
                        allowClear
                      />
                      <div className="flex gap-2 justify-end">
                        <Button
                          size="small"
                          onClick={() => {
                            setLibraryKeyword('');
                            handleLibrarySearch();
                          }}
                        >
                          清除
                        </Button>
                        <Button
                          type="primary"
                          size="small"
                          icon={<SearchOutlined />}
                          onClick={handleLibrarySearch}
                        >
                          搜索
                        </Button>
                      </div>
                    </Space>
                  </div>
                )}
              >
                <Button icon={<SearchOutlined />}>
                  搜索{libraryKeyword && <span className="ml-1 text-blue-500">({libraryKeyword})</span>}
                </Button>
              </Popover>
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
                  onChange={(e) => setMigrateTargetPath(e.target.value)}
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

            {/* 预览区域 */}
            {migratePreviewData && (
              <>
                <Divider orientation="left">迁移预览</Divider>
                <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 4, padding: 8 }}>
                  {migratePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 12, padding: 8, background: 'var(--color-hover)', borderRadius: 4 }}>
                      <div style={{ fontWeight: 500, marginBottom: 4 }}>
                        {item.animeTitle} {item.episodeIndex ? `第${item.episodeIndex}集` : ''}
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
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
                <div style={{ marginTop: 8, color: 'var(--color-text-secondary)' }}>
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

          {/* 重命名Modal - 多规则系统 */}
          <Modal
            title="批量重命名"
            open={renameModalVisible}
            onCancel={() => {
              setRenameModalVisible(false);
              setRenameRules([]);
              setRuleParams({});
              setIsRenamePreviewMode(false);
              setRenamePreviewData(null);
            }}
            onOk={handleExecuteRename}
            confirmLoading={operationLoading}
            okText="确认重命名"
            okButtonProps={{ disabled: renameRules.length === 0 }}
            width={800}
          >
            {/* 规则添加区域 */}
            <div style={{ marginBottom: 16, padding: 12, background: 'var(--color-hover)', borderRadius: 8 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ color: 'var(--color-text-secondary)', fontSize: 13 }}>添加规则:</span>
                <Select
                  value={selectedRuleType}
                  onChange={(v) => { setSelectedRuleType(v); setRuleParams({}); }}
                  style={{ width: 100 }}
                  options={ruleTypeOptions}
                  size="small"
                />
                {/* 替换规则参数 */}
                {selectedRuleType === 'replace' && (
                  <>
                    <Input size="small" value={ruleParams.search || ''} onChange={(e) => setRuleParams(p => ({ ...p, search: e.target.value }))} placeholder="查找" style={{ width: 120 }} />
                    <span style={{ color: 'var(--color-text-secondary)' }}>→</span>
                    <Input size="small" value={ruleParams.replace || ''} onChange={(e) => setRuleParams(p => ({ ...p, replace: e.target.value }))} placeholder="替换为" style={{ width: 120 }} />
                    <Checkbox checked={ruleParams.caseSensitive || false} onChange={(e) => setRuleParams(p => ({ ...p, caseSensitive: e.target.checked }))}>区分大小写</Checkbox>
                  </>
                )}
                {/* 正则规则参数 */}
                {selectedRuleType === 'regex' && (
                  <>
                    <Input size="small" value={ruleParams.pattern || ''} onChange={(e) => setRuleParams(p => ({ ...p, pattern: e.target.value }))} placeholder="正则表达式" style={{ width: 150 }} />
                    <span style={{ color: 'var(--color-text-secondary)' }}>→</span>
                    <Input size="small" value={ruleParams.replace || ''} onChange={(e) => setRuleParams(p => ({ ...p, replace: e.target.value }))} placeholder="替换为" style={{ width: 120 }} />
                  </>
                )}
                {/* 插入规则参数 */}
                {selectedRuleType === 'insert' && (
                  <>
                    <Input size="small" value={ruleParams.text || ''} onChange={(e) => setRuleParams(p => ({ ...p, text: e.target.value }))} placeholder="插入文本" style={{ width: 120 }} />
                    <Select
                      size="small"
                      value={ruleParams.position || 'start'}
                      onChange={(v) => setRuleParams(p => ({ ...p, position: v }))}
                      style={{ width: 100 }}
                      options={[
                        { value: 'start', label: '开头' },
                        { value: 'end', label: '结尾' },
                        { value: 'index', label: '指定位置' }
                      ]}
                    />
                    {ruleParams.position === 'index' && (
                      <InputNumber
                        size="small"
                        value={ruleParams.index || 0}
                        onChange={(v) => setRuleParams(p => ({ ...p, index: v }))}
                        min={0}
                        placeholder="位置"
                        style={{ width: 80 }}
                        addonAfter="位"
                      />
                    )}
                  </>
                )}
                {/* 删除规则参数 */}
                {selectedRuleType === 'delete' && (
                  <>
                    <Select
                      size="small"
                      value={ruleParams.mode || 'text'}
                      onChange={(v) => setRuleParams(p => ({ ...p, mode: v }))}
                      style={{ width: 140 }}
                      options={[
                        { value: 'text', label: '删除文本' },
                        { value: 'first', label: '删除前N个字符' },
                        { value: 'last', label: '删除后N个字符' },
                        { value: 'toText', label: '从开头删到文本' },
                        { value: 'fromText', label: '从文本删到结尾' },
                        { value: 'range', label: '删除范围' },
                      ]}
                    />
                    {/* 删除指定文本 */}
                    {(ruleParams.mode === 'text' || !ruleParams.mode) && (
                      <>
                        <Input
                          size="small"
                          value={ruleParams.text || ''}
                          onChange={(e) => setRuleParams(p => ({ ...p, text: e.target.value }))}
                          placeholder="要删除的文本"
                          style={{ width: 120 }}
                        />
                        <Checkbox
                          checked={ruleParams.caseSensitive || false}
                          onChange={(e) => setRuleParams(p => ({ ...p, caseSensitive: e.target.checked }))}
                        >
                          区分大小写
                        </Checkbox>
                      </>
                    )}
                    {/* 删除前N个字符 */}
                    {ruleParams.mode === 'first' && (
                      <Input
                        size="small"
                        type="number"
                        value={ruleParams.count || ''}
                        onChange={(e) => setRuleParams(p => ({ ...p, count: e.target.value }))}
                        placeholder="字符数"
                        style={{ width: 100 }}
                      />
                    )}
                    {/* 删除后N个字符 */}
                    {ruleParams.mode === 'last' && (
                      <Input
                        size="small"
                        type="number"
                        value={ruleParams.count || ''}
                        onChange={(e) => setRuleParams(p => ({ ...p, count: e.target.value }))}
                        placeholder="字符数"
                        style={{ width: 100 }}
                      />
                    )}
                    {/* 从开头删到文本 */}
                    {ruleParams.mode === 'toText' && (
                      <>
                        <Input
                          size="small"
                          value={ruleParams.text || ''}
                          onChange={(e) => setRuleParams(p => ({ ...p, text: e.target.value }))}
                          placeholder="删除到此文本"
                          style={{ width: 120 }}
                        />
                        <Checkbox
                          checked={ruleParams.caseSensitive || false}
                          onChange={(e) => setRuleParams(p => ({ ...p, caseSensitive: e.target.checked }))}
                        >
                          区分大小写
                        </Checkbox>
                      </>
                    )}
                    {/* 从文本删到结尾 */}
                    {ruleParams.mode === 'fromText' && (
                      <>
                        <Input
                          size="small"
                          value={ruleParams.text || ''}
                          onChange={(e) => setRuleParams(p => ({ ...p, text: e.target.value }))}
                          placeholder="从此文本删除"
                          style={{ width: 120 }}
                        />
                        <Checkbox
                          checked={ruleParams.caseSensitive || false}
                          onChange={(e) => setRuleParams(p => ({ ...p, caseSensitive: e.target.checked }))}
                        >
                          区分大小写
                        </Checkbox>
                      </>
                    )}
                    {/* 删除范围 */}
                    {ruleParams.mode === 'range' && (
                      <>
                        <span style={{ fontSize: 13 }}>从位置</span>
                        <Input
                          size="small"
                          type="number"
                          value={ruleParams.from || ''}
                          onChange={(e) => setRuleParams(p => ({ ...p, from: e.target.value }))}
                          placeholder="起始位置"
                          style={{ width: 90 }}
                        />
                        <span style={{ fontSize: 13 }}>删除</span>
                        <Input
                          size="small"
                          type="number"
                          value={ruleParams.count || ''}
                          onChange={(e) => setRuleParams(p => ({ ...p, count: e.target.value }))}
                          placeholder="字符数"
                          style={{ width: 80 }}
                        />
                        <span style={{ fontSize: 13 }}>个字符</span>
                      </>
                    )}
                  </>
                )}
                {/* 序列化规则参数 */}
                {selectedRuleType === 'serialize' && (
                  <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px', background: 'var(--color-hover)', borderRadius: '6px' }}>
                    {/* 第一行：格式结构 */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>格式结构:</span>
                      <Input
                        size="small"
                        value={ruleParams.prefix || ''}
                        onChange={(e) => setRuleParams(p => ({ ...p, prefix: e.target.value }))}
                        placeholder="第"
                        style={{ width: 120 }}
                        addonBefore="前缀"
                      />
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>+</span>
                      <span style={{ padding: '2px 8px', background: '#e6f7ff', color: '#1890ff', borderRadius: '4px', fontSize: 12, fontFamily: 'monospace' }}>
                        序号
                      </span>
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>+</span>
                      <Input
                        size="small"
                        value={ruleParams.suffix || ''}
                        onChange={(e) => setRuleParams(p => ({ ...p, suffix: e.target.value }))}
                        placeholder="集"
                        style={{ width: 120 }}
                        addonBefore="后缀"
                      />
                    </div>
                    {/* 第二行：序号参数 */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 13, color: 'var(--color-text-tertiary)' }}>序号设置:</span>
                      <InputNumber
                        size="small"
                        value={ruleParams.start || 1}
                        onChange={(v) => setRuleParams(p => ({ ...p, start: v }))}
                        min={0}
                        placeholder="起始"
                        style={{ width: 130 }}
                        addonBefore="起始值"
                      />
                      <InputNumber
                        size="small"
                        value={ruleParams.digits || 2}
                        onChange={(v) => setRuleParams(p => ({ ...p, digits: v }))}
                        min={1}
                        max={5}
                        placeholder="位数"
                        style={{ width: 130 }}
                        addonBefore="补零位数"
                      />
                      <Select
                        size="small"
                        value={ruleParams.position || 'replace'}
                        onChange={(v) => setRuleParams(p => ({ ...p, position: v }))}
                        style={{ width: 100 }}
                        options={[
                          { value: 'start', label: '添加到开头' },
                          { value: 'end', label: '添加到结尾' },
                          { value: 'replace', label: '替换文件名' }
                        ]}
                      />
                    </div>
                    {/* 第三行：效果预览 */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>效果预览:</span>
                      <span style={{ fontSize: 13, fontFamily: 'monospace', color: '#1890ff', fontWeight: '600' }}>
                        {
                          ruleParams.position === 'start'
                            ? `${ruleParams.prefix || ''}${String(ruleParams.start || 1).padStart(ruleParams.digits || 2, '0')}${ruleParams.suffix || ''}原文件名`
                            : ruleParams.position === 'end'
                            ? `原文件名${ruleParams.prefix || ''}${String(ruleParams.start || 1).padStart(ruleParams.digits || 2, '0')}${ruleParams.suffix || ''}`
                            : `${ruleParams.prefix || ''}${String(ruleParams.start || 1).padStart(ruleParams.digits || 2, '0')}${ruleParams.suffix || ''}`
                        }
                      </span>
                    </div>
                  </div>
                )}
                {/* 大小写规则参数 */}
                {selectedRuleType === 'case' && (
                  <Select size="small" value={ruleParams.mode || 'upper'} onChange={(v) => setRuleParams(p => ({ ...p, mode: v }))} style={{ width: 120 }} options={[{ value: 'upper', label: '全大写' }, { value: 'lower', label: '全小写' }, { value: 'title', label: '首字母大写' }]} />
                )}
                {/* 清理规则参数 */}
                {selectedRuleType === 'strip' && (
                  <>
                    <Checkbox checked={ruleParams.trimSpaces || false} onChange={(e) => setRuleParams(p => ({ ...p, trimSpaces: e.target.checked }))}>首尾空格</Checkbox>
                    <Checkbox checked={ruleParams.trimDuplicateSpaces || false} onChange={(e) => setRuleParams(p => ({ ...p, trimDuplicateSpaces: e.target.checked }))}>重复空格</Checkbox>
                    <Input size="small" value={ruleParams.chars || ''} onChange={(e) => setRuleParams(p => ({ ...p, chars: e.target.value }))} placeholder="删除字符" style={{ width: 80 }} />
                  </>
                )}
                <Button type="primary" size="small" onClick={handleAddRenameRule}>+ 添加</Button>
              </div>
            </div>

            {/* 已添加的规则列表 */}
            {renameRules.length > 0 && (
              <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: 8, marginBottom: 16, background: 'var(--color-card)', maxHeight: 120, overflowY: 'auto' }}>
                {renameRules.map((rule, idx) => (
                  <div key={rule.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: idx < renameRules.length - 1 ? '1px solid var(--color-border)' : 'none' }}>
                    <Checkbox checked={rule.enabled} onChange={() => handleToggleRenameRule(rule.id)} />
                    <span style={{ color: 'var(--color-text-secondary)', fontSize: 12 }}>{idx + 1}.</span>
                    <Tag color={rule.enabled ? 'blue' : 'default'}>{ruleTypeOptions.find(r => r.value === rule.type)?.label}</Tag>
                    <span style={{ fontSize: 13, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {rule.type === 'replace' && `"${rule.params.search}" → "${rule.params.replace || ''}"`}
                      {rule.type === 'regex' && `/${rule.params.pattern}/ → "${rule.params.replace || ''}"`}
                      {rule.type === 'insert' && `"${rule.params.text}" (${rule.params.position === 'start' ? '开头' : '结尾'})`}
                      {rule.type === 'delete' && (() => {
                        const mode = rule.params.mode || 'text';
                        switch (mode) {
                          case 'text':
                            return `删除文本 "${rule.params.text}"`;
                          case 'first':
                            return `删除前 ${rule.params.count || 0} 个字符`;
                          case 'last':
                            return `删除后 ${rule.params.count || 0} 个字符`;
                          case 'toText':
                            return `从开头删到 "${rule.params.text}"`;
                          case 'fromText':
                            return `从 "${rule.params.text}" 删到结尾`;
                          case 'range':
                            return `从位置 ${rule.params.from || 0} 删除 ${rule.params.count || 0} 个字符`;
                          default:
                            return '删除';
                        }
                      })()}
                      {rule.type === 'serialize' && `${rule.params.prefix || ''}{${String(rule.params.start || 1).padStart(rule.params.digits || 2, '0')}}${rule.params.suffix || ''}`}
                      {rule.type === 'case' && (rule.params.mode === 'upper' ? '全大写' : rule.params.mode === 'lower' ? '全小写' : '首字母大写')}
                      {rule.type === 'strip' && '清理空格/字符'}
                    </span>
                    <Button type="text" danger size="small" onClick={() => handleDeleteRenameRule(rule.id)}>🗑</Button>
                  </div>
                ))}
              </div>
            )}

            {/* 预览开关和操作 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13 }}>👁 预览效果</span>
                <Switch
                  checked={isRenamePreviewMode}
                  onChange={(checked) => {
                    if (checked && renameOriginalItems.length > 0) {
                      // 使用从后端获取的原始文件名列表计算预览数据
                      const previewItems = renameOriginalItems.map((item, index) => {
                        const oldName = item.oldName;
                        const baseName = oldName.replace(/\.[^/.]+$/, '');
                        const ext = oldName.includes('.') ? '.' + oldName.split('.').pop() : '';
                        const newBaseName = applyAllRenameRules(baseName, index);
                        return {
                          oldName: oldName,
                          newName: newBaseName + ext,
                          episodeId: item.episodeId,
                          oldPath: item.oldPath
                        };
                      });
                      setRenamePreviewData({ totalCount: previewItems.length, previewItems: previewItems.slice(0, 20) });
                      setIsRenamePreviewMode(true);
                    } else {
                      setIsRenamePreviewMode(false);
                      setRenamePreviewData(null);
                    }
                  }}
                  disabled={renameOriginalItems.length === 0}
                  size="small"
                />
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                将重命名 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{renameOriginalItems.length}</strong> 个弹幕文件
              </Text>
            </div>

            {/* 预览区域 */}
            {isRenamePreviewMode && renamePreviewData && (
              <>
                <Divider orientation="left" style={{ margin: '8px 0' }}>重命名预览 (显示前20条)</Divider>
                <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 4, padding: 8 }}>
                  {renamePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 8, padding: 6, background: 'var(--color-hover)', borderRadius: 4 }}>
                      <div style={{ fontSize: 13 }}>
                        <Text code style={{ fontSize: 12 }}>{item.oldName}</Text>
                        <span style={{ margin: '0 8px', color: 'var(--color-text-secondary)' }}>→</span>
                        <Text code style={{ fontSize: 12, color: '#52c41a' }}>{item.newName}</Text>
                      </div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 8, color: 'var(--color-text-secondary)', fontSize: 12 }}>
                  共 <strong>{renamePreviewData.totalCount}</strong> 个文件将被重命名
                </div>
              </>
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
                {(templateVariables || []).map((v) => (
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
                            customTemplate: v === 'custom' ? customTemplate : undefined,
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
                <div style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 4, padding: 8 }}>
                  {templatePreviewData.previewItems.map((item, index) => (
                    <div key={index} style={{ marginBottom: 12, padding: 8, background: 'var(--color-hover)', borderRadius: 4 }}>
                      <div style={{ fontWeight: 500, marginBottom: 4 }}>
                        {item.animeTitle} {item.episodeIndex ? `第${item.episodeIndex}集` : ''}
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>
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
                <div style={{ marginTop: 8, color: 'var(--color-text-secondary)' }}>
                  共 <strong>{templatePreviewData.totalCount}</strong> 个文件将被转换
                </div>
              </>
            )}

            {!templatePreviewData && !templatePreviewLoading && (
              <>
                <Divider />
                <div style={{ color: 'var(--color-text-secondary)' }}>
                  将转换 <strong>{selectedRows.length}</strong> 个条目，共 <strong>{selectedEpisodeCount}</strong> 个弹幕文件
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    <Text type="secondary">选择模板后将自动显示预览</Text>
                  </div>
                </div>
              </>
            )}
            {templatePreviewLoading && (
              <div style={{ textAlign: 'center', padding: 20, color: 'var(--color-text-secondary)' }}>
                正在加载预览...
              </div>
            )}
          </Modal>
        </TabPane>

        <TabPane tab="设置" key="settings">
          <div style={{ maxWidth: 600 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              <span>获取点赞</span>
              <Switch
                checked={likesFetchEnabled}
                onChange={async (checked) => {
                  setLikesFetchEnabled(checked);
                  try {
                    await setDanmakuLikesFetchEnabled({ value: checked ? 'true' : 'false' });
                    message.success(checked ? '已启用获取点赞' : '已关闭获取点赞');
                  } catch (error) {
                    message.error('保存失败');
                    setLikesFetchEnabled(!checked);
                  }
                }}
              />
            </div>
            <div style={{ color: '#999', fontSize: 12 }}>
              启用后，下载弹幕时会获取并存储点赞信息到弹幕文件中。关闭后新下载的弹幕将不包含点赞数据。
            </div>
          </div>
        </TabPane>
      </Tabs>

      {/* 目录浏览器（用于存储配置中选择目录） */}
      <DirectoryBrowser
        visible={browserVisible}
        onClose={() => setBrowserVisible(false)}
        onSelect={handleSelectDirectory}
      />

      {/* 快速模板选择弹窗 */}
      <Modal
        title="📋 选择模板"
        open={quickTemplateModalVisible}
        onCancel={() => setQuickTemplateModalVisible(false)}
        footer={null}
        width={500}
      >
        <div style={{ marginBottom: '16px', color: 'var(--color-text-secondary)', fontSize: '13px' }}>
          选择一个预设模板，将自动填充到{quickTemplateType === 'movie' ? '电影' : '电视节目'}命名模板中
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {presetTemplates.filter(t => !t.value.startsWith('custom_')).map((tpl) => (
            <Button
              key={tpl.value}
              block
              style={{
                textAlign: 'left',
                height: 'auto',
                padding: '12px 16px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start'
              }}
              onClick={() => {
                if (quickTemplateType === 'movie') {
                  setMovieDanmakuFilenameTemplate(tpl.template);
                  form.setFieldValue('movieDanmakuFilenameTemplate', tpl.template);
                } else {
                  setTvDanmakuFilenameTemplate(tpl.template);
                  form.setFieldValue('tvDanmakuFilenameTemplate', tpl.template);
                }
                setQuickTemplateModalVisible(false);
                message.success(`已应用模板: ${tpl.label}`);
              }}
            >
              <div style={{ fontWeight: 500 }}>{tpl.label}</div>
              <div style={{
                fontSize: '12px',
                color: 'var(--color-text-secondary)',
                fontFamily: 'monospace',
                marginTop: '4px'
              }}>
                {tpl.template}
              </div>
            </Button>
          ))}
        </div>
      </Modal>
    </Card>
  );
};

export default DanmakuStorage;

