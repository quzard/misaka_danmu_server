import { useState, useEffect } from 'react'
import { Modal, Select, Checkbox, Form, Input, InputNumber, Radio, Spin, Empty, Button, List } from 'antd'
import { InfoCircleOutlined, ScissorOutlined } from '@ant-design/icons'
import { getSourceEpisodesForSplit, splitSource, getAnimeLibrary } from '../apis'
import { useMessage } from '../MessageContext'

export const SplitSourceModal = ({ open, animeId, animeTitle, sources, onCancel, onSuccess }) => {
  const [form] = Form.useForm()
  const messageApi = useMessage()
  
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [selectedSourceId, setSelectedSourceId] = useState(null)
  const [episodes, setEpisodes] = useState([])
  const [selectedEpisodeIds, setSelectedEpisodeIds] = useState([])
  const [targetType, setTargetType] = useState('new')
  const [searchKeyword, setSearchKeyword] = useState('')
  const [libraryList, setLibraryList] = useState([])
  const [libraryLoading, setLibraryLoading] = useState(false)
  const [selectedExistingId, setSelectedExistingId] = useState(null)

  // 重置状态
  useEffect(() => {
    if (open) {
      setSelectedSourceId(null)
      setEpisodes([])
      setSelectedEpisodeIds([])
      setTargetType('new')
      setSearchKeyword('')
      setLibraryList([])
      setSelectedExistingId(null)
      form.resetFields()
      // 如果只有一个数据源，自动选中
      if (sources?.length === 1) {
        setSelectedSourceId(sources[0].sourceId)
      }
    }
  }, [open, sources, form])

  // 加载分集列表
  useEffect(() => {
    if (selectedSourceId) {
      loadEpisodes(selectedSourceId)
    }
  }, [selectedSourceId])

  const loadEpisodes = async (sourceId) => {
    setLoading(true)
    setSelectedEpisodeIds([]) // 切换数据源时清空已选分集
    try {
      const res = await getSourceEpisodesForSplit(sourceId)
      console.log('分集列表响应:', res.data) // 调试日志
      setEpisodes(res.data?.episodes || [])
    } catch (error) {
      console.error('加载分集列表失败:', error)
      messageApi.error('加载分集列表失败')
    } finally {
      setLoading(false)
    }
  }

  // 搜索已有条目
  const searchLibrary = async (keyword) => {
    if (!keyword?.trim()) {
      setLibraryList([])
      return
    }
    setLibraryLoading(true)
    try {
      const res = await getAnimeLibrary({ keyword: keyword.trim(), pageSize: 20 })
      // 过滤掉当前条目
      const filtered = (res.data?.list || []).filter(item => item.animeId !== animeId)
      setLibraryList(filtered)
    } catch (error) {
      messageApi.error('搜索失败')
    } finally {
      setLibraryLoading(false)
    }
  }

  const handleSubmit = async () => {
    if (!selectedSourceId) {
      messageApi.warning('请选择数据源')
      return
    }
    if (selectedEpisodeIds.length === 0) {
      messageApi.warning('请选择要拆分的分集')
      return
    }

    let payload = {
      sourceId: selectedSourceId,
      episodeIds: selectedEpisodeIds,
      targetType,
      reindexEpisodes: true,
    }

    if (targetType === 'new') {
      try {
        const values = await form.validateFields()
        payload.newMediaInfo = {
          title: values.title,
          season: values.season || 1,
          year: values.year || null,
        }
      } catch {
        return
      }
    } else {
      if (!selectedExistingId) {
        messageApi.warning('请选择目标条目')
        return
      }
      payload.existingMediaId = selectedExistingId
    }

    setSubmitting(true)
    try {
      const res = await splitSource(animeId, payload)
      messageApi.success(res.data?.message || '拆分成功')
      onSuccess?.(res.data)
    } catch (error) {
      messageApi.error(error.detail || '拆分失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSelectAll = () => {
    if (selectedEpisodeIds.length === episodes.length) {
      setSelectedEpisodeIds([])
    } else {
      setSelectedEpisodeIds(episodes.map(ep => ep.episodeId))
    }
  }

  return (
    <Modal
      title={<><ScissorOutlined className="mr-2" />拆分数据源</>}
      open={open}
      onCancel={onCancel}
      onOk={handleSubmit}
      confirmLoading={submitting}
      width={600}
      destroyOnHidden
      okText="确认拆分"
    >
      <div className="space-y-4 py-4">
        {/* 提示信息 */}
        <div className="p-3 bg-yellow-50 dark:bg-yellow-900/20 rounded text-sm text-yellow-800 dark:text-yellow-200">
          <InfoCircleOutlined className="mr-2" />
          将选中的分集从当前条目拆分到新条目或已有条目。拆分后，分集将从当前条目移除。
        </div>

        {/* 第一步：选择数据源 */}
        <div>
          <div className="font-medium mb-2" style={{ color: 'var(--color-text)' }}>📌 第一步：选择数据源</div>
          <Select
            className="w-full"
            placeholder="选择要拆分的数据源"
            value={selectedSourceId}
            onChange={(value) => {
              console.log('选择的数据源ID:', value)
              setSelectedSourceId(value)
            }}
            options={sources?.map(s => {
              console.log('数据源:', s)
              return {
                value: s.sourceId,
                label: `${s.providerName} - ${s.mediaId} (${s.episodeCount || 0}集)`
              }
            })}
          />
        </div>

        {/* 第二步：选择分集 */}
        <div>
          <div className="font-medium mb-2 flex items-center justify-between" style={{ color: 'var(--color-text)' }}>
            <span>📌 第二步：选择要拆分的分集</span>
            {episodes.length > 0 && (
              <Button size="small" onClick={handleSelectAll}>
                {selectedEpisodeIds.length === episodes.length ? '取消全选' : '全选'}
              </Button>
            )}
          </div>
          {loading ? (
            <div className="text-center py-4"><Spin /></div>
          ) : episodes.length === 0 ? (
            <Empty description={selectedSourceId ? "该数据源暂无分集" : "请先选择数据源"} />
          ) : (
            <div className="max-h-48 overflow-y-auto border rounded p-2 dark:border-gray-600">
              <Checkbox.Group
                value={selectedEpisodeIds}
                onChange={setSelectedEpisodeIds}
                className="flex flex-col gap-1"
              >
                {episodes.map(ep => (
                  <Checkbox key={ep.episodeId} value={ep.episodeId} className="!ml-0">
                    <span style={{ color: 'var(--color-text)' }}>
                      第{ep.episodeIndex}集 - {ep.title} ({ep.commentCount}条弹幕)
                    </span>
                  </Checkbox>
                ))}
              </Checkbox.Group>
            </div>
          )}
          {selectedEpisodeIds.length > 0 && (
            <div className="text-sm text-gray-500 mt-1">已选择 {selectedEpisodeIds.length} 集</div>
          )}
        </div>

        {/* 第三步：目标设置 */}
        <div>
          <div className="font-medium mb-2" style={{ color: 'var(--color-text)' }}>📌 第三步：选择目标</div>
          <div className="mb-3">
            <Radio.Group value={targetType} onChange={e => setTargetType(e.target.value)}>
              <Radio value="new"><span style={{ color: 'var(--color-text)' }}>创建新条目</span></Radio>
              <Radio value="existing"><span style={{ color: 'var(--color-text)' }}>合并到已有条目</span></Radio>
            </Radio.Group>
          </div>

          {targetType === 'new' ? (
            <div className="p-3 rounded" style={{ backgroundColor: 'var(--color-hover)' }}>
              <Form form={form} layout="vertical" requiredMark={false}>
                <Form.Item
                  name="title"
                  label="标题"
                  rules={[{ required: true, message: '请输入标题' }]}
                  initialValue={animeTitle}
                >
                  <Input placeholder="新条目标题" />
                </Form.Item>
                <div className="flex gap-4">
                  <Form.Item
                    name="season"
                    label="季数"
                    initialValue={1}
                    className="flex-1 !mb-0"
                  >
                    <InputNumber min={1} className="w-full" />
                  </Form.Item>
                  <Form.Item
                    name="year"
                    label="年份"
                    className="flex-1 !mb-0"
                  >
                    <InputNumber min={1900} max={2100} className="w-full" placeholder="可选" />
                  </Form.Item>
                </div>
              </Form>
            </div>
          ) : (
            <div className="p-3 rounded" style={{ backgroundColor: 'var(--color-hover)' }}>
              <Input.Search
                placeholder="搜索目标条目..."
                value={searchKeyword}
                onChange={e => setSearchKeyword(e.target.value)}
                onSearch={searchLibrary}
                enterButton
                loading={libraryLoading}
              />
              {libraryList.length > 0 && (
                <List
                  className="mt-2 max-h-40 overflow-y-auto"
                  size="small"
                  dataSource={libraryList}
                  renderItem={item => (
                    <List.Item
                      className={`cursor-pointer rounded px-2 ${selectedExistingId === item.animeId ? 'bg-blue-100 dark:bg-blue-900' : 'hover:bg-gray-100 dark:hover:bg-gray-700'}`}
                      onClick={() => setSelectedExistingId(item.animeId)}
                    >
                      <span className="text-gray-900 dark:text-gray-100">
                        {item.title} (S{String(item.season).padStart(2, '0')})
                      </span>
                    </List.Item>
                  )}
                />
              )}
              {selectedExistingId && (
                <div className="text-sm text-green-600 dark:text-green-400 mt-2">
                  ✓ 已选择目标条目 ID: {selectedExistingId}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}

