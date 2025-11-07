import { useState, useEffect } from 'react';
import { Card, Input, Button, message, Space } from 'antd';
import { ScanOutlined, FolderOpenOutlined } from '@ant-design/icons';
import LocalItemList from './LocalItemList';
import DirectoryBrowser from './DirectoryBrowser';
import { scanLocalDanmaku, getLastScanPath, saveScanPath } from '../../../apis';

const LocalScan = () => {
  const [scanPath, setScanPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [browserVisible, setBrowserVisible] = useState(false);

  // 组件加载时获取上次使用的路径
  useEffect(() => {
    loadLastPath();
  }, []);

  const loadLastPath = async () => {
    try {
      const response = await getLastScanPath();
      if (response.data.path) {
        setScanPath(response.data.path);
      }
    } catch (error) {
      console.error('加载上次路径失败:', error);
    }
  };

  // 扫描本地弹幕
  const handleScan = async () => {
    if (!scanPath) {
      message.warning('请选择或输入扫描路径');
      return;
    }

    setLoading(true);
    try {
      const res = await scanLocalDanmaku(scanPath);
      message.success(res.data.message || '扫描完成');
      // 触发列表刷新
      setRefreshTrigger(prev => prev + 1);
    } catch (error) {
      message.error('扫描失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 打开目录浏览器
  const handleBrowse = () => {
    setBrowserVisible(true);
  };

  // 选择目录
  const handleSelectDirectory = async (path) => {
    setScanPath(path);
    // 自动保存路径
    try {
      await saveScanPath(path);
      message.success(`已选择目录: ${path}`);
    } catch (error) {
      console.error('保存路径失败:', error);
      message.success(`已选择目录: ${path}`);  // 即使保存失败也显示选择成功
    }
  };

  return (
    <div>
      <Card title="本地弹幕扫描" style={{ marginBottom: '24px' }}>
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ marginBottom: '8px', color: '#666' }}>
              扫描路径 (支持标准媒体服务器结构和纯弹幕文件结构)
            </div>
            <Space.Compact style={{ width: '100%' }}>
              <Input
                placeholder="请选择或输入扫描路径"
                value={scanPath}
                onChange={(e) => setScanPath(e.target.value)}
              />
              <Button
                icon={<FolderOpenOutlined />}
                onClick={handleBrowse}
              >
                浏览
              </Button>
              <Button
                type="primary"
                icon={<ScanOutlined />}
                loading={loading}
                onClick={handleScan}
              >
                扫描
              </Button>
            </Space.Compact>
          </div>

          <div style={{ fontSize: '12px', color: '#999' }}>
            <div>支持的文件结构:</div>
            <div>1. 标准媒体服务器结构: 从nfo文件读取元数据(TMDB ID等)和海报</div>
            <div>2. 纯弹幕文件结构: 从文件夹结构推断标题和季集信息</div>
          </div>
        </Space>
      </Card>

      <LocalItemList refreshTrigger={refreshTrigger} />

      <DirectoryBrowser
        visible={browserVisible}
        onClose={() => setBrowserVisible(false)}
        onSelect={handleSelectDirectory}
      />
    </div>
  );
};

export default LocalScan;

