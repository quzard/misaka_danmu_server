import { Tabs } from 'antd'
import { Security } from './components/Security'
import { Webhook } from './components/Webhook'
import { Proxy } from './components/Proxy'
import { Parameters } from './components/Parameters'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Recognition } from './components/Recognition'
import { Performance } from './components/Performance'
import AutoMatchSetting from './components/AutoMatchSetting'
import { MobileTabs } from '@/components/MobileTabs'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store/index.js'

export const Setting = () => {
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || 'security'
  const navigate = useNavigate()
  const isMobile = useAtomValue(isMobileAtom)

  const tabItems = [
    {
      label: '账户安全',
      key: 'security',
      children: <Security />,
    },
    {
      label: '参数配置',
      key: 'parameters',
      children: <Parameters />,
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
  ]

  const handleTabChange = (newKey) => {
    navigate(`/setting?key=${newKey}`, {
      replace: true,
    })
  }

  return (
    <div className="my-6">
      {isMobile ? (
        <MobileTabs
          items={tabItems}
          defaultActiveKey={key}
          onChange={handleTabChange}
        />
      ) : (
        <Tabs
          activeKey={key}
          items={tabItems}
          onChange={handleTabChange}
        />
      )}
    </div>
  )
}
