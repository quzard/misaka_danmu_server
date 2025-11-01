import { Tabs } from 'antd'
import { Security } from './components/Security'
import { Webhook } from './components/Webhook'
import { Proxy } from './components/Proxy'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Recognition } from './components/Recognition'
import { Performance } from './components/Performance'
import AutoMatchSetting from './components/AutoMatchSetting'

export const Setting = () => {
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || 'security'
  const navigate = useNavigate()

  return (
    <Tabs
      defaultActiveKey={key}
      items={[
        {
          label: '账户安全',
          key: 'security',
          children: <Security />,
        },
        {
          label: '代理设置',
          key: 'proxy',
          children: <Proxy />,
        },
        {
          label: 'Webhook',
          key: 'webhook',
          children: <Webhook />,
        },
        {
          label: '识别词配置',
          key: 'recognition',
          children: <Recognition />,
        },
        {
          label: '性能优化',
          key: 'performance',
          children: <Performance />,
        },
        {
          label: 'AI辅助增强',
          key: 'automatch',
          children: <AutoMatchSetting />,
        },
      ]}
      onChange={key => {
        navigate(`/setting?key=${key}`, {
          replace: true,
        })
      }}
    />
  )
}
