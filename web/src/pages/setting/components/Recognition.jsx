import { Button, Card, Form, Input } from 'antd'
import { useEffect, useState } from 'react'
import { useMessage } from '../../../MessageContext'
import { getRecognition, setRecognition } from '../../../apis'

export const Recognition = () => {
  const [loading, setLoading] = useState(true)
  const [isSaveLoading, setIsSaveLoading] = useState(false)
  const messageApi = useMessage()

  const [text, setText] = useState('')

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
      const response = await setRecognition({
        content: text,
      })
      setIsSaveLoading(false)

      // 检查是否有警告信息
      if (response.data?.warnings && response.data.warnings.length > 0) {
        const warningMessages = response.data.warnings.join('\n')
        messageApi.warning(`保存成功，但发现以下问题：\n${warningMessages}`, 8) // 显示8秒
      } else {
        messageApi.success('保存成功')
      }
    } catch (error) {
      messageApi.error('保存失败')
    } finally {
      setIsSaveLoading(false)
    }
  }

  return (
    <div className="my-6">
      <Card loading={loading} title="自定义识别词配置">
        <div className="mb-4">
          <div className="text-sm mb-2 opacity-75">
            <p className="mb-3">
              <strong>识别词配置说明：</strong>
            </p>
            <div className="bg-blue-50 p-3 rounded mb-3">
              <p className="font-semibold text-blue-800 mb-2">
                🔍 搜索预处理（在搜索前执行）
              </p>
              <p className="text-blue-700 mb-2">
                用于修正搜索关键词，提高搜索准确性
              </p>
              <ul className="list-disc list-inside space-y-1 text-blue-700">
                <li>
                  <strong>屏蔽词：</strong> <code>BLOCK:预告</code>{' '}
                  <code>BLOCK:花絮</code> （从搜索词中移除）
                </li>
                <li>
                  <strong>简单替换：</strong>{' '}
                  <code>奔跑吧 =&gt; 奔跑吧兄弟</code>
                </li>
                <li>
                  <strong>集数偏移：</strong>{' '}
                  <code>第 &lt;&gt; 话 &gt;&gt; EP-1</code>
                </li>
                <li>
                  <strong>季度预处理：</strong>{' '}
                  <code>
                    新说唱2025 =&gt; &#123;&lt;search_season=8&gt;&#125;
                  </code>{' '}
                  （搜索时使用指定季度）
                </li>
              </ul>
            </div>
            <div className="bg-green-50 p-3 rounded">
              <p className="font-semibold text-green-800 mb-2">
                🎯 入库后处理（选择最佳匹配后执行）
              </p>
              <p className="text-green-700 mb-2">
                用于修正最终存储的标题和季数信息
              </p>
              <ul className="list-disc list-inside space-y-1 text-green-700">
                <li>
                  <strong>季度偏移：</strong>{' '}
                  <code>
                    新说唱2025 =&gt; &#123;[title=中国新说唱
                    第8季;season_offset=1&gt;8]&#125;
                  </code>
                </li>
                <li>
                  <strong>元数据替换：</strong>{' '}
                  <code>
                    错误标题 =&gt; &#123;[tmdbid=12345;type=tv;s=1;e=1]&#125;
                  </code>
                </li>
                <li>
                  <strong>源特定偏移：</strong>{' '}
                  <code>
                    某动画 =&gt;
                    &#123;[source=tencent;title=正确标题;season_offset=9&gt;13]&#125;
                  </code>
                </li>
              </ul>
            </div>
            <p className="mt-2">
              <strong>偏移格式：</strong> 1&gt;8(直接映射), 1+7(加法),
              9-1(减法), *+4(通用加法), *&gt;1(通用映射)
            </p>
          </div>
        </div>
        <Input.TextArea
          rows={12}
          value={text}
          onChange={value => setText(value.target.value)}
          placeholder="# ===== 搜索预处理规则 =====
# 屏蔽词（从搜索关键词中移除）
BLOCK:预告
BLOCK:花絮

# 简单替换（搜索前修正关键词）
奔跑吧 => 奔跑吧兄弟
极限挑战 => 极限挑战第一季

# 集数偏移（搜索前修正集数）
第 <> 话 >> EP-1
Episode <> : >> EP+5

# 季度预处理（搜索时使用指定季度）
新说唱2025 => {<search_season=8>}
某动画 第1季 => {<search_season=5>}

# ===== 入库后处理规则 =====
# 季度偏移（入库时修正标题和季数）
新说唱2025 => {[title=中国新说唱 第8季;season_offset=1>8]}
奔跑吧 第9季 => {[source=tencent;title=奔跑吧兄弟;season_offset=9>13]}

# 元数据替换（直接指定TMDB ID）
错误标题 => {[tmdbid=12345;type=tv;s=1;e=1]}"
        />
        <div className="flex justify-end mt-4">
          <Button type="primary" onClick={handleSave} loading={isSaveLoading}>
            保存修改
          </Button>
        </div>
      </Card>
    </div>
  )
}
