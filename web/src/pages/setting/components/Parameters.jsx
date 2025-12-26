import { Card, Empty, Spin } from 'antd'
import { useState, useEffect } from 'react'
import {
  getConfigSchema,
  getGithubToken,
  saveGithubToken,
  verifyGithubToken,
} from '../../../apis'
import { GenericConfigItem } from './GenericConfigItem'

// GitHub Token 的特殊配置（使用自定义 API）
const GITHUB_TOKEN_CONFIG = {
  key: 'github_token',
  getApi: getGithubToken,
  saveApi: saveGithubToken,
  verifyApi: verifyGithubToken,
}

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
      setSchema([])
    } finally {
      setLoading(false)
    }
  }

  // 为特殊配置项注入自定义 API
  const enrichConfig = (config) => {
    if (config.key === 'github_token') {
      return { ...config, ...GITHUB_TOKEN_CONFIG }
    }
    return config
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12">
        <Spin tip="加载中..." />
      </div>
    )
  }

  if (!schema || schema.length === 0) {
    return (
      <Empty
        description="暂无可调整的配置项"
        className="py-12"
      />
    )
  }

  return (
    <div className="space-y-4">
      {schema.map((group) => (
        <Card key={group.key} title={group.label} size="small">
          {group.items?.map((item) => (
            <GenericConfigItem key={item.key} config={enrichConfig(item)} />
          ))}
        </Card>
      ))}
    </div>
  )
}

