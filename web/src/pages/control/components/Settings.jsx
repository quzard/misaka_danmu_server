import {
  Button,
  Card,
  Checkbox,
  Form,
  Space,
  Spin,
  Switch,
  Typography,
  Alert,
  Tooltip,
  Divider,
} from 'antd'
import { useEffect, useState } from 'react'
import { useMessage } from '../../../MessageContext'
import {
  getTmdbReverseLookupConfig,
  saveTmdbReverseLookupConfig,
  getConfig,
  setConfig,
} from '../../../apis'
import { InfoCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

export const Settings = () => {
  const [isLoading, setLoading] = useState(true)
  const [isSaving, setSaving] = useState(false)
  const messageApi = useMessage()
  const [form] = Form.useForm()

  // 动态监听表单中的值
  const tmdbEnabled = Form.useWatch('tmdbEnabled', form)
  const fallbackEnabled = Form.useWatch('externalApiFallbackEnabled', form)

  // 可用的元数据源
  const availableSources = [
    { value: 'imdb', label: 'IMDB' },
    { value: 'tvdb', label: 'TVDB' },
    { value: 'douban', label: '豆瓣' },
    { value: 'bangumi', label: 'Bangumi' },
  ]

  const getTmdbConfig = async () => {
    try {
      const response = await getTmdbReverseLookupConfig()
      return response.data
    } catch (error) {
      messageApi.error('获取TMDB反查配置失败')
      return { enabled: false, sources: ['imdb', 'tvdb'] }
    }
  }

  const getFallbackConfig = async () => {
    try {
      const response = await getConfig('externalApiFallbackEnabled')
      return response.data?.value === 'true'
    } catch (error) {
      return false // 默认关闭
    }
  }

  const saveTmdbConfig = async values => {
    try {
      const response = await saveTmdbReverseLookupConfig({
        enabled: values.tmdbEnabled,
        sources: values.tmdbSources,
      })
      return response.data
    } catch (error) {
      throw error
    }
  }

  const saveFallbackConfig = async enabled => {
    try {
      await setConfig('externalApiFallbackEnabled', enabled ? 'true' : 'false')
    } catch (error) {
      throw error
    }
  }

  const loadConfig = async () => {
    setLoading(true)
    try {
      const [tmdbConfig, fallbackConfig] = await Promise.all([
        getTmdbConfig(),
        getFallbackConfig(),
      ])
      
      form.setFieldsValue({
        tmdbEnabled: tmdbConfig.enabled,
        tmdbSources: tmdbConfig.sources,
        externalApiFallbackEnabled: fallbackConfig,
      })
    } catch (error) {
      messageApi.error('加载配置失败')
    } finally {
      setLoading(false)
    }
  }

  const onSave = async () => {
    try {
      setSaving(true)
      const values = await form.validateFields()
      
      // 保存 TMDB 反查配置
      await saveTmdbConfig(values)
      
      // 保存顺延机制配置
      await saveFallbackConfig(values.externalApiFallbackEnabled)
      
      messageApi.success('配置已保存')
    } catch (error) {
      messageApi.error('保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    loadConfig()
  }, [])

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div className="my-6">
      <Card title="设置">
        <Form
          form={form}
          layout="vertical"
          onFinish={onSave}
          className="px-6 pb-6"
        >
          {/* TMDB 反查配置 */}
          <div className="mb-6">
            <Text strong className="text-lg">
              TMDB 反查配置
            </Text>
            <Alert
              message="功能说明"
              description="当使用TVDB、IMDB、豆瓣、Bangumi等ID搜索时，如果获取到的标题不是中文，系统会自动通过这些ID反查TMDB获取中文标题，提高搜索准确性。"
              type="info"
              showIcon
              className="!mt-2 !mb-4"
            />

            <Form.Item
              name="tmdbEnabled"
              label="启用TMDB反查"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            {tmdbEnabled && (
              <Form.Item
                name="tmdbSources"
                label="启用反查的元数据源"
                tooltip="选择哪些元数据源在获取非中文标题时触发TMDB反查"
              >
                <Checkbox.Group
                  options={availableSources}
                  className="flex flex-col gap-2"
                />
              </Form.Item>
            )}

            {tmdbEnabled && (
              <div className="mt-4 p-4 bg-base-bg rounded">
                <Text strong className="te">
                  工作流程：
                </Text>
                <ol className="p-0 mt-2 text-sm">
                  <li>1. 使用选中的元数据源ID进行搜索</li>
                  <li>2. 检测获取到的标题是否为中文</li>
                  <li>3. 如果不是中文，通过该ID反查TMDB获取中文标题</li>
                  <li>4. 使用中文标题进行后续的全网搜索和识别词匹配</li>
                </ol>
              </div>
            )}
          </div>

          <Divider />

          {/* 顺延机制配置 */}
          <div className="mb-6">
            <Text strong className="text-lg">
              智能顺延机制
            </Text>
            <Alert
              message="功能说明"
              description="当选中的源没有有效分集时（如只有预告片被过滤掉），自动尝试下一个候选源，提高导入成功率。"
              type="info"
              showIcon
              className="!mt-2 !mb-4"
            />

            <Form.Item
              name="externalApiFallbackEnabled"
              label={
                <div className="flex items-center gap-2">
                  <span>启用外部控制API顺延机制</span>
                  <Tooltip
                    title="当外部控制API选中的源没有有效分集时，自动尝试下一个候选源。关闭此选项时，将使用传统的单源选择模式。"
                    placement="top"
                  >
                    <InfoCircleOutlined />
                  </Tooltip>
                </div>
              }
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>

            {fallbackEnabled && (
              <div className="mt-4 p-4 bg-base-bg rounded">
                <Text strong className="te">
                  工作流程：
                </Text>
                <ol className="p-0 mt-2 text-sm">
                  <li>1. 按优先级排序所有搜索结果</li>
                  <li>2. 验证首选源是否有有效分集</li>
                  <li>3. 如果首选源无效，自动尝试下一个候选源</li>
                  <li>4. 重复直到找到有效源或所有候选源都失败</li>
                </ol>
              </div>
            )}
          </div>

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={isSaving}>
                保存配置
              </Button>
              <Button onClick={loadConfig}>重置</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
