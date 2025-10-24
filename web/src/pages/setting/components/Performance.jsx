import { Form, InputNumber, Button, Spin, Card, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { getConfig, setConfig } from '../../../apis'
import { useMessage } from '../../../MessageContext'

const { Text } = Typography

export const Performance = () => {
  const [loading, setLoading] = useState(true)
  const [form] = Form.useForm()
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const messageApi = useMessage()

  useEffect(() => {
    setLoading(true)
    getConfig('searchMaxResultsPerSource')
      .then(res => {
        const value = parseInt(res.data?.value ?? '30')
        form.setFieldsValue({ searchMaxResultsPerSource: value })
      })
      .catch(() => {
        form.setFieldsValue({ searchMaxResultsPerSource: 30 })
      })
      .finally(() => {
        setLoading(false)
      })
  }, [form])

  const handleSave = async () => {
    try {
      setIsSaveLoading(true)
      const values = await form.validateFields()
      await setConfig('searchMaxResultsPerSource', String(values.searchMaxResultsPerSource))
      setIsSaveLoading(false)
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  return (
    <Spin spinning={loading}>
      <Card title="性能优化设置" bordered={false}>
        <Form form={form} layout="vertical">
          <Form.Item
            label="每个搜索源最多返回结果数"
            name="searchMaxResultsPerSource"
            rules={[
              { required: true, message: '请输入结果数量' },
              { type: 'number', min: 1, max: 100, message: '请输入1-100之间的数字' }
            ]}
            extra={
              <Text type="secondary">
                限制每个搜索源返回的最大结果数量，可以提高搜索速度。建议值：30
              </Text>
            }
          >
            <InputNumber
              min={1}
              max={100}
              style={{ width: '100%' }}
              placeholder="请输入结果数量（1-100）"
            />
          </Form.Item>

          <Form.Item>
            <Button type="primary" onClick={handleSave} loading={isSaveLoading}>
              保存
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </Spin>
  )
}

