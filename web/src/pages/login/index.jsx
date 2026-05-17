import { useState, useEffect, useCallback } from 'react'
import { Form, Input, Button, Card, message } from 'antd'
import {
  UserOutlined,
  LockOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
} from '@ant-design/icons'
import { login, autoLogin } from '../../apis'
import { useNavigate } from 'react-router-dom'
import Cookies from 'js-cookie'
import { useMessage } from '../../MessageContext'
import { MfaVerifyModal } from '../../components/MfaVerifyModal'

export const Login = () => {
  const [form] = Form.useForm()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [checkingWhitelist, setCheckingWhitelist] = useState(true)
  const [mfaModalOpen, setMfaModalOpen] = useState(false)
  const [mfaTypes, setMfaTypes] = useState([])
  const [pendingCredentials, setPendingCredentials] = useState(null)
  const navigate = useNavigate()
  const messageApi = useMessage()

  // 页面加载时尝试白名单自动登录
  useEffect(() => {
    const token = Cookies.get('danmu_token')

    // 如果已有 token，直接跳转到主页
    if (token) {
      navigate('/')
      return
    }

    // 尝试白名单自动登录
    autoLogin()
      .then(res => {
        // 自动登录成功，保存 token
        const { accessToken, expiresIn } = res.data
        const expiresInDays = expiresIn / (60 * 24)
        Cookies.set('danmu_token', accessToken, {
          expires: expiresInDays,
          path: '/',
          secure: location.protocol === 'https:',
          sameSite: 'lax'
        })
        messageApi.success('白名单自动登录成功！')
        navigate('/')
      })
      .catch(() => {
        // 不在白名单中，显示登录表单
        setCheckingWhitelist(false)
      })
  }, [])

  // 保存 token 并跳转
  const saveTokenAndNavigate = useCallback((accessToken, expiresIn) => {
    const expiresInMinutes = expiresIn || 4320
    const expiresInDays = expiresInMinutes / (60 * 24)
    Cookies.set('danmu_token', accessToken, {
      expires: expiresInDays,
      path: '/',
      secure: location.protocol === 'https:',
      sameSite: 'lax'
    })
    messageApi.success('登录成功！')
    navigate('/')
  }, [messageApi, navigate])

  // 处理登录逻辑
  const handleLogin = async values => {
    try {
      setIsLoading(true)
      const res = await login(values)

      if (res.data.accessToken) {
        saveTokenAndNavigate(res.data.accessToken, res.data.expiresIn)
      } else {
        messageApi.error('登录失败，请检查用户名或密码')
      }
    } catch (error) {
      // 检查是否是 403 MFA 要求
      if (error.response && error.response.status === 403 && error.response.data?.mfaRequired) {
        setMfaTypes(error.response.data.mfaTypes || [])
        setPendingCredentials(values)
        setMfaModalOpen(true)
      } else {
        console.error('登录失败:', error)
        messageApi.error('登录失败，请检查用户名或密码')
      }
    } finally {
      setIsLoading(false)
    }
  }

  // MFA 验证回调
  const handleMfaVerify = useCallback(async ({ type, code, verified }) => {
    if (!pendingCredentials) return

    if (type === 'totp') {
      try {
        // 重新提交登录，带上 OTP 验证码
        const formData = { ...pendingCredentials, otp_password: code }
        const res = await login(formData)
        if (res.data.accessToken) {
          setMfaModalOpen(false)
          saveTokenAndNavigate(res.data.accessToken, res.data.expiresIn)
        }
      } catch (err) {
        messageApi.error(err.response?.data?.detail || '验证码错误')
        throw err // 让 MfaVerifyModal 知道验证失败
      }
    } else if (type === 'passkey' && verified) {
      // PassKey 验证已在 MfaVerifyModal 中完成，现在用 OTP 占位码登录
      try {
        const formData = { ...pendingCredentials, otp_password: 'passkey_verified' }
        const res = await login(formData)
        if (res.data.accessToken) {
          setMfaModalOpen(false)
          saveTokenAndNavigate(res.data.accessToken, res.data.expiresIn)
        }
      } catch (err) {
        messageApi.error('PassKey 登录失败')
        throw err
      }
    }
  }, [pendingCredentials, saveTokenAndNavigate, messageApi])

  return (
    <div className="my-6 flex items-center justify-center">
      {/* 白名单检查中显示加载状态 */}
      {checkingWhitelist ? (
        <Card className="w-full max-w-md rounded-xl shadow-lg overflow-hidden mx-auto">
          <div className="text-center py-12">
            <p className="text-base-text text-lg">正在检查白名单...</p>
          </div>
        </Card>
      ) : (
        /* 登录卡片容器 */
        <Card className="w-full max-w-md rounded-xl shadow-lg overflow-hidden mx-auto">
          {/* 登录标题区域 */}
          <div className="text-center mb-8 pt-4">
            <h2 className="text-[clamp(1.5rem,3vw,2rem)] font-bold text-base-text">
              账户登录
            </h2>
            <p className="text-base-text mt-2">请输入您的账号信息以继续</p>
          </div>

          {/* 表单区域 */}
          <Form
            form={form}
            layout="vertical"
            onFinish={handleLogin}
            className="px-6 pb-6"
            size="large"
          >
            {/* 用户名输入 */}
            <Form.Item
              name="username"
              label="用户名"
              rules={[{ required: true, message: '请输入用户名' }]}
              className="mb-4"
            >
              <Input
                prefix={<UserOutlined className="text-gray-400" />}
                placeholder="请输入用户名"
              />
            </Form.Item>

            {/* 密码输入 */}
            <Form.Item
              name="password"
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
              className="mb-6"
            >
              <Input.Password
                prefix={<LockOutlined className="text-gray-400" />}
                placeholder="请输入密码"
                visibilityToggle={{
                  visible: showPassword,
                  onVisibleChange: setShowPassword,
                }}
                iconRender={visible =>
                  visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
                }
              />
            </Form.Item>

            {/* 登录按钮 */}
            <Form.Item>
              <Button block type="primary" htmlType="submit" loading={isLoading}>
                登录
              </Button>
            </Form.Item>
          </Form>
        </Card>      )}

      {/* MFA 验证弹窗 */}
      <MfaVerifyModal
        open={mfaModalOpen}
        onCancel={() => setMfaModalOpen(false)}
        onVerify={handleMfaVerify}
        mfaTypes={mfaTypes}
        username={pendingCredentials?.username || ''}
      />
    </div>
  )
}
