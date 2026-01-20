import { useEffect, useState } from 'react'
import { Button, Card, ColorPicker, InputNumber, Select, Tag, Switch, Input, Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import {
  getDanmuOutputTotal,
  setDanmuOutputTotal,
  getDanmakuMergeOutputEnabled,
  setDanmakuMergeOutputEnabled,
  getDanmakuRandomColorMode,
  setDanmakuRandomColorMode,
  getDanmakuRandomColorPalette,
  setDanmakuRandomColorPalette,
  getDanmakuBlacklistEnabled,
  setDanmakuBlacklistEnabled,
  getDanmakuBlacklistPatterns,
  setDanmakuBlacklistPatterns,
} from '../../../apis'
import { useMessage } from '../../../MessageContext'

const { TextArea } = Input

const DEFAULT_COLOR_PALETTE = [
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ffffff',
  '#ff7f7f',
  '#ffa07a',
  '#fff68f',
  '#90ee90',
  '#7fffd4',
  '#87cefa',
  '#d8bfd8',
  '#ffb6c1',
]

const parsePaletteFromServer = (raw) => {
  if (!raw) return DEFAULT_COLOR_PALETTE
  let values = []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) values = parsed
  } catch {
    values = String(raw)
      .split(',')
      .map(v => v.trim())
  }
  const toHex = (val) => {
    const num = parseInt(String(val).replace('#', ''), 10)
    if (Number.isNaN(num)) return null
    return `#${num.toString(16).padStart(6, '0')}`
  }
  const palette = values
    .map(toHex)
    .filter(Boolean)
  return palette.length > 0 ? palette : DEFAULT_COLOR_PALETTE
}

const paletteToServer = (palette) => {
  const toInt = (hex) => parseInt(hex.replace('#', ''), 16)
  const arr = palette.map(toInt)
  return JSON.stringify(arr)
}

export const OutputManage = () => {
  const [loading, setLoading] = useState(false)
  const [limit, setLimit] = useState('-1')
  const [mergeEnabled, setMergeEnabled] = useState(false)
  const [saveLoading, setSaveLoading] = useState(false)
  const [colorMode, setColorMode] = useState('off')
  const [palette, setPalette] = useState(DEFAULT_COLOR_PALETTE)
  const [colorPickerValue, setColorPickerValue] = useState('#ffffff')
  const [colorSaveLoading, setColorSaveLoading] = useState(false)
  const [blacklistEnabled, setBlacklistEnabled] = useState(false)
  const [blacklistPatterns, setBlacklistPatterns] = useState('')
  const [blacklistSaveLoading, setBlacklistSaveLoading] = useState(false)

  const messageApi = useMessage()

  const getConfig = async () => {
    setLoading(true)
    try {
      const [limitRes, mergeEnabledRes, colorModeRes, colorPaletteRes, blacklistEnabledRes, blacklistPatternsRes] = await Promise.all([
        getDanmuOutputTotal(),
        getDanmakuMergeOutputEnabled(),
        getDanmakuRandomColorMode(),
        getDanmakuRandomColorPalette(),
        getDanmakuBlacklistEnabled(),
        getDanmakuBlacklistPatterns(),
      ])
      setLimit(limitRes.data?.value ?? '-1')
      setMergeEnabled(mergeEnabledRes.data?.value === 'true')
      setColorMode(colorModeRes.data?.value || 'off')
      setPalette(parsePaletteFromServer(colorPaletteRes.data?.value))
      setBlacklistEnabled(blacklistEnabledRes.data?.value === 'true')
      setBlacklistPatterns(blacklistPatternsRes.data?.value || '')
    } catch (e) {
      console.log(e)
      messageApi.error('获取配置失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveLimit = async () => {
    setSaveLoading(true)
    try {
      await Promise.all([
        setDanmuOutputTotal({ value: `${limit}` }),
        setDanmakuMergeOutputEnabled({ value: mergeEnabled ? 'true' : 'false' }),
      ])
      messageApi.success('弹幕输出配置已保存')
    } catch (e) {
      messageApi.error('保存失败')
    } finally {
      setSaveLoading(false)
    }
  }

  const handleSaveColor = async () => {
    setColorSaveLoading(true)
    try {
      await Promise.all([
        setDanmakuRandomColorMode({ value: colorMode }),
        setDanmakuRandomColorPalette({ value: paletteToServer(palette) }),
      ])
      messageApi.success('随机颜色配置已保存')
    } catch (e) {
      messageApi.error('保存随机颜色配置失败')
    } finally {
      setColorSaveLoading(false)
    }
  }

  const handleSaveBlacklist = async () => {
    setBlacklistSaveLoading(true)
    try {
      await Promise.all([
        setDanmakuBlacklistEnabled({ value: blacklistEnabled ? 'true' : 'false' }),
        setDanmakuBlacklistPatterns({ value: blacklistPatterns }),
      ])
      messageApi.success('弹幕黑名单配置已保存')
    } catch (e) {
      messageApi.error('保存弹幕黑名单配置失败')
    } finally {
      setBlacklistSaveLoading(false)
    }
  }

  const addColorToPalette = (color) => {
    const hex = color.toLowerCase()
    if (palette.includes(hex)) {
      messageApi.info('该颜色已存在')
      return
    }
    setPalette(prev => [...prev, hex])
  }

  const removeColor = (color) => {
    setPalette(prev => prev.filter(c => c !== color))
  }

  const randomColor = () => {
    const rand = Math.floor(Math.random() * 16777216)
    return `#${rand.toString(16).padStart(6, '0')}`
  }

  useEffect(() => {
    getConfig()
  }, [])

  return (
    <div className="my-6">
      <Card loading={loading} title="弹幕输出配置">
        <div>在这里调整弹幕 API 的输出行为。</div>
        <div className="my-4">
          <div className="flex items-center justify-start gap-4 mb-2 flex-wrap">
            <div className="flex items-center gap-2">
              <span>弹幕输出上限</span>
              <InputNumber value={limit} onChange={v => setLimit(v)} />
            </div>
            <div className="flex items-center gap-2">
              <span>合并输出</span>
              <Switch
                checked={mergeEnabled}
                onChange={setMergeEnabled}
              />
              <Tooltip title="启用后，将所有源的弹幕合并后再进行均衡采样输出，而不是每个源单独采样">
                <QuestionCircleOutlined className="text-gray-400 cursor-help" />
              </Tooltip>
            </div>
          </div>
          <div className="text-sm text-gray-600">
            设置弹幕 API 返回的最大数量。-1 表示无限制。为防止客户端卡顿，建议设置 1000-5000。
            当弹幕总数超过限制时，系统按时间段均匀采样，确保弹幕在视频时长中分布均匀。
          </div>
        </div>
        <div className="flex items-center justify-end gap-3">
          <Button
            type="primary"
            loading={saveLoading}
            onClick={handleSaveLimit}
          >
            保存输出配置
          </Button>
        </div>
      </Card>

      <Card loading={loading} title="随机弹幕颜色" className="mt-4">
        <div className="text-sm text-gray-600 mb-3">
          可配置随机色板和生效模式。默认不改色。
        </div>
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <span>模式</span>
            <Select
              value={colorMode}
              style={{ width: 220 }}
              onChange={setColorMode}
              options={[
                { label: '不使用', value: 'off' },
                { label: '随机白色弹幕', value: 'white_to_random' },
                { label: '全部随机上色', value: 'all_random' },
              ]}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-4 mb-3">
          <div className="flex items-center gap-3">
            <ColorPicker
              value={colorPickerValue}
              showText
              presets={[
                { label: '默认色板', colors: DEFAULT_COLOR_PALETTE },
              ]}
              onChange={(_, hex) => setColorPickerValue(hex)}
            />
            <Button
              onClick={() => addColorToPalette(colorPickerValue)}
              disabled={!colorPickerValue}
            >
              添加到色板
            </Button>
            <Button
              onClick={() => {
                const next = randomColor()
                setColorPickerValue(next)
                addColorToPalette(next)
              }}
            >
              随机一个颜色
            </Button>
          </div>
        </div>

        <div className="mb-3">
          <div className="mb-2 text-sm text-gray-700">当前随机颜色序列</div>
          <div className="flex flex-wrap gap-2">
            {palette.map(color => (
              <Tag
                key={color}
                closable
                onClose={() => removeColor(color)}
                style={{
                  backgroundColor: color,
                  borderColor: '#ccc',
                  color: '#000',
                  minWidth: 72,
                  textAlign: 'center',
                }}
              >
                {color}
              </Tag>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <Button
            type="primary"
            loading={colorSaveLoading}
            onClick={handleSaveColor}
          >
            保存随机颜色
          </Button>
        </div>
      </Card>

      <Card loading={loading} title="弹幕输出黑名单" className="mt-4">
        <div className="text-sm text-gray-600 mb-4">
          使用正则表达式过滤弹幕内容。启用后，匹配黑名单规则的弹幕将被拦截，不会输出到客户端。
        </div>

        <div className="mb-4">
          <div className="flex items-center gap-2 mb-3">
            <span>启用黑名单过滤</span>
            <Switch
              checked={blacklistEnabled}
              onChange={setBlacklistEnabled}
            />
          </div>

          <div className="mb-2 text-sm text-gray-700">
            黑名单规则（正则表达式）
          </div>
          <TextArea
            value={blacklistPatterns}
            onChange={e => setBlacklistPatterns(e.target.value)}
            placeholder="支持两种格式：&#10;1. 单行格式：用 | 分隔多个规则，如：广告|推广|666&#10;2. 多行格式：每行一个正则表达式"
            rows={6}
            disabled={!blacklistEnabled}
            style={{ fontFamily: 'monospace', fontSize: '12px' }}
          />

          <div className="mt-2 text-xs text-gray-500">
            <div>• 默认过滤规则参考hills TG群群友分享过滤规则</div>
            <div>• 支持单行格式（用 | 分隔）或多行格式（每行一个规则）</div>
            <div>• 不区分大小写，自动匹配弹幕内容</div>
            <div>• 示例（单行）：<code className="bg-gray-100 px-1">广告|推广|666</code></div>
            <div>• 示例（多行）：每行写一个规则，# 开头的行为注释</div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3">
          <Button
            type="primary"
            loading={blacklistSaveLoading}
            onClick={handleSaveBlacklist}
          >
            保存黑名单配置
          </Button>
        </div>
      </Card>
    </div>
  )
}
