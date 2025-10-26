import React, { useState, useEffect } from 'react'
import { Form, Input, Select, Switch, Button, message, Spin, Card, Tabs, Space, Tooltip, Row, Col, Alert } from 'antd'
import { QuestionCircleOutlined, SaveOutlined, ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { getConfig, setConfig } from '@/apis'
import api from '@/apis/fetch'

const { TextArea } = Input
const { Option } = Select
const { TabPane } = Tabs

const AutoMatchSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [matchMode, setMatchMode] = useState('traditional')
  const [fallbackEnabled, setFallbackEnabled] = useState(false)
  const [recognitionEnabled, setRecognitionEnabled] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

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
        aliasCorrectionEnabledRes
      ] = await Promise.all([
        getConfig('aiMatchEnabled'),
        getConfig('aiMatchFallbackEnabled'),
        getConfig('aiMatchProvider'),
        getConfig('aiMatchApiKey'),
        getConfig('aiMatchBaseUrl'),
        getConfig('aiMatchModel'),
        getConfig('aiMatchPrompt'),
        getConfig('aiRecognitionEnabled'),
        getConfig('aiRecognitionPrompt'),
        getConfig('aiAliasValidationPrompt'),
        getConfig('aiAliasCorrectionEnabled')
      ])

      const enabled = enabledRes.data.value === 'true'
      const fallback = fallbackRes.data.value === 'true'
      const recognition = recognitionEnabledRes.data.value === 'true'
      const aliasCorrection = aliasCorrectionEnabledRes.data.value === 'true'
      setMatchMode(enabled ? 'ai' : 'traditional')
      setFallbackEnabled(fallback)
      setRecognitionEnabled(recognition)

      form.setFieldsValue({
        aiMatchEnabled: enabled,
        aiMatchFallbackEnabled: fallback,
        aiMatchProvider: providerRes.data.value || 'deepseek',
        aiMatchApiKey: apiKeyRes.data.value || '',
        aiMatchBaseUrl: baseUrlRes.data.value || '',
        aiMatchModel: modelRes.data.value || 'deepseek-chat',
        aiMatchPrompt: promptRes.data.value || '',
        aiRecognitionEnabled: recognition,
        aiRecognitionPrompt: recognitionPromptRes.data.value || '',
        aiAliasValidationPrompt: aliasValidationPromptRes.data.value || '',
        aiAliasCorrectionEnabled: aliasCorrection
      })
    } catch (error) {
      message.error(`加载配置失败: ${error.message}`)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSettings()
  }, [])

  // 保存配置
  const handleSave = async () => {
    try {
      setSaving(true)
      const values = matchMode === 'ai'
        ? await form.validateFields()
        : form.getFieldsValue()

      await Promise.all([
        setConfig('aiMatchEnabled', values.aiMatchEnabled ? 'true' : 'false'),
        setConfig('aiMatchFallbackEnabled', values.aiMatchFallbackEnabled ? 'true' : 'false'),
        setConfig('aiMatchProvider', values.aiMatchProvider || ''),
        setConfig('aiMatchApiKey', values.aiMatchApiKey || ''),
        setConfig('aiMatchBaseUrl', values.aiMatchBaseUrl || ''),
        setConfig('aiMatchModel', values.aiMatchModel || ''),
        setConfig('aiMatchPrompt', values.aiMatchPrompt || ''),
        setConfig('aiRecognitionEnabled', values.aiRecognitionEnabled ? 'true' : 'false'),
        setConfig('aiRecognitionPrompt', values.aiRecognitionPrompt || ''),
        setConfig('aiAliasValidationPrompt', values.aiAliasValidationPrompt || ''),
        setConfig('aiAliasCorrectionEnabled', values.aiAliasCorrectionEnabled ? 'true' : 'false')
      ])

      message.success('保存成功')
    } catch (error) {
      message.error(`保存失败: ${error.message}`)
    } finally {
      setSaving(false)
    }
  }

  // 获取模型名称占位符
  const getModelPlaceholder = (provider) => {
    switch (provider) {
      case 'deepseek':
        return 'deepseek-chat'
      case 'openai':
        return 'gpt-4, gpt-4-turbo, gpt-3.5-turbo'
      default:
        return '请输入模型名称'
    }
  }

  // 获取Base URL占位符
  const getBaseUrlPlaceholder = (provider) => {
    switch (provider) {
      case 'deepseek':
        return 'https://api.deepseek.com (默认)'
      case 'openai':
        return 'https://api.openai.com/v1 (默认) 或自定义兼容接口'
      default:
        return '可选,用于自定义接口地址'
    }
  }

  // 测试AI连接
  const handleTestConnection = async () => {
    try {
      setTesting(true)
      setTestResult(null)

      const values = form.getFieldsValue(['aiMatchProvider', 'aiMatchApiKey', 'aiMatchBaseUrl', 'aiMatchModel'])

      if (!values.aiMatchProvider || !values.aiMatchApiKey || !values.aiMatchModel) {
        message.warning('请先填写AI提供商、API密钥和模型名称')
        return
      }

      const response = await api.post('/api/ui/config/ai/test', {
        provider: values.aiMatchProvider,
        apiKey: values.aiMatchApiKey,
        baseUrl: values.aiMatchBaseUrl || null,
        model: values.aiMatchModel
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
        error: error.message || error.detail || String(error)
      })
      message.error(`测试失败: ${error.message || error.detail}`)
    } finally {
      setTesting(false)
    }
  }

  return (
    <Spin spinning={loading}>
      <Card
        title="AI辅助增强"
        extra={
          <Button
            type="primary"
            icon={<SaveOutlined />}
            onClick={handleSave}
            loading={saving}
          >
            保存设置
          </Button>
        }
      >
        <Form
          form={form}
          layout="vertical"
          onValuesChange={(changedValues) => {
            if ('aiMatchEnabled' in changedValues) {
              setMatchMode(changedValues.aiMatchEnabled ? 'ai' : 'traditional')
            }
            if ('aiMatchFallbackEnabled' in changedValues) {
              setFallbackEnabled(changedValues.aiMatchFallbackEnabled)
            }
            if ('aiRecognitionEnabled' in changedValues) {
              setRecognitionEnabled(changedValues.aiRecognitionEnabled)
            }
          }}
        >
          <Tabs defaultActiveKey="connection">
            {/* 标签页1: AI连接配置 */}
            <TabPane tab="AI连接配置" key="connection">
              <Form.Item
                name="aiMatchProvider"
                label={
                  <Space>
                    <span>AI提供商</span>
                    <Tooltip title="选择AI服务提供商。DeepSeek性价比高,OpenAI兼容各种第三方接口。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                rules={[{ required: matchMode === 'ai', message: '请选择AI提供商' }]}
              >
                <Select>
                  <Option value="deepseek">DeepSeek (推荐)</Option>
                  <Option value="openai">OpenAI (兼容接口)</Option>
                </Select>
              </Form.Item>

              <Form.Item
                name="aiMatchApiKey"
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
                  prevValues.aiMatchProvider !== currentValues.aiMatchProvider
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item
                    name="aiMatchBaseUrl"
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
                      placeholder={getBaseUrlPlaceholder(getFieldValue('aiMatchProvider'))}
                    />
                  </Form.Item>
                )}
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prevValues, currentValues) =>
                  prevValues.aiMatchProvider !== currentValues.aiMatchProvider
                }
              >
                {({ getFieldValue }) => (
                  <Form.Item
                    name="aiMatchModel"
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
                      placeholder={getModelPlaceholder(getFieldValue('aiMatchProvider'))}
                    />
                  </Form.Item>
                )}
              </Form.Item>

              {/* AI连接测试 */}
              <Form.Item label="连接测试">
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Button
                    icon={<ThunderboltOutlined />}
                    onClick={handleTestConnection}
                    loading={testing}
                  >
                    测试AI连接
                  </Button>

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

            {/* 标签页2: 自动匹配 */}
            <TabPane tab="自动匹配" key="match">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="aiMatchEnabled"
                    label={
                      <Space>
                        <span>匹配模式</span>
                        <Tooltip title="AI智能匹配: 使用大语言模型理解上下文,综合考虑标题、类型、季度、年份、集数和精确标记等因素,选择最佳匹配结果。传统匹配: 基于标题相似度和类型匹配的算法,快速但可能不够精准。">
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                    }
                    valuePropName="checked"
                  >
                    <Switch
                      checkedChildren="AI智能匹配"
                      unCheckedChildren="传统匹配"
                      checked={matchMode === 'ai'}
                      onChange={checked => {
                        setMatchMode(checked ? 'ai' : 'traditional')
                        form.setFieldValue('aiMatchEnabled', checked)
                      }}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item
                    name="aiMatchFallbackEnabled"
                    label={
                      <Space>
                        <span>启用传统匹配兜底</span>
                        <Tooltip title={matchMode === 'traditional' ? '传统匹配模式下无需兜底' : '当AI匹配失败时,自动降级到传统匹配算法,确保功能可用性'}>
                          <QuestionCircleOutlined />
                        </Tooltip>
                      </Space>
                    }
                    valuePropName="checked"
                  >
                    <Switch disabled={matchMode === 'traditional'} />
                  </Form.Item>
                </Col>
              </Row>

              <Form.Item
                name="aiMatchPrompt"
                label={
                  <Space>
                    <span>AI匹配提示词</span>
                    <Tooltip title="用于指导AI如何选择最佳匹配结果的提示词。留空使用默认提示词。高级用户可自定义以优化匹配效果。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <TextArea
                  rows={8}
                  placeholder="留空使用默认提示词..."
                  style={{ fontFamily: 'monospace', fontSize: '12px' }}
                  disabled={matchMode !== 'ai'}
                />
              </Form.Item>
            </TabPane>

            {/* 标签页3: AI识别增强 */}
            <TabPane tab="AI识别增强" key="recognition">
              <Form.Item
                name="aiRecognitionEnabled"
                label={
                  <Space>
                    <span>启用AI辅助识别</span>
                    <Tooltip title="使用AI从标题中提取结构化信息(作品名称、季度、类型等),提高TMDB搜索准确率。应用于TMDB自动刮削定时任务。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                valuePropName="checked"
              >
                <Switch disabled={matchMode !== 'ai'} />
              </Form.Item>

              <Form.Item
                name="aiAliasCorrectionEnabled"
                label={
                  <Space>
                    <span>启用AI别名修正</span>
                    <Tooltip title="使用AI修正已有的错误别名(例如中文别名字段写入了非中文内容)。启用后,TMDB自动刮削任务会强制更新所有别名字段。注意:已锁定的别名不会被修正。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
                valuePropName="checked"
              >
                <Switch disabled={matchMode !== 'ai' || !recognitionEnabled} />
              </Form.Item>

              <Form.Item
                name="aiRecognitionPrompt"
                label={
                  <Space>
                    <span>AI识别提示词</span>
                    <Tooltip title="用于指导AI如何从标题中提取结构化信息的提示词。留空使用默认提示词。高级用户可自定义以优化识别效果。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <TextArea
                  rows={8}
                  placeholder="留空使用默认提示词..."
                  style={{ fontFamily: 'monospace', fontSize: '12px' }}
                  disabled={matchMode !== 'ai' || !recognitionEnabled}
                />
              </Form.Item>

              <Form.Item
                name="aiAliasValidationPrompt"
                label={
                  <Space>
                    <span>AI别名验证提示词</span>
                    <Tooltip title="用于指导AI如何验证和分类别名的提示词。AI会识别别名的语言类型(英文/日文/罗马音/中文)并验证是否真正属于该作品。留空使用默认提示词。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <TextArea
                  rows={8}
                  placeholder="留空使用默认提示词..."
                  style={{ fontFamily: 'monospace', fontSize: '12px' }}
                  disabled={matchMode !== 'ai' || !recognitionEnabled}
                />
              </Form.Item>
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
              <strong>传统匹配兜底</strong>: 当AI匹配失败时,自动降级到传统匹配算法,确保功能可用性(仅AI模式下可用)
            </li>
            <li>
              <strong>应用场景</strong>:
              <ul>
                <li>AI智能匹配: 外部控制API全自动导入、Webhook自动导入、匹配后备机制</li>
                <li>AI辅助识别: TMDB自动刮削与剧集组映射定时任务</li>
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
