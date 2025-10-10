import {
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Tooltip,
} from 'antd'
import { useEffect, useState } from 'react'
import {
  getWebhookApikey,
  getWebhookServices,
  refreshWebhookApikey,
  getWebhookSettings,
  setWebhookSettings,
} from '../../../apis'
import {
  CopyOutlined,
  ReloadOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import copy from 'copy-to-clipboard'
import { useMessage } from '../../../MessageContext'

export const Webhook = () => {
  const [isLoading, setLoading] = useState(true)
  const [isSaving, setSaving] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [services, setServices] = useState([])
  const messageApi = useMessage()
  const [form] = Form.useForm()

  // 动态监听表单中的值，以便实时更新UI
  const webhookEnabled = Form.useWatch('webhookEnabled', form)
  const isDelayedImportEnabled = Form.useWatch(
    'webhookDelayedImportEnabled',
    form
  )
  const domain = Form.useWatch('webhookCustomDomain', form)

  const getApiKey = async () => {
    const res = await getWebhookApikey()
    return res.data?.value || ''
  }
  const getServices = async () => {
    const res = await getWebhookServices()
    return res.data
  }

  const getInfo = async () => {
    setLoading(true)
    try {
      const [apiKeyRes, servicesRes, settingsRes] = await Promise.all([
        getApiKey(),
        getWebhookServices(),
        getWebhookSettings(),
      ])
      setApiKey(apiKeyRes)
      setServices(servicesRes.data)
      // 使用 setFieldsValue 将从后端获取的设置填充到表单中
      form.setFieldsValue(settingsRes.data)
    } catch (error) {
      messageApi.error('加载Webhook配置失败')
    } finally {
      setLoading(false)
    }
  }

  const onRefresh = async () => {
    try {
      const res = await refreshWebhookApikey()
      setApiKey(res.data.value)
      messageApi.success('API Key 已刷新')
    } catch (error) {
      messageApi.error('刷新API Key失败')
    }
  }

  const onSave = async values => {
    try {
      setSaving(true)
      // 修正：确保所有字段都存在，即使它们的值是 undefined 或 null。
      // 为这些字段提供合理的默认值，以确保发送到后端的对象结构始终完整且有效。
      const payload = {
        webhookEnabled: values.webhookEnabled ?? false,
        webhookDelayedImportEnabled:
          values.webhookDelayedImportEnabled ?? false,
        webhookDelayedImportHours: values.webhookDelayedImportHours ?? 24,
        webhookCustomDomain: values.webhookCustomDomain ?? '',
        webhookFilterMode: values.webhookFilterMode ?? 'blacklist',
        webhookFilterRegex: values.webhookFilterRegex ?? '',
        webhookLogRawRequest: values.webhookLogRawRequest ?? false,
        webhookFallbackEnabled: values.webhookFallbackEnabled ?? false,
      }
      await setWebhookSettings(payload)
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    getInfo()
  }, []) // eslint-disable-line

  return (
    <div className="my-6">
      <Card loading={isLoading} title="Webhook 配置">
        <div>
          <div className="mb-3">
            Webhook
            用于接收来自外部服务的通知，以实现自动化导入。请将下方对应服务的 URL
            填入其 Webhook 通知设置中。
          </div>
          <div className="mb-4">{`URL 格式为：http(s)://域名(ip):端口(port)/api/webhook/{服务名}?api_key={你的API Key}`}</div>
          <div className="flex items-center justify-start gap-3 mb-4">
            <div className="shrink-0 w-auto md:w-[120px]">API Key:</div>
            <div className="w-full">
              <Space.Compact style={{ width: '100%' }}>
                <Input readOnly value={apiKey} />
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  onClick={onRefresh}
                />
              </Space.Compact>
            </div>
          </div>
        </div>
        <Divider />
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            label={<div className="text-base font-medium">Webhook 控制</div>}
          >
            <Row gutter={[16, 12]} align={'stretch'}>
              <Col md={5} xs={12}>
                <div className="h-full flex items-center gap-2">
                  <span>启用 Webhook</span>
                  <Form.Item
                    name="webhookEnabled"
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch />
                  </Form.Item>
                </div>
              </Col>
              <Col md={5} xs={12}>
                <div className="h-full flex items-center gap-2">
                  <span>启用延时导入</span>
                  <Tooltip
                    title="延时导入需要配合定时任务功能使用。启用后，Webhook接收到的通知会先存储到数据库中，等待定时任务在指定时间后执行导入。这样可以避免媒体文件还未完全扫描完成就开始导入弹幕的问题。请确保在【任务管理-定时任务】中启用了Webhook任务处理。"
                    placement="top"
                  >
                    <InfoCircleOutlined />
                  </Tooltip>
                  <Form.Item
                    name="webhookDelayedImportEnabled"
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch disabled={!webhookEnabled} />
                  </Form.Item>
                </div>
              </Col>
              <Col md={6} xs={12}>
                <div className="h-full flex items-center gap-2">
                  <span>自定义延时时间 (小时)</span>
                  <Form.Item name="webhookDelayedImportHours" noStyle>
                    <InputNumber
                      min={1}
                      disabled={!webhookEnabled || !isDelayedImportEnabled}
                    />
                  </Form.Item>
                </div>
              </Col>
              <Col md={6} xs={12}>
                <div className="h-full flex items-center gap-2">
                  <span>记录原始请求</span>
                  <Form.Item
                    name="webhookLogRawRequest"
                    valuePropName="checked"
                    noStyle
                  >
                    <Switch disabled={!webhookEnabled} />
                  </Form.Item>
                </div>
              </Col>
            </Row>
            <div className="text-gray-400 text-xs mt-2">
              全局启用或禁用Webhook，并可选择延时导入以等待媒体文件被完整扫描。
            </div>
          </Form.Item>

          <Form.Item label="过滤规则 (正则表达式)">
            <Form.Item name="webhookFilterRegex" noStyle>
              <Input
                addonBefore={
                  <Form.Item name="webhookFilterMode" noStyle>
                    <Select
                      defaultValue="blacklist"
                      style={{ width: 100 }}
                      options={[
                        { value: 'blacklist', label: '黑名单' },
                        { value: 'whitelist', label: '白名单' },
                      ]}
                    />
                  </Form.Item>
                }
                placeholder="留空则不过滤"
              />
            </Form.Item>
            <div className="text-gray-400 text-xs mt-1">
              黑名单：匹配规则的标题将被忽略。白名单：只有匹配规则的标题才会被处理。
            </div>
          </Form.Item>

          <Form.Item name="webhookCustomDomain" label="自定义域名 (可选)">
            <Input placeholder="例如：https://your.domain.com" />
          </Form.Item>

          <Form.Item
            label={
              <div className="flex items-center gap-2">
                <span className="text-base font-medium">启用顺延机制</span>
                <Tooltip
                  title="当选中的源没有有效分集时（如只有预告片被过滤掉），自动尝试下一个候选源。关闭此选项时，将使用传统的单源选择模式。"
                  placement="top"
                >
                  <InfoCircleOutlined />
                </Tooltip>
              </div>
            }
          >
            <div className="flex items-center gap-2">
              <Form.Item
                name="webhookFallbackEnabled"
                valuePropName="checked"
                noStyle
              >
                <Switch disabled={!webhookEnabled} />
              </Form.Item>
              <span className="text-gray-400 text-sm">
                启用后，当首选源无法提供有效分集时，会自动尝试其他候选源
              </span>
            </div>
          </Form.Item>

          {webhookEnabled &&
            services?.map(it => (
              <Form.Item key={it} label={`${it} Webhook地址`}>
                <Space.Compact style={{ width: '100%' }}>
                  <Input
                    readOnly
                    value={`${domain || window.location.origin}/api/webhook/${it}?api_key=${apiKey}`}
                  />
                  <Button
                    type="primary"
                    icon={<CopyOutlined />}
                    onClick={() => {
                      copy(
                        `${domain || window.location.origin}/api/webhook/${it}?api_key=${apiKey}`
                      )
                      messageApi.success('复制成功')
                    }}
                  />
                </Space.Compact>
              </Form.Item>
            ))}

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={isSaving}>
              保存设置
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
