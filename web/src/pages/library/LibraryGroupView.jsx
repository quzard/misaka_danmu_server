/**
 * 弹幕库分组 + 拖拽容器
 * - 列表模式：单个 antd Table，dataSource 包含"分组头行"和"普通条目行"，保持列宽一致
 * - 卡片模式：平铺 grid，分组头是宽行，组内是卡片
 * - 拖拽：整行/整卡可拖，条目拖到条目上弹窗创建分组
 */
import { useState, useCallback } from 'react'
import { Input, Modal, Tag, Tooltip, Space, Table, Dropdown, theme, Button } from 'antd'
import { FolderOutlined, RightOutlined, DownOutlined, MenuOutlined } from '@ant-design/icons'
import {
  DndContext, DragOverlay, TouchSensor, MouseSensor,
  useSensor, useSensors, closestCenter,
  useDraggable, useDroppable,
} from '@dnd-kit/core'
import { MyIcon } from '@/components/MyIcon'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../../store/index.js'
import dayjs from 'dayjs'

const getImageSrc = (r) => {
  let src = r.localImagePath || r.imageUrl
  if (src?.startsWith('/images/')) src = src.replace('/images/', '/data/images/')
  return src
}

// ---- 可拖拽 + 可投放 Table Row（整行既能拖出，也能接收拖入）----
const DraggableTableRow = (props) => {
  const rowKey = props['data-row-key']
  const isGroupHeader = props['data-group-header'] === 'true'

  const { attributes, listeners, setNodeRef: setDragRef, isDragging } = useDraggable({
    id: `anime-${rowKey}`,
    data: { type: 'anime', animeId: rowKey },
    disabled: isGroupHeader,
  })

  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: `anime-${rowKey}`,
    data: { type: 'anime', animeId: rowKey },
    disabled: isGroupHeader,
  })

  // 合并 drag ref 和 drop ref 到同一个 <tr> 节点
  const setNodeRef = useCallback(
    (node) => { setDragRef(node); setDropRef(node) },
    [setDragRef, setDropRef]
  )

  if (isGroupHeader) {
    return <tr {...props} />
  }

  return (
    <tr
      ref={setNodeRef}
      {...props}
      {...listeners}
      {...attributes}
      style={{
        ...props.style,
        opacity: isDragging ? 0.45 : 1,
        cursor: 'grab',
        outline: isOver ? '2px solid #1677ff' : undefined,
        outlineOffset: isOver ? '-2px' : undefined,
      }}
    />
  )
}

// ---- 分组头展开/折叠状态 ----
const useGroupCollapse = () => {
  const [collapsed, setCollapsed] = useState({})
  const toggle = (id) => setCollapsed(prev => ({ ...prev, [id]: !prev[id] }))
  const isCollapsed = (id) => !!collapsed[id]
  return { toggle, isCollapsed }
}

// ---- 分组头名称编辑（单击进入编辑，带边框显示）----
const GroupNameEditor = ({ group, onRename }) => {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(group.name)
  const confirm = () => {
    if (name.trim() && name.trim() !== group.name) onRename(group.id, name.trim())
    setEditing(false)
  }
  if (editing) {
    return (
      <Input
        size="small"
        value={name}
        autoFocus
        style={{ width: 140, fontWeight: 600 }}
        onChange={e => setName(e.target.value)}
        onBlur={confirm}
        onPressEnter={confirm}
        onClick={e => e.stopPropagation()}
      />
    )
  }
  return (
    <span
      style={{
        fontWeight: 600, fontSize: 13,
        padding: '1px 7px', borderRadius: 4,
        border: '1px solid rgba(0,0,0,0.12)',
        cursor: 'text',
        background: 'rgba(255,255,255,0.6)',
        display: 'inline-block', lineHeight: '22px',
        userSelect: 'none',
      }}
      onClick={e => { e.stopPropagation(); setName(group.name); setEditing(true) }}
    >
      {group.name}
    </span>
  )
}



// ---- 卡片模式：小海报卡片 ----
const typeIconMap = {
  tv_series: 'tv',
  movie: 'movie',
  ova: 'tv',
  other: 'tv',
}

const AnimeCard = ({ record, onEdit, onDelete, onNavigate, onFavorite, onIncremental, onFinished, isDragging, isMobile }) => {
  const imageSrc = getImageSrc(record)
  const hasFav = record.sources?.some(s => s.isFavorited)
  const hasInc = record.sources?.some(s => s.incrementalRefreshEnabled)
  const allFin = record.sources?.length > 0 && record.sources.every(s => s.isFinished)
  const menuItems = [
    { key: 'fav', label: hasFav ? '取消标记' : '标记', icon: <MyIcon icon={hasFav ? 'favorites-fill' : 'favorites'} size={15} />, onClick: () => onFavorite?.(record) },
    { key: 'inc', label: hasInc ? '取消追更' : '追更', icon: <MyIcon icon={hasInc ? 'zengliang' : 'clock'} size={15} />, onClick: () => onIncremental?.(record) },
    { key: 'fin', label: allFin ? '取消完结' : '完结', icon: <MyIcon icon={allFin ? 'wanjie1' : 'wanjie'} size={15} />, onClick: () => onFinished?.(record) },
  ]
  return (
    <div className="group relative flex flex-col rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 hover:shadow-md transition-shadow select-none"
      style={{ opacity: isDragging ? 0.45 : 1 }}>
      {/* 封面区 */}
      <div className="relative overflow-hidden bg-gray-100 dark:bg-gray-700" style={{ aspectRatio: '2/3' }}
        onClick={e => { e.stopPropagation(); onNavigate?.(record) }}>
        {imageSrc
          ? <img src={imageSrc} alt={record.title} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200" />
          : <div className="w-full h-full flex items-center justify-center text-gray-300 text-4xl">🎬</div>
        }
        {/* 类型角标 */}
        <div className="absolute top-1 left-1 bg-black/60 rounded px-1.5 py-1 pointer-events-none">
          <MyIcon icon={typeIconMap[record.type] || 'tv'} size={isMobile ? 20 : 14} color="#fff" />
        </div>
        {/* 右上角状态标记（完结/追更/标记，从右到左） */}
        <div className="absolute top-1 right-1 flex items-center gap-0.5 pointer-events-none">
          {allFin && (
            <div className="bg-black/60 rounded px-1 py-0.5">
              <MyIcon icon="wanjie1" size={isMobile ? 16 : 12} color="#60a5fa" />
            </div>
          )}
          {hasInc && (
            <div className="bg-black/60 rounded px-1 py-0.5">
              <MyIcon icon="zengliang" size={isMobile ? 16 : 12} color="#4ade80" />
            </div>
          )}
          {hasFav && (
            <div className="bg-black/60 rounded px-1 py-0.5">
              <MyIcon icon="favorites-fill" size={isMobile ? 16 : 12} color="#facc15" />
            </div>
          )}
        </div>
        {/* 悬浮操作层 — 移动端常驻，PC端hover显示 */}
        <div className={`absolute inset-0 transition-all duration-200 flex items-end justify-end p-1 ${
          isMobile
            ? 'bg-black/20'
            : 'bg-black/0 group-hover:bg-black/20 opacity-0 group-hover:opacity-100'
        }`}>
          <Space size={isMobile ? 6 : 4} onClick={e => e.stopPropagation()}>
            <span className={`${isMobile ? 'w-8 h-8' : 'w-6 h-6'} bg-white/90 rounded flex items-center justify-center cursor-pointer hover:bg-white`} onClick={() => onEdit?.(record)}><MyIcon icon="edit" size={isMobile ? 16 : 12} /></span>
            <Dropdown menu={{ items: menuItems }} trigger={['click']}>
              <span className={`${isMobile ? 'w-8 h-8' : 'w-6 h-6'} bg-white/90 rounded flex items-center justify-center cursor-pointer hover:bg-white`}><MenuOutlined style={{ fontSize: isMobile ? 15 : 11 }} /></span>
            </Dropdown>
            <span className={`${isMobile ? 'w-8 h-8' : 'w-6 h-6'} bg-white/90 rounded flex items-center justify-center cursor-pointer hover:bg-white hover:text-red-500`} onClick={() => onDelete?.(record)}><MyIcon icon="delete" size={isMobile ? 16 : 12} /></span>
          </Space>
        </div>
      </div>
      {/* 信息区 */}
      <div className="p-1.5 flex flex-col gap-1">
        <Tooltip title={record.title}>
          <div className="text-xs font-medium leading-tight line-clamp-2" style={{ minHeight: '2.2em' }}>{record.title}</div>
        </Tooltip>
        <div className="text-xs text-gray-400 flex items-center gap-1">
          {record.year && <span>{record.year}</span>}
          {record.type !== 'movie' && record.season && <><span>·</span><span>S{record.season}</span></>}
          {record.episodeCount > 0 && <><span>·</span><span>{record.episodeCount}集</span></>}
        </div>
      </div>
    </div>
  )
}

// ---- 卡片模式：可拖拽包装 ----
const DraggableCard = ({ record, ...handlers }) => {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `anime-${record.animeId}`,
    data: { type: 'anime', animeId: record.animeId, groupId: record.groupId ?? null },
  })
  return (
    <div ref={setNodeRef} {...listeners} {...attributes} style={{ cursor: 'grab' }}>
      <AnimeCard record={record} isDragging={isDragging} {...handlers} />
    </div>
  )
}

// ---- 卡片模式：可投放（让 item 也能接收拖拽）----
const DroppableCardItem = ({ record, children }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: `anime-${record.animeId}`,
    data: { type: 'anime', animeId: record.animeId, groupId: record.groupId ?? null },
  })
  return (
    <div ref={setNodeRef} style={{ outline: isOver ? '2px solid #1677ff' : undefined, borderRadius: 8 }}>
      {children}
    </div>
  )
}

// ---- 移动端列表模式：大卡片样式（复原旧版 renderCard 风格，集成拖拽）----
const MobileLibraryCard = ({ record, onEdit, onDelete, onNavigate, onFavorite, onIncremental, onFinished }) => {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `anime-${record.animeId}`,
    data: { type: 'anime', animeId: record.animeId, groupId: record.groupId ?? null },
  })
  const imageSrc = (() => {
    let src = record.localImagePath || record.imageUrl
    if (src?.startsWith('/images/')) src = src.replace('/images/', '/data/images/')
    return src
  })()
  const hasFav = record.sources?.some(s => s.isFavorited)
  const hasInc = record.sources?.some(s => s.incrementalRefreshEnabled)
  const allFin = record.sources?.length > 0 && record.sources.every(s => s.isFinished)
  return (
    <div ref={setNodeRef} {...listeners} {...attributes}
      className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 mb-2 bg-white dark:bg-gray-800"
      style={{ opacity: isDragging ? 0.45 : 1, userSelect: 'none' }}>
      <div className="flex gap-3">
        {/* 海报（点击进入详情） */}
        <div className="relative flex-shrink-0 w-20 h-28 rounded overflow-hidden bg-gray-100 dark:bg-gray-700 cursor-pointer hover:opacity-80 transition-opacity"
          onClick={e => { e.stopPropagation(); onNavigate?.(record) }}>
          {imageSrc
            ? <img src={imageSrc} className="w-full h-full object-cover" alt={record.title} />
            : <div className="w-full h-full flex items-center justify-center text-gray-300"><MyIcon icon="image" size={32} /></div>
          }
        </div>
        {/* 信息 */}
        <div className="flex-1 space-y-2 min-w-0">
          <div className="font-bold text-base line-clamp-2">{record.title}</div>
          <div className="flex flex-wrap gap-1">
            <Tag color="blue" style={{ fontSize: 12 }}>{typeIconMap[record.type] === 'movie' ? '电影/剧场版' : record.type === 'tv_series' ? '电视节目' : record.type === 'ova' ? 'OVA' : '其他'}</Tag>
            {record.type !== 'movie' && record.season > 1 && <Tag style={{ fontSize: 12 }}>第{record.season}季</Tag>}
            {record.year && <Tag style={{ fontSize: 12 }}>{record.year}年</Tag>}
          </div>
          <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 gap-1">
            <span>集数: {record.episodeCount || 0}</span>
            <span className="mx-1">·</span>
            <span>源: {record.sourceCount || 0}</span>
            {/* 状态图标：放在源数量右边 */}
            {(hasFav || hasInc || allFin) && (
              <>
                <span className="mx-1">·</span>
                {allFin && <MyIcon icon="wanjie1" size={13} color="#60a5fa" />}
                {hasInc && <MyIcon icon="zengliang" size={13} color="#4ade80" />}
                {hasFav && <MyIcon icon="favorites-fill" size={13} color="#facc15" />}
              </>
            )}
          </div>
        </div>
      </div>
      {/* 操作按钮行 */}
      <div className="flex justify-around pt-2 mt-2 border-t border-gray-200 dark:border-gray-700"
        onClick={e => e.stopPropagation()}>
        <Button size="small" type="text" icon={<MyIcon icon="edit" size={16} />}
          onClick={() => onEdit?.(record)}>编辑</Button>
        <Button size="small" type="text" icon={<MyIcon icon="book" size={16} />}
          onClick={() => onNavigate?.(record)}>详情</Button>
        <Dropdown menu={{ items: [
          { key: 'fav', label: hasFav ? '取消标记' : '标记', icon: <MyIcon icon={hasFav ? 'favorites-fill' : 'favorites'} size={15} />, onClick: () => onFavorite?.(record) },
          { key: 'inc', label: hasInc ? '取消追更' : '追更', icon: <MyIcon icon={hasInc ? 'zengliang' : 'clock'} size={15} />, onClick: () => onIncremental?.(record) },
          { key: 'fin', label: allFin ? '取消完结' : '完结', icon: <MyIcon icon={allFin ? 'wanjie1' : 'wanjie'} size={15} />, onClick: () => onFinished?.(record) },
        ]}} trigger={['click']}>
          <Button size="small" type="text" icon={<MenuOutlined />}>更多</Button>
        </Dropdown>
        <Button size="small" type="text" danger icon={<MyIcon icon="delete" size={16} />}
          onClick={() => onDelete?.(record)}>删除</Button>
      </div>
    </div>
  )
}

// ---- 折叠状态的分组卡片（同时是可投放区域）----
const CollapsedGroupDropzone = ({ group, items, onToggle, onDelete, headerBg, isMobile }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: `group-${group.id}`,
    data: { type: 'group', groupId: group.id },
  })
  const previews = items.slice(0, 4)

  // 移动端：大卡片样式（和普通条目一致）
  if (isMobile) {
    return (
      <div ref={setNodeRef}
        className="border border-gray-200 dark:border-gray-700 rounded-lg p-3 mb-2 bg-white dark:bg-gray-800"
        style={{ outline: isOver ? '2px solid #1677ff' : undefined, outlineOffset: -2 }}
      >
        <div className="flex gap-3 cursor-pointer" onClick={onToggle}>
          {/* 2×2 海报拼图 */}
          <div style={{
            width: 80, height: 112, display: 'grid', flexShrink: 0,
            gridTemplateColumns: '1fr 1fr', gridTemplateRows: '1fr 1fr',
            gap: 2, borderRadius: 6, overflow: 'hidden', background: '#f0f0f0',
          }}>
            {previews.map((r, i) => {
              const src = r.localImagePath || r.imageUrl
              const imgSrc = src?.startsWith('/images/') ? src.replace('/images/', '/data/images/') : src
              return imgSrc
                ? <img key={i} src={imgSrc} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="" />
                : <div key={i} style={{ width: '100%', height: '100%', background: '#e0e0e0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14 }}>🎬</div>
            })}
            {Array.from({ length: Math.max(0, 4 - previews.length) }).map((_, i) => (
              <div key={`e-${i}`} style={{ background: '#ebebeb' }} />
            ))}
          </div>
          {/* 分组信息 */}
          <div className="flex-1 min-w-0 flex flex-col justify-center gap-2">
            <div className="flex items-center gap-1 flex-wrap">
              <FolderOutlined style={{ color: '#faad14', fontSize: 18 }} />
              <span className="font-bold" style={{ fontSize: 16 }}>{group.name}</span>
              <Tag color="orange" style={{ fontSize: 13 }}>{items.length}部</Tag>
            </div>
            {isOver
              ? <div style={{ fontSize: 13, color: '#1677ff', fontWeight: 500 }}>松开以加入此分组</div>
              : <div style={{ fontSize: 13, color: '#aaa' }}>点击展开 · 向上拖拽可加入</div>
            }
          </div>
        </div>
        {/* 操作按钮行 */}
        <div className="flex justify-center gap-2 pt-2 mt-2 border-t border-gray-200 dark:border-gray-700">
          <Button size="small" type="text" danger icon={<MyIcon icon="delete" size={16} />}
            onClick={e => { e.stopPropagation(); onDelete() }}>解散分组</Button>
        </div>
      </div>
    )
  }

  // PC 端：原来的横向样式
  return (
    <div ref={setNodeRef} style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '4px 8px',
      background: isOver ? 'rgba(22,119,255,0.06)' : (headerBg || 'rgba(250,173,20,0.04)'),
      cursor: 'pointer', userSelect: 'none',
      outline: isOver ? '2px solid #1677ff' : 'none',
      outlineOffset: '-2px', borderRadius: 5,
    }} onClick={onToggle}>
      {/* 2×2 海报拼图，与条目单张海报等尺寸（56×80） */}
      <div style={{
        width: 56, height: 80, display: 'grid', flexShrink: 0,
        gridTemplateColumns: '1fr 1fr', gridTemplateRows: '1fr 1fr',
        gap: 1, borderRadius: 4, overflow: 'hidden', background: '#f0f0f0',
      }}>
        {previews.map((r, i) => {
          const src = r.localImagePath || r.imageUrl
          const imgSrc = src?.startsWith('/images/') ? src.replace('/images/', '/data/images/') : src
          return imgSrc
            ? <img key={i} src={imgSrc} style={{ width: '100%', height: '100%', objectFit: 'cover' }} alt="" />
            : <div key={i} style={{ width: '100%', height: '100%', background: '#e0e0e0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10 }}>🎬</div>
        })}
        {Array.from({ length: Math.max(0, 4 - previews.length) }).map((_, i) => (
          <div key={`e-${i}`} style={{ background: '#ebebeb' }} />
        ))}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <FolderOutlined style={{ color: '#faad14', fontSize: 13 }} />
          <RightOutlined style={{ fontSize: 9, color: '#aaa' }} />
          <span style={{ fontWeight: 600, fontSize: 13 }}>{group.name}</span>
          <Tag color="default" style={{ marginLeft: 2 }}>{items.length} 个条目</Tag>
        </div>
        {/* 收录时间显示在第二行（副标题），避免与 Table 固定右列对齐问题 */}
        {items.length > 0 && (() => {
          const latestAt = items.reduce((max, r) => (!max || r.createdAt > max ? r.createdAt : max), null)
          return <div style={{ fontSize: 12, color: '#aaa', marginTop: 2 }}>
            最新收录：{dayjs(latestAt).format('YYYY-MM-DD HH:mm')}
          </div>
        })()}
        {isOver && <div style={{ fontSize: 11, color: '#1677ff', marginTop: 2 }}>松开以加入此分组</div>}
      </div>
      <Button
        size="small"
        type="text"
        danger
        icon={<MyIcon icon="delete" size={16} />}
        style={{ flexShrink: 0, marginRight: 40 }}
        onClick={e => { e.stopPropagation(); onDelete() }}
      >
        拆分分组
      </Button>
    </div>
  )
}

// ---- 拆分投放区（拖出分组时显示在全局列头上方）----
const UngroupDropzone = ({ visible, children }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: 'ungroup-zone',
    data: { type: 'ungroup' },
    disabled: !visible,
  })
  return (
    <div ref={setNodeRef} style={{ position: 'relative' }}>
      {children}
      {visible && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 10,
          border: `2px dashed ${isOver ? '#1677ff' : '#aaa'}`,
          borderRadius: 6,
          background: isOver ? 'rgba(22,119,255,0.1)' : 'rgba(255,255,255,0.75)',
          backdropFilter: 'blur(2px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          gap: 6,
          color: isOver ? '#1677ff' : '#888',
          fontSize: 14, fontWeight: 600,
          pointerEvents: 'none', // 让拖拽事件穿透到下层 setNodeRef
          transition: 'all 0.15s',
        }}>
          <span style={{ fontSize: 18 }}>📤</span>
          <span>拖到此处拆分出分组</span>
        </div>
      )}
    </div>
  )
}

// ---- 移动端专用：固定悬浮拆分投放区（position:fixed，覆盖在顶部控制区域上方）----
const MobileUngroupOverlay = ({ visible }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: 'ungroup-zone',
    data: { type: 'ungroup' },
    disabled: !visible,
  })
  if (!visible) return null
  return (
    <div
      ref={setNodeRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        height: 260,
        zIndex: 1200,
        border: `2px dashed ${isOver ? '#1677ff' : '#aaa'}`,
        borderRadius: 0,
        background: isOver ? 'rgba(22,119,255,0.13)' : 'rgba(255,255,255,0.88)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        color: isOver ? '#1677ff' : '#888',
        fontSize: 16,
        fontWeight: 600,
        pointerEvents: 'all',
        transition: 'all 0.15s',
        boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
      }}
    >
      <span style={{ fontSize: 22 }}>📤</span>
      <span>拖到此处拆分出分组</span>
    </div>
  )
}

// ---- 卡片模式：折叠分组卡片（卡片样式，2×2 海报拼图，支持 drop）----
const CollapsedGroupCard = ({ group, items, onClick, onDelete }) => {
  const { isOver, setNodeRef } = useDroppable({
    id: `group-${group.id}`,
    data: { type: 'group', groupId: group.id },
  })
  const previews = items.slice(0, 4)
  return (
    <div
      ref={setNodeRef}
      className="group relative flex flex-col rounded-lg overflow-hidden bg-white dark:bg-gray-800 hover:shadow-md transition-shadow cursor-pointer"
      style={{
        width: '100%',
        border: isOver ? '2px solid #1677ff' : '1px solid rgba(0,0,0,0.1)',
        outline: isOver ? undefined : 'none',
      }}
    >
      {/* 封面区：2×2 海报拼图 */}
      <div className="relative aspect-[2/3] overflow-hidden bg-gray-100 dark:bg-gray-700"
        onClick={onClick}>
        <div style={{
          width: '100%', height: '100%', display: 'grid',
          gridTemplateColumns: '1fr 1fr', gridTemplateRows: '1fr 1fr',
          gap: 2, padding: 2,
        }}>
          {previews.map((r, i) => {
            const src = r.localImagePath || r.imageUrl
            const imgSrc = src?.startsWith('/images/') ? src.replace('/images/', '/data/images/') : src
            return imgSrc ? (
              <img key={i} src={imgSrc}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
                alt="" />
            ) : (
              <div key={i} className="w-full h-full flex items-center justify-center text-gray-300 text-2xl bg-gray-200 dark:bg-gray-600">
                🎬
              </div>
            )
          })}
          {Array.from({ length: Math.max(0, 4 - previews.length) }).map((_, i) => (
            <div key={`e-${i}`} className="bg-gray-200 dark:bg-gray-600" />
          ))}
        </div>
        {/* 拖拽悬停提示层 */}
        {isOver && (
          <div className="absolute inset-0 bg-blue-500/20 flex items-center justify-center z-10 pointer-events-none">
            <span className="text-xs text-blue-600 font-medium bg-white/90 px-2 py-1 rounded">加入此分组</span>
          </div>
        )}
        {/* 悬浮操作层 */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/20 transition-all duration-200 flex items-end justify-end p-2 opacity-0 group-hover:opacity-100">
          <Space size={6} onClick={e => e.stopPropagation()}>
            <Tooltip title="解散分组">
              <span className="w-7 h-7 bg-white/90 rounded flex items-center justify-center cursor-pointer hover:bg-white hover:text-red-500"
                onClick={onDelete}>
                <MyIcon icon="delete" size={14} />
              </span>
            </Tooltip>
          </Space>
        </div>
      </div>

      {/* 信息区 */}
      <div className="p-1.5 flex flex-col gap-1" onClick={onClick}>
        <Tooltip title={group.name}>
          <div className="text-xs font-medium leading-tight line-clamp-2 flex items-start gap-1" style={{ minHeight: '2.2em' }}>
            <FolderOutlined style={{ color: '#faad14', fontSize: 12, flexShrink: 0, marginTop: 2 }} />
            <span className="flex-1">{group.name}</span>
          </div>
        </Tooltip>
        <div className="text-xs text-gray-400">
          {items.length} 个条目
        </div>
      </div>
    </div>
  )
}

const LibraryGroupView = ({
  list, groups, viewMode,
  columns,           // antd Table columns（列表模式）
  onEdit, onDelete, onNavigate, onFavorite, onIncremental, onFinished,
  onSetGroup, onCreateGroup, onRenameGroup, onDeleteGroup, onDeleteGroupSilent,
}) => {
  const { token } = theme.useToken()
  const { toggle, isCollapsed } = useGroupCollapse()

  // 卡片模式：分组详情视图状态
  const [viewingGroupId, setViewingGroupId] = useState(null)
  const [activeItem, setActiveItem] = useState(null)
  const [isDraggingFromGroup, setIsDraggingFromGroup] = useState(false)
  const [nameModalOpen, setNameModalOpen] = useState(false)
  const [pendingInfo, setPendingInfo] = useState(null)
  const [newGroupName, setNewGroupName] = useState('')

  // 鼠标：移动 8px 触发；触摸：长按 400ms 且移动容差 8px 才触发，避免轻扫误触
  const sensors = useSensors(
    useSensor(MouseSensor, {
      activationConstraint: { distance: 8 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 400, tolerance: 8 },
    }),
  )

  const handleDragStart = ({ active }) => {
    const item = list.find(a => `anime-${a.animeId}` === active.id) || null
    setActiveItem(item)
    // 如果拖拽的条目属于某个分组，标记为"从分组拖出"
    setIsDraggingFromGroup(!!(item?.groupId))
  }

  const handleDragEnd = ({ active, over }) => {
    setActiveItem(null)
    setIsDraggingFromGroup(false)
    if (!over || !active) return
    const draggedId = Number(active.id.replace('anime-', ''))
    const dragged = list.find(a => a.animeId === draggedId)
    if (!dragged) return

    // 拖入拆分区 → 移出分组，如果是最后一个条目则顺便静默删除空分组
    if (over.id === 'ungroup-zone') {
      if (dragged.groupId) {
        const groupItems = list.filter(a => a.groupId === dragged.groupId)
        onSetGroup(dragged.animeId, null)
        if (groupItems.length === 1) {
          const emptyGroup = groups.find(g => g.id === dragged.groupId)
          if (emptyGroup) onDeleteGroupSilent(emptyGroup)
        }
      }
      return
    }

    if (over.data?.current?.type === 'group') {
      const targetGroupId = over.data.current.groupId
      if (targetGroupId !== (dragged.groupId ?? null)) onSetGroup(dragged.animeId, targetGroupId)
      return
    }

    if (over.data?.current?.type === 'anime') {
      const overId = Number(over.id.replace('anime-', ''))
      const overItem = list.find(a => a.animeId === overId)
      if (!overItem || overItem.animeId === dragged.animeId) return
      if (overItem.groupId && overItem.groupId === dragged.groupId) return

      if (overItem.groupId) {
        onSetGroup(dragged.animeId, overItem.groupId)
      } else if (dragged.groupId) {
        onSetGroup(overItem.animeId, dragged.groupId)
      } else {
        setPendingInfo({ draggedId: dragged.animeId, overId: overItem.animeId })
        setNewGroupName('')
        setNameModalOpen(true)
      }
    }
  }

  const confirmCreate = () => {
    if (!newGroupName.trim() || !pendingInfo) return
    onCreateGroup(newGroupName.trim(), [pendingInfo.draggedId, pendingInfo.overId])
    setNameModalOpen(false)
    setPendingInfo(null)
    setNewGroupName('')
  }

  const isMobile = useAtomValue(isMobileAtom)

  // 按分组聚合（同时计算每个分组在 list 中的代表排序位置）
  const grouped = {}
  groups.forEach(g => { grouped[g.id] = [] })
  const ungrouped = []
  list.forEach((item, idx) => {
    if (item.groupId && grouped[item.groupId] !== undefined) grouped[item.groupId].push({ ...item, _sortIndex: idx })
    else ungrouped.push({ ...item, _sortIndex: idx })
  })

  // 每个分组的代表排序位置 = 分组内条目中最小的 _sortIndex（最先出现的条目）
  const groupSortIndex = {}
  groups.forEach(g => {
    const items = grouped[g.id] || []
    groupSortIndex[g.id] = items.length > 0 ? Math.min(...items.map(i => i._sortIndex)) : Infinity
  })

  // 分组按代表排序位置排序（而非固定 sortOrder），让分组参与全局排序
  const sortedGroups = [...groups].sort((a, b) => groupSortIndex[a.id] - groupSortIndex[b.id])

  const handlers = { onEdit, onDelete, onNavigate, onFavorite, onIncremental, onFinished, isMobile }

  // ---- 列表模式渲染 ----
  const renderListMode = () => {
    // 分组展开时：分组头 + Table（列头由外部全局列头统一显示）
    const renderGroupExpanded = (g, items) => (
      <>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px',
          background: token.colorFillAlter, cursor: 'pointer', userSelect: 'none',
          borderBottom: '1px dashed #d9d9d9',
        }} onClick={() => toggle(g.id)}>
          <FolderOutlined style={{ color: '#faad14', fontSize: 14 }} />
          <DownOutlined style={{ fontSize: 9, color: '#aaa' }} />
          <GroupNameEditor group={g} onRename={onRenameGroup} />
          <Tag color="default" style={{ marginLeft: 2 }}>{items.length} 个条目</Tag>
          {isMobile
            ? <Button size="small" type="text" danger icon={<MyIcon icon="delete" size={15} />}
                style={{ marginLeft: 'auto' }}
                onClick={e => { e.stopPropagation(); onDeleteGroup(g) }}>拆分分组</Button>
            : <Button
                size="small"
                type="text"
                danger
                icon={<MyIcon icon="delete" size={16} />}
                style={{ marginLeft: 'auto', marginRight: 56 }}
                onClick={e => { e.stopPropagation(); onDeleteGroup(g) }}
              >
                拆分分组
              </Button>
          }
        </div>
        {isMobile
          ? <div className="px-1 pt-1">{items.map(record => (
              <DroppableCardItem key={record.animeId} record={record}>
                <MobileLibraryCard record={record} {...handlers} />
              </DroppableCardItem>
            ))}</div>
          : <Table
              dataSource={items}
              columns={columns}
              loading={false}
              rowKey="animeId"
              pagination={false}
              size="middle"
              showHeader={false}
              components={{ body: { row: DraggableTableRow } }}
              onRow={(record) => ({
                'data-row-key': record.animeId,
                'data-group-header': 'false',
              })}
            />
        }
      </>
    )

    // 构建统一渲染列表：分组块 + 未分组条目，按后端排序位置混排
    const allListItems = [
      ...sortedGroups.map(g => ({ type: 'group', group: g, items: grouped[g.id] || [], sortIndex: groupSortIndex[g.id] })),
      ...ungrouped.map(record => ({ type: 'anime', record, sortIndex: record._sortIndex })),
    ].sort((a, b) => a.sortIndex - b.sortIndex)

    // 把连续的 anime 条目合并成批次，减少 Table 实例数量
    const renderChunks = []
    let currentChunk = null
    allListItems.forEach((entry, idx) => {
      if (entry.type === 'group') {
        if (currentChunk) { renderChunks.push(currentChunk); currentChunk = null }
        renderChunks.push({ type: 'group', ...entry, key: `g-${entry.group.id}` })
      } else {
        if (!currentChunk) currentChunk = { type: 'chunk', records: [], key: `chunk-${idx}` }
        currentChunk.records.push(entry.record)
      }
    })
    if (currentChunk) renderChunks.push(currentChunk)

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {renderChunks.map(chunk => {
          if (chunk.type === 'group') {
            const { group: g, items } = chunk
            return (
              <div key={g.id} style={{ border: '1px dashed #d9d9d9', borderRadius: 6, marginBottom: 12 }}>
                {isCollapsed(g.id)
                  ? <CollapsedGroupDropzone
                      group={g}
                      items={items}
                      onToggle={() => toggle(g.id)}
                      onDelete={() => onDeleteGroup(g)}
                      headerBg={token.colorFillAlter}
                      isMobile={isMobile}
                    />
                  : renderGroupExpanded(g, items)
                }
              </div>
            )
          }
          // type === 'chunk'：一批连续未分组条目
          const { records } = chunk
          return isMobile
            ? <div key={chunk.key}>{records.map(record => (
                <DroppableCardItem key={record.animeId} record={record}>
                  <MobileLibraryCard record={record} {...handlers} />
                </DroppableCardItem>
              ))}</div>
            : <Table
                key={chunk.key}
                dataSource={records}
                columns={columns}
                loading={false}
                rowKey="animeId"
                pagination={false}
                size="middle"
                showHeader={false}
                components={{ body: { row: DraggableTableRow } }}
                onRow={(r) => ({
                  'data-row-key': r.animeId,
                  'data-group-header': 'false',
                })}
              />
        })}
      </div>
    )
  }

  // ---- 卡片模式渲染 ----
  const renderCardMode = () => {
    const renderItems = (items) => (
      <div className="grid gap-2" style={{ gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(auto-fill, minmax(120px, 1fr))' }}>
        {items.map(record => (
          <DroppableCardItem key={record.animeId} record={record}>
            <DraggableCard record={record} {...handlers} />
          </DroppableCardItem>
        ))}
      </div>
    )

    // 如果正在查看某个分组的详情
    if (viewingGroupId) {
      const viewingGroup = groups.find(g => g.id === viewingGroupId)
      const groupItems = grouped[viewingGroupId] || []

      return (
        <div>
          {/* 面包屑导航（带拆分 dropzone）*/}
          <UngroupDropzone visible={isDraggingFromGroup}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 16, padding: '8px 0', minHeight: 44, width: '100%' }}>
              <span
                className="cursor-pointer hover:text-primary text-gray-500 text-sm"
                onClick={() => setViewingGroupId(null)}
              >
                弹幕库
              </span>
              <span className="text-gray-300 text-sm">/</span>
              <FolderOutlined style={{ color: '#faad14', fontSize: 13 }} />
              <span style={{ fontWeight: 600, fontSize: 14 }}>{viewingGroup?.name || '分组'}</span>
              <Tag color="orange" style={{ marginLeft: 2 }}>{groupItems.length}</Tag>
              <div style={{ flex: 1 }} />
              {/* 返回按钮 */}
              <Button
                size="small"
                onClick={() => setViewingGroupId(null)}
              >
                返回
              </Button>
              {/* 解散分组按钮 */}
              <Button
                size="small"
                danger
                icon={<MyIcon icon="delete" size={14} />}
                onClick={() => {
                  onDeleteGroup(viewingGroup)
                  setViewingGroupId(null)
                }}
              >
                解散分组
              </Button>
            </div>
          </UngroupDropzone>
          {/* 组内卡片网格 */}
          {renderItems(groupItems)}
        </div>
      )
    }

    // 如果没有分组，直接显示所有条目
    if (groups.length === 0) return renderItems(list)

    // 主列表：分组卡片 + 未分组条目，按后端排序位置混排
    const allItems = [
      ...sortedGroups.map(g => ({ type: 'group', group: g, items: grouped[g.id] || [], sortIndex: groupSortIndex[g.id] })),
      ...ungrouped.map(item => ({ type: 'item', item, sortIndex: item._sortIndex })),
    ].sort((a, b) => a.sortIndex - b.sortIndex)

    return (
      <div
        className="grid gap-2"
        style={{
          gridTemplateColumns: isMobile ? 'repeat(2, 1fr)' : 'repeat(auto-fill, minmax(120px, 1fr))',
        }}
      >
        {allItems.map((entry) => {
          if (entry.type === 'group') {
            const { group, items } = entry
            return (
              <CollapsedGroupCard
                key={group.id}
                group={group}
                items={items}
                onClick={() => setViewingGroupId(group.id)}
                onDelete={() => onDeleteGroup(group)}
              />
            )
          } else {
            // 直接渲染单个条目卡片
            const record = entry.item
            return (
              <DroppableCardItem key={record.animeId} record={record}>
                <DraggableCard record={record} {...handlers} />
              </DroppableCardItem>
            )
          }
        })}
      </div>
    )
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter}
      onDragStart={handleDragStart} onDragEnd={handleDragEnd}>
      {/* 卡片模式无需列头；列表模式统一显示一个全局列头（拖拽时变为拆分区）；移动端不显示列头 */}
      {viewMode !== 'card' && !isMobile && (
        <UngroupDropzone visible={isDraggingFromGroup}>
          <Table
            dataSource={[]}
            columns={columns}
            loading={false}
            rowKey="animeId"
            pagination={false}
            size="middle"
            showHeader={true}
            style={{ marginBottom: 0 }}
            locale={{ emptyText: <></> }}
          />
        </UngroupDropzone>
      )}

      {viewMode === 'card' ? renderCardMode() : renderListMode()}

      {/* 移动端：拖拽分组内条目时，固定悬浮在顶部控制区域上方的拆分投放区 */}
      {isMobile && <MobileUngroupOverlay visible={isDraggingFromGroup} />}

      <DragOverlay>
        {activeItem && (
          <div style={{ background: '#fff', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', borderRadius: 6, padding: '6px 14px', border: '1px solid #e6f4ff' }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>{activeItem.title}</span>
          </div>
        )}
      </DragOverlay>

      <Modal title="为新分组命名" open={nameModalOpen}
        onOk={confirmCreate} onCancel={() => { setNameModalOpen(false); setPendingInfo(null) }}
        okText="创建" cancelText="取消" okButtonProps={{ disabled: !newGroupName.trim() }}>
        <Input placeholder="请输入分组名称" value={newGroupName}
          onChange={e => setNewGroupName(e.target.value)} onPressEnter={confirmCreate} autoFocus />
      </Modal>
    </DndContext>
  )
}

export default LibraryGroupView
