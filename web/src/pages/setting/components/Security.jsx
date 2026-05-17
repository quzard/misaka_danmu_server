import { useState, useEffect, useCallback } from 'react'
import {
  Card, Switch, Button, Space, Typography, Divider, Input, Modal,
  List, Tag, message, Popconfirm, Spin, QRCode, Empty
} from 'antd'
import {
  SafetyOutlined, KeyOutlined, DeleteOutlined, EditOutlined,
  PlusOutlined, CheckCircleOutlined, CloseCircleOutlined, CopyOutlined
} from '@ant-design/icons'
import {
  getMfaStatus, setupTotp, verifyTotpSetup, disableTotp,
  getPasskeyRegisterOptions, verifyPasskeyRegister,
  renamePasskey, deletePasskey
} from '../../../apis'
import { base64urlToBuffer, bufferToBase64url } from '../../../components/MfaVerifyModal'

const { Text, Paragraph } = Typography

const Security = () => {
  const [loading, setLoading] = useState(true)
  const [mfaStatus, setMfaStatus] = useState({ totpEnabled: false, passkeyCount: 0, passkeys: [] })

  // TOTP 状态
  const [totpSetupData, setTotpSetupData] = useState(null)
  const [totpCode, setTotpCode] = useState('')
  const [totpSetupLoading, setTotpSetupLoading] = useState(false)
  const [disablePassword, setDisablePassword] = useState('')
  const [disableModalOpen, setDisableModalOpen] = useState(false)

  // PassKey 状态
  const [registerLoading, setRegisterLoading] = useState(false)
  const [renameModalOpen, setRenameModalOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState(null)
  const [newDeviceName, setNewDeviceName] = useState('')

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true)
      const res = await getMfaStatus()
      setMfaStatus(res.data)
    } catch (err) {
      console.error('获取 MFA 状态失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  // ========== TOTP ==========
  const handleSetupTotp = async () => {
    try {
      setTotpSetupLoading(true)
      const res = await setupTotp()
      setTotpSetupData(res.data)
    } catch (err) {
      message.error(err.response?.data?.detail || '生成 TOTP 密钥失败')
    } finally {
      setTotpSetupLoading(false)
    }
  }

  const handleVerifyTotp = async () => {
    if (!totpCode || totpCode.length !== 6) {
      message.warning('请输入6位验证码')
      return
    }
    try {
      await verifyTotpSetup({ code: totpCode })
      message.success('TOTP 两步验证已启用！')
      setTotpSetupData(null)
      setTotpCode('')
      fetchStatus()
    } catch (err) {
      message.error(err.response?.data?.detail || '验证码错误')
    }
  }

  const handleDisableTotp = async () => {
    try {
      await disableTotp({ password: disablePassword })
      message.success('TOTP 两步验证已关闭')
      setDisableModalOpen(false)
      setDisablePassword('')
      fetchStatus()
    } catch (err) {
      message.error(err.response?.data?.detail || '关闭失败')
    }
  }

  // ========== PassKey ==========
  const handleRegisterPasskey = async () => {
    if (!window.PublicKeyCredential) {
      message.error('当前浏览器不支持 PassKey / WebAuthn')
      return
    }
    setRegisterLoading(true)
    try {
      const optRes = await getPasskeyRegisterOptions()
      const options = JSON.parse(optRes.data.options)
      options.challenge = base64urlToBuffer(options.challenge)
      options.user.id = base64urlToBuffer(options.user.id)
      if (options.excludeCredentials) {
        options.excludeCredentials = options.excludeCredentials.map(c => ({
          ...c, id: base64urlToBuffer(c.id)
        }))
      }

      const credential = await navigator.credentials.create({ publicKey: options })
      const credJSON = JSON.stringify({
        id: credential.id,
        rawId: credential.id,
        type: credential.type,
        response: {
          attestationObject: bufferToBase64url(credential.response.attestationObject),
          clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
        },
      })

      const deviceName = prompt('请为此 PassKey 命名（如：我的电脑）', '未命名设备')
      await verifyPasskeyRegister({ credential: credJSON, deviceName: deviceName || '未命名设备' })
      message.success('PassKey 注册成功！')
      fetchStatus()
    } catch (err) {
      if (err.name === 'NotAllowedError') {
        message.info('PassKey 注册已取消')
      } else {
        message.error('PassKey 注册失败: ' + (err.response?.data?.detail || err.message))
      }
    } finally {
      setRegisterLoading(false)
    }
  }

  const handleRename = async () => {
    if (!renameTarget || !newDeviceName.trim()) return
    try {
      await renamePasskey(renameTarget.id, { deviceName: newDeviceName.trim() })
      message.success('重命名成功')
      setRenameModalOpen(false)
      fetchStatus()
    } catch (err) {
      message.error('重命名失败')
    }
  }

  const handleDelete = async (id) => {
    try {
      await deletePasskey(id)
      message.success('PassKey 已删除')
      fetchStatus()
    } catch (err) {
      message.error('删除失败')
    }
  }

  if (loading) return <Spin className="block mx-auto mt-12" />

  return (
    <div className="space-y-6">
      {/* TOTP 两步验证 */}
      <Card title={<><SafetyOutlined className="mr-2" />TOTP 两步验证</>} size="small">
        <div className="flex items-center justify-between mb-4">
          <div>
            <Text>使用验证器 App 生成一次性验证码</Text>
            <br />
            <Text type="secondary">支持 Google Authenticator、Microsoft Authenticator 等</Text>
          </div>
          {mfaStatus.totpEnabled ? (
            <Space>
              <Tag color="green" icon={<CheckCircleOutlined />}>已启用</Tag>
              <Button danger size="small" onClick={() => setDisableModalOpen(true)}>关闭</Button>
            </Space>
          ) : (
            <Button type="primary" size="small" onClick={handleSetupTotp} loading={totpSetupLoading}>
              启用
            </Button>
          )}
        </div>

        {/* TOTP 设置流程 */}
        {totpSetupData && (
          <div className="border rounded-lg p-4 mt-2">
            <Text strong>1. 使用验证器 App 扫描二维码：</Text>
            <div className="flex justify-center my-4">
              <QRCode value={totpSetupData.uri} size={200} />
            </div>
            <Text type="secondary">或手动输入密钥：</Text>
            <Paragraph copyable className="font-mono bg-gray-50 dark:bg-gray-800 p-2 rounded mt-1">
              {totpSetupData.secret}
            </Paragraph>
            <Divider />
            <Text strong>2. 输入验证器显示的6位验证码：</Text>
            <div className="mt-2">
              <Space.Compact>
                <Input
                  placeholder="6位验证码"
                  maxLength={6}
                  value={totpCode}
                  onChange={e => setTotpCode(e.target.value.replace(/\D/g, ''))}
                  onPressEnter={handleVerifyTotp}
                  style={{ width: 160 }}
                />
                <Button type="primary" onClick={handleVerifyTotp}>确认启用</Button>
              </Space.Compact>
              <Button type="link" onClick={() => { setTotpSetupData(null); setTotpCode('') }}>取消</Button>
            </div>
          </div>
        )}
      </Card>

      {/* PassKey */}
      <Card
        title={<><KeyOutlined className="mr-2" />PassKey / 生物识别</>}
        size="small"
        extra={
          mfaStatus.totpEnabled ? (
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={handleRegisterPasskey}
              loading={registerLoading}
            >
              注册新 PassKey
            </Button>
          ) : null
        }
      >
        {!mfaStatus.totpEnabled ? (
          <div className="text-center py-6">
            <Text type="secondary">
              <SafetyOutlined className="mr-1" />
              请先启用 TOTP 两步验证后才能注册 PassKey
            </Text>
            <br />
            <Text type="secondary" className="text-xs">
              这是为了确保您在 PassKey 不可用时仍有备用验证方式
            </Text>
          </div>
        ) : (
          <>
            <Text type="secondary" className="block mb-4">
              使用指纹、面容识别或硬件安全密钥进行快速验证
            </Text>

        {mfaStatus.passkeys.length === 0 ? (
          <Empty description="暂无已注册的 PassKey" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            dataSource={mfaStatus.passkeys}
            renderItem={item => (
              <List.Item
                actions={[
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => {
                      setRenameTarget(item)
                      setNewDeviceName(item.deviceName || '')
                      setRenameModalOpen(true)
                    }}
                  >
                    重命名
                  </Button>,
                  <Popconfirm title="确定删除此 PassKey？" onConfirm={() => handleDelete(item.id)}>
                    <Button size="small" danger icon={<DeleteOutlined />}>删除</Button>
                  </Popconfirm>,
                ]}
              >
                <List.Item.Meta
                  avatar={<KeyOutlined style={{ fontSize: 20, marginTop: 4 }} />}
                  title={item.deviceName || '未命名设备'}
                  description={
                    <Space size="small" wrap>
                      <Text type="secondary">
                        注册于 {item.createdAt ? new Date(item.createdAt).toLocaleDateString() : '-'}
                      </Text>
                      {item.lastUsedAt && (
                        <Text type="secondary">
                          · 最后使用 {new Date(item.lastUsedAt).toLocaleDateString()}
                        </Text>
                      )}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
          </>
        )}
      </Card>

      {/* 关闭 TOTP 弹窗 */}
      <Modal
        title="关闭两步验证"
        open={disableModalOpen}
        onCancel={() => { setDisableModalOpen(false); setDisablePassword('') }}
        onOk={handleDisableTotp}
        okText="确认关闭"
        okButtonProps={{ danger: true }}
      >
        <Text>关闭两步验证将降低账户安全性。请输入当前密码确认：</Text>
        <Input.Password
          className="mt-3"
          placeholder="当前密码"
          value={disablePassword}
          onChange={e => setDisablePassword(e.target.value)}
        />
      </Modal>

      {/* 重命名 PassKey 弹窗 */}
      <Modal
        title="重命名 PassKey"
        open={renameModalOpen}
        onCancel={() => setRenameModalOpen(false)}
        onOk={handleRename}
      >
        <Input
          placeholder="设备名称"
          value={newDeviceName}
          onChange={e => setNewDeviceName(e.target.value)}
        />
      </Modal>
    </div>
  )
}

export default Security