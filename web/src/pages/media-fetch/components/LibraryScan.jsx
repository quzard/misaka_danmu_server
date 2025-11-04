import React, { useState, useEffect } from 'react';
import { Card, Select, Button, message, Space, Checkbox } from 'antd';
import { ReloadOutlined, PlusOutlined } from '@ant-design/icons';
import ServerConfigPanel from './ServerConfigPanel';
import MediaItemList from './MediaItemList';
import { getMediaServers, scanMediaServer, getMediaServerLibraries, updateMediaServer } from '../../../apis';

const { Option } = Select;

const LibraryScan = () => {
  const [servers, setServers] = useState([]);
  const [selectedServerId, setSelectedServerId] = useState(null);
  const [libraries, setLibraries] = useState([]);
  const [selectedLibraryIds, setSelectedLibraryIds] = useState([]);
  const [loadingLibraries, setLoadingLibraries] = useState(false);
  const [loading, setLoading] = useState(false);
  const [savingLibraries, setSavingLibraries] = useState(false);
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

  // 当选中的服务器变化时,加载媒体库列表
  useEffect(() => {
    if (selectedServerId) {
      loadLibraries();
    } else {
      setLibraries([]);
      setSelectedLibraryIds([]);
    }
  }, [selectedServerId]);

  // 加载媒体库列表
  const loadLibraries = async () => {
    if (!selectedServerId) return;

    setLoadingLibraries(true);
    try {
      const res = await getMediaServerLibraries(selectedServerId);
      const data = res.data;
      setLibraries(data);

      // 从服务器配置中读取已选择的媒体库
      const currentServer = servers.find(s => s.id === selectedServerId);
      if (currentServer && currentServer.selectedLibraries && currentServer.selectedLibraries.length > 0) {
        setSelectedLibraryIds(currentServer.selectedLibraries);
      } else {
        // 如果没有配置,默认选中所有媒体库
        setSelectedLibraryIds(data.map(lib => lib.id));
      }
    } catch (error) {
      message.error('加载媒体库列表失败');
      console.error(error);
      setLibraries([]);
      setSelectedLibraryIds([]);
    } finally {
      setLoadingLibraries(false);
    }
  };

  // 保存媒体库选择
  const handleSaveLibraries = async () => {
    if (!selectedServerId) {
      message.warning('请先选择媒体服务器');
      return;
    }

    setSavingLibraries(true);
    try {
      await updateMediaServer(selectedServerId, {
        selectedLibraries: selectedLibraryIds
      });
      message.success('媒体库选择已保存');
      // 重新加载服务器列表以更新配置
      await loadServers();
    } catch (error) {
      message.error('保存失败: ' + (error.message || '未知错误'));
      console.error(error);
    } finally {
      setSavingLibraries(false);
    }
  };

  // 扫描媒体库
  const handleScan = async () => {
    if (!selectedServerId) {
      message.warning('请先选择媒体服务器');
      return;
    }

    if (selectedLibraryIds.length === 0) {
      message.warning('请至少选择一个媒体库');
      return;
    }

    setLoading(true);
    try {
      const res = await scanMediaServer(selectedServerId, selectedLibraryIds);
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
                <Option key={server.id} value={server.id}>
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

          {selectedServerId && (
            <div>
              <label style={{ marginBottom: '8px', display: 'block' }}>选择媒体库:</label>
              <div style={{
                border: '1px solid #d9d9d9',
                borderRadius: '6px',
                padding: '12px',
                minHeight: '120px',
                backgroundColor: loadingLibraries ? '#f5f5f5' : '#fafafa'
              }}>
                {loadingLibraries ? (
                  <div style={{ textAlign: 'center', color: '#999', padding: '20px' }}>
                    加载中...
                  </div>
                ) : libraries.length === 0 ? (
                  <div style={{ textAlign: 'center', color: '#999', padding: '20px' }}>
                    暂无可用媒体库
                  </div>
                ) : (
                  <>
                    <Checkbox.Group
                      style={{ width: '100%' }}
                      value={selectedLibraryIds}
                      onChange={setSelectedLibraryIds}
                    >
                      <div style={{
                        display: 'flex',
                        flexDirection: 'row',
                        flexWrap: 'wrap',
                        gap: '8px'
                      }}>
                        {libraries.map(library => (
                          <Checkbox
                            key={library.id}
                            value={library.id}
                            style={{
                              padding: '6px 12px',
                              border: '1px solid #e8e8e8',
                              borderRadius: '4px',
                              backgroundColor: '#fff',
                              margin: 0,
                              whiteSpace: 'nowrap'
                            }}
                          >
                            <span style={{ fontWeight: 'normal' }}>
                              {library.name}
                              <span style={{
                                marginLeft: '8px',
                                fontSize: '12px',
                                color: '#666'
                              }}>
                                ({library.type})
                              </span>
                            </span>
                          </Checkbox>
                        ))}
                      </div>
                    </Checkbox.Group>
                    <div style={{ marginTop: '12px', textAlign: 'right' }}>
                      <Button
                        type="primary"
                        loading={savingLibraries}
                        onClick={handleSaveLibraries}
                      >
                        保存
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </div>
          )}
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

