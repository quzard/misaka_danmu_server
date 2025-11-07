import { Tabs } from 'antd'
import { Scrapers } from './components/Scrapers'
import { Metadata } from './components/Metadata'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { GlobalFilter } from './components/GlobalFilter'
import { MobileTabs } from '@/components/MobileTabs'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store/index.js'

export const Source = () => {
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || 'scrapers'
  const navigate = useNavigate()
  const isMobile = useAtomValue(isMobileAtom)

  const tabItems = [
    {
      label: '弹幕搜索源',
      key: 'scrapers',
      children: <Scrapers></Scrapers>,
    },
    {
      label: '元信息搜索源',
      key: 'metadata',
      children: <Metadata></Metadata>,
    },
    {
      label: '设置',
      key: 'global-filter',
      children: <GlobalFilter />,
    },
  ]

  const handleTabChange = (newKey) => {
    navigate(`/source?key=${newKey}`, {
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
