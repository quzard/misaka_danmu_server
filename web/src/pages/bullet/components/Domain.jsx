import { Button, Card, Input, message } from 'antd'
import { useEffect, useState } from 'react'
import { setCustomDomain } from '../../../apis'
import { useMessage } from '../../../MessageContext'

export const Domain = ({ domain: propDomain, onDomainChange }) => {
  const [loading, setLoading] = useState(false)
  const [domain, setDomain] = useState(propDomain || '')
  const messageApi = useMessage()

  // 监听 prop 变化，同步到本地状态
  useEffect(() => {
    setDomain(propDomain || '')
  }, [propDomain])

  const handleEdit = async () => {
    try {
      await setCustomDomain({ value: domain })
      messageApi.success('保存成功')
      // 通知父组件更新 domain
      if (onDomainChange) {
        onDomainChange(domain)
      }
    } catch (error) {
      messageApi.error('保存失败')
    }
  }

  return (
    <div className="my-6">
      <Card loading={loading} title="自定义域名设置">
        <div>
          设置后，复制按钮将自动拼接 "http(s)://域名(ip):端口(port)/api/v1/Token值"
          格式的完整URL。
        </div>
        <div className="flex items-center justify-start mt-4">
          <Input
            placeholder="请输入自定义域名"
            value={domain}
            onChange={e => setDomain(e.target.value)}
          />
          <Button type="primary" className="ml-2" onClick={handleEdit}>
            修改
          </Button>
        </div>
      </Card>
    </div>
  )
}
