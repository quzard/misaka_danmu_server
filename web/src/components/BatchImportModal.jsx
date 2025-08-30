import { Form, Input, Modal, message } from 'antd'
import { useState } from 'react'
import { batchManualImport } from '../apis'

const { TextArea } = Input

export const BatchImportModal = ({ open, sourceInfo, onCancel, onSuccess }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  const isCustomSource = sourceInfo?.providerName === 'custom'
  const placeholderText = isCustomSource
    ? `请使用 ##EPISODE=集数## 作为分隔符来区分不同分集的XML内容。
例如：
##EPISODE=1##
<?xml version="1.0" encoding="UTF-8"?><i>...</i>

##EPISODE=2##
<?xml version="1.0" encoding="UTF-8"?><i>...</i>`
    : `每行一个URL，格式为：集数=URL
例如：
1=https://www.bilibili.com/bangumi/play/ep12345
2=https://www.bilibili.com/bangumi/play/ep12346`

  const handleOk = async () => {
    if (!sourceInfo?.sourceId) return
    try {
      const values = await form.validateFields()
      const content = values.content
      let items = []

      if (isCustomSource) {
        const segments = content.split(/##EPISODE=(\d+)##/g).filter(s => s.trim() !== '')
        if (segments.length > 0 && segments.length % 2 !== 0) {
          throw new Error('自定义源内容格式错误，请确保每个 ##EPISODE=集数## 分隔符后都有XML内容。')
        }
        for (let i = 0; i < segments.length; i += 2) {
          const episodeIndex = parseInt(segments[i], 10)
          const xmlContent = segments[i + 1].trim()
          if (!isNaN(episodeIndex) && xmlContent) {
            items.push({ episodeIndex, content: xmlContent })
          }
        }
      } else {
        const lines = content.split('\n').filter(line => line.trim() !== '')
        items = lines.map(line => {
          const parts = line.split('=')
          if (parts.length < 2 || !/^\d+$/.test(parts[0].trim())) {
            throw new Error(`格式错误，应为 "集数=URL"，错误的行: ${line}`)
          }
          return {
            episodeIndex: parseInt(parts[0].trim(), 10),
            content: parts.slice(1).join('=').trim(), // 允许URL中包含'='
          }
        })
      }

      if (items.length === 0) {
        message.warn('未解析到任何有效条目！')
        return
      }

      setLoading(true)
      const res = await batchManualImport({ sourceId: sourceInfo.sourceId, items })
      if (res.data) {
        message.success('批量导入任务已提交！')
        onSuccess(res.data) // 将任务数据传递回去
        form.resetFields()
      }
    } catch (error) {
      console.error('批量导入失败:', error)
      message.error(error.detail || error.message || '批量导入失败，请检查内容格式和日志')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title={`批量导入 - ${sourceInfo?.title} (${sourceInfo?.providerName})`} open={open} onOk={handleOk} onCancel={onCancel} confirmLoading={loading} destroyOnClose width={720}>
      <Form form={form} layout="vertical" name="batch_import_form" className="!px-4 !pt-6">
        <Form.Item name="content" label={isCustomSource ? 'XML弹幕内容 (使用分隔符)' : '分集URL列表'} rules={[{ required: true, message: '请输入内容！' }]}>
          <TextArea rows={15} placeholder={placeholderText} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
