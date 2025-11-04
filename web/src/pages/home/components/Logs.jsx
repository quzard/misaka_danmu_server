import { useEffect } from 'react'
import { getLogs } from '../../../apis'
import { useState } from 'react'
import { useRef } from 'react'
import { Card, Tooltip, message } from 'antd'
import { ExportOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import Cookies from 'js-cookie'
import { fetchEventSource } from '@microsoft/fetch-event-source'

export const Logs = () => {
  const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState([])
  const abortControllerRef = useRef(null)
  const [messageApi, contextHolder] = message.useMessage()

  useEffect(() => {
    // 获取token
    const token = Cookies.get('danmu_token')
    if (!token) {
      messageApi.error('未登录,无法连接日志流')
      setLoading(false)
      return
    }

    // 创建AbortController用于取消连接
    const abortController = new AbortController()
    abortControllerRef.current = abortController

    // 使用fetch-event-source建立SSE连接
    fetchEventSource('/api/ui/logs/stream', {
      signal: abortController.signal,
      headers: {
        Authorization: `Bearer ${token}`,
      },
      onopen: async response => {
        if (response.ok) {
          console.log('SSE日志流已连接')
          setLoading(false)
        } else {
          throw new Error(`连接失败: ${response.status}`)
        }
      },
      onmessage: event => {
        const newLog = event.data
        setLogs(prevLogs => [newLog, ...prevLogs].slice(0, 200)) // 保持最多200条
      },
      onerror: error => {
        console.error('SSE连接错误:', error)
        messageApi.warning('日志流连接出错')
        setLoading(false)
        throw error // 抛出错误以停止重连
      },
    }).catch(error => {
      if (error.name !== 'AbortError') {
        console.error('SSE流错误:', error)
      }
    })

    // 清理函数
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
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
