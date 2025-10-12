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
} from 'antd'
import { useEffect, useState } from 'react'
import { useMessage } from '../../../MessageContext'
import {
  getTmdbReverseLookupConfig,
  saveTmdbReverseLookupConfig,
} from '../../../apis'

const { Text } = Typography

export const TmdbReverseLookup = () => {
  const [isLoading, setLoading] = useState(true)
  const [isSaving, setSaving] = useState(false)
  const messageApi = useMessage()
  const [form] = Form.useForm()

  // 动态监听表单中的值
  const enabled = Form.useWatch('enabled', form)

  // 可用的元数据源
  const availableSources = [
    { value: 'imdb', label: 'IMDB' },
    { value: 'tvdb', label: 'TVDB' },
    { value: 'douban', label: '豆瓣' },
    { value: 'bangumi', label: 'Bangumi' },
  ]

  const getConfig = async () => {
    try {
      const response = await getTmdbReverseLookupConfig()
      return response.data
    } catch (error) {
      messageApi.error('获取TMDB反查配置失败')
      return { enabled: false, sources: ['imdb', 'tvdb'] }
    }
  }

  const saveConfig = async values => {
    try {
      const response = await saveTmdbReverseLookupConfig(values)
      return response.data
    } catch (error) {
      throw error
    }
  }

  const loadConfig = async () => {
    setLoading(true)
    try {
      const config = await getConfig()
      form.setFieldsValue(config)
    } catch (error) {
      messageApi.error('加载TMDB反查配置失败')
    } finally {
      setLoading(false)
    }
  }

  const onSave = async () => {
    try {
      setSaving(true)
      const values = await form.validateFields()
      await saveConfig(values)
      messageApi.success('TMDB反查配置已保存')
    } catch (error) {
      messageApi.error('保存TMDB反查配置失败')
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
      <Card title="TMDB反查配置">
        <Alert
          message="功能说明"
          description="当使用TVDB、IMDB、豆瓣、Bangumi等ID搜索时，如果获取到的标题不是中文，系统会自动通过这些ID反查TMDB获取中文标题，提高搜索准确性。"
          type="info"
          showIcon
          className="!mb-4"
        />

        <Form
          form={form}
          layout="vertical"
          onFinish={onSave}
          className="px-6 pb-6"
        >
          <Form.Item
            name="enabled"
            label="启用TMDB反查"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>

          {enabled && (
            <Form.Item
              name="sources"
              label="启用反查的元数据源"
              tooltip="选择哪些元数据源在获取非中文标题时触发TMDB反查"
            >
              <Checkbox.Group
                options={availableSources}
                className="flex flex-col gap-2"
              />
            </Form.Item>
          )}

          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={isSaving}>
                保存配置
              </Button>
              <Button onClick={loadConfig}>重置</Button>
            </Space>
          </Form.Item>
        </Form>

        {enabled && (
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
      </Card>
    </div>
  )
}
