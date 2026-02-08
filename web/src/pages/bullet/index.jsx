import { Tabs } from 'antd'
import { TokenManage } from './components/TokenManage'
import { OutputManage } from './components/OutputManage'
import { MatchFallbackSetting } from './components/MatchFallbackSetting'
import DanmakuStorage from '../setting/components/DanmakuStorage'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MobileTabs } from '@/components/MobileTabs'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store/index.js'

export const Bullet = () => {
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || 'token'
  const navigate = useNavigate()
  const isMobile = useAtomValue(isMobileAtom)

  const tabItems = [
    {
      label: 'Token管理',
      key: 'token',
      children: <TokenManage />,
    },
    {
      label: '弹幕输出配置',
      key: 'output',
      children: <OutputManage />,
    },
    {
      label: '弹幕存储配置',
      key: 'storage',
      children: <DanmakuStorage />,
    },
    {
      label: '设置',
      key: 'fallback',
      children: <MatchFallbackSetting />,
    },
  ]

  const handleTabChange = (newKey) => {
    navigate(`/bullet?key=${newKey}`, {
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
