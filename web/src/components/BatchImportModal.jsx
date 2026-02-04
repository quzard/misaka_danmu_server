import {
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Segmented,
  Spin,
  Tag,
  Tooltip,
  Upload,
  message,
} from 'antd'
import { useEffect, useRef, useState } from 'react'
import { batchManualImport, validateImportUrl, importFromUrl } from '../apis'
import {
  CloseCircleOutlined,
  CloudUploadOutlined,
  LinkOutlined,
  UploadOutlined,
  CheckCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useMessage } from '../MessageContext'

import { MyIcon } from '@/components/MyIcon'

import {
  closestCorners,
  DndContext,
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
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

export const BatchImportModal = ({ open, sourceInfo, onCancel, onSuccess }) => {
  const messageApi = useMessage()
  const [loading, setLoading] = useState(false)
  // 导入模式: 'xml' | 'url'
  const [importMode, setImportMode] = useState('xml')
  // 存储解析后的XML数据列表
  const [xmlDataList, setXmlDataList] = useState([])
  const [fileList, setFileList] = useState([])
  // 存储上传状态
  const [uploading, setUploading] = useState(false)
  // 用于跟踪文件拖入顺序的计数器
  const orderCounter = useRef(0)
  // 存储文件ID与拖入顺序的映射
  const fileOrderMap = useRef({})
  const dragOverlayRef = useRef(null)
  const uploadRef = useRef(null)

  const [pageSize, setPageSize] = useState(10)
  const [activeItem, setActiveItem] = useState(null)

  // URL导入相关状态
  const [urlInput, setUrlInput] = useState('')
  const [urlValidating, setUrlValidating] = useState(false)
  const [urlValidationResult, setUrlValidationResult] = useState(null)
  const [urlTitle, setUrlTitle] = useState('')
  const [urlSeason, setUrlSeason] = useState(1)
  const [urlMediaType, setUrlMediaType] = useState('tv_series')
  const [urlEpisodeIndex, setUrlEpisodeIndex] = useState(1)  // 非自定义源URL导入时的集数

  const sensors = useSensors(
    useSensor(MouseSensor, {
      activationConstraint: {
        distance: 5,
      },
    }),
    useSensor(TouchSensor, {
      activationConstraint: {
        distance: 8,
        delay: 100,
      },
    })
  )

  // 判断是否为自定义源
  const isCustomSource = sourceInfo?.providerName === 'custom'

  // URL校验
  const handleValidateUrl = async () => {
    if (!urlInput.trim()) {
      messageApi.warning('请输入URL')
      return
    }

    setUrlValidating(true)
    setUrlValidationResult(null)

    try {
      const res = await validateImportUrl({ url: urlInput.trim() })
      if (res.data) {
        // 对于非自定义源，检查 URL 的 provider 是否匹配当前源
        if (!isCustomSource && res.data.isValid) {
          const currentProvider = sourceInfo?.providerName?.toLowerCase()
          const urlProvider = res.data.provider?.toLowerCase()
          if (currentProvider !== urlProvider) {
            setUrlValidationResult({
              isValid: false,
              provider: res.data.provider,
              errorMessage: `URL来源 (${res.data.provider}) 与当前源 (${sourceInfo?.providerName}) 不匹配，请输入 ${sourceInfo?.providerName} 平台的链接`
            })
            return
          }
        }
        setUrlValidationResult(res.data)
        if (res.data.isValid) {
          // 自动填充标题
          if (res.data.title) {
            setUrlTitle(res.data.title)
          }
          // 自动填充媒体类型
          if (res.data.mediaType) {
            setUrlMediaType(res.data.mediaType)
          }
        }
      }
    } catch (error) {
      console.error('URL校验失败:', error)
      setUrlValidationResult({
        isValid: false,
        errorMessage: error.detail || error.message || 'URL校验失败'
      })
    } finally {
      setUrlValidating(false)
    }
  }

  // URL导入提交
  const handleUrlImport = async () => {
    if (!urlValidationResult?.isValid) {
      messageApi.warning('请先校验URL')
      return
    }

    setLoading(true)
    try {
      let res
      if (isCustomSource) {
        // 自定义源：使用 importFromUrl API 创建新的导入任务
        res = await importFromUrl({
          url: urlInput.trim(),
          provider: urlValidationResult.provider,
          title: urlTitle || urlValidationResult.title,
          media_type: urlMediaType,
          season: urlSeason,
        })
      } else {
        // 非自定义源：使用 batchManualImport API 导入到已有源
        // 需要用户输入集数
        if (!urlEpisodeIndex || urlEpisodeIndex < 1) {
          messageApi.warning('请输入有效的集数')
          setLoading(false)
          return
        }
        res = await batchManualImport({
          sourceId: sourceInfo.sourceId,
          items: [{
            episodeIndex: urlEpisodeIndex,
            content: urlInput.trim(),
            title: urlTitle || urlValidationResult.title || undefined,
          }]
        })
      }
      if (res.data) {
        messageApi.success(res.data.message || 'URL导入任务已提交')
        onSuccess(res.data)
        clearUrlState()
      }
    } catch (error) {
      console.error('URL导入失败:', error)
      messageApi.error(error.detail || error.message || 'URL导入失败')
    } finally {
      setLoading(false)
    }
  }

  // 清空URL相关状态
  const clearUrlState = () => {
    setUrlInput('')
    setUrlValidationResult(null)
    setUrlTitle('')
    setUrlSeason(1)
    setUrlMediaType('tv_series')
    setUrlEpisodeIndex(1)
  }

  const handleOk = async () => {
    // URL导入模式
    if (importMode === 'url') {
      await handleUrlImport()
      return
    }

    // XML导入模式
    if (!sourceInfo?.sourceId) return
    try {
      if (xmlDataList.length === 0) {
        messageApi.warn('未解析到任何有效条目！')
        return
      }
      setLoading(true)
      const res = await batchManualImport({
        sourceId: sourceInfo.sourceId,
        items: xmlDataList.map(it => {
          return {
            episodeIndex: it.episodeIndex,
            content: it.content,
            title: it.title ?? undefined,
          }
        }),
      })
      if (res.data) {
        onSuccess(res.data)
        clearAll()
      }
    } catch (error) {
      console.error('批量导入失败:', error)
      messageApi.error(
        error.detail || error.message || '批量导入失败，请检查内容格式和日志'
      )
    } finally {
      setLoading(false)
    }
  }

  const clearAll = () => {
    // 清空文件列表
    setXmlDataList([])
    // 重置顺序计数器
    orderCounter.current = 0
    // 重置上传状态
    setUploading(false)
    // 清空上传组件的内部文件列表
    setFileList([])
    // 清空URL状态
    clearUrlState()
  }

  const handleDelete = item => {
    setXmlDataList(list => {
      const activeIndex = list.findIndex(o => o.id === item.id)
      const newList = [...list]
      newList.splice(activeIndex, 1)
      return newList
    })
  }

  const handleEditIndex = (item, value) => {
    setXmlDataList(list => {
      return list.map(it => {
        if (it.id === item.id) {
          return {
            ...it,
            episodeIndex: value,
          }
        } else {
          return it
        }
      })
    })
  }

  const handleEditTitle = (item, value) => {
    setXmlDataList(list => {
      return list.map(it => {
        if (it.id === item.id) {
          return {
            ...it,
            title: value,
          }
        } else {
          return it
        }
      })
    })
  }

  const handleDragStart = event => {
    const { active } = event
    // 找到当前拖拽的项
    const item = xmlDataList.find(item => item.id === active.id)
    setActiveItem(item)
  }

  const handleDragEnd = event => {
    const { active, over } = event
    // 拖拽无效或未改变位置
    if (!over || active.id === over.id) {
      setActiveItem(null)
      return
    }

    setXmlDataList(list => {
      const activeIndex = list.findIndex(
        item => item.id === active.data.current.item.id
      )
      const overIndex = list.findIndex(
        item => item.id === over.data.current.item.id
      )

      if (activeIndex !== -1 && overIndex !== -1) {
        // 1. 重新排列数组
        const newList = [...xmlDataList]
        const [movedItem] = newList.splice(activeIndex, 1)
        newList.splice(overIndex, 0, movedItem)

        return newList
      }
      return list
    })

    setActiveItem(null)
  }

  /**
   * 处理文件上传
   * @param {Array} files - 上传的文件列表
   */
  const handleUpload = async ({ file }) => {
    const fileOrder = orderCounter.current++
    fileOrderMap.current[file.uid] = fileOrder
    setUploading(true)

    try {
      // 创建文件读取器
      const reader = new FileReader()

      reader.onload = async e => {
        try {
          const xmlContent = e.target.result
          // 将解析结果添加到列表
          setXmlDataList(prev => {
            const newItems = [
              ...prev,
              {
                id: file.uid,
                episodeIndex: fileOrder + 1,
                title: file.name?.split('.')?.[0],
                content: xmlContent,
                size: file.size,
                order: fileOrder,
              },
            ]

            newItems.sort((a, b) => a.order - b.order)
            const firstIndex = newItems?.[0]?.episodeIndex ?? 1
            return newItems.map((it, i) => {
              return {
                ...it,
                episodeIndex: firstIndex + i,
              }
            })
          })
        } catch (error) {
          messageApi.error(`文件 ${file.name} 解析失败: ${error.message}`)
        }
      }

      reader.readAsText(file)
    } catch (error) {
      messageApi.error(`文件处理失败: ${error.message}`)
    } finally {
      setUploading(false)
    }
  }

  const handleChange = ({ file, fileList }) => {
    // 更新文件列表状态
    setFileList(fileList)

    if (file.status === 'uploading') {
      setUploading(true)
    }
    if (file.status === 'done' || file.status === 'error') {
      setUploading(false)
    }
  }

  const uploadProps = {
    accept: '.xml',
    multiple: true,
    showUploadList: false,
    beforeUpload: () => true,
    customRequest: handleUpload,
    fileList: fileList,
    onChange: handleChange,
    maxCount: 20,
  }

  const renderDragOverlay = () => {
    if (!activeItem) return null

    return (
      <div ref={dragOverlayRef} style={{ width: '100%', maxWidth: '100%' }}>
        <List.Item
          style={{
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
            opacity: 0.9,
          }}
        >
          {/* 保留你原有的列表项渲染逻辑 */}
          <div className="w-full flex items-center justify-between">
            <div>
              <MyIcon icon="drag" size={24} />
            </div>
            <div className="w-full flex items-center justify-start gap-3">
              <InputNumber value={activeItem.episodeIndex} />
              <Input
                style={{
                  width: '100%',
                }}
                value={activeItem.title}
              />
              <div>
                <CloseCircleOutlined />
              </div>
            </div>
          </div>
        </List.Item>
      </div>
    )
  }

  // 渲染URL导入界面
  const renderUrlImport = () => (
    <div className="p-4">
      <div className="mb-4">
        <div className="text-gray-500 dark:text-gray-400 mb-2">
          {isCustomSource
            ? '输入其他平台的视频URL，系统将自动获取弹幕并导入到当前自定义源'
            : `输入 ${sourceInfo?.providerName} 平台的视频URL，系统将自动获取弹幕`
          }
        </div>
        <Input.Search
          placeholder={isCustomSource
            ? '请输入视频URL，如 https://www.XXXXX.com/bangumi/play/ss...'
            : `请输入 ${sourceInfo?.providerName} 的视频URL`
          }
          value={urlInput}
          onChange={e => {
            setUrlInput(e.target.value)
            setUrlValidationResult(null)
          }}
          onSearch={handleValidateUrl}
          enterButton={
            <Button loading={urlValidating}>
              校验URL
            </Button>
          }
          size="large"
        />
      </div>

      {/* 校验结果显示 */}
      {urlValidationResult && (
        <div className={`p-4 rounded-lg mb-4 ${urlValidationResult.isValid ? 'bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-700' : 'bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700'}`}>
          {urlValidationResult.isValid ? (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <CheckCircleOutlined className="text-green-500" />
                <span className="font-medium text-green-700 dark:text-green-400">URL校验通过</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><span className="text-gray-500 dark:text-gray-400">平台：</span><span className="dark:text-gray-200">{urlValidationResult.provider}</span></div>
                <div><span className="text-gray-500 dark:text-gray-400">媒体ID：</span><span className="dark:text-gray-200">{urlValidationResult.mediaId}</span></div>
                {urlValidationResult.title && (
                  <div className="col-span-2"><span className="text-gray-500 dark:text-gray-400">标题：</span><span className="dark:text-gray-200">{urlValidationResult.title}</span></div>
                )}
                {urlValidationResult.mediaType && (
                  <div><span className="text-gray-500 dark:text-gray-400">类型：</span><span className="dark:text-gray-200">{urlValidationResult.mediaType === 'movie' ? '电影' : '剧集'}</span></div>
                )}
                {urlValidationResult.year && (
                  <div><span className="text-gray-500 dark:text-gray-400">年份：</span><span className="dark:text-gray-200">{urlValidationResult.year}</span></div>
                )}
              </div>
              {urlValidationResult.imageUrl && (
                <div className="mt-2">
                  <img src={urlValidationResult.imageUrl} alt="封面" className="h-24 rounded" />
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <ExclamationCircleOutlined className="text-red-500" />
              <span className="text-red-700 dark:text-red-400">{urlValidationResult.errorMessage || 'URL校验失败'}</span>
            </div>
          )}
        </div>
      )}

      {/* 导入参数设置 */}
      {urlValidationResult?.isValid && (
        <div className="border dark:border-gray-600 rounded-lg p-4">
          <div className="font-medium mb-3 dark:text-gray-200">导入设置</div>
          <div className="grid grid-cols-2 gap-4">
            {/* 非自定义源需要输入集数 */}
            {!isCustomSource && (
              <div>
                <div className="text-gray-500 dark:text-gray-400 text-sm mb-1">集数 <span className="text-red-500">*</span></div>
                <InputNumber
                  value={urlEpisodeIndex}
                  onChange={setUrlEpisodeIndex}
                  min={1}
                  style={{ width: '100%' }}
                  placeholder="请输入集数"
                />
              </div>
            )}
            <div>
              <div className="text-gray-500 dark:text-gray-400 text-sm mb-1">标题（可修改）</div>
              <Input
                value={urlTitle}
                onChange={e => setUrlTitle(e.target.value)}
                placeholder="作品标题"
              />
            </div>
            {/* 自定义源显示季度和媒体类型 */}
            {isCustomSource && (
              <>
                <div>
                  <div className="text-gray-500 dark:text-gray-400 text-sm mb-1">季度</div>
                  <InputNumber
                    value={urlSeason}
                    onChange={setUrlSeason}
                    min={1}
                    style={{ width: '100%' }}
                  />
                </div>
                <div className="col-span-2">
                  <div className="text-gray-500 dark:text-gray-400 text-sm mb-1">媒体类型</div>
                  <Segmented
                    value={urlMediaType}
                    onChange={setUrlMediaType}
                    options={[
                      { label: '剧集', value: 'tv_series' },
                      { label: '电影', value: 'movie' },
                    ]}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )

  return (
    <Modal
      title={`批量导入 - ${sourceInfo?.animeName} (${sourceInfo?.providerName})`}
      open={open}
      onOk={handleOk}
      onCancel={onCancel}
      confirmLoading={loading}
      destroyOnHidden
      okText={importMode === 'url' ? '开始导入' : '确定'}
      okButtonProps={{
        disabled: importMode === 'url' && !urlValidationResult?.isValid
      }}
      width={importMode === 'url' ? 600 : 520}
    >
      {/* 导入模式切换 - 所有源都显示 */}
      <div className="mb-4">
        <Segmented
          value={importMode}
          onChange={value => {
            setImportMode(value)
            // 切换模式时清空状态
            if (value === 'xml') {
              clearUrlState()
            } else {
              clearAll()
            }
          }}
          options={[
            { label: <span><UploadOutlined className="mr-1" />{isCustomSource ? 'XML文件导入' : 'XML/URL导入'}</span>, value: 'xml' },
            { label: <span><LinkOutlined className="mr-1" />URL导入</span>, value: 'url' },
          ]}
          block
        />
      </div>

      {/* URL导入模式 */}
      {importMode === 'url' ? (
        renderUrlImport()
      ) : (
        <>
          {/* XML文件导入模式 */}
          <div className="p-4 text-center">
            <Upload {...uploadProps} ref={uploadRef}>
              <div>
                <CloudUploadOutlined style={{ fontSize: 48, marginBottom: 16 }} />
                <div className="flex items-center justify-center">
                  <Button
                    type="primary"
                    icon={<UploadOutlined />}
                    loading={uploading}
                    disabled={uploading}
                  >
                    选择文件
                  </Button>
                  <div className="ml-2">或直接拖拽文件到此处</div>
                </div>
                <div className="mt-2">
                  {isCustomSource
                    ? '支持批量上传，仅接受.xml格式文件'
                    : `支持批量上传，接受.xml格式文件或 ${sourceInfo?.providerName} 的视频URL`
                  }
                </div>
              </div>
            </Upload>
          </div>
          {xmlDataList.length === 0 ? (
            <div className="text-center py-10 text-gray-500">
              <Empty description="暂无解析数据，请上传XML文件" />
            </div>
          ) : (
            <>
              <Tooltip title="以第一个文件集为准依次自增1">
                <Button
                  onClick={() => {
                    setXmlDataList(list => {
                      const index = list[0]?.episodeIndex
                      return list.map((it, i) => {
                        return {
                          ...it,
                          episodeIndex: index + i,
                        }
                      })
                    })
                  }}
                >
                  一键应用集数
                </Button>
              </Tooltip>
              <DndContext
                sensors={sensors}
                collisionDetection={closestCorners}
                onDragStart={handleDragStart}
                onDragEnd={handleDragEnd}
              >
                <SortableContext
                  items={xmlDataList.map(item => item.id)}
                  strategy={verticalListSortingStrategy}
                >
                  <List
                    itemLayout="vertical"
                    size="large"
                    pagination={{
                      pageSize: pageSize,
                      onShowSizeChange: (_, size) => {
                        setPageSize(size)
                      },
                      hideOnSinglePage: true,
                    }}
                    dataSource={xmlDataList}
                    renderItem={(item, index) => (
                      <SortableItem
                        key={item.id}
                        item={item}
                        index={index}
                        handleDelete={() => handleDelete(item)}
                        handleEditTitle={value => handleEditTitle(item, value)}
                        handleEditIndex={value => handleEditIndex(item, value)}
                      />
                    )}
                  />
                </SortableContext>

                {/* 拖拽覆盖层 */}
                <DragOverlay>{renderDragOverlay()}</DragOverlay>
              </DndContext>
            </>
          )}
        </>
      )}
    </Modal>
  )
}

const SortableItem = ({
  item,
  index,
  handleDelete,
  handleEditTitle,
  handleEditIndex,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: item.id,
    data: {
      item,
      index,
    },
  })

  const inputRef = useRef(null)
  const [isFocused, setIsFocused] = useState(false)

  const inputNumberRef = useRef(null)
  const [isNumberFocused, setIsNumberFocused] = useState(false)

  useEffect(() => {
    if (isFocused && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isFocused, item.title])

  useEffect(() => {
    if (isNumberFocused && inputNumberRef.current) {
      inputNumberRef.current.focus()
    }
  }, [isNumberFocused, item.episodeIndex])

  // 只保留必要的样式，移除会阻止滚动的touchAction
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    ...(isDragging && { cursor: 'grabbing' }),
  }

  return (
    <List.Item ref={setNodeRef} style={style}>
      {/* 保留你原有的列表项渲染逻辑 */}
      <div className="w-full flex items-center justify-between">
        {/* 将attributes移到拖拽图标容器上，确保只有拖拽图标可触发拖拽 */}
        <div {...attributes} {...listeners} style={{ cursor: 'grab' }}>
          <MyIcon icon="drag" size={24} />
        </div>
        <div className="w-full flex items-center justify-start gap-3">
          <InputNumber
            ref={inputNumberRef}
            value={item.episodeIndex}
            onChange={value => {
              handleEditIndex(value)
            }}
            onFocus={() => setIsNumberFocused(true)}
            onBlur={() => setIsNumberFocused(false)}
          />
          <Input
            ref={inputRef}
            style={{
              width: '100%',
            }}
            key={item.title}
            value={item.title}
            onChange={e => {
              console.log(e.target.value, 'e.target.value')
              handleEditTitle(e.target.value)
            }}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
          />
          <div onClick={() => handleDelete(item)}>
            <CloseCircleOutlined />
          </div>
        </div>
      </div>
    </List.Item>
  )
}
