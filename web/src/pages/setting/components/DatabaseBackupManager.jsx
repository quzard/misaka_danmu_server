import { useState, useEffect } from 'react'
import { Button, Table, Space, Tag, Modal, Input, Alert, Spin, Popconfirm, message } from 'antd'
import {
  CloudDownloadOutlined,
  DeleteOutlined,
  ReloadOutlined,
  CloudUploadOutlined,
  ExclamationCircleOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import {
  getBackupList,
  createBackup,
  downloadBackup,
  deleteBackup,
  deleteBackupBatch,
  restoreBackup,
  getBackupJobStatus,
} from '../../../apis'

/**
 * 数据库备份管理组件
 * 用于在参数配置-数据库设置中显示
 */
export const DatabaseBackupManager = () => {
  const [backups, setBackups] = useState([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [jobStatus, setJobStatus] = useState(null)
  const [restoreModalVisible, setRestoreModalVisible] = useState(false)
  const [restoreTarget, setRestoreTarget] = useState(null)
  const [restoreConfirmText, setRestoreConfirmText] = useState('')
  const [restoring, setRestoring] = useState(false)

  useEffect(() => {
    loadBackups()
    loadJobStatus()
  }, [])

  const loadBackups = async () => {
    try {
      setLoading(true)
      const res = await getBackupList()
      setBackups(res.data || [])
    } catch (err) {
      message.error('加载备份列表失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setLoading(false)
    }
  }

  const loadJobStatus = async () => {
    try {
      const res = await getBackupJobStatus()
      setJobStatus(res.data)
    } catch (err) {
      console.error('获取定时任务状态失败:', err)
    }
  }

  const handleCreate = async () => {
    try {
      setCreating(true)
      const res = await createBackup()
      message.success(res.data?.message || '备份创建成功')
      loadBackups()
    } catch (err) {
      message.error('创建备份失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (filename) => {
    try {
      await deleteBackup(filename)
      message.success('删除成功')
      loadBackups()
    } catch (err) {
      message.error('删除失败: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) return
    try {
      const res = await deleteBackupBatch(selectedRowKeys)
      message.success(res.data?.message || '批量删除成功')
      setSelectedRowKeys([])
      loadBackups()
    } catch (err) {
      message.error('批量删除失败: ' + (err.response?.data?.detail || err.message))
    }
  }

  const handleDownload = (filename) => {
    window.open(downloadBackup(filename), '_blank')
  }

  const openRestoreModal = (record) => {
    setRestoreTarget(record)
    setRestoreConfirmText('')
    setRestoreModalVisible(true)
  }

  const handleRestore = async () => {
    if (restoreConfirmText !== 'RESTORE') {
      message.error('请输入 RESTORE 确认还原')
      return
    }
    try {
      setRestoring(true)
      const res = await restoreBackup({
        filename: restoreTarget.filename,
        confirm: 'RESTORE',
      })
      message.success(res.data?.message || '还原成功')
      setRestoreModalVisible(false)
    } catch (err) {
      message.error('还原失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setRestoring(false)
    }
  }

  const formatSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  }

  const formatDate = (isoString) => {
    if (!isoString) return '-'
    const date = new Date(isoString)
    return date.toLocaleString('zh-CN')
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
    },
    {
      title: '数据库类型',
      dataIndex: 'db_type',
      key: 'db_type',
      width: 100,
      render: (type) => type ? <Tag color="blue">{type.toUpperCase()}</Tag> : '-',
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size) => formatSize(size),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (time) => formatDate(time),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={<CloudDownloadOutlined />}
            onClick={() => handleDownload(record.filename)}
          />
          <Popconfirm
            title="确定删除此备份？"
            onConfirm={() => handleDelete(record.filename)}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys,
    onChange: setSelectedRowKeys,
  }

  return (
    <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-medium">📦 数据库备份管理</h3>
        <Button
          type="primary"
          icon={<CloudUploadOutlined />}
          onClick={handleCreate}
          loading={creating}
        >
          立即备份
        </Button>
      </div>

      {/* 定时任务状态 */}
      <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
        {jobStatus?.exists ? (
          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-blue-500" />
            <span>定时备份:</span>
            {jobStatus.enabled ? (
              <>
                <Tag icon={<CheckCircleOutlined />} color="success">已启用</Tag>
                <span className="text-gray-500">
                  执行周期: {jobStatus.cron_expression}
                  {jobStatus.next_run_time && ` | 下次执行: ${formatDate(jobStatus.next_run_time)}`}
                </span>
              </>
            ) : (
              <Tag color="default">已暂停</Tag>
            )}
            <a href="#/setting/scheduled-tasks" className="ml-2 text-blue-500 text-sm">
              前往配置 →
            </a>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-gray-500">
            <ClockCircleOutlined />
            <span>定时备份: 未配置</span>
            <a href="#/setting/scheduled-tasks" className="ml-2 text-blue-500 text-sm">
              前往配置 →
            </a>
          </div>
        )}
      </div>

      {/* 备份列表 */}
      <Spin spinning={loading}>
        <Table
          rowKey="filename"
          columns={columns}
          dataSource={backups}
          rowSelection={rowSelection}
          size="small"
          pagination={false}
          locale={{ emptyText: '暂无备份文件' }}
        />
      </Spin>

      {/* 批量操作 */}
      {selectedRowKeys.length > 0 && (
        <div className="mt-3 flex items-center gap-4">
          <span className="text-gray-500">已选中 {selectedRowKeys.length} 项</span>
          <Popconfirm
            title={`确定删除选中的 ${selectedRowKeys.length} 个备份？`}
            onConfirm={handleBatchDelete}
          >
            <Button danger size="small" icon={<DeleteOutlined />}>
              批量删除
            </Button>
          </Popconfirm>
          {selectedRowKeys.length === 1 && (
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => openRestoreModal(backups.find(b => b.filename === selectedRowKeys[0]))}
            >
              还原选中
            </Button>
          )}
        </div>
      )}

      {/* 还原确认弹窗 */}
      <Modal
        title={
          <span className="text-red-500">
            <ExclamationCircleOutlined className="mr-2" />
            危险操作确认
          </span>
        }
        open={restoreModalVisible}
        onCancel={() => setRestoreModalVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setRestoreModalVisible(false)}>
            取消
          </Button>,
          <Button
            key="confirm"
            type="primary"
            danger
            loading={restoring}
            disabled={restoreConfirmText !== 'RESTORE'}
            onClick={handleRestore}
          >
            确认还原
          </Button>,
        ]}
      >
        {restoreTarget && (
          <div>
            <p className="mb-2">您即将从备份文件还原数据库：</p>
            <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded mb-4">
              <div>📄 {restoreTarget.filename}</div>
              <div>📅 创建时间: {formatDate(restoreTarget.created_at)}</div>
              <div>📦 文件大小: {formatSize(restoreTarget.size)}</div>
              {restoreTarget.db_type && (
                <div>🗄️ 数据库类型: {restoreTarget.db_type.toUpperCase()}</div>
              )}
            </div>
            <Alert
              type="error"
              message="警告：此操作将覆盖当前数据库中的所有数据！还原后无法撤销，请确保您了解此操作的后果。"
              className="mb-4"
            />
            <div>
              <p className="mb-2">请输入 <strong>RESTORE</strong> 确认还原：</p>
              <Input
                value={restoreConfirmText}
                onChange={(e) => setRestoreConfirmText(e.target.value)}
                placeholder="输入 RESTORE"
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

