import { useState } from 'react';
import { Card, Input, Button, message, Space } from 'antd';
import { ScanOutlined } from '@ant-design/icons';
import LocalItemList from './LocalItemList';
import { scanLocalDanmaku } from '../../../apis';

const LocalScan = () => {
  const [scanPath, setScanPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // 扫描本地弹幕
  const handleScan = async () => {
    if (!scanPath.trim()) {
      message.warning('请输入扫描路径');
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
                placeholder="例如: /mnt/media/danmaku 或 D:\Media\Danmaku"
                value={scanPath}
                onChange={(e) => setScanPath(e.target.value)}
                onPressEnter={handleScan}
              />
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
    </div>
  );
};

export default LocalScan;

