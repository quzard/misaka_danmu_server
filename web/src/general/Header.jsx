import { useEffect, useMemo, useState } from 'react'
import { RoutePaths } from './RoutePaths.jsx'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAtom, useAtomValue } from 'jotai'
import { isMobileAtom, userinfoAtom } from '../../store/index.js'
import DarkModeToggle from '@/components/DarkModeToggle.jsx';
import { MyIcon } from '@/components/MyIcon'
import classNames from 'classnames'
import { Tag, Dropdown, Modal, Form, Input, Button, Space } from 'antd';
import { logout, changePassword } from '../apis/index.js'
import Cookies from 'js-cookie'
import { EyeInvisibleOutlined, EyeOutlined, LockOutlined } from '@ant-design/icons'
import { useMessage } from '../MessageContext'
import {
  useFloating,
  autoUpdate,
  offset,
  flip,
  shift,
  useInteractions,
  useClick,
  useDismiss,
  FloatingPortal,
} from '@floating-ui/react'

const navItems = [
  { key: RoutePaths.HOME, label: '首页', icon: 'home' },
  { key: RoutePaths.LIBRARY, label: '弹幕库', icon: 'tvlibrary' },
  { key: RoutePaths.TASK, label: '任务管理器', icon: 'renwu' },
  { key: RoutePaths.BULLET, label: '弹幕', icon: 'danmu' },
  { key: RoutePaths.MEDIA_FETCH, label: '媒体获取', icon: 'movie' },
  { key: RoutePaths.SOURCE, label: '搜索源', icon: 'search' },
  { key: RoutePaths.CONTROL, label: '外部控制', icon: 'controlapi' },
  { key: RoutePaths.SETTING, label: '设置', icon: 'setting' },
]
import { getVersion } from '../apis/index.js';

const FloatingMenu = ({ trigger, items, onItemClick, activeKey }) => {
  const [isOpen, setIsOpen] = useState(false)

  const { refs, floatingStyles, context } = useFloating({
    open: isOpen,
    onOpenChange: setIsOpen,
    placement: 'top', // 强制向上展开
    middleware: [
      offset(8),
      shift({ padding: 8 }),
    ],
    whileElementsMounted: autoUpdate,
  })

  const click = useClick(context)
  const dismiss = useDismiss(context)
  const { getReferenceProps, getFloatingProps } = useInteractions([click, dismiss])

  return (
    <>
      <div
        ref={refs.setReference}
        {...getReferenceProps()}
        className="flex-1"
      >
        {trigger}
      </div>
      <FloatingPortal>
        {isOpen && (
          <div
            ref={refs.setFloating}
            style={floatingStyles}
            {...getFloatingProps()}
            className="z-[1000]"
          >
            <div className="space-y-2 bg-base-card backdrop-blur-sm rounded-lg shadow-xl border border-gray-200/50 dark:border-gray-800/30 p-2">
              {items.map((item, index) => (
                <button
                  key={item.key}
                  onClick={() => {
                    onItemClick?.(item)
                    setIsOpen(false)
                  }}
                  className={classNames(
                    'block w-full px-4 py-2 rounded-md transition-all duration-200 text-sm font-medium text-left',
                    activeKey === item.key
                      ? 'bg-primary text-white shadow-sm'
                      : 'text-base-text hover:bg-base-hover'
                  )}
                  style={{
                    animationDelay: `${index * 50}ms`
                  }}
                >
                  <div className="flex items-center justify-start gap-2">
                    <MyIcon icon={item.icon} size={20} />
                    <div>{item.label}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </FloatingPortal>
    </>
  )
}

export const Header = () => {
  const [isMobile, setIsMobile] = useAtom(isMobileAtom)
  const location = useLocation()
  const navigate = useNavigate()
  const [version, setVersion] = useState('N/A');
  console.log(location)

  const activeKey = useMemo(() => {
    if (location.pathname === '/') return RoutePaths.HOME
    return (
      navItems.filter(item => {
        return location.pathname?.includes(item.key) && item.key !== '/'
      })?.[0]?.key || RoutePaths.HOME
    )
  }, [location, navItems])

  useEffect(() => {
    const fetchVersion = async () => {
      const res = await getVersion();
      setVersion(`v${res.data.version}`);
    };
    fetchVersion();
  }, []);
  useEffect(() => {
    const checkScreenSize = () => {
      setIsMobile(window.innerWidth <= 768)
    }
    checkScreenSize()
    window.addEventListener('resize', checkScreenSize)
    return () => {
      window.removeEventListener('resize', checkScreenSize)
    }
  }, [])

  return (
    <>
      {isMobile ? (
        <>
          <div className="fixed top-0 left-0 w-full z-50 py-2 bg-base-bg">
            <div className="flex justify-start items-center px-4 md:px-8">
              <div onClick={() => navigate(RoutePaths.HOME)}>
                <img src="/images/logo.png" className="h-12 cursor-pointer" />
              </div>
              <div className="flex items-center justify-center gap-2 ml-auto">
                <Tag>{version}</Tag>
                <DarkModeToggle />
              </div>
            </div>
          </div>
          <MobileHeader activeKey={activeKey} />
        </>
      ) : (
        <DesktopHeader activeKey={activeKey} version={version} />
      )}
    </>
  )
}

const MobileHeader = ({ activeKey }) => {
  const mobileNavItems = [
    ...navItems.slice(0, 3), // 首页、弹幕库、任务管理器直接显示
    { key: 'user', label: '我的', icon: 'user', children: navItems.slice(3) }, // 其余的放在"我的"菜单下
  ]
  const navigate = useNavigate()
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false)
  const [passwordForm] = Form.useForm()
  const [passwordLoading, setPasswordLoading] = useState(false)
  const [currentPasswordVisible, setCurrentPasswordVisible] = useState(false)
  const [newPasswordVisible, setNewPasswordVisible] = useState(false)
  const [confirmPasswordVisible, setConfirmPasswordVisible] = useState(false)
  const { showMessage } = useMessage()

  const onLogout = async () => {
    await logout()
    Cookies.remove('danmu_token', { path: '/' })
    navigate(RoutePaths.LOGIN)
  }

  const handleChangePassword = async (values) => {
    try {
      setPasswordLoading(true)
      await changePassword(values)
      showMessage('success', '密码修改成功')
      setIsPasswordModalOpen(false)
      passwordForm.resetFields()
    } catch (error) {
      showMessage('error', error.response?.data?.detail || '密码修改失败')
    } finally {
      setPasswordLoading(false)
    }
  }

  const handleMenuItemClick = (item) => {
    if (item.key === 'logout') {
      onLogout()
    } else if (item.key === 'change-password') {
      setIsPasswordModalOpen(true)
    } else {
      navigate(item.key)
    }
  }

  // 计算"我的"菜单的显示标签
  const userMenuItem = mobileNavItems.find(it => it.key === 'user')
  const activeChildItem = userMenuItem?.children?.find(child => child.key === activeKey)
  const userMenuLabel = activeChildItem ? activeChildItem.label : '我的'

  return (
    <>
      <div className="fixed bottom-0 left-0 w-full shadow-box z-50 py-2 overflow-hidden bg-base-bg">
        <div className="flex justify-evenly items-center">
          {mobileNavItems.map(it => (
            <>
              {!it.children?.length ? (
                <div
                  key={it.key}
                  className={classNames(
                    'text-center flex-1',
                    it.key === activeKey && 'text-primary'
                  )}
                  onClick={() => {
                    navigate(it.key)
                  }}
                >
                  <div>
                    <MyIcon icon={it.icon} size={26} />
                  </div>
                  <div className="text-xs">{it.label}</div>
                </div>
              ) : (
                <FloatingMenu
                  key={it.key}
                  trigger={
                    <div
                      className={classNames(
                        'text-center flex-1',
                        it.children.map(o => o.key).includes(activeKey) &&
                          'text-primary'
                      )}
                    >
                      <div>
                        <MyIcon icon={it.icon} size={26} />
                      </div>
                      <div className="text-xs">{userMenuLabel}</div>
                    </div>
                  }
                  items={[
                    ...it.children.map(o => ({
                      key: o.key,
                      label: o.label,
                      icon: o.icon,
                    })),
                    {
                      key: 'change-password',
                      label: '修改密码',
                      icon: 'key',
                    },
                    {
                      key: 'logout',
                      label: '退出登录',
                      icon: 'user',
                    },
                  ]}
                  onItemClick={handleMenuItemClick}
                  activeKey={activeKey}
                />
              )}
            </>
          ))}
        </div>
      </div>

      {/* 修改密码弹框 */}
      <Modal
        title="修改密码"
        open={isPasswordModalOpen}
        onCancel={() => {
          setIsPasswordModalOpen(false)
          passwordForm.resetFields()
        }}
        footer={null}
        width={500}
      >
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={handleChangePassword}
        >
          <Form.Item
            name="currentPassword"
            label="当前密码"
            rules={[{ required: true, message: '请输入当前密码' }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入当前密码"
              iconRender={(visible) =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
              visibilityToggle={{
                visible: currentPasswordVisible,
                onVisibleChange: setCurrentPasswordVisible,
              }}
            />
          </Form.Item>

          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 6, message: '密码长度至少6位' },
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请输入新密码"
              iconRender={(visible) =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
              visibilityToggle={{
                visible: newPasswordVisible,
                onVisibleChange: setNewPasswordVisible,
              }}
            />
          </Form.Item>

          <Form.Item
            name="confirmPassword"
            label="确认新密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请确认新密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) {
                    return Promise.resolve()
                  }
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              }),
            ]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="请再次输入新密码"
              iconRender={(visible) =>
                visible ? <EyeOutlined /> : <EyeInvisibleOutlined />
              }
              visibilityToggle={{
                visible: confirmPasswordVisible,
                onVisibleChange: setConfirmPasswordVisible,
              }}
            />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button
                onClick={() => {
                  setIsPasswordModalOpen(false)
                  passwordForm.resetFields()
                }}
              >
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={passwordLoading}>
                确认修改
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

const DesktopHeader = ({ activeKey, version }) => {
  const navigate = useNavigate()
  const userinfo = useAtomValue(userinfoAtom)
  const messageApi = useMessage()
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [showPassword1, setShowPassword1] = useState(false)
  const [showPassword2, setShowPassword2] = useState(false)
  const [showPassword3, setShowPassword3] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const onLogout = async () => {
    await logout()
    Cookies.remove('danmu_token', { path: '/' })
    navigate(RoutePaths.LOGIN)
  }

  const handleChangePassword = async () => {
    try {
      setIsLoading(true)
      const values = await form.validateFields()
      await changePassword(values)
      form.resetFields()
      messageApi.success('修改成功')
      setIsPasswordModalOpen(false)
    } catch (error) {
      messageApi.error('修改失败')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <>
      <div className="fixed top-0 left-0 w-full shadow-box z-50 py-2 bg-base-bg">
        <div className="flex justify-start items-center max-w-[1200px] mx-auto w-full px-6 gap-4">
          <div onClick={() => navigate(RoutePaths.HOME)}>
            <img src="/images/logo.png" className="h-12 cursor-pointer" />
          </div>
          <div className="flex items-center justify-center">
            {navItems.map(it => (
              <div
                key={it.key}
                className={classNames(
                  'text-base font-semibold cursor-pointer mx-3',
                  {
                    'text-primary': activeKey === it.key,
                  }
                )}
                onClick={() => navigate(it.key)}
              >
                {it.label}
              </div>
            ))}
          </div>
          <div className="flex items-center justify-center gap-6 ml-auto">
            <Tag>{version}</Tag>
            <Dropdown
              menu={{
                items: [
                  {
                    key: 'changePassword',
                    label: (
                      <div onClick={() => setIsPasswordModalOpen(true)} className="text-base">
                        修改密码
                      </div>
                    ),
                  },
                  {
                    key: 'logout',
                    label: (
                      <div onClick={onLogout} className="text-base">
                        退出登录
                      </div>
                    ),
                  },
                ],
              }}
            >
              <div className="text-primary font-medium cursor-pointer flex items-center gap-1">
                <MyIcon icon="user" size={18} />
                {userinfo?.username}
              </div>
            </Dropdown>
            <DarkModeToggle />
          </div>
        </div>
      </div>

      <Modal
        title="修改密码"
        open={isPasswordModalOpen}
        onCancel={() => {
          setIsPasswordModalOpen(false)
          form.resetFields()
        }}
        footer={null}
        width={500}
      >
        <div className="mb-4">
          如果您是使用初始随机密码登录的，建议您在此修改为自己的密码。
        </div>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleChangePassword}
        >
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
            <div className="flex justify-end gap-2">
              <Button onClick={() => {
                setIsPasswordModalOpen(false)
                form.resetFields()
              }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={isLoading}>
                确认修改
              </Button>
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
