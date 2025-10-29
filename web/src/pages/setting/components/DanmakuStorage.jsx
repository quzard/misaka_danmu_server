import React, { useState, useEffect } from 'react';
import { Form, Input, Switch, Button, Space, message, Popconfirm, Card, Divider, Typography } from 'antd';
import { getConfig, setConfig } from '@/apis';

const { Text } = Typography;

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

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 更新路径预览
  useEffect(() => {
    updatePreview();
  }, [customDanmakuPathEnabled, movieDanmakuDirectoryPath, movieDanmakuFilenameTemplate, tvDanmakuDirectoryPath, tvDanmakuFilenameTemplate]);

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

  const setMovieTemplate = (template) => {
    setMovieDanmakuFilenameTemplate(template);
    form.setFieldValue('movieDanmakuFilenameTemplate', template);
  };

  const setTvTemplate = (template) => {
    setTvDanmakuFilenameTemplate(template);
    form.setFieldValue('tvDanmakuFilenameTemplate', template);
  };

  return (
    <Card title="弹幕存储配置" loading={loading}>
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

        <Divider orientation="left">电影/剧场版配置</Divider>

        {/* 电影存储目录 */}
        <Form.Item
          label="电影存储目录"
          name="movieDanmakuDirectoryPath"
        >
          <div>
            <Input
              value={movieDanmakuDirectoryPath}
              onChange={(e) => {
                setMovieDanmakuDirectoryPath(e.target.value);
                form.setFieldValue('movieDanmakuDirectoryPath', e.target.value);
              }}
              placeholder="/app/config/danmaku/movies"
              disabled={!customDanmakuPathEnabled}
            />
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

            <div style={{ marginTop: '12px' }}>
              <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>常用模板示例:</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <Button
                  size="small"
                  onClick={() => setMovieTemplate('${title}/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  按标题分组: {'${title}'}/<wbr/>{'${episodeId}'}
                </Button>
                <Button
                  size="small"
                  onClick={() => setMovieTemplate('${title} (${year})/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  标题+年份: {'${title}'} ({'${year}'})/<wbr/>{'${episodeId}'}
                </Button>
                <Button
                  size="small"
                  onClick={() => setMovieTemplate('${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  扁平结构: {'${episodeId}'}
                </Button>
              </div>
            </div>
          </div>
        </Form.Item>

        {/* 电影路径预览 */}
        <Form.Item label="电影路径预览">
          <div style={{
            padding: '12px',
            background: '#f5f5f5',
            borderRadius: '4px',
            fontFamily: 'monospace',
            wordBreak: 'break-all'
          }}>
            {moviePreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
            示例: 铃芽之旅 (2022)
          </div>
        </Form.Item>

        <Divider orientation="left">电视节目配置</Divider>

        {/* 电视存储目录 */}
        <Form.Item
          label="电视存储目录"
          name="tvDanmakuDirectoryPath"
        >
          <div>
            <Input
              value={tvDanmakuDirectoryPath}
              onChange={(e) => {
                setTvDanmakuDirectoryPath(e.target.value);
                form.setFieldValue('tvDanmakuDirectoryPath', e.target.value);
              }}
              placeholder="/app/config/danmaku/tv"
              disabled={!customDanmakuPathEnabled}
            />
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

            <div style={{ marginTop: '12px' }}>
              <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>常用模板示例:</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <Button
                  size="small"
                  onClick={() => setTvTemplate('${animeId}/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  按番剧ID分组: {'${animeId}'}/<wbr/>{'${episodeId}'}
                </Button>
                <Button
                  size="small"
                  onClick={() => setTvTemplate('${title}/Season ${season}/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  按标题+季度分组: {'${title}'}/Season {'${season}'}/<wbr/>{'${episodeId}'}
                </Button>
                <Button
                  size="small"
                  onClick={() => setTvTemplate('${title}/${title} - S${season:02d}E${episode:02d}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  Plex风格: {'${title}'}/<wbr/>{'${title}'} - S{'${season:02d}'}E{'${episode:02d}'}
                </Button>
                <Button
                  size="small"
                  onClick={() => setTvTemplate('${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  扁平结构: {'${episodeId}'}
                </Button>
              </div>
            </div>
          </div>
        </Form.Item>

        {/* 电视路径预览 */}
        <Form.Item label="电视路径预览">
          <div style={{
            padding: '12px',
            background: '#f5f5f5',
            borderRadius: '4px',
            fontFamily: 'monospace',
            wordBreak: 'break-all'
          }}>
            {tvPreviewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
            示例: 葬送的芙莉莲 S01E01
          </div>
        </Form.Item>

        {/* 操作按钮 */}
        <Form.Item>
          <Space>
            <Button type="primary" onClick={handleSave} loading={loading}>
              保存配置
            </Button>
            <Button onClick={handleBatchRename} disabled={!customDanmakuPathEnabled || loading}>
              批量重命名现有文件
            </Button>
            <Popconfirm
              title="确定要迁移弹幕目录吗?"
              description="此操作会移动所有弹幕文件到新目录"
              onConfirm={handleMigrateDirectory}
              disabled={!customDanmakuPathEnabled || loading}
            >
              <Button danger disabled={!customDanmakuPathEnabled || loading}>
                迁移弹幕目录
              </Button>
            </Popconfirm>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );
};

export default DanmakuStorage;

