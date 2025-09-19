import { Card, Form, Switch, Input, Button, Space, Select, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { getMatchFallback, setMatchFallback, getCustomDanmakuPath, setCustomDanmakuPath } from '../../../apis'
import { useMessage } from '../../../MessageContext'
import { QuestionCircleOutlined } from '@ant-design/icons'

export const MatchFallbackSetting = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(true)
  const [pathSaving, setPathSaving] = useState(false)
  const [customPathEnabled, setCustomPathEnabled] = useState(false)
  const messageApi = useMessage()

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const [fallbackRes, pathRes] = await Promise.all([
        getMatchFallback(),
        getCustomDanmakuPath()
      ])
      const pathEnabled = pathRes.data.enabled === 'true'
      setCustomPathEnabled(pathEnabled)
      form.setFieldsValue({
        matchFallbackEnabled: fallbackRes.data.value === 'true',
        customDanmakuPathEnabled: pathEnabled,
        customDanmakuPathTemplate: pathRes.data.template || '/app/config/danmaku/${animeId}/${episodeId}'
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
        setCustomPathEnabled(changedValues.customDanmakuPathEnabled)
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
    { label: '默认模板', value: '/app/config/danmaku/${animeId}/${episodeId}' },
    { label: '按标题分类', value: '/downloads/弹幕/${title}/${title} - S${season:02d}E${episode:02d}' },
    { label: 'QB下载风格', value: '/downloads/QB下载/动漫/${title}/Season ${season}/${title} - S${season:02d}E${episode:02d}' },
    { label: 'Plex风格', value: '/media/动漫/${title} (${year})/Season ${season:02d}/${title} - S${season:02d}E${episode:02d}' }
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
              弹幕文件路径模板
              <Tooltip title="支持变量：${title}(标题), ${season}(季度), ${episode}(集数), ${year}(年份), ${provider}(提供商), ${animeId}(动画ID), ${episodeId}(分集ID)。格式化：${season:02d}表示两位数字补零。.xml后缀会自动添加。">
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
              disabled={!customPathEnabled}
            />
            <Input
              placeholder="路径模板"
              style={{ flex: 1 }}
              disabled={!customPathEnabled}
            />
            <Button type="primary" loading={pathSaving} onClick={handlePathSave}>
              保存
            </Button>
          </Space.Compact>
        </Form.Item>

        <div style={{ fontSize: '12px', color: '#666', marginTop: '-16px' }}>
          <div>示例路径：/app/config/danmaku/26/25000026010012.xml（.xml后缀自动添加）</div>
          <div>支持的变量：title, season, episode, year, provider, animeId, episodeId</div>
          <div>格式化选项：${`{season:02d}`} 表示季度号补零到2位，${`{episode:03d}`} 表示集数补零到3位</div>
        </div>
      </Form>
    </Card>
  )
}
