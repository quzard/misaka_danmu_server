import { useEffect, useMemo, useRef, useState } from 'react'
import { Modal, Drawer, Button, Tooltip, message, Empty, Switch, Card, Segmented, Input } from 'antd'
import { CopyOutlined, ExportOutlined, ClearOutlined, VerticalAlignBottomOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import Cookies from 'js-cookie'
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../store'

// 级别颜色配置（INFO 使用 CSS 变量跟随主题色）
const LEVEL_COLORS = {
  DEBUG:   { solid: '#1d4ed8', bg: 'rgba(29,78,216,0.07)' },
  INFO:    { solid: 'var(--ant-color-primary)', bg: 'var(--ant-color-primary-bg)' },
  WARNING: { solid: '#f59e0b', bg: 'rgba(245,158,11,0.07)' },
  ERROR:   { solid: '#ef4444', bg: 'rgba(239,68,68,0.07)' },
}

// Segmented 按钮映射（选项值 → 颜色）
const SEG_COLORS = { INFO: 'var(--ant-color-primary)', WARN: '#f59e0b', DEBUG: '#1d4ed8' }

// 级别数值（用于过滤阈值）
const LEVEL_VALUES = { DEBUG: 10, INFO: 20, WARNING: 30, WARN: 30, ERROR: 40 }

export default function RealtimeLogModal({ open, onClose }) {
  const [logs, setLogs] = useState([])
  const [connected, setConnected] = useState(false)
  const [autoScroll, setAutoScroll] = useState(true)
  const [logLevel, setLogLevel] = useState('INFO')
  const [searchText, setSearchText] = useState('')
  const abortRef = useRef(null)
  const containerRef = useRef(null)
  const [messageApi, contextHolder] = message.useMessage()
  const isMobile = useAtomValue(isMobileAtom)

  useEffect(() => {
    if (!open) return
    const token = Cookies.get('danmu_token')
    if (!token) { messageApi.error('未登录'); return }

    const ctrl = new AbortController()
    abortRef.current = ctrl

    fetchEventSource('/api/ui/logs/stream', {
      signal: ctrl.signal,
      headers: { Authorization: `Bearer ${token}` },
      onopen: async (res) => { if (res.ok) setConnected(true); else throw new Error(`连接失败: ${res.status}`) },
      onmessage: (event) => {
        const msg = event.data.trim()
        if (!msg) return
        setLogs(prev => [msg, ...prev].slice(0, 200))
      },
      onerror: (err) => { setConnected(false); throw err },
    }).catch(e => { if (e.name !== 'AbortError') console.error('SSE错误:', e) })

    return () => { ctrl.abort(); setConnected(false) }
  }, [open])

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = 0
    }
  }, [logs, autoScroll])

  const handleClose = () => {
    abortRef.current?.abort()
    setLogs([])
    setConnected(false)
    onClose()
  }

  const exportLogs = () => {
    const blob = new Blob([logs.slice().reverse().join('\r\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `realtime-logs-${dayjs().format('YYYY-MM-DD_HH-mm-ss')}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const copyLogLine = async (logText) => {
    try {
      await navigator.clipboard.writeText(logText)
      messageApi.success('日志已复制到剪贴板')
    } catch {
      const textArea = document.createElement('textarea')
      textArea.value = logText
      document.body.appendChild(textArea)
      textArea.select()
      try { document.execCommand('copy'); messageApi.success('日志已复制到剪贴板') }
      catch { messageApi.error('复制失败') }
      document.body.removeChild(textArea)
    }
  }

  // --- 日志级别工具函数 ---
  const getLineLevel = (line) => {
    const m = line.match(/\[(DEBUG|INFO|WARNING|ERROR)\]/)
    return m ? LEVEL_VALUES[m[1]] : null
  }

  const getLineLevelName = (line) => {
    const m = line.match(/\[(DEBUG|INFO|WARNING|ERROR)\]/)
    return m ? m[1] : 'INFO'
  }

  const stripLevelTag = (text) => text.replace(/\s*\[(DEBUG|INFO|WARNING|ERROR)\]\s*/, ' ')

  // 根据选中级别过滤日志条目
  const filterLog = (entry) => {
    const threshold = LEVEL_VALUES[logLevel] ?? 20
    if (threshold <= 10) return entry

    const lines = entry.split('\n')
    const isBlock = lines.some(l => l.includes('┌───') || l.includes('└───'))

    if (!isBlock) {
      const level = getLineLevel(entry)
      return (level ?? 20) >= threshold ? entry : null
    }

    const filtered = lines.filter(l => {
      if (l.includes('┌───') || l.includes('└───') || l.trim() === '') return true
      const level = getLineLevel(l)
      return (level ?? 20) >= threshold
    })

    const contentLines = filtered.filter(l => !l.includes('┌───') && !l.includes('└───') && l.trim() !== '')
    return contentLines.length > 0 ? filtered.join('\n') : null
  }

  const filteredLogs = useMemo(() => {
    if (!searchText.trim()) return logs
    const kw = searchText.toLowerCase()
    return logs.filter(line => line.toLowerCase().includes(kw))
  }, [logs, searchText])

  const segColor = SEG_COLORS[logLevel] || 'var(--ant-color-primary)'

  // --- 级别徽章 ---
  const LevelBadge = ({ level }) => {
    const c = LEVEL_COLORS[level] || LEVEL_COLORS.INFO
    const label = level === 'WARNING' ? 'WARN' : level
    return (
      <span
        className="inline-block shrink-0 rounded px-1.5 py-0.5 text-white font-mono leading-none"
        style={{ fontSize: 10, backgroundColor: c.solid, opacity: 0.85 }}
      >
        {label}
      </span>
    )
  }

  // --- Segmented 节点（桌面/移动端复用） ---
  const segmentedNode = (
    <>
      <style>{`.log-seg .ant-segmented-item-selected { background: ${segColor} !important; color: #fff !important; }`}</style>
      <div className="log-seg">
        <Segmented size="small" options={['INFO', 'WARN', 'DEBUG']} value={logLevel} onChange={setLogLevel} />
      </div>
    </>
  )

  const titleNode = (
    <div className="flex items-center gap-2">
      <span>实时日志</span>
      <span className={`inline-block w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-400'}`} />
      <span className="text-xs text-gray-400">{connected ? '已连接' : '未连接'}</span>
      {!isMobile && (
        <>
          <span className="text-gray-300 mx-1">|</span>
          {segmentedNode}
          <Input
            size="small"
            placeholder="搜索日志..."
            prefix={<SearchOutlined className="text-gray-400" />}
            allowClear
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ width: 180 }}
          />
        </>
      )}
    </div>
  )

  const actionButtons = (
    <div className="flex gap-1">
      <Tooltip title="清空"><Button size="small" type="text" icon={<ClearOutlined />} onClick={() => setLogs([])} /></Tooltip>
      <Tooltip title="导出"><Button size="small" type="text" icon={<ExportOutlined />} onClick={exportLogs} /></Tooltip>
      <Tooltip title="滚动到顶部">
        <Button size="small" type="text" icon={<VerticalAlignBottomOutlined className="rotate-180" />} onClick={() => {
          if (containerRef.current) containerRef.current.scrollTop = 0
        }} />
      </Tooltip>
    </div>
  )

  const footerNode = (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">自动滚动</span>
        <Switch size="small" checked={autoScroll} onChange={setAutoScroll} />
      </div>
      {!isMobile && (
        <div className="flex gap-2">
          <Tooltip title="清空"><Button icon={<ClearOutlined />} onClick={() => setLogs([])} /></Tooltip>
          <Tooltip title="导出"><Button icon={<ExportOutlined />} onClick={exportLogs} /></Tooltip>
          <Tooltip title="滚动到顶部">
            <Button icon={<VerticalAlignBottomOutlined className="rotate-180" />} onClick={() => {
              if (containerRef.current) containerRef.current.scrollTop = 0
            }} />
          </Tooltip>
        </div>
      )}
    </div>
  )

  const logContent = (
    <div className={isMobile ? 'flex-1 overflow-hidden flex flex-col gap-2' : 'flex flex-col gap-2'}>
      {isMobile && (
        <div className="flex items-center gap-2 flex-wrap">
          {segmentedNode}
          <Input
            size="small"
            placeholder="搜索日志..."
            prefix={<SearchOutlined className="text-gray-400" />}
            allowClear
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ flex: 1, minWidth: 120 }}
          />
        </div>
      )}
      <Card className={isMobile ? 'flex-1 overflow-hidden flex flex-col' : ''} styles={{ body: { padding: isMobile ? 8 : 12, ...(isMobile ? { flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' } : {}) } }}>
        <div
          ref={containerRef}
          className={`${isMobile ? 'flex-1 overflow-y-auto overflow-x-hidden' : 'max-h-[60vh] overflow-y-auto overflow-x-hidden'}`}
        >
          {filteredLogs.length === 0 ? (
            <div className="flex items-center justify-center" style={{ height: '40vh' }}>
              <Empty description={<span className="text-gray-400">{logs.length === 0 ? '等待日志...' : '无匹配日志'}</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            filteredLogs.map((line, i) => {
              const filtered = filterLog(line)
              if (!filtered) return null
              const levelName = getLineLevelName(filtered)
              const lc = LEVEL_COLORS[levelName] || LEVEL_COLORS.INFO
              const displayText = stripLevelTag(filtered)
              return (
                <div
                  key={i}
                  className={`my-1 p-2 rounded group ${isMobile ? 'text-xs' : 'text-sm'} border-l-[3px] hover:brightness-95 transition-all`}
                  style={{ borderLeftColor: lc.solid, backgroundColor: lc.bg }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-start gap-2 flex-1 min-w-0">
                      <LevelBadge level={levelName} />
                      <pre className="whitespace-pre-wrap break-words m-0 font-mono flex-1 min-w-0">
                        {searchText ? highlightText(displayText, searchText) : displayText}
                      </pre>
                    </div>
                    <Button
                      type="text"
                      size="small"
                      icon={<CopyOutlined />}
                      className={`shrink-0 opacity-0 group-hover:opacity-100 transition-opacity ${isMobile ? 'opacity-60' : ''}`}
                      onClick={(e) => { e.stopPropagation(); copyLogLine(filtered) }}
                      title="复制日志"
                    />
                  </div>
                </div>
              )
            })
          )}
        </div>
      </Card>
    </div>
  )

  return (
    <>
      {contextHolder}
      {isMobile ? (
        <Drawer
          title={titleNode}
          placement="bottom"
          height="85%"
          open={open}
          onClose={handleClose}
          extra={actionButtons}
          footer={footerNode}
          destroyOnClose
          styles={{ body: { overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 12 } }}
        >
          {logContent}
        </Drawer>
      ) : (
        <Modal
          title={titleNode}
          open={open}
          onCancel={handleClose}
          width="90%"
          style={{ maxWidth: 900, top: 40 }}
          footer={footerNode}
          destroyOnClose
        >
          {logContent}
        </Modal>
      )}
    </>
  )
}



function highlightText(text, keyword) {
  if (!keyword) return text
  const regex = new RegExp(`(${keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)
  return parts.map((part, i) =>
    regex.test(part) ? <mark key={i} className="bg-yellow-300 dark:bg-yellow-600 px-0.5 rounded">{part}</mark> : part
  )
}
