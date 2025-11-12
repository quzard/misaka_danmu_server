import React, { useState } from 'react'
import { Tabs } from 'antd'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../store/index.js'
import classNames from 'classnames'

/**
 * 统一的标签页组件
 * 使用Ant Design的Tabs组件
 */
export const MobileTabs = ({ items, defaultActiveKey, onChange, ...props }) => {
  const isMobile = useAtomValue(isMobileAtom)
  const [activeKey, setActiveKey] = useState(defaultActiveKey || items[0]?.key)

  const handleChange = (key) => {
    setActiveKey(key)
    onChange?.(key)
  }

  // 统一使用Tabs组件
  return (
    <Tabs
      activeKey={activeKey}
      items={items}
      onChange={(key) => {
        setActiveKey(key)
        onChange?.(key)
      }}
      {...props}
    />
  )
}