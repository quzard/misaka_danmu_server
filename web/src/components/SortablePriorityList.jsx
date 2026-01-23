import { useState, useEffect } from 'react'
import { Switch, Spin, Tag, Tooltip } from 'antd'
import { HolderOutlined, InfoCircleOutlined } from '@ant-design/icons'
import {
  DndContext,
  closestCorners,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { getConfig, setConfig } from '../apis'
import { useMessage } from '../MessageContext'

/**
 * 拖拽项组件
 */
const SortableItem = ({ item, onToggle, showSwitch = true }) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.key })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center justify-between p-3 mb-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
    >
      <div className="flex items-center gap-3">
        <span
          {...attributes}
          {...listeners}
          className="cursor-grab text-gray-400 hover:text-gray-600"
        >
          <HolderOutlined />
        </span>
        <div>
          <div className="font-medium">{item.name}</div>
          {item.description && (
            <div className="text-xs text-gray-500">{item.description}</div>
          )}
        </div>
      </div>
      {showSwitch && (
        <Switch
          checked={item.enabled}
          onChange={(checked) => onToggle(item.key, checked)}
          size="small"
        />
      )}
    </div>
  )
}

/**
 * 通用拖拽排序优先级列表组件
 * 
 * @param {Object} props
 * @param {string} props.configKey - 配置存储的键名
 * @param {Array} props.availableItems - 可用项列表 [{key, name, description}]
 * @param {string} props.title - 标题
 * @param {string} props.titleIcon - 标题图标（emoji）
 * @param {string} props.description - 描述文字
 * @param {Array} props.tips - 使用说明列表
 * @param {boolean} props.showSwitch - 是否显示开关（默认true）
 * @param {Function} props.onConfigChange - 配置变化回调（可选）
 */
export const SortablePriorityList = ({
  configKey,
  availableItems = [],
  title = '优先级配置',
  titleIcon = '🔢',
  description = '',
  tips = [],
  showSwitch = true,
  onConfigChange,
}) => {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activeId, setActiveId] = useState(null)
  const messageApi = useMessage()

  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 5 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 100, tolerance: 5 } })
  )

  useEffect(() => {
    loadConfig()
  }, [configKey])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const res = await getConfig(configKey)
      const savedConfig = res.data?.value

      if (savedConfig) {
        const parsed = JSON.parse(savedConfig)
        // 合并保存的配置和可用项列表
        const merged = parsed.map(saved => {
          const item = availableItems.find(i => i.key === saved.key)
          return item ? { ...item, enabled: saved.enabled } : null
        }).filter(Boolean)

        // 添加新增的项（如果有）
        availableItems.forEach(item => {
          if (!merged.find(m => m.key === item.key)) {
            merged.push({ ...item, enabled: true })
          }
        })
        setItems(merged)
      } else {
        setItems(availableItems.map(i => ({ ...i, enabled: true })))
      }
    } catch (err) {
      console.error('加载配置失败:', err)
      setItems(availableItems.map(i => ({ ...i, enabled: true })))
    } finally {
      setLoading(false)
    }
  }

  const saveConfig = async (newItems) => {
    try {
      setSaving(true)
      const configValue = JSON.stringify(newItems.map(i => ({ key: i.key, enabled: i.enabled })))
      await setConfig(configKey, configValue)
      messageApi.success('保存成功')
      onConfigChange?.(newItems)
    } catch (err) {
      messageApi.error('保存失败: ' + (err.response?.data?.detail || err.message))
    } finally {
      setSaving(false)
    }
  }

  const handleDragStart = (event) => {
    setActiveId(event.active.id)
  }

  const handleDragEnd = (event) => {
    const { active, over } = event
    setActiveId(null)

    if (over && active.id !== over.id) {
      const oldIndex = items.findIndex(i => i.key === active.id)
      const newIndex = items.findIndex(i => i.key === over.id)
      const newItems = arrayMove(items, oldIndex, newIndex)
      setItems(newItems)
      saveConfig(newItems)
    }
  }

  const handleToggle = (key, enabled) => {
    const newItems = items.map(i => i.key === key ? { ...i, enabled } : i)
    setItems(newItems)
    saveConfig(newItems)
  }

  const activeItem = activeId ? items.find(i => i.key === activeId) : null

  if (loading) {
    return <div className="py-4 text-center"><Spin /></div>
  }

  return (
    <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-medium m-0">{titleIcon} {title}</h3>
          {description && (
            <Tooltip title={description}>
              <InfoCircleOutlined className="text-gray-400" />
            </Tooltip>
          )}
        </div>
        {saving && <Tag color="processing">保存中...</Tag>}
      </div>

      {description && (
        <div className="text-sm text-gray-500 mb-3">{description}</div>
      )}

      <DndContext
        sensors={sensors}
        collisionDetection={closestCorners}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={items.map(i => i.key)}
          strategy={verticalListSortingStrategy}
        >
          {items.map(item => (
            <SortableItem
              key={item.key}
              item={item}
              onToggle={handleToggle}
              showSwitch={showSwitch}
            />
          ))}
        </SortableContext>

        <DragOverlay>
          {activeItem && (
            <div className="flex items-center justify-between p-3 rounded-lg border-2 border-blue-400 bg-white dark:bg-gray-800 shadow-lg">
              <div className="flex items-center gap-3">
                <HolderOutlined className="text-gray-400" />
                <div>
                  <div className="font-medium">{activeItem.name}</div>
                  {activeItem.description && (
                    <div className="text-xs text-gray-500">{activeItem.description}</div>
                  )}
                </div>
              </div>
            </div>
          )}
        </DragOverlay>
      </DndContext>

      {tips.length > 0 && (
        <div className="mt-4 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg text-sm text-gray-500">
          <div className="font-medium mb-1">💡 使用说明</div>
          <ul className="list-disc list-inside space-y-1 m-0">
            {tips.map((tip, index) => (
              <li key={index}>{tip}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
