import { useState, useEffect } from 'react';
import { Card, Select, Button, message, Space, Spin } from 'antd';
import { ScanOutlined, FolderOpenOutlined, ReloadOutlined } from '@ant-design/icons';
import LocalItemList from './LocalItemList';
import { scanLocalDanmaku, getAvailableDirectories } from '../../../apis';

const LocalScan = () => {
  const [scanPath, setScanPath] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [loadingDirs, setLoadingDirs] = useState(false);
  const [directories, setDirectories] = useState([]);

  // 加载可用目录列表
  const loadDirectories = async () => {
    try {
      setLoadingDirs(true);
      const response = await getAvailableDirectories();
      const dirs = response.data.directories || [];

      // 转换为Select需要的格式,并添加存在性标识
      setDirectories(dirs.map(dir => ({
        label: dir.exists ? dir.label : `${dir.label} (不存在)`,
        value: dir.value,
        disabled: !dir.exists
      })));
    } catch (error) {
      message.error('加载目录列表失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoadingDirs(false);
    }
  };

  // 组件加载时获取目录列表
  useEffect(() => {
    loadDirectories();
  }, []);

  // 扫描本地弹幕
  const handleScan = async () => {
    if (!scanPath) {
      message.warning('请选择扫描路径');
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
              <Select
                style={{ width: '100%' }}
                placeholder="请选择扫描路径"
                value={scanPath || undefined}
                onChange={setScanPath}
                options={directories}
                loading={loadingDirs}
                suffixIcon={loadingDirs ? <Spin size="small" /> : <FolderOpenOutlined />}
                dropdownRender={(menu) => (
                  <>
                    {menu}
                    <div style={{ padding: '8px', borderTop: '1px solid #f0f0f0' }}>
                      <Button
                        type="link"
                        icon={<ReloadOutlined />}
                        onClick={loadDirectories}
                        size="small"
                        block
                      >
                        刷新目录列表
                      </Button>
                    </div>
                  </>
                )}
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

