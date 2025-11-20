import { useState, useEffect } from 'react';
import { Card, Select, Button, message, Space, Checkbox, Row, Col, Tag, Divider, Typography, Alert, Popconfirm, Grid, Segmented } from 'antd';
import { ReloadOutlined, PlusOutlined, ScanOutlined, SettingOutlined, SaveOutlined, DatabaseOutlined, DeleteOutlined, ImportOutlined, EyeOutlined, EyeInvisibleOutlined, VideoCameraOutlined, PlaySquareOutlined, EditOutlined } from '@ant-design/icons';
import ServerConfigPanel from './ServerConfigPanel';
import MediaItemList from './MediaItemList';
import { getMediaServers, scanMediaServer, getMediaServerLibraries, updateMediaServer, batchDeleteMediaItems, importMediaItems, deleteMediaServer } from '../../../apis';

const { Option } = Select;
const { Title, Text } = Typography;

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
  const [selectedMediaItems, setSelectedMediaItems] = useState([]);
  const [showServerUrl, setShowServerUrl] = useState(false);
  const [mediaTypeFilter, setMediaTypeFilter] = useState('all'); // 添加类型过滤状态

  const screens = Grid.useBreakpoint();

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
      // 检查服务器是否启用
      const currentServer = servers.find(s => s.id === selectedServerId);
      if (currentServer && currentServer.isEnabled) {
        loadLibraries();
      } else {
        setLibraries([]);
        setSelectedLibraryIds([]);
      }
    } else {
      setLibraries([]);
      setSelectedLibraryIds([]);
    }
  }, [selectedServerId, servers]);

  // 确保至少选择一个媒体库
  useEffect(() => {
    if (libraries.length > 0 && selectedLibraryIds.length === 0 && !loadingLibraries) {
      // 如果没有选择任何媒体库，默认选中第一个
      setSelectedLibraryIds([libraries[0].id]);
    }
  }, [libraries, selectedLibraryIds, loadingLibraries]);

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
        // 过滤掉不存在的媒体库ID
        const validSelectedLibraries = currentServer.selectedLibraries.filter(id =>
          data.some(lib => lib.id === id)
        );
        setSelectedLibraryIds(validSelectedLibraries.length > 0 ? validSelectedLibraries : [data[0]?.id].filter(Boolean));
      } else {
        // 如果没有配置,默认选中第一个媒体库
        setSelectedLibraryIds(data.length > 0 ? [data[0].id] : []);
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

    // 检查是否有有效的媒体库选择
    const validSelections = selectedLibraryIds.filter(id => libraries.some(lib => lib.id === id));
    if (validSelections.length === 0) {
      message.warning('请至少选择一个有效的媒体库');
      // 自动选择第一个有效的媒体库
      if (libraries.length > 0) {
        setSelectedLibraryIds([libraries[0].id]);
      }
      return;
    }

    setLoading(true);
    try {
      const res = await scanMediaServer(selectedServerId, validSelections);
      const result = res.data;
      message.success(result.message || '扫描任务已提交');
      // 触发列表刷新
      setRefreshTrigger(prev => prev + 1);
    } catch (error) {
      // axios拦截器已统一转换为message字段
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

  // 删除服务器
  const handleDeleteServer = async () => {
    if (!selectedServerId) {
      message.warning('请先选择媒体服务器');
      return;
    }

    try {
      await deleteMediaServer(selectedServerId);
      message.success('服务器已删除');
      setSelectedServerId(null);
      // 重新加载服务器列表
      await loadServers();
    } catch (error) {
      message.error('删除服务器失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
  };

  // 批量删除媒体项目
  const handleBatchDelete = async () => {
    if (selectedMediaItems.length === 0) {
      message.warning('请先选择要删除的项目');
      return;
    }

    // 分类收集要删除的项目
    const itemIds = [];
    const shows = [];
    const seasons = [];

    // 解析选中的项目key
    selectedMediaItems.forEach(key => {
      // 如果key是数字,说明是电影的id
      if (typeof key === 'number') {
        itemIds.push(key);
        return;
      }

      // 如果key是字符串
      if (typeof key === 'string') {
        if (key.startsWith('movie-') || key.startsWith('episode-')) {
          // 直接删除的电影或剧集
          itemIds.push(parseInt(key.split('-')[1]));
        } else if (key.startsWith('show-')) {
          // 整个剧集组
          const title = key.substring(5); // 移除 'show-' 前缀
          shows.push({
            serverId: selectedServerId,
            title: title
          });
        } else if (key.startsWith('season-')) {
          // 某一季
          // key格式: season-{title}-S{season}
          const parts = key.substring(7); // 移除 'season-' 前缀
          const lastDashIndex = parts.lastIndexOf('-S');
          if (lastDashIndex > 0) {
            const title = parts.substring(0, lastDashIndex);
            const season = parseInt(parts.substring(lastDashIndex + 2));
            seasons.push({
              serverId: selectedServerId,
              title: title,
              season: season
            });
          }
        }
      }
    });

    if (itemIds.length === 0 && shows.length === 0 && seasons.length === 0) {
      message.warning('没有可删除的项目');
      return;
    }

    try {
      const payload = {};
      if (itemIds.length > 0) payload.itemIds = itemIds;
      if (shows.length > 0) payload.shows = shows;
      if (seasons.length > 0) payload.seasons = seasons;

      await batchDeleteMediaItems(payload);
      message.success(`成功删除 ${selectedMediaItems.length} 个项目`);
      setSelectedMediaItems([]);
      // 触发列表刷新
      setRefreshTrigger(prev => prev + 1);
    } catch (error) {
      message.error('批量删除失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
  };

  // 批量导入媒体项目
  const handleImport = async () => {
    if (selectedMediaItems.length === 0) {
      message.warning('请先选择要导入的项目');
      return;
    }

    // 分类收集要导入的项目
    const itemIds = [];
    const shows = [];
    const seasons = [];

    // 解析选中的项目key
    selectedMediaItems.forEach(key => {
      // 如果key是数字,说明是电影的id
      if (typeof key === 'number') {
        itemIds.push(key);
        return;
      }

      // 如果key是字符串
      if (typeof key === 'string') {
        if (key.startsWith('movie-') || key.startsWith('episode-')) {
          // 直接导入的电影或剧集
          itemIds.push(parseInt(key.split('-')[1]));
        } else if (key.startsWith('show-')) {
          // 整个剧集组
          const title = key.substring(5); // 移除 'show-' 前缀
          shows.push({
            serverId: selectedServerId,
            title: title
          });
        } else if (key.startsWith('season-')) {
          // 某一季
          // key格式: season-{title}-S{season}
          const parts = key.substring(7); // 移除 'season-' 前缀
          const lastDashIndex = parts.lastIndexOf('-S');
          if (lastDashIndex > 0) {
            const title = parts.substring(0, lastDashIndex);
            const season = parseInt(parts.substring(lastDashIndex + 2));
            seasons.push({
              serverId: selectedServerId,
              title: title,
              season: season
            });
          }
        }
      }
    });

    if (itemIds.length === 0 && shows.length === 0 && seasons.length === 0) {
      message.warning('没有可导入的项目');
      return;
    }

    try {
      const payload = {};
      if (itemIds.length > 0) payload.itemIds = itemIds;
      if (shows.length > 0) payload.shows = shows;
      if (seasons.length > 0) payload.seasons = seasons;

      const res = await importMediaItems(payload);
      const result = res.data;
      message.success(result.message || '导入任务已提交');
      setSelectedMediaItems([]);
      // 触发列表刷新
      setRefreshTrigger(prev => prev + 1);
    } catch (error) {
      message.error('批量导入失败: ' + (error.message || '未知错误'));
      console.error(error);
    }
  };

  const currentServer = servers.find(s => s.id === selectedServerId);
  const isServerDisabled = currentServer && !currentServer.isEnabled;

  return (
    <div
      style={{
        maxWidth: '1200px',
        margin: '0 auto',
        padding: '20px'
      }}
      className="mobile-reduced-padding"
    >
      {/* 页面标题 */}
      <div style={{ textAlign: 'center', marginBottom: '32px' }}>
        <Title level={2} style={{ marginBottom: '8px' }}>
          <DatabaseOutlined style={{ marginRight: '12px' }} />
          媒体库扫描
        </Title>
        <Text type="secondary">连接您的媒体服务器，扫描并导入媒体内容</Text>
      </div>

      {/* 服务器配置卡片 */}
      <Card
        title={
          <Space>
            <SettingOutlined />
            <span>服务器配置</span>
          </Space>
        }
        style={{ marginBottom: '24px' }}
        extra={
          screens.xs ? null : (
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
          )
        }
      >
        {screens.xs && (
          <div style={{ marginBottom: '16px', textAlign: 'center' }}>
            <Space>
              <Button
                icon={<PlusOutlined />}
                onClick={handleAddServer}
                size="large"
              >
                添加
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={loadServers}
                loading={loading}
                size="large"
              >
                刷新
              </Button>
            </Space>
          </div>
        )}
        <Row gutter={24}>
          <Col xs={24} md={12}>
            <div style={{ marginBottom: '16px' }}>
              <Text strong style={{ display: 'block', marginBottom: '8px' }}>
                选择媒体服务器
              </Text>
              <Select
                style={{ width: '100%' }}
                placeholder="请选择媒体服务器"
                value={selectedServerId}
                onChange={setSelectedServerId}
                loading={loading}
                size="large"
              >
                {servers.map(server => (
                  <Option key={server.id} value={server.id}>
                    <Space>
                      <span>{server.name}</span>
                      <Tag size="small" color={server.isEnabled ? 'green' : 'red'}>
                        {server.providerName}
                      </Tag>
                      {!server.isEnabled && <Tag size="small" color="orange">已禁用</Tag>}
                    </Space>
                  </Option>
                ))}
              </Select>
            </div>

            {selectedServerId && currentServer && (
              <div
                style={{
                  border: currentServer.isEnabled ? '2px solid #52c41a' : '2px solid #faad14',
                  borderRadius: '12px',
                  padding: '20px',
                  backgroundColor: currentServer.isEnabled ? '#f6ffed' : '#fffbe6',
                  marginBottom: '16px',
                  position: 'relative',
                  overflow: 'hidden'
                }}
              >
                {/* 装饰性背景 */}
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    right: 0,
                    width: '80px',
                    height: '80px',
                    backgroundColor: currentServer.isEnabled ? '#b7eb8f' : '#ffe58f',
                    borderRadius: '50%',
                    opacity: 0.1,
                    transform: 'translate(30px, -30px)'
                  }}
                />

                <div style={{ position: 'relative', zIndex: 1 }}>
                  {/* 服务器头部信息 */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '2px' }}>
                      <div
                        style={{
                          width: '8px',
                          height: '8px',
                          borderRadius: '50%',
                          backgroundColor: currentServer.isEnabled ? '#52c41a' : '#faad14',
                          flexShrink: 0
                        }}
                      />
                      <div>
                        <div style={{ display: 'flex', alignItems: screens.xs ? 'flex-start' : 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                          <Text strong style={{ fontSize: screens.xs ? '14px' : '16px', color: '#262626', wordBreak: 'break-word', flex: '1 1 auto' }}>
                            {currentServer.name}
                          </Text>
                          <div style={{ display: 'flex', gap: '4px', flexWrap: screens.xs ? 'nowrap' : 'wrap', flexShrink: 0 }}>
                            <Tag color={currentServer.isEnabled ? 'green' : 'orange'} size="small">
                              {currentServer.providerName}
                            </Tag>
                            <Tag color={currentServer.isEnabled ? 'success' : 'warning'} size="small">
                              {currentServer.isEnabled ? '已启用' : '已禁用'}
                            </Tag>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 操作按钮 */}
                    <Space size="small">
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        size="small"
                        onClick={handleEditServer}
                        title="编辑服务器"
                      />
                      <Popconfirm
                        title={`确定要删除服务器 "${currentServer.name}" 吗？`}
                        description="此操作不可撤销，将删除该服务器的所有配置。"
                        onConfirm={handleDeleteServer}
                        okText="确定删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <Button
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          size="small"
                          title="删除服务器"
                        />
                      </Popconfirm>
                    </Space>
                  </div>

                  {/* 服务器地址 */}
                  {currentServer.url && (
                    <div style={{ marginBottom: '16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Text type="secondary" style={{ fontSize: screens.xs ? '11px' : '12px', minWidth: screens.xs ? '50px' : '60px', flexShrink: 0 }}>
                          服务器地址:
                        </Text>
                        <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                          <Text
                            style={{
                              fontSize: screens.xs ? '12px' : '13px',
                              color: '#666',
                              wordBreak: 'break-all',
                              flex: 1,
                              whiteSpace: 'normal',
                              overflow: 'visible',
                              textOverflow: 'clip'
                            }}
                          >
                            {showServerUrl ? currentServer.url : '•'.repeat(currentServer.url.length)}
                          </Text>
                          <Button
                            type="text"
                            size="small"
                            icon={showServerUrl ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                            onClick={() => setShowServerUrl(!showServerUrl)}
                            style={{ padding: '2px 4px', height: '24px', minWidth: '24px', flexShrink: 0 }}
                            title={showServerUrl ? '隐藏地址' : '显示地址'}
                          />
                        </div>
                      </div>
                    </div>
                  )}

                  {/* 服务器未启用提示 */}
                  {!currentServer.isEnabled && (
                    <Alert
                      message="服务器未启用"
                      description="请先启用该媒体服务器以进行扫描操作"
                      type="warning"
                      showIcon
                      action={
                        <Button size="small" onClick={handleEditServer}>
                          立即配置
                        </Button>
                      }
                      style={{ marginTop: '16px' }}
                    />
                  )}
                </div>
              </div>
            )}
          </Col>

          <Col xs={24} md={12}>
            <div style={{ padding: '20px', borderRadius: '8px', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <Title level={4} style={{ marginBottom: '12px' }}>操作说明</Title>
              <Space direction="vertical" size="small">
                <Text>1. 选择已配置的媒体服务器</Text>
                <Text>2. 配置要扫描的媒体库</Text>
                <Text>3. 保存配置并开始扫描</Text>
                <Text>4. 查看扫描结果和导入媒体</Text>
              </Space>
            </div>
          </Col>
        </Row>
      </Card>

      {/* 媒体库配置卡片 */}
      {selectedServerId && (
        <Card
          title={
            <Space>
              <DatabaseOutlined />
              <span>媒体库配置</span>
            </Space>
          }
          style={{ marginBottom: '24px' }}
          extra={
            screens.xs ? null : (
              <Space>
                <Button
                  icon={<SettingOutlined />}
                  onClick={handleEditServer}
                  disabled={!selectedServerId}
                >
                  编辑服务器
                </Button>
                <Button
                  type="primary"
                  icon={<ScanOutlined />}
                  onClick={handleScan}
                  disabled={!selectedServerId || selectedLibraryIds.length === 0 || !selectedLibraryIds.some(id => libraries.some(lib => lib.id === id)) || isServerDisabled}
                  loading={loading}
                  title={
                    !selectedServerId ? '请先选择媒体服务器' :
                    selectedLibraryIds.length === 0 ? `已选择 ${selectedLibraryIds.length} 个媒体库，请至少选择一个` :
                    isServerDisabled ? '服务器未启用，请先启用服务器' :
                    '开始扫描媒体库'
                  }
                >
                  {screens.xs ? '扫描' : '开始扫描'}
                </Button>
              </Space>
            )
          }
        >
          {screens.xs && (
            <div style={{ marginBottom: '16px', textAlign: 'center' }}>
              <Space>
                <Button
                  icon={<SettingOutlined />}
                  onClick={handleEditServer}
                  disabled={!selectedServerId}
                  size="large"
                >
                  编辑
                </Button>
                <Button
                  type="primary"
                  icon={<ScanOutlined />}
                  onClick={handleScan}
                  disabled={!selectedServerId || selectedLibraryIds.length === 0 || !selectedLibraryIds.some(id => libraries.some(lib => lib.id === id)) || isServerDisabled}
                  loading={loading}
                  size="large"
                  title={
                    !selectedServerId ? '请先选择媒体服务器' :
                    selectedLibraryIds.length === 0 ? '请至少选择一个媒体库' :
                    isServerDisabled ? '服务器未启用，请先启用服务器' :
                    '开始扫描媒体库'
                  }
                >
                  扫描
                </Button>
              </Space>
            </div>
          )}
          {isServerDisabled ? (
            <Alert
              message="服务器未启用"
              description="请先启用该媒体服务器或选择其他服务器"
              type="warning"
              showIcon
              action={
                <Button size="small" onClick={handleEditServer}>
                  {screens.xs ? '配置' : '配置服务器'}
                </Button>
              }
            />
          ) : loadingLibraries ? (
            <div style={{ textAlign: 'center', padding: '40px' }}>
              <div style={{ fontSize: '16px', color: '#666', marginBottom: '16px' }}>
                正在加载媒体库列表...
              </div>
            </div>
          ) : libraries.length === 0 ? (
            <Alert
              message="未找到媒体库"
              description="该服务器可能没有配置媒体库，或连接出现问题"
              type="info"
              showIcon
            />
          ) : (
            <>
              <div style={{ marginBottom: '20px' }}>
                <Text strong style={{ fontSize: '16px' }}>
                  已选择 {selectedLibraryIds.length} 个媒体库
                </Text>
                <Divider />
              </div>

              <Checkbox.Group
                style={{ width: '100%' }}
                value={selectedLibraryIds}
                onChange={setSelectedLibraryIds}
              >
                <Row gutter={[16, 16]}>
                  {libraries.map(library => (
                    <Col xs={24} sm={12} md={8} lg={6} key={library.id}>
                      <div
                        style={{
                          border: selectedLibraryIds.includes(library.id) ? '2px solid #1890ff' : '1px solid #d9d9d9',
                          borderRadius: '8px',
                          padding: '16px',
                          backgroundColor: selectedLibraryIds.includes(library.id) ? '#f0f8ff' : '#fff',
                          cursor: 'pointer',
                          transition: 'all 0.3s',
                          height: '100%',
                          display: 'flex',
                          flexDirection: 'column',
                          justifyContent: 'space-between'
                        }}
                        onClick={(e) => {
                          // 避免触发复选框的onChange
                          if (e.target.type !== 'checkbox') {
                            const newSelected = selectedLibraryIds.includes(library.id)
                              ? selectedLibraryIds.filter(id => id !== library.id)
                              : [...selectedLibraryIds, library.id];
                            setSelectedLibraryIds(newSelected);
                          }
                        }}
                      >
                        <div>
                          <div style={{ display: 'flex', alignItems: 'flex-start', marginBottom: '8px' }}>
                            <Checkbox
                              value={library.id}
                              style={{ marginRight: '8px', marginTop: '2px' }}
                            />
                            <div style={{ flex: 1 }}>
                              <Text strong style={{ fontSize: '14px', display: 'block', marginBottom: '4px' }}>
                                {library.name}
                              </Text>
                              <Tag color="blue" size="small">
                                {library.type}
                              </Tag>
                            </div>
                          </div>
                        </div>
                        {library.episodeCount && (
                          <Text type="secondary" style={{ fontSize: '12px', marginTop: '8px' }}>
                            {library.episodeCount} 个项目
                          </Text>
                        )}
                      </div>
                    </Col>
                  ))}
                </Row>
              </Checkbox.Group>

              <Divider />

              <div style={{ textAlign: 'center' }}>
                <Space size="large">
                  <Button
                    type="default"
                    size="large"
                    onClick={() => {
                      const allIds = libraries.map(lib => lib.id);
                      setSelectedLibraryIds(allIds);
                    }}
                  >
                    全选
                  </Button>
                  <Button
                    type="default"
                    size="large"
                    onClick={() => {
                      // 清空所有选择，但保持至少一个选中
                      if (libraries.length > 0) {
                        setSelectedLibraryIds([libraries[0].id]);
                      } else {
                        setSelectedLibraryIds([]);
                      }
                    }}
                  >
                    清空
                  </Button>
                  <Button
                    type="primary"
                    size="large"
                    icon={<SaveOutlined />}
                    loading={savingLibraries}
                    onClick={handleSaveLibraries}
                  >
                    {screens.xs ? '保存' : '保存配置'}
                  </Button>
                </Space>
              </div>
            </>
          )}
        </Card>
      )}

      {/* 扫描结果 */}
      {selectedServerId && (
        <Card
          title={
            <Space>
              <ScanOutlined />
              <span>扫描结果</span>
              {selectedMediaItems.length > 0 && (
                <Tag color="blue">{selectedMediaItems.length} 已选中</Tag>
              )}
            </Space>
          }
          style={{ marginBottom: '24px' }}
          extra={
            screens.xs ? null : (
              <Space>
                <Segmented
                  value={mediaTypeFilter}
                  onChange={setMediaTypeFilter}
                  options={[
                    { label: '全部', value: 'all' },
                    { label: '电影', value: 'movie', icon: <VideoCameraOutlined /> },
                    { label: '电视节目', value: 'tv_series', icon: <PlaySquareOutlined /> },
                  ]}
                />
                <Popconfirm
                  title={`确定要删除选中的 ${selectedMediaItems.length} 个项目吗?`}
                  onConfirm={handleBatchDelete}
                  okText="确定"
                  cancelText="取消"
                  disabled={selectedMediaItems.length === 0}
                >
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    disabled={selectedMediaItems.length === 0}
                  >
                    删除选中
                  </Button>
                </Popconfirm>
                <Button
                  type="primary"
                  icon={<ImportOutlined />}
                  onClick={handleImport}
                  disabled={selectedMediaItems.length === 0}
                >
                  导入选中
                </Button>
              </Space>
            )
          }
        >
          {screens.xs && (
            <div style={{ marginBottom: '16px', textAlign: 'center' }}>
              <Space>
                <Popconfirm
                  title={`确定要删除选中的 ${selectedMediaItems.length} 个项目吗?`}
                  onConfirm={handleBatchDelete}
                  okText="确定"
                  cancelText="取消"
                  disabled={selectedMediaItems.length === 0}
                >
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    disabled={selectedMediaItems.length === 0}
                    size="large"
                  >
                    删除
                  </Button>
                </Popconfirm>
                <Button
                  type="primary"
                  icon={<ImportOutlined />}
                  onClick={handleImport}
                  disabled={selectedMediaItems.length === 0}
                  size="large"
                >
                  导入
                </Button>
              </Space>
            </div>
          )}
          <MediaItemList
            serverId={selectedServerId}
            refreshTrigger={refreshTrigger}
            selectedItems={selectedMediaItems}
            onSelectionChange={setSelectedMediaItems}
            mediaTypeFilter={mediaTypeFilter}
          />
        </Card>
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