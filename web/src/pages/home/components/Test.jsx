import {
  getMatchTest,
  searchEpisodesTest,
  searchAnimeTest,
  getBangumiDetailTest,
  getCommentTest,
  getTokenList,
} from '../../../apis'
import { useState, useEffect } from 'react'
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Tabs,
  InputNumber,
  Select,
  Tag,
  Alert,
} from 'antd'

export const Test = () => {
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const [result, setResult] = useState(null)
  const [activeTab, setActiveTab] = useState('match')
  const [tokens, setTokens] = useState([])
  const [tokensLoading, setTokensLoading] = useState(false)

  // 加载 token 列表
  useEffect(() => {
    fetchTokens()
  }, [])

  const fetchTokens = async () => {
    try {
      setTokensLoading(true)
      const res = await getTokenList()
      // 只显示已启用且未过期的 token
      const now = new Date()
      const validTokens = (res?.data || []).filter(token => {
        if (!token.isEnabled) return false
        if (token.expiresAt && new Date(token.expiresAt) < now) return false
        return true
      })
      setTokens(validTokens)
    } catch (error) {
      console.error('获取 Token 列表失败:', error)
    } finally {
      setTokensLoading(false)
    }
  }

  // 测试配置：每个测试类型的配置
  const testConfigs = {
    match: {
      label: '文件名匹配',
      apiPath: '/api/v1/{token}/match',
      method: 'POST',
      handler: getMatchTest,
      fields: [
        {
          name: 'fileName',
          label: '文件名',
          apiParam: 'fileName',
          placeholder: '请输入要测试匹配的文件名',
          required: true,
          component: Input,
        },
      ],
      renderResult: data => {
        if (data?.isMatched) {
          return (
            <>
              <div className="font-bold text-green-600">[匹配成功]</div>
              {data.matches?.map((it, index) => (
                <div key={index} className="mt-2 p-2 bg-green-50 rounded">
                  <div>番剧: {it.animeTitle} (ID: {it.animeId})</div>
                  <div>分集: {it.episodeTitle} (ID: {it.episodeId})</div>
                  <div>类型: {it.typeDescription}</div>
                </div>
              ))}
            </>
          )
        }
        return <div className="text-red-600">[匹配失败] 未匹配到任何结果</div>
      },
    },
    searchEpisodes: {
      label: '搜索分集',
      apiPath: '/api/v1/{token}/search/episodes',
      method: 'GET',
      handler: searchEpisodesTest,
      fields: [
        {
          name: 'anime',
          label: '节目名称',
          apiParam: 'anime (query)',
          placeholder: '请输入节目名称',
          required: true,
          component: Input,
        },
        {
          name: 'episode',
          label: '分集标题',
          apiParam: 'episode (query)',
          placeholder: '请输入分集标题（可选）',
          required: false,
          component: Input,
        },
      ],
      renderResult: data => {
        if (data?.animes && data.animes.length > 0) {
          return (
            <>
              <div className="font-bold text-green-600">
                [搜索成功] 找到 {data.animes.length} 个结果
              </div>
              {data.animes.slice(0, 3).map((anime, index) => (
                <div key={index} className="mt-2 p-2 bg-blue-50 rounded">
                  <div>番剧: {anime.animeTitle} (ID: {anime.animeId})</div>
                  <div>类型: {anime.typeDescription}</div>
                  {anime.episodes && (
                    <div>分集数: {anime.episodes.length}</div>
                  )}
                </div>
              ))}
              {data.animes.length > 3 && (
                <div className="text-gray-500 mt-2">
                  ... 还有 {data.animes.length - 3} 个结果
                </div>
              )}
            </>
          )
        }
        return <div className="text-red-600">[搜索失败] 未找到结果</div>
      },
    },
    searchAnime: {
      label: '搜索作品',
      apiPath: '/api/v1/{token}/search/anime',
      method: 'GET',
      handler: searchAnimeTest,
      fields: [
        {
          name: 'keyword',
          label: '关键词',
          apiParam: 'keyword (query)',
          placeholder: '请输入搜索关键词',
          required: true,
          component: Input,
        },
      ],
      renderResult: data => {
        if (data?.animes && data.animes.length > 0) {
          return (
            <>
              <div className="font-bold text-green-600">
                [搜索成功] 找到 {data.animes.length} 个结果
              </div>
              {data.animes.slice(0, 3).map((anime, index) => (
                <div key={index} className="mt-2 p-2 bg-blue-50 rounded">
                  <div>番剧: {anime.animeTitle} (ID: {anime.animeId})</div>
                  <div>类型: {anime.typeDescription}</div>
                  <div>分集数: {anime.episodeCount || 0}</div>
                </div>
              ))}
              {data.animes.length > 3 && (
                <div className="text-gray-500 mt-2">
                  ... 还有 {data.animes.length - 3} 个结果
                </div>
              )}
            </>
          )
        }
        return <div className="text-red-600">[搜索失败] 未找到结果</div>
      },
    },
    bangumiDetail: {
      label: '番剧详情',
      apiPath: '/api/v1/{token}/bangumi/{id}',
      method: 'GET',
      handler: getBangumiDetailTest,
      fields: [
        {
          name: 'bangumiId',
          label: '番剧ID',
          apiParam: 'id (path)',
          placeholder: '请输入番剧ID',
          required: true,
          component: InputNumber,
          componentProps: { className: 'w-full' },
        },
      ],
      renderResult: data => {
        if (data?.bangumi) {
          const bangumi = data.bangumi
          return (
            <div className="font-bold text-green-600">
              <div>[查询成功]</div>
              <div className="mt-2 p-2 bg-blue-50 rounded font-normal">
                <div>标题: {bangumi.animeTitle}</div>
                <div>类型: {bangumi.typeDescription}</div>
              </div>
            </div>
          )
        }
        return (
          <div className="text-red-600">
            [查询失败] {data?.errorMessage || '未找到番剧详情'}
          </div>
        )
      },
    },
    comment: {
      label: '弹幕获取',
      apiPath: '/api/v1/{token}/comment/{episodeId}',
      method: 'GET',
      handler: getCommentTest,
      fields: [
        {
          name: 'episodeId',
          label: '分集ID',
          apiParam: 'episodeId (path)',
          placeholder: '请输入分集ID',
          required: true,
          component: InputNumber,
          componentProps: { className: 'w-full' },
        },
      ],
      renderResult: data => {
        if (data?.comments && data.comments.length > 0) {
          return (
            <>
              <div className="font-bold text-green-600">
                [获取成功] 共 {data.count || data.comments.length} 条弹幕
              </div>
              <div className="mt-2 p-2 bg-purple-50 rounded">
                <div>显示前 5 条:</div>
                {data.comments.slice(0, 5).map((comment, index) => (
                  <div key={index} className="text-sm mt-1">
                    [{comment.p}] {comment.m}
                  </div>
                ))}
              </div>
            </>
          )
        }
        return <div className="text-red-600">[获取失败] 未找到弹幕</div>
      },
    },
  }

  const handleTest = async values => {
    try {
      setLoading(true)
      setResult(null)

      const config = testConfigs[activeTab]
      const res = await config.handler({ apiToken: values.apiToken, ...values })
      console.log('测试结果:', res)

      setResult(res?.data || res)
    } catch (error) {
      console.error('测试错误:', error)
      setResult({
        error: true,
        message: error?.detail || error?.message || JSON.stringify(error),
      })
    } finally {
      setLoading(false)
    }
  }

  const currentConfig = testConfigs[activeTab]

  return (
    <div className="my-4">
      <Card title="API 接口测试">
        <Tabs
          activeKey={activeTab}
          onChange={key => {
            setActiveTab(key)
            form.resetFields()
            setResult(null)
          }}
          items={Object.entries(testConfigs).map(([key, config]) => ({
            key,
            label: config.label,
          }))}
        />

        <Row gutter={24} className="mt-4">
          <Col md={12} sm={24}>
            {/* 接口信息展示 */}
            <Alert
              message={
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Tag color="blue">{currentConfig.method}</Tag>
                    <code className="text-sm bg-gray-100 px-2 py-1 rounded">
                      {currentConfig.apiPath}
                    </code>
                  </div>
                  {currentConfig.fields.length > 0 && (
                    <div className="text-xs text-gray-600">
                      <div className="font-semibold mb-1">参数说明:</div>
                      <div className="pl-2">
                        {currentConfig.fields.map(field => (
                          <div key={field.name} className="mb-1">
                            <span className="font-mono text-blue-600">
                              {field.label}
                            </span>
                            {' → '}
                            <span className="text-gray-500">
                              {field.apiParam || field.name}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              }
              type="info"
              className="mb-4"
            />

            <Form
              form={form}
              layout="vertical"
              onFinish={handleTest}
              className="px-6 pb-6"
            >
              {/* Token选择（所有测试都需要） */}
              <Form.Item
                name="apiToken"
                label={
                  <div className="flex items-center justify-between w-full">
                    <div className="flex items-center gap-2">
                      <span>弹幕 Token</span>
                      <span className="text-xs text-gray-400 font-normal">
                        (token path)
                      </span>
                    </div>
                    <Button
                      type="link"
                      size="small"
                      onClick={fetchTokens}
                      loading={tokensLoading}
                      className="p-0 h-auto"
                    >
                      刷新
                    </Button>
                  </div>
                }
                rules={[{ required: true, message: '请选择弹幕token' }]}
              >
                <Select
                  placeholder={
                    tokens.length === 0
                      ? '暂无可用 Token，请先创建'
                      : '请选择弹幕token'
                  }
                  loading={tokensLoading}
                  showSearch
                  optionFilterProp="searchLabel"
                  disabled={tokens.length === 0}
                  notFoundContent={
                    <div className="text-center p-4 text-gray-400">
                      暂无可用 Token
                      <br />
                      <span className="text-xs">
                        请在 Token 管理页面创建
                      </span>
                    </div>
                  }
                  options={tokens.map(token => ({
                    value: token.token,
                    searchLabel: token.name,
                    label: (
                      <div className="flex items-center justify-between">
                        <div className="flex flex-col">
                          <span>{token.name}</span>
                          {token.expiresAt && (
                            <span className="text-xs text-gray-400">
                              到期: {new Date(token.expiresAt).toLocaleDateString()}
                            </span>
                          )}
                        </div>
                        <Tag color="blue" className="ml-2 text-xs">
                          {token.dailyCallCount || 0}/
                          {token.dailyCallLimit === -1
                            ? '∞'
                            : token.dailyCallLimit}
                        </Tag>
                      </div>
                    ),
                  }))}
                />
              </Form.Item>

              {/* 动态字段 */}
              {currentConfig.fields.map(field => {
                const Component = field.component
                return (
                  <Form.Item
                    key={field.name}
                    name={field.name}
                    label={
                      <div className="flex items-center gap-2">
                        <span>{field.label}</span>
                        {field.apiParam && (
                          <span className="text-xs text-gray-400 font-normal">
                            ({field.apiParam})
                          </span>
                        )}
                      </div>
                    }
                    rules={[
                      {
                        required: field.required,
                        message: `请输入${field.label}`,
                      },
                    ]}
                  >
                    <Component
                      placeholder={field.placeholder}
                      {...(field.componentProps || {})}
                    />
                  </Form.Item>
                )
              })}

              {/* 测试按钮 */}
              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={loading}
                  className="w-full h-11 text-base font-medium rounded-lg bg-primary hover:bg-primary/90 transition-all duration-300 transform hover:scale-[1.02] active:scale-[0.98]"
                >
                  测试
                </Button>
              </Form.Item>
            </Form>
          </Col>

          <Col md={12} sm={24}>
            <div className="px-6">
              <div className="text-sm text-gray-500 mb-2">测试结果:</div>
              <div className="max-h-[400px] overflow-y-auto p-4 bg-gray-50 rounded">
                {result ? (
                  result.error ? (
                    <div className="text-red-600">
                      <div className="font-bold">[错误]</div>
                      <div className="mt-2">{result.message}</div>
                    </div>
                  ) : (
                    currentConfig.renderResult(result)
                  )
                ) : (
                  <div className="text-gray-400">
                    测试结果将显示在这里。
                  </div>
                )}
              </div>
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  )
}

