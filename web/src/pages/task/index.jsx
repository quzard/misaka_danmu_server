import { ImportTask } from './components/ImportTask'
import { ScheduleTask } from './components/ScheduleTask'
import { RateLimitPanel } from './components/RateLimitPanel'
import { WebhookTasks } from './components/WebhookTasks'
import { Tabs } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { MobileTabs } from '@/components/MobileTabs'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store/index.js'

export const Task = () => {
  const [searchParams] = useSearchParams()
  const key = searchParams.get('key') || 'task'
  const isMobile = useAtomValue(isMobileAtom)
  const navigate = useNavigate()

  const tabItems = [
    {
      label: '进行中的任务',
      key: 'task',
      children: <ImportTask />,
    },
    {
      label: 'Webhook 任务',
      key: 'webhook',
      children: <WebhookTasks />,
    },
    {
      label: '定时任务',
      key: 'schedule',
      children: <ScheduleTask />,
    },
    {
      label: '流控面板',
      key: 'ratelimit',
      children: <RateLimitPanel />,
    },
  ]

  const handleTabChange = (newKey) => {
    navigate(`/task?key=${newKey}`, {
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
