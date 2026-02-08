import { Card, Collapse, Table, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { getControlApiKeyLog } from '../../../apis'
import dayjs from 'dayjs'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../../store'

const DetailBlock = ({ label, content }) => {
  if (!content) return null
  return (
    <div className="mb-3">
      <div className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">{label}</div>
      <pre className="text-xs bg-gray-50 dark:bg-gray-800 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto m-0">
        {content}
      </pre>
    </div>
  )
}

const LogDetailPanel = ({ log }) => {
  const hasRequest = log.requestHeaders || log.requestBody
  const hasResponse = log.responseHeaders || log.responseBody
  if (!hasRequest && !hasResponse) {
    return <div className="text-xs text-gray-400 py-2">暂无详细请求/响应记录</div>
  }
  const items = []
  if (hasRequest) {
    items.push({
      key: 'request',
      label: '📤 请求信息',
      children: (
        <div>
          <DetailBlock label="请求头" content={log.requestHeaders} />
          <DetailBlock label="请求内容" content={log.requestBody} />
        </div>
      ),
    })
  }
  if (hasResponse) {
    items.push({
      key: 'response',
      label: '📥 响应信息',
      children: (
        <div>
          <DetailBlock label="响应头" content={log.responseHeaders} />
          <DetailBlock label="响应内容" content={log.responseBody} />
        </div>
      ),
    })
  }
  return <Collapse size="small" items={items} />
}

export const ApiLogs = () => {
  const [loading, setLoading] = useState(true)
  const [logs, setLogs] = useState([])
  const isMobile = useAtomValue(isMobileAtom)

  useEffect(() => {
    setLoading(true)
    getControlApiKeyLog()
      .then(res => {
        setLogs(res.data ?? [])
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const columns = [
    {
      title: '访问时间',
      dataIndex: 'accessTime',
      key: 'accessTime',
      width: 200,
      render: (_, record) => {
        return (
          <div>{dayjs(record.accessTime).format('YYYY-MM-DD HH:mm:ss')}</div>
        )
      },
    },
    {
      title: 'IP地址',
      dataIndex: 'ipAddress',
      key: 'ipAddress',
      width: 150,
    },
    {
      title: '端点',
      dataIndex: 'endpoint',
      key: 'endpoint',
      width: 200,
    },
    {
      title: '状态码',
      width: 200,
      dataIndex: 'statusCode',
      key: 'statusCode',
      render: (_, record) => {
        return (
          <Tag color={record.statusCode >= 400 ? 'red' : 'green'}>
            {record.statusCode}
          </Tag>
        )
      },
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      width: 400,
    },
  ]

  return (
    <div className="my-6">
      <Card title="API访问日志" loading={loading}>
        <div className="mb-4">这里显示最近100条通过外部API的访问记录。</div>
        {isMobile ? (
          <div className="space-y-4">
            {logs.map((log, index) => {
              const isSuccess = log.statusCode < 400;
              return (
                <Card
                  key={index}
                  size="small"
                  className="hover:shadow-lg transition-shadow duration-300"
                  bodyStyle={{ padding: '12px' }}
                >
                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${isSuccess ? 'bg-green-500' : 'bg-red-500'}`} />
                        <span className="text-sm font-medium">
                          {dayjs(log.accessTime).format('MM-DD HH:mm:ss')}
                        </span>
                      </div>
                      <Tag color={isSuccess ? 'success' : 'error'}>
                        {log.statusCode}
                      </Tag>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-8 shrink-0">IP:</span>
                        <Typography.Text code className="text-sm font-mono">
                          {log.ipAddress}
                        </Typography.Text>
                      </div>
                      <div className="flex items-start gap-3">
                        <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-8 shrink-0 mt-1">端点:</span>
                        <Typography.Text code className="text-xs break-all flex-1">
                          {log.endpoint}
                        </Typography.Text>
                      </div>
                      {log.message && (
                        <div className="flex items-start gap-3">
                          <span className="text-xs font-medium text-gray-500 dark:text-gray-400 w-8 shrink-0 mt-1">消息:</span>
                          <Typography.Text code className="text-xs break-all flex-1">
                            {log.message}
                          </Typography.Text>
                        </div>
                      )}
                    </div>
                    <LogDetailPanel log={log} />
                  </div>
                </Card>
              );
            })}
          </div>
        ) : (
          <Table
            pagination={false}
            size="small"
            dataSource={logs}
            columns={columns}
            rowKey={(_, index) => index}
            expandable={{
              expandedRowRender: (record) => <LogDetailPanel log={record} />,
              rowExpandable: (record) => !!(record.requestHeaders || record.requestBody || record.responseHeaders || record.responseBody),
            }}
            scroll={{
              x: '100%',
              y: 400,
            }}
          />
        )}
      </Card>
    </div>
  )
}
