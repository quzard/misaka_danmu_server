import { Card, Form, Switch, Input, Button, Space, Tooltip, Checkbox } from 'antd'
import { useEffect, useState } from 'react'
import { getMatchFallback, setMatchFallback, getMatchFallbackBlacklist, setMatchFallbackBlacklist, getMatchFallbackTokens, setMatchFallbackTokens, getTokenList, getSearchFallback, setSearchFallback, getConfig, setConfig } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../../store'

export const MatchFallbackSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [blacklistSaving, setBlacklistSaving] = useState(false)
  const [tokensSaving, setTokensSaving] = useState(false)
  const [tokenList, setTokenList] = useState([])
  const messageApi = useMessage()
  const isMobile = useAtomValue(isMobileAtom)

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const [fallbackRes, blacklistRes, tokensRes, tokenListRes, searchFallbackRes, externalApiFallbackRes, preDownloadRes] = await Promise.all([
        getMatchFallback(),
        getMatchFallbackBlacklist(),
        getMatchFallbackTokens(),
        getTokenList(),
        getSearchFallback(),
        getConfig('externalApiFallbackEnabled'),
        getConfig('preDownloadNextEpisodeEnabled')
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
        externalApiFallbackEnabled: externalApiFallbackRes.data?.value === 'true',
        preDownloadNextEpisodeEnabled: preDownloadRes.data?.value === 'true'
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
      if ('preDownloadNextEpisodeEnabled' in changedValues) {
        await setConfig('preDownloadNextEpisodeEnabled', String(changedValues.preDownloadNextEpisodeEnabled))
        messageApi.success('预下载设置已保存')
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
          preDownloadNextEpisodeEnabled: false,
          matchFallbackBlacklist: '',
          matchFallbackTokens: []
        }}
      >
        <div className={isMobile ? "space-y-4" : ""} style={isMobile ? {} : { display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
          {isMobile ? (
            <>
              <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start', marginBottom: '16px' }}>
                <Form.Item
                  name="matchFallbackEnabled"
                  label="启用后备匹配"
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
              </div>

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
                    <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
                      <Form.Item
                        name="externalApiFallbackEnabled"
                        label={
                          <div className="flex items-center gap-2">
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

                      <Form.Item
                        name="preDownloadNextEpisodeEnabled"
                        label={
                          <div className="flex items-center gap-2">
                            <span>启用预下载</span>
                            <Tooltip title="启用后，当播放当前集时，系统会自动在后台下载下一集的弹幕（如果下一集存在且没有弹幕）。需要启用匹配后备或后备搜索。">
                              <QuestionCircleOutlined />
                            </Tooltip>
                          </div>
                        }
                        valuePropName="checked"
                        style={{ flex: 1 }}
                      >
                        <Switch disabled={isFallbackDisabled} />
                      </Form.Item>
                    </div>
                  )
                }}
              </Form.Item>
            </>
          ) : (
            <>
              <Form.Item
                name="matchFallbackEnabled"
                label="启用匹配后备"
                valuePropName="checked"
                tooltip="启用后，当播放客户端尝试使用match接口时，接口在本地库中找不到任何结果时，系统将自动触发一个后台任务，尝试从全网搜索并导入对应的弹幕。"
                style={isMobile ? {} : { flex: 1 }}
              >
                <Switch />
              </Form.Item>

              <Form.Item
                name="searchFallbackEnabled"
                label="启用后备搜索"
                valuePropName="checked"
                tooltip="启用后，当使用search/anime接口搜索时，如果本地库中没有结果，系统将自动触发全网搜索并返回搜索结果。用户可以直接选择搜索结果进行下载。"
                style={isMobile ? {} : { flex: 1 }}
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
                        <div className="flex items-center gap-2">
                          <span>启用顺延机制</span>
                          <Tooltip title="当选中的源没有有效分集时（如只有预告片被过滤掉），自动尝试下一个候选源，提高导入成功率。关闭此选项时，将使用传统的单源选择模式。">
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                      }
                      valuePropName="checked"
                      style={isMobile ? {} : { flex: 1 }}
                    >
                      <Switch disabled={isFallbackDisabled} />
                    </Form.Item>
                  )
                }}
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
                      name="preDownloadNextEpisodeEnabled"
                      label={
                        <div className="flex items-center gap-2">
                          <span>启用预下载</span>
                          <Tooltip title="启用后，当播放当前集时，系统会自动在后台下载下一集的弹幕（如果下一集存在且没有弹幕）。需要启用匹配后备或后备搜索。">
                            <QuestionCircleOutlined />
                          </Tooltip>
                        </div>
                      }
                      valuePropName="checked"
                      style={isMobile ? {} : { flex: 1 }}
                    >
                      <Switch disabled={isFallbackDisabled} />
                    </Form.Item>
                  )
                }}
              </Form.Item>

            </>
          )}
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
                    后备功能 Token 授权
                    <Tooltip title="选择允许触发匹配后备功能的Token。如果不选择任何Token，则所有Token都可以触发后备功能。只有被选中的Token才能在匹配失败时自动触发后备搜索任务。">
                      <QuestionCircleOutlined />
                    </Tooltip>
                  </Space>
                }
              >
                <Card
                  size="small"
                  className={`transition-all duration-200 ${
                    isTokenSelectionDisabled
                      ? 'bg-gray-50 border-gray-200 opacity-60'
                      : 'bg-gradient-to-br from-blue-50 to-indigo-50 border-blue-200 shadow-sm hover:shadow-md'
                  }`}
                  bodyStyle={{ padding: '16px' }}
                >
                  {tokenList.length === 0 ? (
                    <div className="text-center py-8 text-gray-500">
                      <div className="text-lg mb-2">📝</div>
                      <div>暂无可用Token</div>
                      <div className="text-sm mt-1">请先创建API Token</div>
                    </div>
                  ) : (
                    <>
                      <Form.Item
                        name="matchFallbackTokens"
                        style={{ marginBottom: 0 }}
                      >
                        <Checkbox.Group
                          style={{ width: '100%' }}
                          disabled={isTokenSelectionDisabled}
                        >
                          <div className={`grid gap-3 ${
                            isMobile ? 'grid-cols-1' : 'grid-cols-2 md:grid-cols-3'
                          }`}>
                            {tokenList.map(token => (
                              <div
                                key={token.id}
                                className={`
                                  relative p-3 rounded-lg border transition-all duration-200 cursor-pointer
                                  ${isTokenSelectionDisabled
                                    ? 'bg-gray-100 border-gray-200 cursor-not-allowed'
                                    : 'bg-white border-gray-200 hover:border-blue-300 hover:shadow-sm'
                                  }
                                `}
                              >
                                <Checkbox
                                  value={token.id}
                                  disabled={isTokenSelectionDisabled}
                                  className="absolute top-2 right-2"
                                />
                                <div className="pr-6">
                                  <div className="font-medium text-gray-900 mb-1">
                                    {token.name}
                                  </div>
                                  <div className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                                    token.isEnabled
                                      ? 'bg-green-100 text-green-800'
                                      : 'bg-red-100 text-red-800'
                                  }`}>
                                    <span className={`w-1.5 h-1.5 rounded-full mr-1.5 ${
                                      token.isEnabled ? 'bg-green-500' : 'bg-red-500'
                                    }`}></span>
                                    {token.isEnabled ? '启用' : '禁用'}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </Checkbox.Group>
                      </Form.Item>
                      <div className="mt-4 pt-4 border-t border-gray-200 flex justify-end">
                        <Button
                          type="primary"
                          loading={tokensSaving}
                          onClick={handleTokensSave}
                          disabled={isTokenSelectionDisabled}
                          className="min-w-[100px]"
                        >
                          保存配置
                        </Button>
                      </div>
                    </>
                  )}
                </Card>
              </Form.Item>
            )
          }}
        </Form.Item>

        <Form.Item
          label={
            <Space>
              后备匹配黑名单
              <Tooltip title="使用正则表达式过滤文件名，匹配的文件不会触发后备机制。例如：预告|广告|花絮 可以过滤包含这些关键词的文件。留空表示不过滤。">
                <QuestionCircleOutlined />
              </Tooltip>
            </Space>
          }
        >
          <div className={isMobile ? "space-y-3" : "flex gap-3"}>
            <Form.Item
              name="matchFallbackBlacklist"
              className={isMobile ? "mb-0" : "flex-1 mb-0"}
            >
              <Input.TextArea
                placeholder="输入正则表达式，例如：预告|广告|花絮"
                rows={isMobile ? 3 : 1}
                className="resize-none"
              />
            </Form.Item>
            <Button
              type="primary"
              loading={blacklistSaving}
              onClick={handleBlacklistSave}
              className={isMobile ? "w-full" : ""}
              style={isMobile ? {} : { height: '32px', minHeight: '32px', minWidth: '100px' }}
            >
              保存黑名单
            </Button>
          </div>
        </Form.Item>
      </Form>
    </Card>
  )
}