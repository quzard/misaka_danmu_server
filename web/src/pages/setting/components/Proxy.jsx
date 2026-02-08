import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Switch,
  Spin,
  Tag,
  Divider,
  Space,
} from 'antd'
import { useEffect, useState } from 'react'
import { getProxyConfig, setProxyConfig, testProxy } from '../../../apis'
import { useMessage } from '../../../MessageContext'

export const Proxy = () => {
  const [proxyMode, setProxyMode] = useState('none')
  const [loading, setLoading] = useState(true)
  const [form] = Form.useForm()
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const [isTestLoading, setIsTestLoading] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const messageApi = useMessage()

  useEffect(() => {
    getProxyConfig()
      .then(res => {
        const mode = res.data?.proxyMode ?? 'none'
        setProxyMode(mode)
        form.setFieldsValue({
          ...res.data,
          proxyMode: mode,
          proxySslVerify: res.data?.proxySslVerify ?? true,
        })
      })
      .finally(() => {
        setLoading(false)
      })
  }, [form])

  const handleSave = async () => {
    try {
      setIsSaveLoading(true)
      const values = await form.validateFields()
      setProxyMode(values.proxyMode)
      await setProxyConfig(values)
      setIsSaveLoading(false)
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  const handleTest = async () => {
    try {
      setIsTestLoading(true)
      setTestResult(null)
      const values = await form.validateFields()

      // 构建测试请求参数
      let proxyUrl = ''
      if (
        values.proxyMode === 'http_socks' &&
        values.proxyHost &&
        values.proxyPort &&
        values.proxyProtocol
      ) {
        let userinfo = ''
        if (values.proxyUsername) {
          userinfo = encodeURIComponent(values.proxyUsername)
          if (values.proxyPassword) {
            userinfo += ':' + encodeURIComponent(values.proxyPassword)
          }
          userinfo += '@'
        }
        proxyUrl = `${values.proxyProtocol}://${userinfo}${values.proxyHost}:${values.proxyPort}`
      }

      const res = await testProxy({
        proxy_mode: values.proxyMode,
        proxy_url: proxyUrl,
        accelerate_proxy_url: values.accelerateProxyUrl || ''
      })
      setTestResult(res.data)
    } catch (error) {
      messageApi.error('测试请求失败')
    } finally {
      setIsTestLoading(false)
    }
  }

  const ResultTag = ({ result }) => {
    const isSuccess = result.status === 'success'
    const color = isSuccess ? 'green' : 'red'
    const text = isSuccess
      ? `成功 (${result.latency.toFixed(0)} ms)`
      : `失败: ${result.error}`
    return <Tag color={color}>{text}</Tag>
  }

  return (
    <div className="my-6">
      <Card loading={loading} title="代理配置">
        <div className="mb-4">
          配置一个全局代理，可用于访问受限的网络资源。
        </div>

        <Form
          form={form}
          layout="horizontal"
          onFinish={handleSave}
          className="px-6 pb-6"
        >
          <Form.Item
            name="proxyMode"
            label="代理模式"
            className="mb-6"
          >
            <Select
              onChange={value => setProxyMode(value)}
              options={[
                { value: 'none', label: '不使用代理' },
                { value: 'http_socks', label: 'HTTP/SOCKS 代理' },
                { value: 'accelerate', label: '加速代理' },
              ]}
            />
          </Form.Item>

          {/* HTTP/SOCKS 代理配置 */}
          {proxyMode === 'http_socks' && (
            <>
              <Form.Item name="proxyProtocol" label="协议" className="mb-6">
                <Select
                  options={[
                    { value: 'http', label: 'http' },
                    { value: 'https', label: 'https' },
                    { value: 'socks5', label: 'socks5' },
                  ]}
                />
              </Form.Item>
              <Row gutter={[12, 12]}>
                <Col md={12} xs={24}>
                  <Form.Item name="proxyHost" label="主机" className="mb-4">
                    <Input placeholder="例如：127.0.0.1" />
                  </Form.Item>
                </Col>
                <Col md={12} xs={24}>
                  <Form.Item name="proxyPort" label="端口" className="mb-4">
                    <Input placeholder="例如：7890" />
                  </Form.Item>
                </Col>
              </Row>
              <Row gutter={[12, 12]}>
                <Col md={12} xs={24}>
                  <Form.Item
                    name="proxyUsername"
                    label="用户名(可选)"
                    className="mb-4"
                  >
                    <Input />
                  </Form.Item>
                </Col>
                <Col md={12} xs={24}>
                  <Form.Item
                    name="proxyPassword"
                    label="密码(可选)"
                    className="mb-4"
                  >
                    <Input />
                  </Form.Item>
                </Col>
                <Col md={12} xs={24}>
                  <Form.Item
                    label="跳过SSL证书验证"
                    name="proxySslVerify"
                    valuePropName="checked"
                    tooltip="当您的HTTPS代理使用自签名证书时，请开启此项以避免SSL验证错误。"
                    className="mb-4"
                  >
                    <Switch />
                  </Form.Item>
                </Col>
              </Row>
            </>
          )}

          {/* 加速代理配置 */}
          {proxyMode === 'accelerate' && (
            <Form.Item
              name="accelerateProxyUrl"
              label="加速代理地址"
              className="mb-6"
            >
              <Input placeholder="例如：https://your-proxy.vercel.app" />
            </Form.Item>
          )}

          <Form.Item>
            <div className="flex justify-end">
              <Space>
                <Button onClick={handleTest} loading={isTestLoading}>
                  测试连接
                </Button>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={isSaveLoading}
                >
                  保存修改
                </Button>
              </Space>
            </div>
          </Form.Item>
        </Form>
        {isTestLoading && (
          <div className="text-center">
            <Spin />
            <p>正在测试连接，请稍候...</p>
          </div>
        )}
        {testResult && (
          <div>
            <Divider>测试结果</Divider>
            <div className="flex flex-col gap-2">
              {testResult.proxy_connectivity &&
                testResult.proxy_connectivity.status !== 'skipped' && (
                  <div className="flex justify-between">
                    <span>代理服务器连通性:</span>
                    <ResultTag result={testResult.proxy_connectivity} />
                  </div>
                )}
              {Object.entries(testResult.target_sites).map(([site, result]) => (
                <div key={site} className="flex justify-between">
                  <span>
                    {site.replace('https://', '').replace('http://', '')}:
                  </span>
                  <ResultTag result={result} />
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
