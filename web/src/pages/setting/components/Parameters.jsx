import { Button, Card, Form, Input, message, Space, Tag } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useState, useEffect } from 'react'
import {
  getGithubToken,
  saveGithubToken,
  verifyGithubToken,
} from '../../../apis'
import { TrustedProxies } from './TrustedProxies'

export const Parameters = () => {
  const [form] = Form.useForm()
  const [messageApi, contextHolder] = message.useMessage()
  const [loading, setLoading] = useState(false)
  const [tokenInfo, setTokenInfo] = useState(null)

  useEffect(() => {
    loadGithubToken()
  }, [])

  const loadGithubToken = async () => {
    try {
      const res = await getGithubToken()
      form.setFieldsValue({
        githubToken: res.data?.token || '',
      })
      if (res.data?.token) {
        await verifyToken(res.data.token)
      }
    } catch (error) {
      console.error('加载GitHub Token失败:', error)
    }
  }

  const verifyToken = async (token) => {
    if (!token) {
      setTokenInfo(null)
      return
    }
    try {
      const res = await verifyGithubToken({ token })
      setTokenInfo(res.data)
    } catch (error) {
      setTokenInfo({ valid: false, error: error.response?.data?.detail || '验证失败' })
    }
  }

  const handleSave = async () => {
    try {
      setLoading(true)
      const values = await form.validateFields()
      await saveGithubToken({ token: values.githubToken })
      messageApi.success('保存成功')
      await verifyToken(values.githubToken)
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      {contextHolder}
      <Card title="GitHub Token 配置" className="mb-4">
        <Form form={form} layout="vertical">
          <Form.Item
            name="githubToken"
            label="GitHub Personal Access Token"
            extra="用于请求 GitHub API,避免速率限制。无需任何权限,只需创建一个 Token 即可。"
          >
            <Input.Password
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              onChange={(e) => verifyToken(e.target.value)}
            />
          </Form.Item>

          {tokenInfo && (
            <div className="mb-4">
              {tokenInfo.valid ? (
                <Space direction="vertical" className="w-full">
                  <Tag icon={<CheckCircleOutlined />} color="success">
                    Token 有效
                  </Tag>
                  <div className="text-sm text-gray-600">
                    <div>用户: {tokenInfo.username}</div>
                    <div>剩余配额: {tokenInfo.rateLimit?.remaining} / {tokenInfo.rateLimit?.limit}</div>
                    <div>重置时间: {new Date(tokenInfo.rateLimit?.reset * 1000).toLocaleString()}</div>
                  </div>
                </Space>
              ) : (
                <Tag icon={<CloseCircleOutlined />} color="error">
                  {tokenInfo.error || 'Token 无效'}
                </Tag>
              )}
            </div>
          )}

          <Form.Item>
            <Button type="primary" onClick={handleSave} loading={loading}>
              保存
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <TrustedProxies />
    </div>
  )
}

