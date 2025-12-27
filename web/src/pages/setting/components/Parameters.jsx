import { Empty, Spin, Tabs } from 'antd'
import { useState, useEffect } from 'react'
import {
  getConfigSchema,
  getGithubToken,
  saveGithubToken,
  verifyGithubToken,
} from '../../../apis'
import { GenericConfigItem } from './GenericConfigItem'
import { DatabaseBackupManager } from './DatabaseBackupManager'

// GitHub Token 的特殊配置（使用自定义 API）
const GITHUB_TOKEN_CONFIG = {
  key: 'github_token',
  getApi: getGithubToken,
  saveApi: saveGithubToken,
  verifyApi: verifyGithubToken,
}

// 需要渲染自定义组件的分组
const CUSTOM_COMPONENTS = {
  database: DatabaseBackupManager,
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

  // 构建 Tabs 的 items
  const tabItems = schema.map((group) => {
    // 检查是否有自定义组件
    const CustomComponent = CUSTOM_COMPONENTS[group.key] || (group.customComponent && CUSTOM_COMPONENTS[group.customComponent])

    return {
      key: group.key,
      label: group.label,
      children: (
        <div className="py-2">
          {group.items?.map((item) => (
            <GenericConfigItem key={item.key} config={enrichConfig(item)} />
          ))}
          {/* 渲染自定义组件 */}
          {CustomComponent && <CustomComponent />}
        </div>
      ),
    }
  })

  return (
    <Tabs
      defaultActiveKey={schema[0]?.key}
      items={tabItems}
      tabPosition="left"
      className="parameters-tabs"
    />
  )
}

