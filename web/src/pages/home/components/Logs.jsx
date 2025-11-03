import { useEffect } from 'react'
import { getLogs } from '../../../apis'
import { useState } from 'react'
import { useRef } from 'react'
import { Card, Tooltip, message } from 'antd'
import { ExportOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

export const Logs = () => {
  const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState([])
  const eventSourceRef = useRef(null)
  const [messageApi, contextHolder] = message.useMessage()

  useEffect(() => {
    // 获取token
    const token = localStorage.getItem('token')
    if (!token) {
      messageApi.error('未登录,无法连接日志流')
      setLoading(false)
      return
    }

    // 创建SSE连接
    const eventSource = new EventSource(`/api/ui/logs/stream`, {
      withCredentials: true,
    })
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      console.log('SSE日志流已连接')
      setLoading(false)
    }

    eventSource.onmessage = event => {
      const newLog = event.data
      setLogs(prevLogs => [newLog, ...prevLogs].slice(0, 200)) // 保持最多200条
    }

    eventSource.onerror = error => {
      console.error('SSE连接错误:', error)
      if (eventSource.readyState === EventSource.CLOSED) {
        messageApi.warning('日志流连接已断开')
      }
      setLoading(false)
    }

    // 清理函数
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        console.log('SSE日志流已关闭')
      }
    }
  }, [])

  const exportLogs = () => {
    const blob = new Blob([logs.join('\r\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `logs-${dayjs().format('YYYY-MM-DD_HH-mm-ss')}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <>
      {contextHolder}
      <div className="my-6">
        <Card
          loading={loading}
          title="日志/状态 (实时)"
          extra={
            <Tooltip title="导出日志">
              <div onClick={exportLogs}>
                <ExportOutlined />
              </div>
            </Tooltip>
          }
        >
          <div className="max-h-[400px] overflow-y-auto">
            {logs?.map((it, index) => (
              <div key={index}>
                <div className="my-1">
                  <pre>{it}</pre>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  )
}
