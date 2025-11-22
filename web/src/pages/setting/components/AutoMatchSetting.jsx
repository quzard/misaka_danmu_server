import React, { useState, useEffect } from 'react'
import { Form, Input, Select, Switch, Button, message, Spin, Card, Tabs, Space, Tooltip, Row, Col, Alert, Statistic } from 'antd'
const { TextArea } = Input
const { TabPane } = Tabs
const { Option } = Select
import { getConfig, setConfig, getDefaultAIPrompts, getAIBalance } from '@/apis'
import api from '@/apis/fetch'
import { QuestionCircleOutlined, SaveOutlined, ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import AIMetrics from './AIMetrics'

const CustomSwitch = (props) => {
  return <Switch {...props} />
}

const AutoMatchSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [matchMode, setMatchMode] = useState('traditional')
  const [fallbackEnabled, setFallbackEnabled] = useState(false)
  const [recognitionEnabled, setRecognitionEnabled] = useState(false)
  const [aliasExpansionEnabled, setAliasExpansionEnabled] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [selectedMetadataSource, setSelectedMetadataSource] = useState('tmdb')
  const [balanceInfo, setBalanceInfo] = useState(null)
  const [balanceLoading, setBalanceLoading] = useState(false)
  const [aiProviders, setAiProviders] = useState([])
  const [providersLoading, setProvidersLoading] = useState(false)

  // 加载配置
  const loadSettings = async () => {
    try {
      setLoading(true)
      const [
        enabledRes,
        fallbackRes,
        providerRes,
        apiKeyRes,
        baseUrlRes,
        modelRes,
        promptRes,
        recognitionEnabledRes,
        recognitionPromptRes,
        aliasValidationPromptRes,
        aliasCorrectionEnabledRes,
        aliasExpansionEnabledRes,
        aliasExpansionPromptRes,
        logRawResponseRes,
        webhookSeasonMappingRes,
        matchFallbackSeasonMappingRes,
        autoImportSeasonMappingRes,
        seasonMappingSourceRes,
        seasonMappingPromptRes
      ] = await Promise.all([
        getConfig('aiMatchEnabled'),
        getConfig('aiFallbackEnabled'),
        getConfig('aiProvider'),
        getConfig('aiApiKey'),
        getConfig('aiBaseUrl'),
        getConfig('aiModel'),
        getConfig('aiPrompt'),
        getConfig('aiRecognitionEnabled'),
        getConfig('aiRecognitionPrompt'),
        getConfig('aiAliasValidationPrompt'),
        getConfig('aiAliasCorrectionEnabled'),
        getConfig('aiAliasExpansionEnabled'),
        getConfig('aiAliasExpansionPrompt'),
        getConfig('aiLogRawResponse'),
        getConfig('webhookEnableTmdbSeasonMapping'),
        getConfig('matchFallbackEnableTmdbSeasonMapping'),
        getConfig('autoImportEnableTmdbSeasonMapping'),
        getConfig('seasonMappingMetadataSource'),
        getConfig('seasonMappingPrompt')
      ])

      const enabled = enabledRes.data.value === 'true'
      const fallback = fallbackRes.data.value === 'true'
      const recognition = recognitionEnabledRes.data.value === 'true'
      const aliasCorrection = aliasCorrectionEnabledRes.data.value === 'true'
      const aliasExpansion = aliasExpansionEnabledRes.data.value === 'true'
      const logRawResponse = logRawResponseRes.data.value === 'true'
      setMatchMode(enabled ? 'ai' : 'traditional')
      setFallbackEnabled(fallback)
      setRecognitionEnabled(recognition)
      setAliasExpansionEnabled(aliasExpansion)
      setSelectedMetadataSource(seasonMappingSourceRes.data.value || 'tmdb')

      form.setFieldsValue({
        aiMatchEnabled: enabled,
        aiFallbackEnabled: fallback,
        aiProvider: providerRes.data.value || 'deepseek',
        aiApiKey: apiKeyRes.data.value || '',
        aiBaseUrl: baseUrlRes.data.value || '',
        aiModel: modelRes.data.value || 'deepseek-chat',
        aiPrompt: promptRes.data.value || '',
        aiRecognitionEnabled: recognition,
        aiRecognitionPrompt: recognitionPromptRes.data.value || '',
        aiAliasValidationPrompt: aliasValidationPromptRes.data.value || '',
        aiAliasCorrectionEnabled: aliasCorrection,
        aiAliasExpansionEnabled: aliasExpansion,
        aiAliasExpansionPrompt: aliasExpansionPromptRes.data.value || '',
        aiLogRawResponse: logRawResponse,
        webhookEnableTmdbSeasonMapping: webhookSeasonMappingRes.data.value === 'true',
        matchFallbackEnableTmdbSeasonMapping: matchFallbackSeasonMappingRes.data.value === 'true',
        autoImportEnableTmdbSeasonMapping: autoImportSeasonMappingRes.data.value === 'true',
        seasonMappingMetadataSource: seasonMappingSourceRes.data.value || 'tmdb',
        seasonMappingPrompt: seasonMappingPromptRes.data.value || ''
      })
    } catch (error) {
      console.error('加载配置失败:', error)
      message.error(`加载配置失败: ${error?.response?.data?.message || error?.message || error?.detail || String(error) || '未知错误'}`)
    } finally {
      setLoading(false)
    }
  }

  // 加载AI提供商列表
  const loadAIProviders = async () => {
    try {
      setProvidersLoading(true)
      const res = await api.get('/api/ui/config/ai/providers')
      setAiProviders(res.data || [])
    } catch (error) {
      console.error('加载AI提供商列表失败:', error)
      // 使用默认配置
      setAiProviders([
        {
          id: 'deepseek',
          displayName: 'DeepSeek (推荐)',
          defaultModel: 'deepseek-chat',
          modelPlaceholder: 'deepseek-chat',
          baseUrlPlaceholder: 'https://api.deepseek.com (默认)'
        },
        {
          id: 'siliconflow',
          displayName: 'SiliconFlow 硅基流动',
          defaultModel: 'Qwen/Qwen2.5-7B-Instruct',
          modelPlaceholder: 'Qwen/Qwen2.5-7B-Instruct, deepseek-ai/DeepSeek-V2.5',
          baseUrlPlaceholder: 'https://api.siliconflow.cn/v1 (默认)'
        },
        {
          id: 'openai',
          displayName: 'OpenAI (兼容接口)',
          defaultModel: 'gpt-4-turbo',
          modelPlaceholder: 'gpt-4, gpt-4-turbo, gpt-3.5-turbo',
          baseUrlPlaceholder: 'https://api.openai.com/v1 (默认) 或自定义兼容接口'
        }
      ])
    } finally {
      setProvidersLoading(false)
    }
  }

  useEffect(() => {
    loadAIProviders()
    loadSettings()
    fetchBalance()
  }, [])

  // 获取余额
  const fetchBalance = async () => {
    try {
      setBalanceLoading(true)
      const res = await getAIBalance()
      setBalanceInfo(res.data)
    } catch (error) {
      console.error('获取余额失败:', error)
      // 不显示错误消息,因为可能是提供商不支持
    } finally {
      setBalanceLoading(false)
    }
  }

  // 保存配置
  const handleSave = async () => {
    try {
      setSaving(true)
      const values = matchMode === 'ai'
        ? await form.validateFields()
        : form.getFieldsValue()

      await Promise.all([
        setConfig('aiMatchEnabled', values.aiMatchEnabled ? 'true' : 'false'),
        setConfig('aiFallbackEnabled', values.aiFallbackEnabled ? 'true' : 'false'),
        setConfig('aiProvider', values.aiProvider || ''),
        setConfig('aiApiKey', values.aiApiKey || ''),
        setConfig('aiBaseUrl', values.aiBaseUrl || ''),
        setConfig('aiModel', values.aiModel || ''),
        setConfig('aiPrompt', values.aiPrompt || ''),
        setConfig('aiRecognitionEnabled', values.aiRecognitionEnabled ? 'true' : 'false'),
        setConfig('aiRecognitionPrompt', values.aiRecognitionPrompt || ''),
        setConfig('aiAliasValidationPrompt', values.aiAliasValidationPrompt || ''),
        setConfig('aiAliasCorrectionEnabled', values.aiAliasCorrectionEnabled ? 'true' : 'false'),
        setConfig('aiAliasExpansionEnabled', values.aiAliasExpansionEnabled ? 'true' : 'false'),
        setConfig('aiAliasExpansionPrompt', values.aiAliasExpansionPrompt || ''),
        setConfig('aiLogRawResponse', values.aiLogRawResponse ? 'true' : 'false'),
        setConfig('webhookEnableTmdbSeasonMapping', values.webhookEnableTmdbSeasonMapping ? 'true' : 'false'),
        setConfig('matchFallbackEnableTmdbSeasonMapping', values.matchFallbackEnableTmdbSeasonMapping ? 'true' : 'false'),
        setConfig('autoImportEnableTmdbSeasonMapping', values.autoImportEnableTmdbSeasonMapping ? 'true' : 'false'),
        setConfig('seasonMappingMetadataSource', values.seasonMappingMetadataSource || 'tmdb'),
        setConfig('seasonMappingPrompt', values.seasonMappingPrompt || '')
      ])

      message.success('保存成功')
    } catch (error) {
      console.error('保存配置失败:', error)
      message.error(`保存失败: ${error?.response?.data?.message || error?.message || '未知错误'}`)
    } finally {
      setSaving(false)
    }
  }

  // 获取模型名称占位符
  const getModelPlaceholder = (provider) => {
    const providerConfig = aiProviders.find(p => p.id === provider)
    return providerConfig?.modelPlaceholder || '请输入模型名称'
  }

  // 获取Base URL占位符
  const getBaseUrlPlaceholder = (provider) => {
    const providerConfig = aiProviders.find(p => p.id === provider)
    return providerConfig?.baseUrlPlaceholder || '可选,用于自定义接口地址'
  }

  // 测试AI连接
  const handleTestConnection = async () => {
    try {
      setTesting(true)
      setTestResult(null)

      const values = form.getFieldsValue(['aiProvider', 'aiApiKey', 'aiBaseUrl', 'aiModel'])

      if (!values.aiProvider || !values.aiApiKey || !values.aiModel) {
        message.warning('请先填写AI提供商、API密钥和模型名称')
        return
      }

      const response = await api.post('/api/ui/config/ai/test', {
        provider: values.aiProvider,
        apiKey: values.aiApiKey,
        baseUrl: values.aiBaseUrl || null,
        model: values.aiModel
      })

      setTestResult(response.data)

      if (response.data.success) {
        message.success(`测试成功! 响应时间: ${response.data.latency}ms`)
      } else {
        message.error('测试失败,请查看详细信息')
      }
    } catch (error) {
      setTestResult({
        success: false,
        message: '测试请求失败',
        error: error?.response?.data?.message || error?.message || error?.detail || String(error) || '未知错误'
      })
      message.error(`测试失败: ${error?.response?.data?.message || error?.message || error?.detail || String(error) || '未知错误'}`)
    } finally {
      setTesting(false)
    }
  }

  // 填充默认提示词
  const handleFillDefaultPrompt = async (promptKey) => {
    try {
      const response = await getDefaultAIPrompts()
      const defaultValue = response.data[promptKey]

      if (defaultValue) {
        form.setFieldValue(promptKey, defaultValue)
        message.success('已填充默认提示词')
      } else {
        message.error('未找到默认提示词')
      }
    } catch (error) {
      console.error('获取默认提示词失败:', error)
      message.error(`获取默认提示词失败: ${error?.response?.data?.message || error?.message || '未知错误'}`)
    }
  }

  return (
    <Spin spinning={loading}>
      <Card
        title="AI辅助增强"
        extra={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSave}
              loading={saving}
              style={{
                minWidth: '100px',
                whiteSpace: 'nowrap'
              }}
            >
              保存设置
            </Button>
          </div>
        }
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={(changedValues) => {
            if ('aiMatchEnabled' in changedValues) {
              setMatchMode(changedValues.aiMatchEnabled ? 'ai' : 'traditional')
            }
            if ('aiFallbackEnabled' in changedValues) {
              setFallbackEnabled(changedValues.aiFallbackEnabled)
            }
            if ('aiRecognitionEnabled' in changedValues) {
              setRecognitionEnabled(changedValues.aiRecognitionEnabled)
            }
            if ('aiAliasExpansionEnabled' in changedValues) {
              setAliasExpansionEnabled(changedValues.aiAliasExpansionEnabled)
            }
          }}
        >
          <Tabs defaultActiveKey="connection">
            {/* 标签页1: AI连接配置 */}
            <TabPane tab="AI连接配置" key="connection">
              <Form.Item
                name="aiProvider"
                label={
                  <Space>
                    <span>AI提供商</span>
                    <Tooltip title="选择AI服务提供商。不同提供商支持不同的模型和功能。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                rules={[{ required: matchMode === 'ai', message: '请选择AI提供商' }]}
              >
                <Select loading={providersLoading}>
                  {aiProviders.map(provider => (
                    <Option key={provider.id} value={provider.id}>
                      {provider.displayName}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                name="aiApiKey"
                label={
                  <Space>
                    <span>API密钥</span>
                    <Tooltip title="从AI服务提供商获取的API密钥。必填项。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                rules={[{ required: matchMode === 'ai', message: '请输入API密钥' }]}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues.aiProvider !== currentValues.aiProvider
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item
                    name="aiBaseUrl"
                    label={
                      <Space>
                        <span>Base URL</span>
                        <Tooltip title="自定义API接口地址。通常用于第三方兼容接口或代理服务。留空使用默认地址。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                    }
                  >
                    <Input
                      placeholder={getBaseUrlPlaceholder(getFieldValue('aiProvider'))}
                    />
                  </Form.Item>
                )}
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues.aiProvider !== currentValues.aiProvider
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item
                    name="aiModel"
                    label={
                      <Space>
                        <span>模型名称</span>
                        <Tooltip title="AI模型的名称。不同模型有不同的性能和价格。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                    }
                    rules={[{ required: matchMode === 'ai', message: '请输入模型名称' }]}
                  >
                    <Input
                      placeholder={getModelPlaceholder(getFieldValue('aiProvider'))}
                    />
                  </Form.Item>
                )}
              </Form.Item>

              {/* AI连接测试与调试 */}
              <Form.Item label="连接测试与调试">
                <Space direction="vertical" style={{ width: '100%' }}>
                  <div style={{ width: '100%', display: 'flex', justifyContent: 'center' }}>
                    <Button
                      icon={<ThunderboltOutlined />}
                      onClick={handleTestConnection}
                      loading={testing}
                      style={{
                        width: '100%',
                        maxWidth: '200px'
                      }}
                    >
                      测试AI连接
                    </Button>
                  </div>

                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>记录AI原始响应</span>
                        <Tooltip title="启用后，AI的所有原始响应将被记录到 config/logs/ai_responses.log 文件中，用于调试。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiLogRawResponse" valuePropName="checked" noStyle>
                        <CustomSwitch />
                      </Form.Item>
                    </div>
                  </Card>

                  <div style={{ fontSize: '12px', color: '#666', marginBottom: '16px' }}>
                    启用后，AI的所有原始响应将被记录到 config/logs/ai_responses.log 文件中，用于调试。
                  </div>

                  {/* 余额卡片 - 仅当支持时显示 */}
                  {balanceInfo?.supported && (
                    <Card size="small" style={{ marginBottom: '16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontWeight: 500 }}>💰 账户余额</span>
                          <Tooltip title={`查询 ${balanceInfo.provider} 账户余额`}>
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                        <Button
                          size="small"
                          onClick={fetchBalance}
                          loading={balanceLoading}
                          icon={<ReloadOutlined />}
                        >
                          刷新
                        </Button>
                      </div>

                      {balanceInfo.error ? (
                        <Alert
                          type="error"
                          message={balanceInfo.error}
                          showIcon
                        />
                      ) : balanceInfo.data ? (
                        <Row gutter={16}>
                          <Col span={8}>
                            <Statistic
                              title="总余额"
                              value={balanceInfo.data.total_balance}
                              prefix={balanceInfo.data.currency === 'CNY' ? '¥' : '$'}
                              precision={2}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title="赠金余额"
                              value={balanceInfo.data.granted_balance}
                              prefix={balanceInfo.data.currency === 'CNY' ? '¥' : '$'}
                              precision={2}
                            />
                          </Col>
                          <Col span={8}>
                            <Statistic
                              title="充值余额"
                              value={balanceInfo.data.topped_up_balance}
                              prefix={balanceInfo.data.currency === 'CNY' ? '¥' : '$'}
                              precision={2}
                            />
                          </Col>
                        </Row>
                      ) : (
                        <div style={{ color: '#999', textAlign: 'center' }}>
                          点击刷新按钮查询余额
                        </div>
                      )}
                    </Card>
                  )}

                  {testResult && (
                    <Alert
                      type={testResult.success ? 'success' : 'error'}
                      message={
                        <Space>
                          {testResult.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                          <span>{testResult.message}</span>
                          {testResult.latency && <span>({testResult.latency}ms)</span>}
                        </Space>
                      }
                      description={testResult.error}
                      showIcon={false}
                      closable
                      onClose={() => setTestResult(null)}
                    />
                  )}
                </Space>
              </Form.Item>
            </TabPane>

            {/* 标签页2: AI自动匹配 */}
            <TabPane tab="AI自动匹配" key="match">
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>匹配模式</span>
                        <Tooltip title="AI智能匹配: 使用大语言模型理解上下文,综合考虑标题、类型、季度、年份、集数和精确标记等因素,选择最佳匹配结果。传统匹配: 基于标题相似度和类型匹配的算法,快速但可能不够精准。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiMatchEnabled" valuePropName="checked" noStyle>
                        <CustomSwitch
                          checkedChildren="AI智能匹配"
                          unCheckedChildren="传统匹配"
                          checked={matchMode === 'ai'}
                          onChange={checked => {
                            setMatchMode(checked ? 'ai' : 'traditional')
                            form.setFieldValue('aiMatchEnabled', checked)
                          }}
                        />
                      </Form.Item>
                    </div>
                  </Card>
                </Col>
                <Col xs={24} sm={12}>
                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>传统匹配兜底</span>
                        <Tooltip title={matchMode === 'traditional' ? '传统匹配模式下无需兜底' : '当AI匹配失败时,自动降级到传统匹配算法,确保功能可用性'}>
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiFallbackEnabled" valuePropName="checked" noStyle>
                        <CustomSwitch disabled={matchMode === 'traditional'} />
                      </Form.Item>
                    </div>
                  </Card>
                </Col>
              </Row>

              {/* 季度映射配置 */}
              <Card size="small" style={{ marginBottom: '16px' }}>
                <Row gutter={[16, 16]}>
                  <Col xs={24} sm={12}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div style={{ fontWeight: 500, marginBottom: '4px' }}>季度映射开关</div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>Webhook季度映射</span>
                          <Tooltip title="启用后，Webhook导入时会通过元数据源获取季度名称">
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                        <Form.Item name="webhookEnableTmdbSeasonMapping" valuePropName="checked" noStyle>
                          <CustomSwitch size="small" />
                        </Form.Item>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>后备匹配季度映射</span>
                          <Tooltip title="启用后，匹配后备时会通过元数据源获取季度名称">
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                        <Form.Item name="matchFallbackEnableTmdbSeasonMapping" valuePropName="checked" noStyle>
                          <CustomSwitch size="small" />
                        </Form.Item>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>全自动导入季度映射</span>
                          <Tooltip title="启用后，全自动导入时会通过元数据源获取季度名称">
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                        <Form.Item name="autoImportEnableTmdbSeasonMapping" valuePropName="checked" noStyle>
                          <CustomSwitch size="small" />
                        </Form.Item>
                      </div>
                    </div>
                  </Col>
                  <Col xs={24} sm={12}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                        <span style={{ fontWeight: 500 }}>元数据源选择</span>
                        <Tooltip title="选择用于季度映射的元数据源。只能选择一个源。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="seasonMappingMetadataSource" noStyle>
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                          {[
                            { value: 'tmdb', label: 'TMDB' },
                            { value: 'tvdb', label: 'TVDB' },
                            { value: 'imdb', label: 'IMDB' },
                            { value: 'douban', label: '豆瓣' },
                            { value: 'bangumi', label: 'Bangumi' }
                          ].map(source => (
                            <div
                              key={source.value}
                              onClick={() => {
                                setSelectedMetadataSource(source.value)
                                form.setFieldValue('seasonMappingMetadataSource', source.value)
                              }}
                              style={{
                                border: '1px solid #d9d9d9',
                                borderRadius: '4px',
                                padding: '12px',
                                textAlign: 'center',
                                cursor: 'pointer',
                                backgroundColor: selectedMetadataSource === source.value ? '#1890ff' : 'transparent',
                                color: selectedMetadataSource === source.value ? '#fff' : 'inherit',
                                transition: 'all 0.3s'
                              }}
                            >
                              {source.label}
                            </div>
                          ))}
                        </div>
                      </Form.Item>
                    </div>
                  </Col>
                </Row>
              </Card>

              <Card size="small" style={{ marginTop: '16px' }}>
                <Form.Item
                  name="aiPrompt"
                  label={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <Space>
                        <span>AI匹配提示词</span>
                        <Tooltip title="用于指导AI如何选择最佳匹配结果的提示词。留空使用默认提示词。高级用户可自定义以优化匹配效果。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={() => handleFillDefaultPrompt('aiPrompt')}
                        disabled={matchMode !== 'ai'}
                      >
                        填充默认提示词
                      </Button>
                    </div>
                  }
                >
                  <TextArea
                    rows={6}
                    placeholder="留空使用默认提示词..."
                    style={{ fontFamily: 'monospace', fontSize: '12px' }}
                    disabled={matchMode !== 'ai'}
                  />
                </Form.Item>
              </Card>

              <Card size="small" style={{ marginTop: '16px' }}>
                <Form.Item
                  name="seasonMappingPrompt"
                  label={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <Space>
                        <span>AI季度映射提示词</span>
                        <Tooltip title="用于指导AI从元数据源搜索结果中选择最佳匹配的提示词。留空使用默认提示词。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={() => handleFillDefaultPrompt('seasonMappingPrompt')}
                        disabled={matchMode !== 'ai'}
                      >
                        填充默认提示词
                      </Button>
                    </div>
                  }
                >
                  <TextArea
                    rows={6}
                    placeholder="留空使用默认提示词..."
                    style={{ fontFamily: 'monospace', fontSize: '12px' }}
                    disabled={matchMode !== 'ai'}
                  />
                </Form.Item>
              </Card>
            </TabPane>

            {/* 标签页3: AI识别增强 */}
            <TabPane tab="AI识别增强" key="recognition">
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={8}>
                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>AI辅助识别</span>
                        <Tooltip title="使用AI从标题中提取结构化信息(作品名称、季度、类型等),提高TMDB搜索准确率。应用于TMDB自动刮削定时任务。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiRecognitionEnabled" valuePropName="checked" noStyle>
                        <CustomSwitch disabled={matchMode !== 'ai'} />
                      </Form.Item>
                    </div>
                  </Card>
                </Col>
                <Col xs={24} sm={8}>
                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>AI别名修正</span>
                        <Tooltip title="使用AI修正已有的错误别名(例如中文别名字段写入了非中文内容)。启用后,TMDB自动刮削任务会强制更新所有别名字段。注意:已锁定的别名不会被修正。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiAliasCorrectionEnabled" valuePropName="checked" noStyle>
                        <CustomSwitch disabled={matchMode !== 'ai' || !recognitionEnabled} />
                      </Form.Item>
                    </div>
                  </Card>
                </Col>
                <Col xs={24} sm={8}>
                  <Card size="small" style={{ marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>AI别名扩展</span>
                        <Tooltip title="当元数据源返回非中文标题时，使用AI生成可能的别名（中文、罗马音、英文缩写等），然后在Bangumi/Douban中搜索以获取中文标题。应用于外部控制API全自动导入、Webhook自动导入等场景。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </div>
                      <Form.Item name="aiAliasExpansionEnabled" valuePropName="checked" noStyle>
                        <CustomSwitch disabled={matchMode !== 'ai'} />
                      </Form.Item>
                    </div>
                  </Card>
                </Col>
              </Row>

              <Card size="small" style={{ marginTop: '16px' }}>
                <Form.Item
                  name="aiRecognitionPrompt"
                  label={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <Space>
                        <span>AI识别提示词</span>
                        <Tooltip title="用于指导AI如何从标题中提取结构化信息的提示词。留空使用默认提示词。高级用户可自定义以优化识别效果。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={() => handleFillDefaultPrompt('aiRecognitionPrompt')}
                        disabled={matchMode !== 'ai' || !recognitionEnabled}
                      >
                        填充默认提示词
                      </Button>
                    </div>
                  }
                >
                  <TextArea
                    rows={6}
                    placeholder="留空使用默认提示词..."
                    style={{ fontFamily: 'monospace', fontSize: '12px' }}
                    disabled={matchMode !== 'ai' || !recognitionEnabled}
                  />
                </Form.Item>
              </Card>

              <Card size="small" style={{ marginTop: '16px' }}>
                <Form.Item
                  name="aiAliasValidationPrompt"
                  label={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <Space>
                        <span>AI别名验证提示词</span>
                        <Tooltip title="用于指导AI如何验证和分类别名的提示词。AI会识别别名的语言类型(英文/日文/罗马音/中文)并验证是否真正属于该作品。留空使用默认提示词。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={() => handleFillDefaultPrompt('aiAliasValidationPrompt')}
                        disabled={matchMode !== 'ai' || !recognitionEnabled}
                      >
                        填充默认提示词
                      </Button>
                    </div>
                  }
                >
                  <TextArea
                    rows={6}
                    placeholder="留空使用默认提示词..."
                    style={{ fontFamily: 'monospace', fontSize: '12px' }}
                    disabled={matchMode !== 'ai' || !recognitionEnabled}
                  />
                </Form.Item>
              </Card>

              <Card size="small" style={{ marginTop: '16px' }}>
                <Form.Item
                  name="aiAliasExpansionPrompt"
                  label={
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <Space>
                        <span>AI别名扩展提示词</span>
                        <Tooltip title="用于指导AI如何生成可能的别名的提示词。AI会生成中文译名、罗马音、英文缩写等别名，用于在中文元数据源中搜索。留空使用默认提示词。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                      <Button
                        size="small"
                        icon={<ReloadOutlined />}
                        onClick={() => handleFillDefaultPrompt('aiAliasExpansionPrompt')}
                        disabled={matchMode !== 'ai' || !aliasExpansionEnabled}
                      >
                        填充默认提示词
                      </Button>
                    </div>
                  }
                >
                  <TextArea
                    rows={6}
                    placeholder="留空使用默认提示词..."
                    style={{ fontFamily: 'monospace', fontSize: '12px' }}
                    disabled={matchMode !== 'ai' || !aliasExpansionEnabled}
                  />
                </Form.Item>
              </Card>
            </TabPane>

            {/* 标签页4: AI使用统计 */}
            <TabPane tab="AI使用统计" key="metrics">
              <AIMetrics />
            </TabPane>
          </Tabs>
        </Form>

        {/* 说明文字 */}
        <div style={{ marginTop: 24, padding: 16, background: '#f5f5f5', borderRadius: 4 }}>
          <h4 style={{ marginTop: 0 }}>功能说明</h4>
          <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
            <li>
              <strong>传统匹配</strong>: 基于标题相似度和类型匹配的算法,快速但可能不够精准
            </li>
            <li>
              <strong>AI智能匹配</strong>: 使用大语言模型理解上下文,综合考虑标题、类型、季度、年份、集数和精确标记等因素,选择最佳匹配结果
            </li>
            <li>
              <strong>AI辅助识别</strong>: 使用AI从标题中提取结构化信息(作品名称、季度、类型等),提高TMDB搜索准确率。应用于TMDB自动刮削定时任务
            </li>
            <li>
              <strong>AI别名修正</strong>: 使用AI修正已有的错误别名(例如中文别名字段写入了非中文内容)。启用后会强制更新所有别名字段,但已锁定的别名不会被修正
            </li>
            <li>
              <strong>AI别名扩展</strong>: 当元数据源返回非中文标题时,使用AI生成可能的别名(中文译名、罗马音、英文缩写等),然后在Bangumi/Douban中搜索以获取中文标题
            </li>
            <li>
              <strong>传统匹配兜底</strong>: 当AI匹配失败时,自动降级到传统匹配算法,确保功能可用性(仅AI模式下可用)
            </li>
            <li>
              <strong>应用场景</strong>:
              <ul>
                <li>AI智能匹配: 外部控制API全自动导入、Webhook自动导入、匹配后备机制</li>
                <li>AI辅助识别: TMDB自动刮削与剧集组映射定时任务</li>
                <li>AI别名扩展: 外部控制API全自动导入、Webhook自动导入等场景（当元数据源返回非中文标题时）</li>
              </ul>
            </li>
            <li>
              <strong>精确标记优先</strong>: AI会优先选择被用户标记为"精确"的数据源
            </li>
          </ul>
        </div>
      </Card>
    </Spin>
  )
}

export default AutoMatchSetting
