import { useState, useEffect } from 'react'
import { Button, Input, InputNumber, Switch, Select, Tag, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { getConfig, setConfig } from '../../../apis'

/**
 * 通用配置项组件
 * 根据配置的 type 自动渲染对应的输入组件
 */
export const GenericConfigItem = ({ config }) => {
  const [value, setValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [verifyInfo, setVerifyInfo] = useState(null)
  const [messageApi, contextHolder] = message.useMessage()

  // 加载配置值
  useEffect(() => {
    loadValue()
  }, [config.key])

  const loadValue = async () => {
    try {
      setLoading(true)
      // 如果有自定义 getApi，使用自定义的
      if (config.getApi) {
        const res = await config.getApi()
        const val = res.data?.token ?? res.data?.value ?? ''
        setValue(val)
        // 如果有验证 API 且有值，自动验证
        if (config.verifyApi && val) {
          await verifyValue(val)
        }
      } else {
        const res = await getConfig(config.key)
        setValue(res.data?.value ?? '')
      }
    } catch (err) {
      console.error(`加载配置 ${config.key} 失败:`, err)
    } finally {
      setLoading(false)
    }
  }

  const verifyValue = async (val) => {
    if (!config.verifyApi || !val) {
      setVerifyInfo(null)
      return
    }
    try {
      const res = await config.verifyApi({ token: val })
      setVerifyInfo(res.data)
    } catch (err) {
      setVerifyInfo({ valid: false, error: err.response?.data?.detail || '验证失败' })
    }
  }

  const handleSave = async () => {
    try {
      setSaving(true)
      // 如果有自定义 saveApi，使用自定义的
      if (config.saveApi) {
        await config.saveApi({ token: value })
      } else {
        await setConfig(config.key, value)
      }
      messageApi.success('保存成功')
      // 保存后验证
      if (config.verifyApi) {
        await verifyValue(value)
      }
    } catch (err) {
      messageApi.error(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 根据类型渲染输入组件
  const renderInput = () => {
    const commonProps = {
      placeholder: config.placeholder,
      disabled: loading,
      className: 'flex-1',
    }

    switch (config.type) {
      case 'password':
        return (
          <Input.Password
            {...commonProps}
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              if (config.verifyApi) {
                verifyValue(e.target.value)
              }
            }}
          />
        )

      case 'number':
        return (
          <InputNumber
            {...commonProps}
            value={value ? Number(value) : undefined}
            min={config.min}
            max={config.max}
            addonAfter={config.suffix}
            onChange={(val) => setValue(val?.toString() ?? '')}
            style={{ width: '100%' }}
          />
        )

      case 'boolean':
        return (
          <Switch
            checked={value === 'true'}
            onChange={(checked) => setValue(checked ? 'true' : 'false')}
            disabled={loading}
          />
        )

      case 'textarea':
        return (
          <Input.TextArea
            {...commonProps}
            value={value}
            rows={config.rows || 3}
            onChange={(e) => setValue(e.target.value)}
          />
        )

      case 'select':
        return (
          <Select
            {...commonProps}
            value={value || undefined}
            onChange={(val) => setValue(val)}
            options={config.options?.map(opt => 
              typeof opt === 'string' ? { value: opt, label: opt } : opt
            )}
            style={{ width: '100%' }}
          />
        )

      default: // string
        return (
          <Input
            {...commonProps}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        )
    }
  }

  // 渲染验证信息（用于 GitHub Token 等）
  const renderVerifyInfo = () => {
    if (!verifyInfo) return null

    if (verifyInfo.valid) {
      return (
        <div className="mt-2">
          <Tag icon={<CheckCircleOutlined />} color="success">Token 有效</Tag>
          <div className="text-sm text-gray-500 mt-1">
            <div>用户: {verifyInfo.username}</div>
            <div>剩余配额: {verifyInfo.rateLimit?.remaining} / {verifyInfo.rateLimit?.limit}</div>
            <div>重置时间: {new Date(verifyInfo.rateLimit?.reset * 1000).toLocaleString()}</div>
          </div>
        </div>
      )
    } else {
      return (
        <div className="mt-2">
          <Tag icon={<CloseCircleOutlined />} color="error">
            {verifyInfo.error || 'Token 无效'}
          </Tag>
        </div>
      )
    }
  }

  return (
    <div className="mb-6">
      {contextHolder}
      <div className="mb-1 font-medium">{config.label}</div>
      {config.description && (
        <div className="text-sm text-gray-500 mb-2">{config.description}</div>
      )}
      <div className="flex items-start gap-2">
        <div className="flex-1">
          {renderInput()}
          {renderVerifyInfo()}
        </div>
        <Button type="primary" onClick={handleSave} loading={saving}>
          保存
        </Button>
      </div>
    </div>
  )
}

