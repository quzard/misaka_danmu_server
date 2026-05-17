import { useState, useCallback } from 'react'
import { Modal, Input, Button, Space, Typography, Divider, message } from 'antd'
import { SafetyOutlined, KeyOutlined } from '@ant-design/icons'
import { verifyPasskeyAuth, getPasskeyAuthOptions } from '../apis'

const { Text } = Typography

/**
 * MFA 验证弹窗组件
 * 支持 TOTP 验证码输入和 PassKey 认证
 */
export const MfaVerifyModal = ({ open, onCancel, onVerify, mfaTypes = [], username = '' }) => {
  const [otpCode, setOtpCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [passkeyLoading, setPasskeyLoading] = useState(false)

  const hasTotp = mfaTypes.includes('totp')
  const hasPasskey = mfaTypes.includes('passkey')

  // TOTP 验证
  const handleTotpVerify = useCallback(async () => {
    if (!otpCode || otpCode.length !== 6) {
      message.warning('请输入6位验证码')
      return
    }
    setLoading(true)
    try {
      await onVerify({ type: 'totp', code: otpCode })
    } finally {
      setLoading(false)
    }
  }, [otpCode, onVerify])

  // PassKey 验证
  const handlePasskeyVerify = useCallback(async () => {
    if (!window.PublicKeyCredential) {
      message.error('当前浏览器不支持 PassKey')
      return
    }

    setPasskeyLoading(true)
    try {
      // 1. 获取认证选项
      const optionsRes = await getPasskeyAuthOptions(username)
      const options = JSON.parse(optionsRes.data.options)

      // 2. 转换 base64url 为 ArrayBuffer
      options.challenge = base64urlToBuffer(options.challenge)
      if (options.allowCredentials) {
        options.allowCredentials = options.allowCredentials.map(cred => ({
          ...cred,
          id: base64urlToBuffer(cred.id),
        }))
      }

      // 3. 调用浏览器 WebAuthn API
      const credential = await navigator.credentials.get({ publicKey: options })

      // 4. 序列化凭证
      const credentialJSON = JSON.stringify({
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

      // 5. 发送到服务器验证
      const verifyRes = await verifyPasskeyAuth({ credential: credentialJSON }, username)
      if (verifyRes.data.verified) {
        await onVerify({ type: 'passkey', verified: true })
      }
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        message.info('PassKey 验证已取消')
      } else {
        console.error('PassKey 验证失败:', err)
        message.error('PassKey 验证失败: ' + (err.message || '未知错误'))
      }
    } finally {
      setPasskeyLoading(false)
    }
  }, [username, onVerify])

  const handleKeyDown = e => {
    if (e.key === 'Enter' && hasTotp) {
      handleTotpVerify()
    }
  }

  return (
    <Modal
      title="两步验证"
      open={open}
      onCancel={onCancel}
      footer={null}
      destroyOnClose
      width={400}
    >
      <div className="py-4">
        <Text type="secondary">
          您的账户已开启多因素认证，请完成验证以继续登录。
        </Text>

        {hasTotp && (
          <div className="mt-4">
            <Text strong><SafetyOutlined className="mr-1" />验证器验证码</Text>
            <div className="mt-2">
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  placeholder="请输入6位验证码"
                  maxLength={6}
                  value={otpCode}
                  onChange={e => setOtpCode(e.target.value.replace(/\D/g, ''))}
                  onKeyDown={handleKeyDown}
                  size="large"
                  autoFocus
                />
                <Button
                  type="primary"
                  size="large"
                  loading={loading}
                  onClick={handleTotpVerify}
                >
                  验证
                </Button>
              </Space.Compact>
            </div>
          </div>
        )}

        {hasTotp && hasPasskey && (
          <Divider plain>或</Divider>
        )}

        {hasPasskey && (
          <div className={hasTotp ? '' : 'mt-4'}>
            <Button
              block
              size="large"
              icon={<KeyOutlined />}
              loading={passkeyLoading}
              onClick={handlePasskeyVerify}
            >
              使用 PassKey 验证
            </Button>
          </div>
        )}
      </div>
    </Modal>
  )
}

// ========== WebAuthn 工具函数 ==========

function base64urlToBuffer(base64url) {
  const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/')
  const pad = base64.length % 4 === 0 ? '' : '='.repeat(4 - (base64.length % 4))
  const binary = atob(base64 + pad)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes.buffer
}

function bufferToBase64url(buffer) {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// 导出工具函数供其他组件使用
export { base64urlToBuffer, bufferToBase64url }
