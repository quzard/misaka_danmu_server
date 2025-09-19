import { Card, Form, Switch, Input, Button, Space, Select, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { getMatchFallback, setMatchFallback, getCustomDanmakuPath, setCustomDanmakuPath } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { QuestionCircleOutlined } from '@ant-design/icons'

export const MatchFallbackSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [pathSaving, setPathSaving] = useState(false)
  const messageApi = useMessage()

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const [fallbackRes, pathRes] = await Promise.all([
        getMatchFallback(),
        getCustomDanmakuPath()
      ])
      form.setFieldsValue({
        matchFallbackEnabled: fallbackRes.data.value === 'true',
        customDanmakuPathEnabled: pathRes.data.enabled === 'true',
        customDanmakuPathTemplate: pathRes.data.template || '/downloads/QB下载/动漫/${title}/Season ${season}/${title} - S${season:02d}E${episode:02d}'
      })
    } catch (error) {
      messageApi.error('获取设置失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSettings()
  }, [])

  const handleValueChange = async changedValues => {
    try {
      if ('matchFallbackEnabled' in changedValues) {
        await setMatchFallback({ value: String(changedValues.matchFallbackEnabled) })
      }
      if ('customDanmakuPathEnabled' in changedValues) {
        const currentValues = form.getFieldsValue()
        await setCustomDanmakuPath({
          enabled: String(changedValues.customDanmakuPathEnabled),
          template: currentValues.customDanmakuPathTemplate
        })
      }
      messageApi.success('设置已保存')
    } catch (error) {
      messageApi.error('保存设置失败')
      fetchSettings()
    }
  }

  const handlePathSave = async () => {
    try {
      setPathSaving(true)
      const values = form.getFieldsValue()
      await setCustomDanmakuPath({
        enabled: String(values.customDanmakuPathEnabled),
        template: values.customDanmakuPathTemplate
      })
      messageApi.success('路径模板已保存')
    } catch (error) {
      messageApi.error('保存路径模板失败')
    } finally {
      setPathSaving(false)
    }
  }

  const templateOptions = [
    { label: '默认模板', value: '/downloads/QB下载/动漫/${title}/Season ${season}/${title} - S${season:02d}E${episode:02d}' },
    { label: '简单模板', value: '/downloads/${title}/${title} - ${episode}' },
    { label: '按年份分类', value: '/downloads/${year}/${title}/Season ${season}/${episode}' },
    { label: '按提供商分类', value: '/downloads/${provider}/${title}/Season ${season}/${episode}' }
  ]

  return (
    <Card title="配置" loading={loading}>
      <Form form={form} onValuesChange={handleValueChange} layout="vertical">
        <Form.Item
          name="matchFallbackEnabled"
          label="启用匹配后备"
          valuePropName="checked"
          tooltip="启用后，当播放客户端尝试使用match接口时，接口在本地库中找不到任何结果时，系统将自动触发一个后台任务，尝试从全网搜索并导入对应的弹幕。"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="customDanmakuPathEnabled"
          label="启用自定义弹幕保存路径"
          valuePropName="checked"
          tooltip="启用后，弹幕文件将按照自定义路径模板保存，而不是使用默认路径。"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          name="customDanmakuPathTemplate"
          label={
            <Space>
              自定义路径模板
              <Tooltip title="支持变量：${title}(标题), ${season}(季度), ${episode}(集数), ${year}(年份), ${provider}(提供商), ${animeId}(动画ID), ${episodeId}(分集ID)。格式化：${season:02d}表示两位数字补零。">
                <QuestionCircleOutlined />
              </Tooltip>
            </Space>
          }
        >
          <Space.Compact style={{ width: '100%' }}>
            <Select
              style={{ width: '200px' }}
              placeholder="选择预设模板"
              options={templateOptions}
              onChange={(value) => form.setFieldValue('customDanmakuPathTemplate', value)}
            />
            <Input
              placeholder="输入自定义路径模板"
              style={{ flex: 1 }}
            />
            <Button type="primary" loading={pathSaving} onClick={handlePathSave}>
              保存
            </Button>
          </Space.Compact>
        </Form.Item>

        <div style={{ fontSize: '12px', color: '#666', marginTop: '-16px' }}>
          <div>示例路径：/downloads/QB下载/动漫/天才基本法/Season 01/天才基本法 - S01E05.xml（.xml后缀自动添加）</div>
          <div>支持的变量：title, season, episode, year, provider, animeId, episodeId</div>
        </div>
      </Form>
    </Card>
  )
}
