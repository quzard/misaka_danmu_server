import { Card, Form, Switch, Input, Button, Space, Tooltip, Checkbox } from 'antd'
import { useEffect, useState } from 'react'
import { getMatchFallback, setMatchFallback, getMatchFallbackBlacklist, setMatchFallbackBlacklist, getMatchFallbackTokens, setMatchFallbackTokens, getTokenList, getSearchFallback, setSearchFallback, getConfig, setConfig } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { QuestionCircleOutlined } from '@ant-design/icons'

export const MatchFallbackSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [blacklistSaving, setBlacklistSaving] = useState(false)
  const [tokensSaving, setTokensSaving] = useState(false)
  const [tokenList, setTokenList] = useState([])
  const messageApi = useMessage()

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const [fallbackRes, blacklistRes, tokensRes, tokenListRes, searchFallbackRes, externalApiFallbackRes] = await Promise.all([
        getMatchFallback(),
        getMatchFallbackBlacklist(),
        getMatchFallbackTokens(),
        getTokenList(),
        getSearchFallback(),
        getConfig('externalApiFallbackEnabled')
      ])
      setTokenList(tokenListRes.data || [])

      // 解析token配置
      let selectedTokens = []
      try {
        selectedTokens = JSON.parse(tokensRes.data.value || '[]')
      } catch (e) {
        console.warn('解析匹配后备Token配置失败:', e)
      }

      form.setFieldsValue({
        matchFallbackEnabled: fallbackRes.data.value === 'true',
        matchFallbackBlacklist: blacklistRes.data.value || '',
        matchFallbackTokens: selectedTokens,
        searchFallbackEnabled: searchFallbackRes.data.value === 'true',
        externalApiFallbackEnabled: externalApiFallbackRes.data?.value === 'true'
      })
    } catch (error) {
      messageApi.error('获取设置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSettings()
  }, [])

  // 监听页面焦点，当页面重新获得焦点时刷新数据
  useEffect(() => {
    const handleFocus = () => {
      fetchSettings()
    }

    window.addEventListener('focus', handleFocus)
    return () => {
      window.removeEventListener('focus', handleFocus)
    }
  }, [])

  const handleValueChange = async changedValues => {
    try {
      if ('matchFallbackEnabled' in changedValues) {
        await setMatchFallback({ value: String(changedValues.matchFallbackEnabled) })
        messageApi.success('匹配后备开关已保存')
      }
      if ('searchFallbackEnabled' in changedValues) {
        await setSearchFallback({ value: String(changedValues.searchFallbackEnabled) })
        messageApi.success('后备搜索开关已保存')
      }
      if ('externalApiFallbackEnabled' in changedValues) {
        await setConfig('externalApiFallbackEnabled', String(changedValues.externalApiFallbackEnabled))
        messageApi.success('顺延机制已保存')
      }
      // 黑名单不自动保存，需要点击保存按钮
    } catch (error) {
      messageApi.error('保存设置失败')
      fetchSettings()
    }
  }

  const handleBlacklistSave = async () => {
    try {
      setBlacklistSaving(true)
      const values = form.getFieldsValue()
      await setMatchFallbackBlacklist({ value: values.matchFallbackBlacklist || '' })
      messageApi.success('黑名单已保存')
    } catch (error) {
      messageApi.error('保存黑名单失败')
    } finally {
      setBlacklistSaving(false)
    }
  }

  const handleTokensSave = async () => {
    try {
      setTokensSaving(true)
      const values = form.getFieldsValue()
      const tokensValue = JSON.stringify(values.matchFallbackTokens || [])
      await setMatchFallbackTokens({ value: tokensValue })
      messageApi.success('Token配置已保存')
    } catch (error) {
      messageApi.error('保存Token配置失败')
    } finally {
      setTokensSaving(false)
    }
  }

  return (
    <Card title="配置" loading={loading}>
      <Form
        form={form}
        onValuesChange={handleValueChange}
        layout="vertical"
        initialValues={{
          matchFallbackEnabled: false,
          searchFallbackEnabled: false,
          externalApiFallbackEnabled: false,
          matchFallbackBlacklist: '',
          matchFallbackTokens: []
        }}
      >
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
          <Form.Item
            name="matchFallbackEnabled"
            label="启用匹配后备"
            valuePropName="checked"
            tooltip="启用后，当播放客户端尝试使用match接口时，接口在本地库中找不到任何结果时，系统将自动触发一个后台任务，尝试从全网搜索并导入对应的弹幕。"
            style={{ flex: 1 }}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            name="searchFallbackEnabled"
            label="启用后备搜索"
            valuePropName="checked"
            tooltip="启用后，当使用search/anime接口搜索时，如果本地库中没有结果，系统将自动触发全网搜索并返回搜索结果。用户可以直接选择搜索结果进行下载。"
            style={{ flex: 1 }}
          >
            <Switch />
          </Form.Item>

          <Form.Item
            noStyle
            shouldUpdate={(prevValues, currentValues) =>
              prevValues.matchFallbackEnabled !== currentValues.matchFallbackEnabled ||
              prevValues.searchFallbackEnabled !== currentValues.searchFallbackEnabled
            }
          >
            {({ getFieldValue }) => {
              const matchFallbackEnabled = getFieldValue('matchFallbackEnabled')
              const searchFallbackEnabled = getFieldValue('searchFallbackEnabled')
              const isFallbackDisabled = !matchFallbackEnabled && !searchFallbackEnabled

              return (
                <Form.Item
                  name="externalApiFallbackEnabled"
                  label={
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <span>启用顺延机制</span>
                      <Tooltip title="当选中的源没有有效分集时（如只有预告片被过滤掉），自动尝试下一个候选源，提高导入成功率。关闭此选项时，将使用传统的单源选择模式。">
                        <QuestionCircleOutlined />
                      </Tooltip>
                    </div>
                  }
                  valuePropName="checked"
                  style={{ flex: 1 }}
                >
                  <Switch disabled={isFallbackDisabled} />
                </Form.Item>
              )
            }}
          </Form.Item>
        </div>

        <Form.Item
          noStyle
          shouldUpdate={(prevValues, currentValues) =>
            prevValues.matchFallbackEnabled !== currentValues.matchFallbackEnabled ||
            prevValues.searchFallbackEnabled !== currentValues.searchFallbackEnabled
          }
        >
          {({ getFieldValue }) => {
            const isTokenSelectionDisabled = !getFieldValue('matchFallbackEnabled') && !getFieldValue('searchFallbackEnabled')

            return (
              <Form.Item
                label={
                  <Space>
                    匹配后备Token授权
                    <Tooltip title="选择允许触发匹配后备功能的Token。如果不选择任何Token，则所有Token都可以触发后备功能。只有被选中的Token才能在匹配失败时自动触发后备搜索任务。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <div style={{
                  border: '1px solid #d9d9d9',
                  borderRadius: '6px',
                  padding: '12px',
                  minHeight: '120px',
                  backgroundColor: isTokenSelectionDisabled ? '#f5f5f5' : '#fafafa',
                  opacity: isTokenSelectionDisabled ? 0.6 : 1
                }}>
                  {tokenList.length === 0 ? (
                    <div style={{ textAlign: 'center', color: '#999', padding: '20px' }}>
                      暂无可用Token
                    </div>
                  ) : (
                    <Form.Item
                      name="matchFallbackTokens"
                      style={{ marginBottom: 0 }}
                    >
                      <Checkbox.Group
                        style={{ width: '100%' }}
                        disabled={isTokenSelectionDisabled}
                      >
                        <div style={{
                          display: 'flex',
                          flexDirection: 'row',
                          flexWrap: 'wrap',
                          gap: '8px'
                        }}>
                          {tokenList.map(token => (
                            <Checkbox
                              key={token.id}
                              value={token.id}
                              disabled={isTokenSelectionDisabled}
                              style={{
                                padding: '6px 12px',
                                border: '1px solid #e8e8e8',
                                borderRadius: '4px',
                                backgroundColor: '#fff',
                                margin: 0,
                                whiteSpace: 'nowrap'
                              }}
                            >
                              <span style={{ fontWeight: 'normal' }}>
                                {token.name}
                                <span style={{
                                  marginLeft: '8px',
                                  fontSize: '12px',
                                  color: token.isEnabled ? '#52c41a' : '#ff4d4f'
                                }}>
                                  ({token.isEnabled ? '启用' : '禁用'})
                                </span>
                              </span>
                            </Checkbox>
                          ))}
                        </div>
                      </Checkbox.Group>
                    </Form.Item>
                  )}
                  <div style={{ marginTop: '12px', textAlign: 'right' }}>
                    <Button
                      type="primary"
                      loading={tokensSaving}
                      onClick={handleTokensSave}
                      disabled={isTokenSelectionDisabled}
                    >
                      保存
                    </Button>
                  </div>
                </div>
              </Form.Item>
            )
          }}
        </Form.Item>

        <Form.Item
          label={
            <Space>
              匹配后备黑名单
              <Tooltip title="使用正则表达式过滤文件名，匹配的文件不会触发后备机制。例如：预告|广告|花絮 可以过滤包含这些关键词的文件。留空表示不过滤。">
                <QuestionCircleOutlined />
              </Tooltip>
            </Space>
          }
        >
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item
              name="matchFallbackBlacklist"
              style={{ flex: 1, marginBottom: 0 }}
            >
              <Input.TextArea
                placeholder="输入正则表达式，例如：预告|广告|花絮"
                rows={2}
                showCount
              />
            </Form.Item>
            <Button type="primary" loading={blacklistSaving} onClick={handleBlacklistSave}>
              保存
            </Button>
          </Space.Compact>
        </Form.Item>
      </Form>
    </Card>
  )
}