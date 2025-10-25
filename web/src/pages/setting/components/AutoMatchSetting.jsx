import React, { useState, useEffect } from 'react'
import { Form, Input, Select, Switch, Button, message, Spin, Card, Space, Tooltip } from 'antd'
import { QuestionCircleOutlined, SaveOutlined } from '@ant-design/icons'
import { getConfig, setConfig } from '@/apis'

const { TextArea } = Input
const { Option } = Select

const AutoMatchSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [matchMode, setMatchMode] = useState('traditional') // 'traditional' or 'ai'
  const [fallbackEnabled, setFallbackEnabled] = useState(false)

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
        promptRes
      ] = await Promise.all([
        getConfig('aiMatchEnabled'),
        getConfig('aiMatchFallbackEnabled'),
        getConfig('aiMatchProvider'),
        getConfig('aiMatchApiKey'),
        getConfig('aiMatchBaseUrl'),
        getConfig('aiMatchModel'),
        getConfig('aiMatchPrompt')
      ])

      const enabled = enabledRes.data.value === 'true'
      const fallback = fallbackRes.data.value === 'true'
      setMatchMode(enabled ? 'ai' : 'traditional')
      setFallbackEnabled(fallback)

      form.setFieldsValue({
        aiMatchEnabled: enabled,
        aiMatchFallbackEnabled: fallback,
        aiMatchProvider: providerRes.data.value || 'deepseek',
        aiMatchApiKey: apiKeyRes.data.value || '',
        aiMatchBaseUrl: baseUrlRes.data.value || '',
        aiMatchModel: modelRes.data.value || 'deepseek-chat',
        aiMatchPrompt: promptRes.data.value || ''
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
      // 如果AI匹配未启用,跳过必填字段验证
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
        setConfig('aiMatchPrompt', values.aiMatchPrompt || '')
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

  return (
    <Spin spinning={loading}>
      <Card
        title="自动匹配设置"
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
          }}
        >
          {/* 匹配模式开关 */}
          <Form.Item
            name="aiMatchEnabled"
            label="匹配模式"
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

          {/* 传统匹配兜底开关 - 始终显示,传统模式下禁用 */}
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

          {/* AI配置区域 - 禁用时字段保持显示但不可编辑 */}
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
            <Select disabled={matchMode !== 'ai'}>
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
            <Input.Password placeholder="sk-..." disabled={matchMode !== 'ai'} />
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
                  disabled={matchMode !== 'ai'}
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
                  disabled={matchMode !== 'ai'}
                />
              </Form.Item>
            )}
          </Form.Item>

          <Form.Item
            name="aiMatchPrompt"
            label={
              <Space>
                <span>AI提示词</span>
                <Tooltip title="用于指导AI如何选择最佳匹配结果的提示词。留空使用默认提示词。高级用户可自定义以优化匹配效果。">
                  <QuestionCircleOutlined />
                </Tooltip>
              </Space>
            }
          >
            <TextArea
              rows={12}
              placeholder="留空使用默认提示词..."
              style={{ fontFamily: 'monospace', fontSize: '12px' }}
              disabled={matchMode !== 'ai'}
            />
          </Form.Item>
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
              <strong>传统匹配兜底</strong>: 当AI匹配失败时,自动降级到传统匹配算法,确保功能可用性(仅AI模式下可用)
            </li>
            <li>
              <strong>应用场景</strong>: 外部控制API全自动导入、Webhook自动导入、匹配后备机制
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

