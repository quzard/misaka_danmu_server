import { useState, useEffect, useMemo } from 'react'
import {
  Modal,
  Tabs,
  Select,
  InputNumber,
  Button,
  Table,
  Checkbox,
  Space,
  Spin,
  Empty,
  Tag,
  Tooltip,
  Input,
  Form,
  Divider,
  Progress,
} from 'antd'
import {
  InfoCircleOutlined,
  ClockCircleOutlined,
  ScissorOutlined,
  MergeCellsOutlined,
  PlusOutlined,
  DeleteOutlined,
  HolderOutlined,
} from '@ant-design/icons'
import { useMessage } from '../MessageContext'
import {
  getDanmakuEditDetail,
  getDanmakuEditComments,
  applyDanmakuOffset,
  splitEpisodeDanmaku,
  mergeEpisodesDanmaku,
} from '../apis'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

// 格式化时间显示
const formatTime = (seconds) => {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

// 可拖拽的合并项组件
const SortableMergeItem = ({ item, index, onOffsetChange, onRemove }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.episodeId })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-3 p-3 mb-2 bg-gray-50 dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-700"
    >
      <div {...attributes} {...listeners} className="cursor-grab">
        <HolderOutlined className="text-gray-400" />
      </div>
      <div className="flex-1">
        <div className="font-medium">第{item.episodeIndex}集</div>
        <div className="text-sm text-gray-500 truncate">{item.title}</div>
        <div className="text-xs text-gray-400">弹幕: {item.commentCount}条</div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-sm">偏移:</span>
        <InputNumber
          value={item.offsetSeconds}
          onChange={(val) => onOffsetChange(item.episodeId, val || 0)}
          addonAfter="秒"
          style={{ width: 120 }}
        />
      </div>
      <Button
        type="text"
        danger
        icon={<DeleteOutlined />}
        onClick={() => onRemove(item.episodeId)}
      />
    </div>
  )
}

export const DanmakuEditModal = ({ open, onCancel, onSuccess, episodes, sourceInfo }) => {
  const messageApi = useMessage()
  const [activeTab, setActiveTab] = useState('detail')
  const [loading, setLoading] = useState(false)
  
  // 弹幕详情状态
  const [selectedDetailEpisode, setSelectedDetailEpisode] = useState(null)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  
  // 时间偏移状态
  const [offsetEpisodes, setOffsetEpisodes] = useState([])
  const [offsetValue, setOffsetValue] = useState(0)
  const [offsetLoading, setOffsetLoading] = useState(false)
  
  // 分集拆分状态
  const [splitSourceEpisode, setSplitSourceEpisode] = useState(null)
  const [splitConfigs, setSplitConfigs] = useState([])
  const [splitDeleteSource, setSplitDeleteSource] = useState(true)
  const [splitResetTime, setSplitResetTime] = useState(true)
  const [splitLoading, setSplitLoading] = useState(false)
  
  // 分集合并状态
  const [mergeEpisodes, setMergeEpisodes] = useState([])
  const [mergeTargetIndex, setMergeTargetIndex] = useState(1)
  const [mergeTargetTitle, setMergeTargetTitle] = useState('')
  const [mergeDeleteSources, setMergeDeleteSources] = useState(true)
  const [mergeDeduplicate, setMergeDeduplicate] = useState(false)
  const [mergeLoading, setMergeLoading] = useState(false)

  // 拖拽传感器
  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  )

  // 初始化
  useEffect(() => {
    if (open && episodes?.length > 0) {
      setSelectedDetailEpisode(episodes[0].episodeId)
      setOffsetEpisodes([])
      setSplitSourceEpisode(null)
      setSplitConfigs([])
      setMergeEpisodes([])
    }
  }, [open, episodes])

  // 加载弹幕详情
  useEffect(() => {
    if (selectedDetailEpisode && activeTab === 'detail') {
      loadDetailData(selectedDetailEpisode)
    }
  }, [selectedDetailEpisode, activeTab])

  const loadDetailData = async (episodeId) => {
    setDetailLoading(true)
    try {
      const res = await getDanmakuEditDetail(episodeId)
      setDetailData(res.data)
    } catch (error) {
      messageApi.error('获取弹幕详情失败')
      setDetailData(null)
    } finally {
      setDetailLoading(false)
    }
  }

  // 时间偏移处理
  const handleApplyOffset = async () => {
    if (offsetEpisodes.length === 0) {
      messageApi.warning('请选择要调整的分集')
      return
    }
    if (offsetValue === 0) {
      messageApi.warning('偏移值不能为0')
      return
    }
    setOffsetLoading(true)
    try {
      await applyDanmakuOffset({
        episodeIds: offsetEpisodes,
        offsetSeconds: offsetValue,
      })
      messageApi.success(`已对 ${offsetEpisodes.length} 个分集应用 ${offsetValue}s 偏移`)
      onSuccess?.()
    } catch (error) {
      messageApi.error('应用时间偏移失败: ' + error.message)
    } finally {
      setOffsetLoading(false)
    }
  }

  // 添加拆分配置
  const addSplitConfig = () => {
    const lastConfig = splitConfigs[splitConfigs.length - 1]
    const newIndex = lastConfig ? lastConfig.episodeIndex + 1 : 1
    const newStartTime = lastConfig ? lastConfig.endTime : 0
    setSplitConfigs([
      ...splitConfigs,
      {
        id: Date.now(),
        episodeIndex: newIndex,
        startTime: newStartTime,
        endTime: newStartTime + 1500, // 默认25分钟
        title: `第${newIndex}集`,
      },
    ])
  }

  // 删除拆分配置
  const removeSplitConfig = (id) => {
    setSplitConfigs(splitConfigs.filter((c) => c.id !== id))
  }

  // 更新拆分配置
  const updateSplitConfig = (id, field, value) => {
    setSplitConfigs(
      splitConfigs.map((c) => (c.id === id ? { ...c, [field]: value } : c))
    )
  }

  // 执行拆分
  const handleSplit = async () => {
    if (!splitSourceEpisode) {
      messageApi.warning('请选择源分集')
      return
    }
    if (splitConfigs.length === 0) {
      messageApi.warning('请添加拆分配置')
      return
    }
    setSplitLoading(true)
    try {
      const res = await splitEpisodeDanmaku({
        sourceEpisodeId: splitSourceEpisode,
        splits: splitConfigs.map((c) => ({
          episodeIndex: c.episodeIndex,
          startTime: c.startTime,
          endTime: c.endTime,
          title: c.title,
        })),
        deleteSource: splitDeleteSource,
        resetTime: splitResetTime,
      })
      if (res.data.success) {
        messageApi.success(`拆分成功，创建了 ${res.data.newEpisodes.length} 个新分集`)
        onSuccess?.()
      } else {
        messageApi.error(res.data.error || '拆分失败')
      }
    } catch (error) {
      messageApi.error('拆分失败: ' + error.message)
    } finally {
      setSplitLoading(false)
    }
  }

  // 添加合并分集
  const addMergeEpisode = (episodeId) => {
    const episode = episodes.find((e) => e.episodeId === episodeId)
    if (episode && !mergeEpisodes.find((e) => e.episodeId === episodeId)) {
      setMergeEpisodes([
        ...mergeEpisodes,
        { ...episode, offsetSeconds: 0 },
      ])
    }
  }

  // 移除合并分集
  const removeMergeEpisode = (episodeId) => {
    setMergeEpisodes(mergeEpisodes.filter((e) => e.episodeId !== episodeId))
  }

  // 更新合并分集偏移
  const updateMergeOffset = (episodeId, offset) => {
    setMergeEpisodes(
      mergeEpisodes.map((e) =>
        e.episodeId === episodeId ? { ...e, offsetSeconds: offset } : e
      )
    )
  }

  // 拖拽排序处理
  const handleDragEnd = (event) => {
    const { active, over } = event
    if (active.id !== over?.id) {
      setMergeEpisodes((items) => {
        const oldIndex = items.findIndex((i) => i.episodeId === active.id)
        const newIndex = items.findIndex((i) => i.episodeId === over.id)
        return arrayMove(items, oldIndex, newIndex)
      })
    }
  }

  // 执行合并
  const handleMerge = async () => {
    if (mergeEpisodes.length < 2) {
      messageApi.warning('请至少选择2个分集进行合并')
      return
    }
    if (!mergeTargetTitle.trim()) {
      messageApi.warning('请输入目标标题')
      return
    }
    setMergeLoading(true)
    try {
      const res = await mergeEpisodesDanmaku({
        sourceEpisodes: mergeEpisodes.map((e) => ({
          episodeId: e.episodeId,
          offsetSeconds: e.offsetSeconds,
        })),
        targetEpisodeIndex: mergeTargetIndex,
        targetTitle: mergeTargetTitle,
        deleteSources: mergeDeleteSources,
        deduplicate: mergeDeduplicate,
      })
      if (res.data.success) {
        messageApi.success(`合并成功，新分集共 ${res.data.commentCount} 条弹幕`)
        onSuccess?.()
      } else {
        messageApi.error(res.data.error || '合并失败')
      }
    } catch (error) {
      messageApi.error('合并失败: ' + error.message)
    } finally {
      setMergeLoading(false)
    }
  }

  // 计算时间分布的最大值（用于进度条）
  const maxDistribution = useMemo(() => {
    if (!detailData?.distribution) return 1
    return Math.max(...detailData.distribution.map((d) => d.count), 1)
  }, [detailData])

  // 可选的分集列表（排除已选择的）
  const availableMergeEpisodes = useMemo(() => {
    const selectedIds = mergeEpisodes.map((e) => e.episodeId)
    return episodes?.filter((e) => !selectedIds.includes(e.episodeId)) || []
  }, [episodes, mergeEpisodes])

  // 渲染弹幕详情标签页
  const renderDetailTab = () => (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <span>选择分集：</span>
        <Select
          value={selectedDetailEpisode}
          onChange={setSelectedDetailEpisode}
          style={{ width: 300 }}
          options={episodes?.map((e) => ({
            value: e.episodeId,
            label: `第${e.episodeIndex}集 - ${e.title} (${e.commentCount}条)`,
          }))}
        />
      </div>

      {detailLoading ? (
        <div className="flex justify-center py-8">
          <Spin />
        </div>
      ) : detailData ? (
        <div className="space-y-4">
          {/* 统计信息 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-3 bg-blue-50 dark:bg-blue-900/30 rounded">
              <div className="text-sm text-gray-500 dark:text-gray-400">总弹幕数</div>
              <div className="text-xl font-bold">{detailData.totalCount}</div>
            </div>
            <div className="p-3 bg-green-50 dark:bg-green-900/30 rounded">
              <div className="text-sm text-gray-500 dark:text-gray-400">时间范围</div>
              <div className="text-xl font-bold">
                {formatTime(detailData.timeRange.start)} - {formatTime(detailData.timeRange.end)}
              </div>
            </div>
            <div className="p-3 bg-purple-50 dark:bg-purple-900/30 rounded">
              <div className="text-sm text-gray-500 dark:text-gray-400">来源数</div>
              <div className="text-xl font-bold">{detailData.sources.length}</div>
            </div>
            <div className="p-3 bg-orange-50 dark:bg-orange-900/30 rounded">
              <div className="text-sm text-gray-500 dark:text-gray-400">时长</div>
              <div className="text-xl font-bold">
                {Math.ceil((detailData.timeRange.end - detailData.timeRange.start) / 60)}分钟
              </div>
            </div>
          </div>

          {/* 来源分布 */}
          <div>
            <div className="text-sm font-medium mb-2">来源分布</div>
            <div className="flex flex-wrap gap-2">
              {detailData.sources.map((s) => (
                <Tag key={s.name} color="blue">
                  {s.name}: {s.count}条
                </Tag>
              ))}
            </div>
          </div>

          {/* 时间分布图 */}
          <div>
            <div className="text-sm font-medium mb-2">时间分布（每分钟弹幕数）</div>
            <div className="max-h-40 overflow-y-auto space-y-1">
              {detailData.distribution.map((d) => (
                <div key={d.minute} className="flex items-center gap-2 text-xs">
                  <span className="w-16 text-right">{d.minute}分钟</span>
                  <Progress
                    percent={(d.count / maxDistribution) * 100}
                    showInfo={false}
                    size="small"
                    className="flex-1"
                  />
                  <span className="w-12">{d.count}条</span>
                </div>
              ))}
            </div>
          </div>

          {/* 弹幕预览 */}
          <div>
            <div className="text-sm font-medium mb-2">弹幕预览（前100条）</div>
            <div className="max-h-60 overflow-y-auto border rounded dark:border-gray-700">
              <Table
                dataSource={detailData.comments}
                columns={[
                  {
                    title: '时间',
                    dataIndex: 'time',
                    width: 80,
                    render: (t) => formatTime(t),
                  },
                  { title: '内容', dataIndex: 'content', ellipsis: true },
                  {
                    title: '来源',
                    dataIndex: 'source',
                    width: 100,
                    render: (s) => <Tag>{s}</Tag>,
                  },
                ]}
                rowKey={(_, i) => i}
                size="small"
                pagination={false}
              />
            </div>
          </div>
        </div>
      ) : (
        <Empty description="暂无弹幕数据" />
      )}
    </div>
  )

  // 渲染时间偏移标签页
  const renderOffsetTab = () => (
    <div className="space-y-4">
      <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded text-sm">
        <InfoCircleOutlined className="mr-2" />
        选择要调整的分集，设置偏移秒数（正数延后，负数提前），然后点击应用。
      </div>

      <div>
        <div className="text-sm font-medium mb-2">选择分集</div>
        <div className="max-h-60 overflow-y-auto border rounded p-2 dark:border-gray-700">
          <Checkbox
            checked={offsetEpisodes.length === episodes?.length}
            indeterminate={offsetEpisodes.length > 0 && offsetEpisodes.length < episodes?.length}
            onChange={(e) => {
              if (e.target.checked) {
                setOffsetEpisodes(episodes?.map((ep) => ep.episodeId) || [])
              } else {
                setOffsetEpisodes([])
              }
            }}
          >
            全选
          </Checkbox>
          <Divider className="my-2" />
          <div className="space-y-1">
            {episodes?.map((ep) => (
              <div key={ep.episodeId}>
                <Checkbox
                  checked={offsetEpisodes.includes(ep.episodeId)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setOffsetEpisodes([...offsetEpisodes, ep.episodeId])
                    } else {
                      setOffsetEpisodes(offsetEpisodes.filter((id) => id !== ep.episodeId))
                    }
                  }}
                >
                  第{ep.episodeIndex}集 - {ep.title} ({ep.commentCount}条)
                </Checkbox>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <span>偏移秒数：</span>
        <InputNumber
          value={offsetValue}
          onChange={setOffsetValue}
          addonAfter="秒"
          style={{ width: 150 }}
        />
        <span className="text-gray-500 text-sm">
          {offsetValue > 0 ? '弹幕将延后出现' : offsetValue < 0 ? '弹幕将提前出现' : ''}
        </span>
      </div>

      <div className="flex justify-end">
        <Button
          type="primary"
          onClick={handleApplyOffset}
          loading={offsetLoading}
          disabled={offsetEpisodes.length === 0 || offsetValue === 0}
        >
          应用偏移 ({offsetEpisodes.length}个分集)
        </Button>
      </div>
    </div>
  )

  // 渲染分集拆分标签页
  const renderSplitTab = () => (
    <div className="space-y-4">
      <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded text-sm">
        <InfoCircleOutlined className="mr-2" />
        将一个分集的弹幕按时间范围拆分到多个新分集。适用于合集视频拆分为单集。
      </div>

      <div className="flex items-center gap-4">
        <span>源分集：</span>
        <Select
          value={splitSourceEpisode}
          onChange={(val) => {
            setSplitSourceEpisode(val)
            setSplitConfigs([])
          }}
          style={{ width: 300 }}
          placeholder="选择要拆分的分集"
          options={episodes?.map((e) => ({
            value: e.episodeId,
            label: `第${e.episodeIndex}集 - ${e.title} (${e.commentCount}条)`,
          }))}
        />
        {splitSourceEpisode && (
          <Button size="small" onClick={() => loadDetailData(splitSourceEpisode)}>
            查看详情
          </Button>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">拆分配置</span>
          <Button size="small" icon={<PlusOutlined />} onClick={addSplitConfig}>
            添加
          </Button>
        </div>
        <div className="space-y-2">
          {splitConfigs.map((config, index) => (
            <div
              key={config.id}
              className="flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-800 rounded"
            >
              <span className="w-16">新分集{index + 1}</span>
              <InputNumber
                value={config.episodeIndex}
                onChange={(val) => updateSplitConfig(config.id, 'episodeIndex', val)}
                addonBefore="集数"
                style={{ width: 100 }}
                min={1}
              />
              <InputNumber
                value={config.startTime}
                onChange={(val) => updateSplitConfig(config.id, 'startTime', val)}
                addonBefore="开始"
                addonAfter="秒"
                style={{ width: 140 }}
                min={0}
              />
              <InputNumber
                value={config.endTime}
                onChange={(val) => updateSplitConfig(config.id, 'endTime', val)}
                addonBefore="结束"
                addonAfter="秒"
                style={{ width: 140 }}
                min={0}
              />
              <Input
                value={config.title}
                onChange={(e) => updateSplitConfig(config.id, 'title', e.target.value)}
                placeholder="标题"
                style={{ width: 150 }}
              />
              <Button
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => removeSplitConfig(config.id)}
              />
            </div>
          ))}
          {splitConfigs.length === 0 && (
            <Empty description="点击添加按钮创建拆分配置" />
          )}
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Checkbox checked={splitDeleteSource} onChange={(e) => setSplitDeleteSource(e.target.checked)}>
          删除原分集
        </Checkbox>
        <Checkbox checked={splitResetTime} onChange={(e) => setSplitResetTime(e.target.checked)}>
          新分集时间从0开始
        </Checkbox>
      </div>

      <div className="flex justify-end">
        <Button
          type="primary"
          onClick={handleSplit}
          loading={splitLoading}
          disabled={!splitSourceEpisode || splitConfigs.length === 0}
        >
          执行拆分
        </Button>
      </div>
    </div>
  )

  // 渲染分集合并标签页
  const renderMergeTab = () => (
    <div className="space-y-4">
      <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded text-sm">
        <InfoCircleOutlined className="mr-2" />
        将多个分集的弹幕合并到一个新分集。可拖拽调整顺序，并为每个源分集设置时间偏移。
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 左侧：可选分集 */}
        <div>
          <div className="text-sm font-medium mb-2">可选分集</div>
          <div className="max-h-60 overflow-y-auto border rounded p-2 dark:border-gray-700">
            {availableMergeEpisodes.length > 0 ? (
              availableMergeEpisodes.map((ep) => (
                <div
                  key={ep.episodeId}
                  className="flex items-center justify-between p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer"
                  onClick={() => addMergeEpisode(ep.episodeId)}
                >
                  <div>
                    <div className="font-medium">第{ep.episodeIndex}集</div>
                    <div className="text-sm text-gray-500 truncate">{ep.title}</div>
                  </div>
                  <Button size="small" icon={<PlusOutlined />} />
                </div>
              ))
            ) : (
              <Empty description="所有分集已添加" />
            )}
          </div>
        </div>

        {/* 右侧：已选分集（可拖拽排序） */}
        <div>
          <div className="text-sm font-medium mb-2">合并顺序（可拖拽调整）</div>
          <div className="max-h-60 overflow-y-auto">
            {mergeEpisodes.length > 0 ? (
              <DndContext
                sensors={sensors}
                collisionDetection={closestCenter}
                onDragEnd={handleDragEnd}
              >
                <SortableContext
                  items={mergeEpisodes.map((e) => e.episodeId)}
                  strategy={verticalListSortingStrategy}
                >
                  {mergeEpisodes.map((item, index) => (
                    <SortableMergeItem
                      key={item.episodeId}
                      item={item}
                      index={index}
                      onOffsetChange={updateMergeOffset}
                      onRemove={removeMergeEpisode}
                    />
                  ))}
                </SortableContext>
              </DndContext>
            ) : (
              <Empty description="点击左侧分集添加" />
            )}
          </div>
        </div>
      </div>

      {/* 目标配置 */}
      <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded space-y-3">
        <div className="text-sm font-medium">目标分集配置</div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <span>集数：</span>
            <InputNumber
              value={mergeTargetIndex}
              onChange={setMergeTargetIndex}
              min={1}
              style={{ width: 80 }}
            />
          </div>
          <div className="flex items-center gap-2 flex-1">
            <span>标题：</span>
            <Input
              value={mergeTargetTitle}
              onChange={(e) => setMergeTargetTitle(e.target.value)}
              placeholder="输入合并后的标题"
              style={{ maxWidth: 300 }}
            />
          </div>
        </div>
        <div className="flex items-center gap-4">
          <Checkbox checked={mergeDeleteSources} onChange={(e) => setMergeDeleteSources(e.target.checked)}>
            删除原分集
          </Checkbox>
          <Checkbox checked={mergeDeduplicate} onChange={(e) => setMergeDeduplicate(e.target.checked)}>
            去除重复弹幕
          </Checkbox>
        </div>
      </div>

      <div className="flex justify-end">
        <Button
          type="primary"
          onClick={handleMerge}
          loading={mergeLoading}
          disabled={mergeEpisodes.length < 2 || !mergeTargetTitle.trim()}
        >
          执行合并 ({mergeEpisodes.length}个分集)
        </Button>
      </div>
    </div>
  )

  const tabItems = [
    {
      key: 'detail',
      label: (
        <span>
          <InfoCircleOutlined />
          弹幕详情
        </span>
      ),
      children: renderDetailTab(),
    },
    {
      key: 'offset',
      label: (
        <span>
          <ClockCircleOutlined />
          时间偏移
        </span>
      ),
      children: renderOffsetTab(),
    },
    {
      key: 'split',
      label: (
        <span>
          <ScissorOutlined />
          分集拆分
        </span>
      ),
      children: renderSplitTab(),
    },
    {
      key: 'merge',
      label: (
        <span>
          <MergeCellsOutlined />
          分集合并
        </span>
      ),
      children: renderMergeTab(),
    },
  ]

  return (
    <Modal
      title="弹幕编辑"
      open={open}
      onCancel={onCancel}
      footer={null}
      width={900}
      destroyOnClose
    >
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
      />
    </Modal>
  )
}