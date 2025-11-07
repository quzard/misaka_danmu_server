import React from 'react'
import { Input, Button, Space, Drawer } from 'antd'
import { SearchOutlined, FilterOutlined } from '@ant-design/icons'
import { useAtomValue } from 'jotai'
import { isMobileAtom } from '../../store/index.js'
import classNames from 'classnames'

/**
 * 响应式搜索栏组件
 * 移动端优化的搜索和筛选布局
 */
export const ResponsiveSearchBar = ({
  searchPlaceholder = '搜索...',
  onSearch,
  searchValue,
  onSearchChange,
  extra,
  filters,
  onFilterChange,
  className,
}) => {
  const isMobile = useAtomValue(isMobileAtom)
  const [filterVisible, setFilterVisible] = React.useState(false)

  if (isMobile) {
    return (
      <>
        <div className={classNames('space-y-3', className)}>
          <Input.Search
            placeholder={searchPlaceholder}
            value={searchValue}
            onChange={onSearchChange}
            onSearch={onSearch}
            size="large"
            enterButton={<SearchOutlined />}
          />
          <div className="flex gap-2">
            {filters && (
              <Button
                icon={<FilterOutlined />}
                onClick={() => setFilterVisible(true)}
                block
              >
                筛选
              </Button>
            )}
            {extra}
          </div>
        </div>
        
        {filters && (
          <Drawer
            title="筛选条件"
            placement="bottom"
            onClose={() => setFilterVisible(false)}
            open={filterVisible}
            height="auto"
          >
            <div className="space-y-4">
              {filters}
              <Button
                type="primary"
                block
                onClick={() => {
                  onFilterChange?.()
                  setFilterVisible(false)
                }}
              >
                应用筛选
              </Button>
            </div>
          </Drawer>
        )}
      </>
    )
  }

  // 桌面端布局
  return (
    <div className={classNames('flex items-center gap-4', className)}>
      <Input.Search
        placeholder={searchPlaceholder}
        value={searchValue}
        onChange={onSearchChange}
        onSearch={onSearch}
        className="flex-1 max-w-md"
        enterButton
      />
      {filters}
      {extra}
    </div>
  )
}
