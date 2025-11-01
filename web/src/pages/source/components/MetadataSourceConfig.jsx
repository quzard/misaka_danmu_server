/**
 * 元信息搜索源特定配置组件
 * 根据不同的源类型显示不同的配置表单
 */
import { Form, Input, Switch, Button, Alert, Space, Typography, Divider } from 'antd'
import { useState, useEffect } from 'react'
import {
  EyeInvisibleOutlined,
  EyeOutlined,
  LockOutlined,
  QuestionCircleOutlined,
  KeyOutlined,
} from '@ant-design/icons'
import {
  getBangumiConfig,
  setBangumiConfig,
  getBangumiAuth,
  getBangumiAuthUrl,
  logoutBangumiAuth,
  getTmdbConfig,
  setTmdbConfig,
  getTvdbConfig,
  setTvdbConfig,
  getDoubanConfig,
  setDoubanConfig,
} from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { useModal } from '../../../ModalContext'
import dayjs from 'dayjs'

const { Text, Link } = Typography

/**
 * Bangumi 配置组件
 */
export function BangumiConfig({ form }) {
  const { showMessage } = useMessage()
  const { showModal } = useModal()
  const [authMethod, setAuthMethod] = useState('token')
  const [authStatus, setAuthStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [showToken, setShowToken] = useState(false)

  // 加载配置
  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const config = await getBangumiConfig()
      form.setFieldsValue({
        bangumiAccessToken: config.bangumiAccessToken || '',
        bangumiUseProxy: config.bangumiUseProxy || false,
      })
      setAuthMethod(config.bangumiAuthMethod || 'token')

      // 如果使用 OAuth,检查授权状态
      if (config.bangumiAuthMethod === 'oauth') {
        checkAuthStatus()
      }
    } catch (error) {
      console.error('加载 Bangumi 配置失败:', error)
    }
  }

  const checkAuthStatus = async () => {
    try {
      const status = await getBangumiAuth()
      setAuthStatus(status)
    } catch (error) {
      console.error('检查 Bangumi 授权状态失败:', error)
    }
  }

  const handleAuthMethodChange = async (method) => {
    setAuthMethod(method)
    try {
      await setBangumiConfig({ bangumiAuthMethod: method })
      if (method === 'oauth') {
        checkAuthStatus()
      }
    } catch (error) {
      showMessage('error', '切换认证方式失败')
    }
  }

  const handleOAuthLogin = async () => {
    try {
      const { authUrl } = await getBangumiAuthUrl()
      window.open(authUrl, '_blank')
      showMessage('info', '请在新窗口中完成授权，授权完成后点击"检查授权状态"')
    } catch (error) {
      showMessage('error', '获取授权链接失败')
    }
  }

  const handleLogout = async () => {
    showModal({
      title: '确认退出登录',
      content: '确定要退出 Bangumi 登录吗？',
      onOk: async () => {
        try {
          await logoutBangumiAuth()
          setAuthStatus(null)
          showMessage('success', '已退出登录')
        } catch (error) {
          showMessage('error', '退出登录失败')
        }
      },
    })
  }

  return (
    <div className="space-y-4">
      <Alert
        message="Bangumi 配置"
        description="Bangumi 是一个动画、漫画、游戏等 ACG 作品的数据库，可以提供作品的元数据信息。"
        type="info"
        showIcon
      />

      {/* 认证方式选择 */}
      <div>
        <Text strong>认证方式:</Text>
        <div className="mt-2 space-x-4">
          <Button
            type={authMethod === 'token' ? 'primary' : 'default'}
            onClick={() => handleAuthMethodChange('token')}
          >
            Access Token
          </Button>
          <Button
            type={authMethod === 'oauth' ? 'primary' : 'default'}
            onClick={() => handleAuthMethodChange('oauth')}
          >
            OAuth 授权
          </Button>
        </div>
      </div>

      <Divider />

      {/* Access Token 方式 */}
      {authMethod === 'token' && (
        <>
          <Form.Item
            name="bangumiAccessToken"
            label={
              <span>
                Access Token{' '}
                <a
                  href="https://bgm.tv/dev/app"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <QuestionCircleOutlined />
                </a>
              </span>
            }
            rules={[{ required: true, message: '请输入 Bangumi Access Token' }]}
          >
            <Input.Password
              placeholder="请输入 Bangumi Access Token"
              iconRender={(visible) =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
              visibilityToggle={{
                visible: showToken,
                onVisibleChange: setShowToken,
              }}
            />
          </Form.Item>
          <div className="text-gray-500 text-sm -mt-2">
            在{' '}
            <a
              href="https://bgm.tv/dev/app"
              target="_blank"
              rel="noopener noreferrer"
            >
              Bangumi 开发者中心
            </a>{' '}
            创建应用后获取 Access Token
          </div>
        </>
      )}

      {/* OAuth 方式 */}
      {authMethod === 'oauth' && (
        <div className="space-y-4">
          {authStatus?.isAuthorized ? (
            <Alert
              message="已授权"
              description={
                <div>
                  <div>用户: {authStatus.username}</div>
                  <div>授权时间: {dayjs(authStatus.authorizedAt).format('YYYY-MM-DD HH:mm:ss')}</div>
                  <div className="mt-2">
                    <Button size="small" onClick={handleLogout}>
                      退出登录
                    </Button>
                  </div>
                </div>
              }
              type="success"
              showIcon
            />
          ) : (
            <Alert
              message="未授权"
              description={
                <div>
                  <div className="mb-2">请点击下方按钮进行 OAuth 授权</div>
                  <Space>
                    <Button type="primary" onClick={handleOAuthLogin}>
                      <LockOutlined /> 授权登录
                    </Button>
                    <Button onClick={checkAuthStatus}>检查授权状态</Button>
                  </Space>
                </div>
              }
              type="warning"
              showIcon
            />
          )}
        </div>
      )}

      <Divider />

      {/* 代理设置 */}
      <Form.Item
        name="bangumiUseProxy"
        label="使用代理"
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>
      <div className="text-gray-500 text-sm -mt-2">
        启用后，Bangumi API 请求将通过全局代理服务器进行
      </div>
    </div>
  )
}

/**
 * TMDB 配置组件
 */
export function TMDBConfig({ form }) {
  const { showMessage } = useMessage()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const config = await getTmdbConfig()
      form.setFieldsValue({
        tmdbApiKey: config.tmdbApiKey || '',
        tmdbApiDomain: config.tmdbApiDomain || 'https://api.themoviedb.org',
        tmdbImageDomain: config.tmdbImageDomain || 'https://image.tmdb.org',
      })
    } catch (error) {
      console.error('加载 TMDB 配置失败:', error)
    }
  }

  return (
    <div className="space-y-4">
      <Alert
        message="TMDB 配置"
        description="The Movie Database (TMDB) 是一个电影和电视节目的数据库，可以提供作品的元数据信息。"
        type="info"
        showIcon
      />

      <Form.Item
        name="tmdbApiKey"
        label={
          <span>
            API Key{' '}
            <a
              href="https://www.themoviedb.org/settings/api"
              target="_blank"
              rel="noopener noreferrer"
            >
              <QuestionCircleOutlined />
            </a>
          </span>
        }
        rules={[{ required: true, message: '请输入 TMDB API Key' }]}
      >
        <Input.Password
          placeholder="请输入 TMDB API Key"
          prefix={<KeyOutlined />}
        />
      </Form.Item>
      <div className="text-gray-500 text-sm -mt-2">
        在{' '}
        <a
          href="https://www.themoviedb.org/settings/api"
          target="_blank"
          rel="noopener noreferrer"
        >
          TMDB 设置页面
        </a>{' '}
        获取 API Key
      </div>

      <Form.Item
        name="tmdbApiDomain"
        label="API 域名"
        rules={[{ required: true, message: '请输入 TMDB API 域名' }]}
      >
        <Input placeholder="https://api.themoviedb.org" />
      </Form.Item>

      <Form.Item
        name="tmdbImageDomain"
        label="图片域名"
        rules={[{ required: true, message: '请输入 TMDB 图片域名' }]}
      >
        <Input placeholder="https://image.tmdb.org" />
      </Form.Item>
    </div>
  )
}

/**
 * TVDB 配置组件
 */
export function TVDBConfig({ form }) {
  const { showMessage } = useMessage()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const config = await getTvdbConfig()
      form.setFieldsValue({
        tvdbApiKey: config.tvdbApiKey || '',
      })
    } catch (error) {
      console.error('加载 TVDB 配置失败:', error)
    }
  }

  return (
    <div className="space-y-4">
      <Alert
        message="TVDB 配置"
        description="The TVDB 是一个电视节目的数据库，可以提供电视节目的元数据信息。"
        type="info"
        showIcon
      />

      <Form.Item
        name="tvdbApiKey"
        label={
          <span>
            API Key{' '}
            <a
              href="https://thetvdb.com/dashboard/account/apikeys"
              target="_blank"
              rel="noopener noreferrer"
            >
              <QuestionCircleOutlined />
            </a>
          </span>
        }
        rules={[{ required: true, message: '请输入 TVDB API Key' }]}
      >
        <Input.Password
          placeholder="请输入 TVDB API Key"
          prefix={<KeyOutlined />}
        />
      </Form.Item>
      <div className="text-gray-500 text-sm -mt-2">
        在{' '}
        <a
          href="https://thetvdb.com/dashboard/account/apikeys"
          target="_blank"
          rel="noopener noreferrer"
        >
          TVDB API Keys 页面
        </a>{' '}
        获取 API Key
      </div>
    </div>
  )
}

/**
 * 豆瓣配置组件
 */
export function DoubanConfig({ form }) {
  const { showMessage } = useMessage()

  useEffect(() => {
    loadConfig()
  }, [])

  const loadConfig = async () => {
    try {
      const config = await getDoubanConfig()
      form.setFieldsValue({
        doubanCookie: config.doubanCookie || '',
      })
    } catch (error) {
      console.error('加载豆瓣配置失败:', error)
    }
  }

  return (
    <div className="space-y-4">
      <Alert
        message="豆瓣配置"
        description="豆瓣是一个提供书籍、电影、音乐等作品信息的社区网站，可以提供作品的元数据信息。"
        type="info"
        showIcon
      />

      <Form.Item
        name="doubanCookie"
        label="Cookie"
        rules={[{ required: true, message: '请输入豆瓣 Cookie' }]}
      >
        <Input.TextArea
          placeholder="请输入豆瓣 Cookie"
          rows={4}
        />
      </Form.Item>
      <div className="text-gray-500 text-sm -mt-2">
        <div>在浏览器中登录豆瓣后，打开开发者工具 (F12)，在 Network 标签页中找到任意请求，复制 Cookie 值</div>
        <div className="mt-1">Cookie 格式示例: bid=xxx; dbcl2=xxx; ...</div>
      </div>
    </div>
  )
}

