import React, { useState, useMemo } from 'react'
import { Modal, Table, Radio, Button, Space, InputNumber, Alert, Tag } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

/**
 * 番剧源关联冲突解决对话框
 */
const ReassociationConflictModal = ({ open, onCancel, onConfirm, conflictData, targetAnimeTitle }) => {
  // 每个提供商的解决方案状态
  const [resolutions, setResolutions] = useState({})
  // 每个提供商的偏移量
  const [offsets, setOffsets] = useState({})

  // 初始化解决方案(默认全选目标)
  useMemo(() => {
    if (!conflictData || !conflictData.conflicts) return

    const initialResolutions = {}
    const initialOffsets = {}

    conflictData.conflicts.forEach(conflict => {
      const providerResolutions = {}
      conflict.conflictEpisodes.forEach(ep => {
        providerResolutions[ep.episodeIndex] = false // false = 保留目标
      })
      initialResolutions[conflict.providerName] = providerResolutions
      initialOffsets[conflict.providerName] = 0
    })

    setResolutions(initialResolutions)
    setOffsets(initialOffsets)
  }, [conflictData])

  // 处理单个分集的选择
  const handleEpisodeSelection = (providerName, episodeIndex, keepSource) => {
    setResolutions(prev => ({
      ...prev,
      [providerName]: {
        ...prev[providerName],
        [episodeIndex]: keepSource,
      },
    }))
  }

  // 全选源番剧
  const handleSelectAllSource = providerName => {
    const conflict = conflictData.conflicts.find(c => c.providerName === providerName)
    if (!conflict) return

    const newResolutions = {}
    conflict.conflictEpisodes.forEach(ep => {
      newResolutions[ep.episodeIndex] = true // true = 保留源
    })

    setResolutions(prev => ({
      ...prev,
      [providerName]: newResolutions,
    }))
  }

  // 全选目标番剧
  const handleSelectAllTarget = providerName => {
    const conflict = conflictData.conflicts.find(c => c.providerName === providerName)
    if (!conflict) return

    const newResolutions = {}
    conflict.conflictEpisodes.forEach(ep => {
      newResolutions[ep.episodeIndex] = false // false = 保留目标
    })

    setResolutions(prev => ({
      ...prev,
      [providerName]: newResolutions,
    }))
  }

  // 按弹幕数量选择
  const handleSelectByDanmakuCount = providerName => {
    const conflict = conflictData.conflicts.find(c => c.providerName === providerName)
    if (!conflict) return

    const newResolutions = {}
    conflict.conflictEpisodes.forEach(ep => {
      // 选择弹幕更多的
      newResolutions[ep.episodeIndex] = ep.sourceDanmakuCount > ep.targetDanmakuCount
    })

    setResolutions(prev => ({
      ...prev,
      [providerName]: newResolutions,
    }))
  }

  // 处理偏移量变化
  const handleOffsetChange = (providerName, value) => {
    setOffsets(prev => ({
      ...prev,
      [providerName]: value || 0,
    }))
  }

  // 确认关联
  const handleConfirm = () => {
    // 构建解决方案数据
    const resolutionData = conflictData.conflicts.map(conflict => ({
      providerName: conflict.providerName,
      sourceOffset: offsets[conflict.providerName] || 0,
      episodeResolutions: Object.entries(resolutions[conflict.providerName] || {}).map(
        ([episodeIndex, keepSource]) => ({
          episodeIndex: parseInt(episodeIndex),
          keepSource,
        })
      ),
    }))

    onConfirm(resolutionData)
  }

  // 表格列定义
  const getColumns = providerName => [
    {
      title: '集数',
      dataIndex: 'episodeIndex',
      key: 'episodeIndex',
      width: 80,
      align: 'center',
    },
    {
      title: '源番剧',
      key: 'source',
      width: 150,
      render: record => (
        <div>
          <div>🎬 {record.sourceDanmakuCount} 条弹幕</div>
          {record.sourceLastFetchTime && (
            <div style={{ fontSize: '12px', color: '#999' }}>
              📅 {dayjs(record.sourceLastFetchTime).format('YYYY-MM-DD')}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '目标番剧',
      key: 'target',
      width: 150,
      render: record => (
        <div>
          <div>🎬 {record.targetDanmakuCount} 条弹幕</div>
          {record.targetLastFetchTime && (
            <div style={{ fontSize: '12px', color: '#999' }}>
              📅 {dayjs(record.targetLastFetchTime).format('YYYY-MM-DD')}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '保留',
      key: 'keep',
      width: 150,
      align: 'center',
      render: record => (
        <Radio.Group
          value={resolutions[providerName]?.[record.episodeIndex] ?? false}
          onChange={e =>
            handleEpisodeSelection(providerName, record.episodeIndex, e.target.value)
          }
        >
          <Radio value={true}>源</Radio>
          <Radio value={false}>目标</Radio>
        </Radio.Group>
      ),
    },
  ]

  if (!conflictData || !conflictData.hasConflict) {
    return null
  }

  return (
    <Modal
      title="🔀 数据源关联冲突解决"
      open={open}
      onCancel={onCancel}
      onOk={handleConfirm}
      width={900}
      okText="确认关联"
      cancelText="取消"
    >
      <Alert
        message="检测到以下提供商存在冲突"
        description={`目标番剧: ${targetAnimeTitle}`}
        type="warning"
        icon={<InfoCircleOutlined />}
        showIcon
        style={{ marginBottom: 16 }}
      />

      {conflictData.conflicts.map(conflict => (
        <div key={conflict.providerName} style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 12 }}>
            <Tag color="blue" style={{ fontSize: '14px', padding: '4px 12px' }}>
              📺 {conflict.providerName}
            </Tag>
            <span style={{ marginLeft: 8, color: '#999' }}>
              冲突分集: {conflict.conflictEpisodes.length} 集
            </span>
          </div>

          <Table
            dataSource={conflict.conflictEpisodes}
            columns={getColumns(conflict.providerName)}
            rowKey="episodeIndex"
            pagination={false}
            size="small"
            scroll={{ y: 300 }}
            style={{ marginBottom: 12 }}
          />

          <Space style={{ marginBottom: 12 }}>
            <Button size="small" onClick={() => handleSelectAllSource(conflict.providerName)}>
              全选源番剧
            </Button>
            <Button size="small" onClick={() => handleSelectAllTarget(conflict.providerName)}>
              全选目标番剧
            </Button>
            <Button
              size="small"
              type="primary"
              onClick={() => handleSelectByDanmakuCount(conflict.providerName)}
            >
              按弹幕数量选择
            </Button>
          </Space>

          <div style={{ marginTop: 12 }}>
            <span style={{ marginRight: 8 }}>集数偏移:</span>
            <InputNumber
              size="small"
              value={offsets[conflict.providerName] || 0}
              onChange={value => handleOffsetChange(conflict.providerName, value)}
              style={{ width: 100 }}
              placeholder="0"
            />
            <span style={{ marginLeft: 8, color: '#999', fontSize: '12px' }}>
              (正数向后偏移，负数向前偏移)
            </span>
          </div>
        </div>
      ))}
    </Modal>
  )
}

export default ReassociationConflictModal

