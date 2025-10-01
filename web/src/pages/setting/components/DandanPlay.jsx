import {
  Button,
  Card,
  Form,
  Input,
  message,
  Switch,
  Tooltip,
  Space,
} from 'antd'
import {
  getScraperConfig,
  updateScraperConfig,
} from '../../../apis'
import { useEffect, useState } from 'react'
import {
  EyeInvisibleOutlined,
  EyeOutlined,
  LockOutlined,
  QuestionCircleOutlined,
  KeyOutlined,
  CloudOutlined,
  DesktopOutlined,
} from '@ant-design/icons'
import { useMessage } from '../../../MessageContext'

export const DandanPlay = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const [showAppSecret, setShowAppSecret] = useState(false)
  const [showAppSecretAlt, setShowAppSecretAlt] = useState(false)
  const [authMode, setAuthMode] = useState('local') // 'local' or 'proxy'

  const messageApi = useMessage()

  const getConfig = async () => {
    try {
      const res = await getScraperConfig('dandanplay')
      return res.data || {}
    } catch (error) {
      messageApi.error('获取配置失败')
      return {}
    }
  }

  const getInfo = async () => {
    try {
      setLoading(true)
      const config = await getConfig()
      form.setFieldsValue(config)
      
      // 根据配置判断当前模式
      if (config.dandanplay_proxy_config) {
        setAuthMode('proxy')
      } else {
        setAuthMode('local')
      }
      
      setLoading(false)
    } catch (error) {
      setLoading(false)
      messageApi.error('加载配置失败')
    }
  }

  const handleSave = async () => {
    try {
      setIsSaveLoading(true)
      const values = await form.validateFields()
      
      // 根据当前模式，清空另一种模式的配置
      if (authMode === 'local') {
        values.dandanplay_proxy_config = ''
      } else {
        values.dandanplay_app_id = ''
        values.dandanplay_app_secret = ''
        values.dandanplay_app_secret_alt = ''
      }
      
      await updateScraperConfig('dandanplay', values)
      setIsSaveLoading(false)
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  useEffect(() => {
    getInfo()
  }, [])

  return (
    <div className="my-6">
      <Card loading={loading} title="DanDanPlay API 配置">
        <div className="mb-4">
          选择一种认证方式。本地模式需要自己的App ID和Secret，跨域代理模式使用第三方代理服务。
        </div>
        <Form
          form={form}
          layout="horizontal"
          onFinish={handleSave}
          className="px-6 pb-6"
        >
          <Form.Item label="认证方式" className="mb-6">
            <Switch
              checkedChildren={
                <Space>
                  <CloudOutlined />
                  跨域代理
                </Space>
              }
              unCheckedChildren={
                <Space>
                  <DesktopOutlined />
                  本地功能
                </Space>
              }
              checked={authMode === 'proxy'}
              onChange={checked => setAuthMode(checked ? 'proxy' : 'local')}
            />
          </Form.Item>

          {authMode === 'local' && (
            <>
              <Form.Item
                name="dandanplay_app_id"
                label={
                  <span>
                    App ID{' '}
                    <a
                      href="https://www.dandanplay.com/dev"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <QuestionCircleOutlined className="cursor-pointer text-gray-400" />
                    </a>
                  </span>
                }
                rules={[{ required: true, message: '请输入App ID' }]}
                className="mb-4"
              >
                <Input 
                  prefix={<KeyOutlined className="text-gray-400" />}
                  placeholder="请输入App ID" 
                />
              </Form.Item>

              <Form.Item
                name="dandanplay_app_secret"
                label="App Secret"
                rules={[{ required: true, message: '请输入App Secret' }]}
                className="mb-4"
              >
                <Input.Password
                  prefix={<LockOutlined className="text-gray-400" />}
                  placeholder="请输入App Secret"
                  visibilityToggle={{
                    visible: showAppSecret,
                    onVisibleChange: setShowAppSecret,
                  }}
                  iconRender={visible =>
                    visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
                  }
                />
              </Form.Item>

              <Form.Item
                name="dandanplay_app_secret_alt"
                label={
                  <span>
                    备用App Secret{' '}
                    <Tooltip title="可选的备用密钥，用于轮换使用以避免频率限制">
                      <QuestionCircleOutlined className="cursor-pointer text-gray-400" />
                    </Tooltip>
                  </span>
                }
                className="mb-6"
              >
                <Input.Password
                  prefix={<LockOutlined className="text-gray-400" />}
                  placeholder="请输入备用App Secret（可选）"
                  visibilityToggle={{
                    visible: showAppSecretAlt,
                    onVisibleChange: setShowAppSecretAlt,
                  }}
                  iconRender={visible =>
                    visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
                  }
                />
              </Form.Item>
            </>
          )}

          {authMode === 'proxy' && (
            <Form.Item
              name="dandanplay_proxy_config"
              label={
                <span>
                  跨域代理配置{' '}
                  <Tooltip title="JSON格式的代理配置，支持多个代理服务器">
                    <QuestionCircleOutlined className="cursor-pointer text-gray-400" />
                  </Tooltip>
                </span>
              }
              rules={[
                { required: true, message: '请输入代理配置' },
                {
                  validator: (_, value) => {
                    if (!value) return Promise.resolve()
                    try {
                      JSON.parse(value)
                      return Promise.resolve()
                    } catch {
                      return Promise.reject(new Error('请输入有效的JSON格式'))
                    }
                  }
                }
              ]}
              className="mb-6"
            >
              <Input.TextArea
                placeholder={`{
  "Msaka10876": {
    "TYPE": "HTTPS",
    "HOST": "danmu-api.misaka10876.top",
    "PORT": 443,
    "PATH": "/cors",
    "Headers": {
      "NEW": {
        "KEY": "X-User-Agent",
        "VALUE": "misaka10876/server_v1.0.0"
      }
    }
  }
}`}
                rows={12}
                showCount
                maxLength={2000}
              />
            </Form.Item>
          )}

          <Form.Item>
            <div className="flex justify-end">
              <Button type="primary" htmlType="submit" loading={isSaveLoading}>
                保存修改
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Card>
    </div>
  )
}
