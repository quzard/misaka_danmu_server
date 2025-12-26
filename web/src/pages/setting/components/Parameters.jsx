import { Card, Spin, Empty } from 'antd'
import { useState, useEffect } from 'react'
import { getConfigSchema } from '../../../apis'
import { GenericConfigItem } from './GenericConfigItem'

export const Parameters = () => {
  const [schema, setSchema] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadSchema()
  }, [])

  const loadSchema = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await getConfigSchema()
      console.log('Schema loaded:', res.data)
      setSchema(res.data || [])
    } catch (err) {
      console.error('加载配置 Schema 失败:', err)
      setError(err.message || '加载失败')
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

  if (error) {
    return (
      <div className="py-12">
        <Empty description={`加载配置失败: ${error}`} />
      </div>
    )
  }

  if (!schema || schema.length === 0) {
    return (
      <div className="py-12">
        <Empty description="暂无配置项" />
      </div>
    )
  }

  return (
    <div>
      {schema.map((group) => (
        <Card key={group.key} title={group.label} className="mb-4">
          {group.items?.map((item) => (
            <GenericConfigItem key={item.key} config={item} />
          ))}
        </Card>
      ))}
    </div>
  )
}

