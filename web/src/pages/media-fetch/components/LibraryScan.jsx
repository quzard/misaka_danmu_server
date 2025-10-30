import React, { useState, useEffect } from 'react';
import { Card, Select, Button, message, Space, Spin } from 'antd';
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons';
import ServerConfigPanel from './ServerConfigPanel';
import MediaItemList from './MediaItemList';
import { getMediaServers, scanMediaServer } from '../../../apis';

const { Option } = Select;

const LibraryScan = () => {
  const [servers, setServers] = useState([]);
  const [selectedServerId, setSelectedServerId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [editingServer, setEditingServer] = useState(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // 加载服务器列表
  const loadServers = async () => {
    setLoading(true);
    try {
      const res = await getMediaServers();
      const data = res.data;
      setServers(data);

      // 如果有启用的服务器且没有选中,自动选中第一个
      if (!selectedServerId && data.length > 0) {
        const enabledServer = data.find(s => s.isEnabled);
        if (enabledServer) {
          setSelectedServerId(enabledServer.id);
        }
      }
    } catch (error) {
      message.error('加载服务器列表失败');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadServers();
  }, []);

  // 扫描媒体库
  const handleScan = async () => {
    if (!selectedServerId) {
      message.warning('请先选择媒体服务器');
      return;
    }

    setLoading(true);
    try {
      const res = await scanMediaServer(selectedServerId);
      const result = res.data;
      message.success(result.message || '扫描任务已提交');
      // 触发列表刷新
      setRefreshTrigger(prev => prev + 1);
    } catch (error) {
      message.error('扫描失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  // 打开配置面板
  const handleAddServer = () => {
    setEditingServer(null);
    setConfigModalVisible(true);
  };

  const handleEditServer = () => {
    if (!selectedServerId) {
      message.warning('请先选择媒体服务器');
      return;
    }
    const server = servers.find(s => s.id === selectedServerId);
    setEditingServer(server);
    setConfigModalVisible(true);
  };

  const handleConfigSaved = () => {
    setConfigModalVisible(false);
    loadServers();
  };

  return (
    <div>
      <Card 
        title="媒体服务器配置" 
        style={{ marginBottom: '16px' }}
        extra={
          <Space>
            <Button 
              icon={<PlusOutlined />} 
              onClick={handleAddServer}
            >
              添加服务器
            </Button>
            <Button 
              icon={<ReloadOutlined />} 
              onClick={loadServers}
              loading={loading}
            >
              刷新
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <label style={{ marginRight: '8px' }}>选择服务器:</label>
            <Select
              style={{ width: 300 }}
              placeholder="请选择媒体服务器"
              value={selectedServerId}
              onChange={setSelectedServerId}
              loading={loading}
            >
              {servers.map(server => (
                <Option key={server.id} value={server.id} disabled={!server.isEnabled}>
                  {server.name} ({server.providerName}) {!server.isEnabled && '(已禁用)'}
                </Option>
              ))}
            </Select>
          </div>
          
          <Space>
            <Button 
              type="primary" 
              onClick={handleScan}
              disabled={!selectedServerId}
              loading={loading}
            >
              扫描媒体库
            </Button>
            <Button 
              onClick={handleEditServer}
              disabled={!selectedServerId}
            >
              编辑配置
            </Button>
          </Space>
        </Space>
      </Card>

      {selectedServerId && (
        <MediaItemList 
          serverId={selectedServerId} 
          refreshTrigger={refreshTrigger}
        />
      )}

      <ServerConfigPanel
        visible={configModalVisible}
        server={editingServer}
        onClose={() => setConfigModalVisible(false)}
        onSaved={handleConfigSaved}
      />
    </div>
  );
};

export default LibraryScan;

