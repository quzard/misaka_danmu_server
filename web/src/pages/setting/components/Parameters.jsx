import { Card, Spin } from 'antd'
import { useState, useEffect } from 'react'
import { getConfigSchema } from '@/apis'
import { GenericConfigItem } from './GenericConfigItem'

export const Parameters = () => {
  const [schema, setSchema] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSchema()
  }, [])

  const loadSchema = async () => {
    try {
      setLoading(true)
      const res = await getConfigSchema()
      setSchema(res.data || [])
    } catch (err) {
      console.error('加载配置 Schema 失败:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12">
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div>
      {schema.map((group) => (
        <Card key={group.key} title={group.label} className="mb-4">
          {group.items.map((item) => (
            <GenericConfigItem key={item.key} config={item} />
          ))}
        </Card>
      ))}
    </div>
  )
}

