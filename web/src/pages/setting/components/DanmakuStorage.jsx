import React, { useState, useEffect } from 'react';
import { Form, Input, Switch, Button, Space, message, Popconfirm, Card } from 'antd';
import { getConfig, setConfig } from '@/apis';

const DanmakuStorage = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [customDanmakuPathEnabled, setCustomDanmakuPathEnabled] = useState(false);
  const [danmakuDirectoryPath, setDanmakuDirectoryPath] = useState('/app/config/danmaku');
  const [danmakuFilenameTemplate, setDanmakuFilenameTemplate] = useState('${animeId}/${episodeId}');
  const [previewPath, setPreviewPath] = useState('');

  // 加载配置
  useEffect(() => {
    loadConfig();
  }, []);

  // 更新路径预览
  useEffect(() => {
    updatePreview();
  }, [customDanmakuPathEnabled, danmakuDirectoryPath, danmakuFilenameTemplate]);

  const loadConfig = async () => {
    try {
      setLoading(true);
      
      // 加载配置
      const enabledRes = await getConfig('customDanmakuPathEnabled');
      const directoryRes = await getConfig('danmakuDirectoryPath');
      const templateRes = await getConfig('danmakuFilenameTemplate');
      
      const enabled = enabledRes?.data?.configValue === 'true';
      const directory = directoryRes?.data?.configValue || '/app/config/danmaku';
      const template = templateRes?.data?.configValue || '${animeId}/${episodeId}';
      
      setCustomDanmakuPathEnabled(enabled);
      setDanmakuDirectoryPath(directory);
      setDanmakuFilenameTemplate(template);
      
      form.setFieldsValue({
        customDanmakuPathEnabled: enabled,
        danmakuDirectoryPath: directory,
        danmakuFilenameTemplate: template,
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
      setPreviewPath('/app/config/danmaku/160/25000160010001.xml (默认路径)');
      return;
    }

    // 示例数据
    const exampleContext = {
      animeId: '160',
      episodeId: '25000160010001',
      title: '葬送的芙莉莲',
      season: '1',
      episode: '1',
      year: '2023',
      provider: 'bilibili',
      sourceId: '192'
    };

    // 替换变量
    let preview = danmakuFilenameTemplate;
    
    // 处理格式化变量 (如 ${season:02d})
    preview = preview.replace(/\$\{(\w+):(\w+)\}/g, (match, varName, format) => {
      const value = exampleContext[varName];
      if (value && format.endsWith('d')) {
        const num = parseInt(value);
        const width = parseInt(format.match(/\d+/)?.[0] || '0');
        return num.toString().padStart(width, '0');
      }
      return value || match;
    });
    
    // 处理普通变量 (如 ${animeId})
    preview = preview.replace(/\$\{(\w+)\}/g, (match, varName) => {
      return exampleContext[varName] || match;
    });

    // 拼接完整路径
    const directory = danmakuDirectoryPath.replace(/[\/\\]+$/, ''); // 移除末尾斜杠
    const filename = preview.replace(/^[\/\\]+/, ''); // 移除开头斜杠
    
    // 自动添加.xml后缀
    const fullPath = `${directory}/${filename}${filename.endsWith('.xml') ? '' : '.xml'}`;
    
    setPreviewPath(fullPath);
  };

  const handleSave = async () => {
    try {
      setLoading(true);

      // 保存配置
      await setConfig('customDanmakuPathEnabled', customDanmakuPathEnabled ? 'true' : 'false');
      await setConfig('danmakuDirectoryPath', danmakuDirectoryPath);
      await setConfig('danmakuFilenameTemplate', danmakuFilenameTemplate);

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

  const setTemplate = (template) => {
    setDanmakuFilenameTemplate(template);
    form.setFieldValue('danmakuFilenameTemplate', template);
  };

  return (
    <Card title="弹幕存储配置" loading={loading}>
      <Form
        form={form}
        layout="vertical"
        style={{ maxWidth: 800 }}
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

        {/* 弹幕存储目录 */}
        <Form.Item 
          label="弹幕存储目录"
          name="danmakuDirectoryPath"
        >
          <div>
            <Input 
              value={danmakuDirectoryPath}
              onChange={(e) => {
                setDanmakuDirectoryPath(e.target.value);
                form.setFieldValue('danmakuDirectoryPath', e.target.value);
              }}
              placeholder="/app/config/danmaku"
              disabled={!customDanmakuPathEnabled}
            />
            <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
              所有弹幕文件的根目录
            </div>
          </div>
        </Form.Item>

        {/* 弹幕命名模板 */}
        <Form.Item 
          label="弹幕命名模板"
          name="danmakuFilenameTemplate"
        >
          <div>
            <Input 
              value={danmakuFilenameTemplate}
              onChange={(e) => {
                setDanmakuFilenameTemplate(e.target.value);
                form.setFieldValue('danmakuFilenameTemplate', e.target.value);
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
                  onClick={() => setTemplate('${animeId}/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  按番剧ID分组: {'${animeId}'}/<wbr/>{'${episodeId}'}
                </Button>
                <Button 
                  size="small" 
                  onClick={() => setTemplate('${title}/Season ${season}/${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  按标题+季度分组: {'${title}'}/Season {'${season}'}/<wbr/>{'${episodeId}'}
                </Button>
                <Button 
                  size="small" 
                  onClick={() => setTemplate('${title}/${title} - S${season:02d}E${episode:02d}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  Plex风格: {'${title}'}/<wbr/>{'${title}'} - S{'${season:02d}'}E{'${episode:02d}'}
                </Button>
                <Button 
                  size="small" 
                  onClick={() => setTemplate('${episodeId}')}
                  disabled={!customDanmakuPathEnabled}
                >
                  扁平结构: {'${episodeId}'}
                </Button>
              </div>
            </div>
          </div>
        </Form.Item>

        {/* 路径预览 */}
        <Form.Item label="路径预览">
          <div style={{ 
            padding: '12px', 
            background: '#f5f5f5', 
            borderRadius: '4px',
            fontFamily: 'monospace',
            wordBreak: 'break-all'
          }}>
            {previewPath || '请配置模板以查看预览'}
          </div>
          <div style={{ color: '#999', fontSize: '12px', marginTop: '4px' }}>
            示例路径预览(基于当前配置)
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

