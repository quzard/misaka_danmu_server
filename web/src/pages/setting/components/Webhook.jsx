import {
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  message,
  Space,
  Spin,
  Switch,
} from 'antd'
import { useEffect, useState } from 'react'
import {
  getWebhookApikey,
  getWebhookServices,
  refreshWebhookApikey,
  getWebhookSettings,
  setWebhookSettings,
} from '../../../apis'
import { CopyOutlined, ReloadOutlined } from '@ant-design/icons'
import copy from 'copy-to-clipboard'
import { useMessage } from '../../../MessageContext'

export const Webhook = () => {
  const [isLoading, setLoading] = useState(true)
  const [apiKey, setApiKey] = useState('')
  const [domain, setDomain] = useState('')
  const [services, setServices] = useState([])
  const messageApi = useMessage()

  const getApiKey = async () => {
    const res = await getWebhookApikey()
    return res.data?.value || ''
  }
  const getDomain = async () => {
    const res = await getWebhookDomain()
    return res.data?.value || ''
  }
  const getServices = async () => {
    const res = await getWebhookServices()
    return res.data
  }

  const getInfo = async () => {
    try {
      setLoading(true)
      const [apiKey, domain, services] = await Promise.all([
        getApiKey(),
        getDomain(),
        getServices(),
      ])
      setApiKey(apiKey)
      setDomain(domain)
      setServices(services)
      setLoading(false)
    } catch (error) {
      setLoading(false)
    }
  }

  const onRefresh = async () => {
    const res = await refreshWebhookApikey()
    setApiKey(res.data.value)
  }

  const onSaveDoamin = async () => {
    try {
      await setWebhookDomain({ value: domain })
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    }
  }

  useEffect(() => {
    getInfo()
  }, [])

  return (
    <div className="my-6">
      <Spin spinning={isLoading}>
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
              <Input block readOnly value={apiKey} />
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={onRefresh}
              />
            </Space.Compact>
          </div>
        </div>
        <Form form={form} layout="vertical" onFinish={onSave}>
          <Form.Item
            name="webhookEnabled"
            label="启用 Webhook"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="webhookDelayedImportEnabled"
            label="启用延时导入"
            valuePropName="checked"
          >
            <Switch disabled={!webhookEnabled} />
          </Form.Item>
          <Form.Item label="延时时间 (小时)">
            <Form.Item name="webhookDelayedImportHours" noStyle>
              <InputNumber
                min={1}
                disabled={!webhookEnabled || !isDelayedImportEnabled}
              />
            </Form.Item>
            <div className="text-gray-400 text-xs mt-1">
              Webhook 触发后，等待指定的小时数再执行导入任务。
            </div>
          </Form.Item>
          <Form.Item name="webhookCustomDomain" label="自定义域名 (可选)">
            <Input placeholder="例如：https://your.domain.com" />
          </Form.Item>

          {webhookEnabled &&
            services.map(it => (
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
      </Spin>
    </div>
  )
}
