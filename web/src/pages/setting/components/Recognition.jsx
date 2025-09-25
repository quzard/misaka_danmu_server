import { Button, Card, Form, Input } from 'antd'
import { useEffect, useState } from 'react'
import { useMessage } from '../../../MessageContext'
import { getRecognition, setRecognition } from '../../../apis'

export const Recognition = () => {
  const [loading, setLoading] = useState(true)
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const messageApi = useMessage()

  const [text, setText] = useState('')

  useEffect(() => {
    setLoading(true)
    getRecognition()
      .then(res => {
        setText(res.data?.content ?? '')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const handleSave = async () => {
    try {
      setIsSaveLoading(true)
      await setRecognition({
        content: text,
      })
      setIsSaveLoading(false)
      messageApi.success('保存成功')
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  return (
    <div className="my-6">
      <Card loading={loading} title="识别词配置">
        <Input.TextArea
          rows={8}
          value={text}
          onChange={value => setText(value.target.value)}
        />
        <div className="flex justify-end mt-4">
          <Button type="primary" onClick={handleSave} loading={isSaveLoading}>
            保存修改
          </Button>
        </div>
      </Card>
    </div>
  )
}
