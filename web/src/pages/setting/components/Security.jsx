import {
  EyeInvisibleOutlined,
  EyeOutlined,
  LockOutlined,
} from '@ant-design/icons'
import { Button, Card, Form, Input, message, Popconfirm } from 'antd'
import { useState, useEffect } from 'react'
import { changePassword, logout, getDockerStatus, restartService } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { useNavigate } from 'react-router-dom'
import { RoutePaths } from '../../../general/RoutePaths'
import Cookies from 'js-cookie'

export const Security = () => {
  const [form] = Form.useForm()
  const [showPassword1, setShowPassword1] = useState(false)
  const [showPassword2, setShowPassword2] = useState(false)
  const [showPassword3, setShowPassword3] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [dockerAvailable, setDockerAvailable] = useState(false)
  const [restartLoading, setRestartLoading] = useState(false)
  const messageApi = useMessage()
  const navigate = useNavigate()

  // 检查 Docker 套接字是否可用
  useEffect(() => {
    const checkDocker = async () => {
      try {
        const res = await getDockerStatus()
        // API 返回 socketAvailable 字段
        setDockerAvailable(res.data?.socketAvailable || false)
      } catch (error) {
        setDockerAvailable(false)
      }
    }
    checkDocker()
  }, [])

  const onSave = async () => {
    try {
      setIsLoading(true)
      const values = await form.validateFields()
      await changePassword(values)
      form.resetFields()
      messageApi.success('修改成功')
    } catch (error) {
      // 优先从 error.response.data.detail 获取（直接来自后端）
      const detail = error.response?.data?.detail || error.detail

      let errorMsg = '修改失败'

      if (Array.isArray(detail)) {
        // Pydantic 422 验证错误：[{loc, msg, type}, ...]
        errorMsg = detail.map(err => err.msg || JSON.stringify(err)).join('; ')
      } else if (typeof detail === 'string') {
        // 业务逻辑错误：字符串
        errorMsg = detail
      } else if (error.message && typeof error.message === 'string') {
        // fetch.js 拦截器添加的 message 字段
        errorMsg = error.message
      }

      messageApi.error(errorMsg)
    } finally {
      setIsLoading(false)
    }
  }

  const onLogout = async () => {
    await logout()
    Cookies.remove('danmu_token', { path: '/' })
    navigate(RoutePaths.LOGIN)
  }

  const handleRestart = async () => {
    try {
      setRestartLoading(true)
      await restartService()
      messageApi.success('重启指令已发送，请稍候...')
    } catch (error) {
      messageApi.error(error.response?.data?.detail || '重启失败')
    } finally {
      setRestartLoading(false)
    }
  }

  return (
    <div className="my-6">
      <Card title="修改密码" className="mb-4">
        <div className="mb-4">
          如果您是使用初始随机密码登录的，建议您在此修改为自己的密码。
        </div>
        <Form
          form={form}
          layout="horizontal"
          onFinish={onSave}
          className="px-6 pb-6"
        >
          {/* 密码输入 */}
          <Form.Item
            name="oldPassword"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined className="text-gray-400" />}
              placeholder="请输入当前密码"
              visibilityToggle={{
                visible: showPassword1,
                onVisibleChange: setShowPassword1,
              }}
              iconRender={visible =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
            />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[{ required: true, message: '请输入新密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined className="text-gray-400" />}
              placeholder="请输入新密码"
              visibilityToggle={{
                visible: showPassword2,
                onVisibleChange: setShowPassword2,
              }}
              iconRender={visible =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
            />
          </Form.Item>
          <Form.Item
            name="checkPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              {
                required: true,
                message: '请输入新密码',
              },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('新密码不匹配'))
                },
              }),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined className="text-gray-400" />}
              placeholder="请输入新密码"
              visibilityToggle={{
                visible: showPassword3,
                onVisibleChange: setShowPassword3,
              }}
              iconRender={visible =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
            />
          </Form.Item>

          <Form.Item>
            <div className="flex justify-end">
              <Button type="primary" htmlType="submit" loading={isLoading}>
                确认修改
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Card>

      {dockerAvailable && (
        <Card title="重启服务" className="mb-4">
          <div className="mb-4">
            重启容器服务。通常在更新弹幕源或修改配置后需要重启。
          </div>
          <div className="px-6 pb-6">
            <Popconfirm
              title="确认重启"
              description="确定要重启服务吗？"
              onConfirm={handleRestart}
              okText="确定"
              cancelText="取消"
            >
              <Button type="primary" loading={restartLoading}>
                重启服务
              </Button>
            </Popconfirm>
          </div>
        </Card>
      )}

      <Card title="退出登录">
        <div className="mb-4">
          退出当前账户，返回登录页面。
        </div>
        <div className="px-6 pb-6">
          <Button type="primary" danger onClick={onLogout}>
            退出登录
          </Button>
        </div>
      </Card>
    </div>
  )
}
