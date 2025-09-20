import { Card, Form, Switch, Input, Button, Space, Tooltip } from 'antd'
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
        customDanmakuPathTemplate: pathRes.data.template
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

  const handlePathReset = () => {
    const defaultTemplate = '/app/config/danmaku/${animeId}/${episodeId}'
    form.setFieldValue('customDanmakuPathTemplate', defaultTemplate)
    messageApi.success('已重置为默认路径模板')
  }

  return (
    <Card title="配置" loading={loading}>
      <Form
        form={form}
        onValuesChange={handleValueChange}
        layout="vertical"
        initialValues={{
          matchFallbackEnabled: false,
          customDanmakuPathEnabled: false,
          customDanmakuPathTemplate: '/app/config/danmaku/${animeId}/${episodeId}'
        }}
      >
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
          label={
            <Space>
              弹幕文件保存路径
              <Tooltip title="支持变量：${title}(标题), ${season}(季度), ${episode}(集数), ${year}(年份), ${provider}(提供商), ${animeId}(动画ID), ${episodeId}(分集ID)。格式化：${season:02d}表示两位数字补零。.xml后缀会自动添加。Windows系统可使用绝对路径如：D:/弹幕/${title}/${episode:03d}">
                <QuestionCircleOutlined />
              </Tooltip>
            </Space>
          }
        >
          <Space.Compact style={{ width: '100%' }}>
            <Form.Item
              name="customDanmakuPathTemplate"
              style={{ flex: 1, marginBottom: 0 }}
            >
              <Input
                placeholder="自定义保存路径"
                disabled={!customPathEnabled}
              />
            </Form.Item>
            <Button onClick={handlePathReset} disabled={!customPathEnabled}>
              重置
            </Button>
            <Button type="primary" loading={pathSaving} onClick={handlePathSave}>
              保存
            </Button>
          </Space.Compact>
        </Form.Item>

        <div style={{ fontSize: '12px', color: '#666', marginTop: '-16px' }}>
          <div>默认路径：config/danmaku/$&#123;animeId&#125;/$&#123;episodeId&#125;</div>
          <div>Windows绝对路径示例：D:/弹幕/$&#123;title&#125;/$&#123;episode:03d&#125;</div>
          <div>支持的变量：$&#123;title&#125;, $&#123;season&#125;, $&#123;episode&#125;, $&#123;year&#125;, $&#123;provider&#125;, $&#123;animeId&#125;, $&#123;episodeId&#125;</div>
          <div>格式化选项：$&#123;season:02d&#125; 表示季度号补零到2位，$&#123;episode:03d&#125; 表示集数补零到3位</div>
        </div>
      </Form>
    </Card>
  )
}