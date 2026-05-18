import { useState, useEffect, useCallback } from 'react'
import { Form, Input, Button, Card, Divider } from 'antd'
import {
  UserOutlined,
  LockOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
  KeyOutlined,
  ClearOutlined,
} from '@ant-design/icons'
import { login, autoLogin, getUserInfo, getPasskeyLoginOptions, verifyPasskeyLogin } from '../../apis'
import { useNavigate } from 'react-router-dom'
import Cookies from 'js-cookie'
import { useMessage } from '../../MessageContext'
import { MfaVerifyModal, base64urlToBuffer, bufferToBase64url } from '../../components/MfaVerifyModal'
import { clearBrowserCache } from '../../utils/clearCache'

export const Login = () => {
  const [form] = Form.useForm()
  const [isLoading, setIsLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [checkingWhitelist, setCheckingWhitelist] = useState(true)
  const [mfaModalOpen, setMfaModalOpen] = useState(false)
  const [mfaTypes, setMfaTypes] = useState([])
  const [mfaToken, setMfaToken] = useState('')
  const [mfaUsername, setMfaUsername] = useState('')
  const [passkeyLoginLoading, setPasskeyLoginLoading] = useState(false)
  const navigate = useNavigate()
  const messageApi = useMessage()

  // 页面加载时先校验已保存登录状态，失效后再尝试白名单自动登录
  useEffect(() => {
    let cancelled = false

    const checkLoginState = async () => {
      const token = Cookies.get('danmu_token')

      // 如果已有 token，必须先校验有效性，避免残留旧 token 导致跳首页后 401 循环
      if (token) {
        try {
          const res = await getUserInfo()
          if (!cancelled && res.data?.username) {
            navigate('/')
          }
          return
        } catch (error) {
          Cookies.remove('danmu_token', { path: '/' })
          if (!cancelled) {
            setCheckingWhitelist(false)
          }
          return
        }
      }

      // 尝试白名单自动登录
      try {
        const res = await autoLogin()
        const { accessToken, expiresIn } = res.data
        const expiresInDays = expiresIn / (60 * 24)
        Cookies.set('danmu_token', accessToken, {
          expires: expiresInDays,
          path: '/',
          secure: location.protocol === 'https:',
          sameSite: 'lax'
        })
        if (!cancelled) {
          messageApi.success('白名单自动登录成功！')
          navigate('/')
        }
      } catch (error) {
        // 不在白名单中，显示登录表单
        if (!cancelled) {
          setCheckingWhitelist(false)
        }
      }
    }

    checkLoginState()

    return () => {
      cancelled = true
    }
  }, [messageApi, navigate])

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
      if (error.code === 403 && error.mfaRequired) {
        setMfaTypes(error.mfaTypes || [])
        setMfaToken(error.mfaToken || '')
        setMfaUsername(values.username || '')
        setMfaModalOpen(true)
      } else if (error.code === 429) {
        // 暴力破解防护：登录次数过多
        messageApi.error(error.message || '登录失败次数过多，请稍后重试')
      } else {
        console.error('登录失败:', error)
        messageApi.error('登录失败，请检查用户名或密码')
      }
    } finally {
      setIsLoading(false)
    }
  }

  // MFA 验证成功回调（MfaVerifyModal 直接返回 JWT 数据）
  const handleMfaSuccess = useCallback((tokenData) => {
    setMfaModalOpen(false)
    if (tokenData.accessToken) {
      saveTokenAndNavigate(tokenData.accessToken, tokenData.expiresIn)
    }
  }, [saveTokenAndNavigate])

  // PassKey 无密码直接登录
  const handlePasskeyLogin = useCallback(async () => {
    if (!window.PublicKeyCredential) {
      messageApi.error('当前环境不支持 PassKey，请使用 HTTPS 或 localhost 访问')
      return
    }
    setPasskeyLoginLoading(true)
    try {
      // 1. 获取认证选项
      const optionsRes = await getPasskeyLoginOptions()
      const options = JSON.parse(optionsRes.data.options)
      const passkeySessionId = optionsRes.data.sessionId
      options.challenge = base64urlToBuffer(options.challenge)
      if (options.allowCredentials) {
        options.allowCredentials = options.allowCredentials.map(c => ({
          ...c, id: base64urlToBuffer(c.id),
        }))
      }

      // 2. 浏览器 WebAuthn
      const credential = await navigator.credentials.get({ publicKey: options })
      const credJSON = JSON.stringify({
        id: credential.id,
        rawId: credential.id,
        type: credential.type,
        response: {
          authenticatorData: bufferToBase64url(credential.response.authenticatorData),
          clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
          signature: bufferToBase64url(credential.response.signature),
          userHandle: credential.response.userHandle
            ? bufferToBase64url(credential.response.userHandle)
            : null,
        },
      })

      // 3. 服务端验证 → 直接拿 JWT
      const res = await verifyPasskeyLogin({ credential: credJSON, session_id: passkeySessionId })
      if (res.data.accessToken) {
        saveTokenAndNavigate(res.data.accessToken, res.data.expiresIn)
      }
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        messageApi.info('PassKey 登录已取消')
      } else {
        console.error('PassKey 登录失败:', err)
        messageApi.error('PassKey 登录失败，请重试')
      }
    } finally {
      setPasskeyLoginLoading(false)
    }
  }, [saveTokenAndNavigate, messageApi])

  return (
    <div className="my-6 flex items-center justify-center relative">
      {/* 右上角：清理浏览器缓存 */}
      <Button
        type="link"
        size="small"
        icon={<ClearOutlined />}
        onClick={clearBrowserCache}
        className="!absolute top-0 right-4"
      >
        清理浏览器缓存
      </Button>

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

          {/* PassKey 无密码登录 */}
          {window.PublicKeyCredential && (
            <>
              <Divider plain className="!mt-0 !mb-3 px-6">或</Divider>
              <div className="px-6 pb-6">
                <Button
                  block
                  icon={<KeyOutlined />}
                  loading={passkeyLoginLoading}
                  onClick={handlePasskeyLogin}
                >
                  使用 PassKey 登录
                </Button>
              </div>
            </>
          )}
        </Card>      )}

      {/* MFA 验证弹窗 */}
      <MfaVerifyModal
        open={mfaModalOpen}
        onCancel={() => setMfaModalOpen(false)}
        onSuccess={handleMfaSuccess}
        mfaTypes={mfaTypes}
        mfaToken={mfaToken}
        username={mfaUsername}
      />
    </div>
  )
}
