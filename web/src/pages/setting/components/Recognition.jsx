import { Button, Card, Collapse, Input, InputNumber, Modal, Select, Space, Tag, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { useMessage } from '../../../MessageContext'
import { getRecognition, setRecognition, testRecognition, generateRegex } from '../../../apis'
import { RobotOutlined } from '@ant-design/icons'

export const Recognition = () => {
  const [loading, setLoading] = useState(true)
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const [isTestLoading, setIsTestLoading] = useState(false)
  const messageApi = useMessage()

  const [text, setText] = useState('')
  const [aiModalOpen, setAiModalOpen] = useState(false)
  const [aiDesc, setAiDesc] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiResult, setAiResult] = useState('')

  // 测试工具状态
  const [testTitle, setTestTitle] = useState('')
  const [testSeason, setTestSeason] = useState(1)
  const [testEpisode, setTestEpisode] = useState(1)
  const [testSource, setTestSource] = useState(null)
  const [testStage, setTestStage] = useState('all')
  const [testResult, setTestResult] = useState(null)

  useEffect(() => {
    setLoading(true)
    getRecognition()
      .then(res => {
        setText(res.data?.content ?? '')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const handleSave = async () => {
    try {
      setIsSaveLoading(true)
      const response = await setRecognition({ content: text })
      if (response.data?.warnings && response.data.warnings.length > 0) {
        const warningMessages = response.data.warnings.join('\n')
        messageApi.warning(`保存成功，但发现以下问题：\n${warningMessages}`, 8)
      } else {
        messageApi.success('保存成功')
      }
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  const handleAiGenerate = async () => {
    if (!aiDesc.trim()) {
      messageApi.warning('请输入需求描述')
      return
    }
    setAiLoading(true)
    setAiResult('')
    try {
      const res = await generateRegex(aiDesc.trim(), text, 'recognition_rules')
      if (res.data?.regex) {
        setAiResult(res.data.regex)
      } else {
        messageApi.error('AI 未能生成有效的配置规则')
      }
    } catch (e) {
      messageApi.error(e?.response?.data?.detail || 'AI 生成失败')
    } finally {
      setAiLoading(false)
    }
  }

  const handleApplyAiResult = () => {
    if (!aiResult) return
    setText(aiResult)
    setAiModalOpen(false)
    setAiDesc('')
    setAiResult('')
    messageApi.success('已应用 AI 生成的配置')
  }

  const handleTest = async () => {
    if (!testTitle.trim()) {
      messageApi.warning('请输入要测试的标题')
      return
    }
    try {
      setIsTestLoading(true)
      const res = await testRecognition({
        title: testTitle,
        season: testSeason,
        episode: testEpisode,
        source: testSource || null,
        stage: testStage,
      })
      setTestResult(res.data)
    } catch (error) {
      messageApi.error(`测试失败: ${error.message || '未知错误'}`)
    } finally {
      setIsTestLoading(false)
    }
  }

  return (
    <div className="my-6 space-y-4">
      <Card loading={loading} title="自定义识别词配置">
        <Collapse
          ghost
          items={[{
            key: 'help',
            label: <span className="text-sm opacity-75"><strong>📖 配置说明（点击展开）</strong></span>,
            children: (
              <div className="text-sm opacity-75">
                <div className="bg-blue-50 dark:bg-blue-950/30 p-3 rounded mb-3">
                  <p className="font-semibold text-blue-800 dark:text-blue-300 mb-2">🔍 搜索预处理（在搜索前执行）</p>
                  <ul className="list-disc list-inside space-y-1 text-blue-700 dark:text-blue-400">
                    <li><strong>屏蔽词：</strong> <code>BLOCK:预告</code></li>
                    <li><strong>简单替换：</strong> <code>奔跑吧 =&gt; 奔跑吧兄弟</code></li>
                    <li><strong>集数偏移：</strong> <code>第 &lt;&gt; 话 &gt;&gt; EP-1</code></li>
                    <li><strong>复合格式：</strong> <code>某动画 =&gt; 正确名称 &amp;&amp; 第 &lt;&gt; 话 &gt;&gt; EP-1</code></li>
                    <li><strong>季度预处理：</strong> <code>{'新说唱2025 => {<search_season=8>}'}</code></li>
                  </ul>
                </div>
                <div className="bg-green-50 dark:bg-green-950/30 p-3 rounded">
                  <p className="font-semibold text-green-800 dark:text-green-300 mb-2">🎯 入库后处理（匹配后执行）</p>
                  <ul className="list-disc list-inside space-y-1 text-green-700 dark:text-green-400">
                    <li><strong>季度偏移：</strong> <code>{'新说唱2025 => {[title=中国新说唱;season_offset=1>8]}'}</code></li>
                    <li><strong>元数据替换：</strong> <code>{'错误标题 => {[tmdbid=12345;type=tv;s=1;e=1]}'}</code></li>
                    <li><strong>源特定偏移：</strong> <code>{'某动画 => {[source=tencent;title=正确标题;season_offset=9>13]}'}</code></li>
                    <li><strong>部分集数偏移：</strong> <code>{'某动画(下) => {[ep_range=1-12;ep_offset=+12]}'}</code></li>
                  </ul>
                </div>
                <p className="mt-2"><strong>季度偏移：</strong> 1&gt;8(直接映射), 1+7(加法), 9-1(减法), *+4(通用加法)　<strong>集偏移：</strong> EP+1, 2*EP, 2*EP-1</p>
              </div>
            ),
          }]}
          className="mb-4"
        />
        <div className="flex justify-end mb-2">
          <Tooltip title="使用 AI 根据自然语言描述生成识别词配置">
            <Button
              type="link"
              size="small"
              icon={<RobotOutlined />}
              onClick={() => setAiModalOpen(true)}
            >
              AI 生成
            </Button>
          </Tooltip>
        </div>
        <Input.TextArea
          rows={12}
          value={text}
          onChange={value => setText(value.target.value)}
          placeholder={`# ===== 搜索预处理规则 =====
BLOCK:预告
奔跑吧 => 奔跑吧兄弟

# ===== 入库后处理规则 =====
新说唱2025 => {[title=中国新说唱 第8季;season_offset=1>8]}`}
        />
        <div className="flex justify-end mt-4">
          <Button type="primary" onClick={handleSave} loading={isSaveLoading}>
            保存修改
          </Button>
        </div>
      </Card>

      <Card title="🧪 规则测试工具" size="small">
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[200px]">
              <div className="text-xs text-gray-500 mb-1">标题</div>
              <Input
                value={testTitle}
                onChange={e => setTestTitle(e.target.value)}
                placeholder="输入要测试的标题"
                onPressEnter={handleTest}
              />
            </div>
            <div className="w-20">
              <div className="text-xs text-gray-500 mb-1">季度</div>
              <InputNumber value={testSeason} onChange={setTestSeason} min={1} className="w-full" />
            </div>
            <div className="w-20">
              <div className="text-xs text-gray-500 mb-1">集数</div>
              <InputNumber value={testEpisode} onChange={setTestEpisode} min={1} className="w-full" />
            </div>
            <div className="w-32">
              <div className="text-xs text-gray-500 mb-1">数据源</div>
              <Input value={testSource} onChange={e => setTestSource(e.target.value)} placeholder="可选" />
            </div>
            <div className="w-36">
              <div className="text-xs text-gray-500 mb-1">阶段</div>
              <Select value={testStage} onChange={setTestStage} className="w-full" options={[
                { value: 'all', label: '全部' },
                { value: 'preprocess', label: '搜索预处理' },
                { value: 'postprocess', label: '入库后处理' },
              ]} />
            </div>
            <Button type="primary" onClick={handleTest} loading={isTestLoading}>测试</Button>
          </div>

          {testResult && (
            <div className={`p-3 rounded border ${testResult.matched ? 'bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800' : 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700'}`}>
              <div className="flex items-center gap-2 mb-2">
                <Tag color={testResult.matched ? 'green' : 'default'}>
                  {testResult.matched ? '✓ 命中规则' : '○ 未命中'}
                </Tag>
              </div>
              <div className="text-sm space-y-1">
                <div className="flex gap-2">
                  <span className="text-gray-500 w-12 shrink-0">标题:</span>
                  <span>{testResult.originalTitle}</span>
                  {testResult.originalTitle !== testResult.processedTitle && (
                    <><span className="text-gray-400">→</span><span className="font-semibold text-green-600">{testResult.processedTitle}</span></>
                  )}
                </div>
                <div className="flex gap-2">
                  <span className="text-gray-500 w-12 shrink-0">季/集:</span>
                  <span>S{String(testResult.originalSeason ?? '?').padStart(2, '0')}E{String(testResult.originalEpisode ?? '?').padStart(2, '0')}</span>
                  {(testResult.originalSeason !== testResult.processedSeason || testResult.originalEpisode !== testResult.processedEpisode) && (
                    <><span className="text-gray-400">→</span><span className="font-semibold text-green-600">S{String(testResult.processedSeason ?? '?').padStart(2, '0')}E{String(testResult.processedEpisode ?? '?').padStart(2, '0')}</span></>
                  )}
                </div>
                {testResult.matchedRules?.length > 0 && (
                  <div className="mt-2 pt-2 border-t border-gray-200 dark:border-gray-600">
                    <div className="text-xs text-gray-500 mb-1">命中规则:</div>
                    {testResult.matchedRules.map((rule, i) => (
                      <div key={i} className="text-xs text-gray-600 dark:text-gray-400 pl-2">• {rule}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </Card>

      <Modal
        title={<><RobotOutlined /> AI 识别词配置助手</>}
        open={aiModalOpen}
        onCancel={() => { setAiModalOpen(false); setAiResult('') }}
        footer={null}
        destroyOnClose
        width={700}
      >
        <div className="space-y-4">
          <div>
            <div className="text-sm text-gray-600 mb-2">
              用自然语言描述你的需求，AI 会按照识别词 DSL 语法生成对应的配置规则。
            </div>
            <Input.TextArea
              value={aiDesc}
              onChange={e => setAiDesc(e.target.value)}
              placeholder={'例如：\n• 新说唱2025 搜索时使用"中国新说唱 第8季"，季度偏移 1>8\n• 屏蔽包含"预告"的标题\n• 奔跑吧 替换为 奔跑吧兄弟'}
              rows={4}
              onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleAiGenerate() } }}
            />
          </div>
          <div className="flex justify-end">
            <Button
              type="primary"
              icon={<RobotOutlined />}
              loading={aiLoading}
              onClick={handleAiGenerate}
            >
              生成
            </Button>
          </div>
          {aiResult && (
            <div>
              <div className="text-sm text-gray-600 mb-1">{text.trim() ? '合并后的完整配置：' : '生成结果：'}</div>
              <div className="bg-gray-50 border rounded p-3 font-mono text-sm whitespace-pre-wrap" style={{ maxHeight: 300, overflow: 'auto' }}>
                {aiResult}
              </div>
              <div className="flex justify-end mt-3">
                <Space>
                  <Button onClick={() => setAiResult('')}>清除</Button>
                  <Button type="primary" onClick={handleApplyAiResult}>
                    应用配置
                  </Button>
                </Space>
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
