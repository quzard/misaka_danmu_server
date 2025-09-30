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
            <p>
              <strong>支持的格式（参考MoviePilot）：</strong>
            </p>
            <ul className="list-disc list-inside space-y-1">
              <li>
                <strong>屏蔽词：</strong> <code>屏蔽词</code>
              </li>
              <li>
                <strong>简单替换：</strong> <code>被替换词 =&gt; 替换词</code>
              </li>
              <li>
                <strong>集数偏移：</strong>{' '}
                <code>前定位词 &lt;&gt; 后定位词 &gt;&gt; 集偏移量</code>
              </li>
              <li>
                <strong>复合格式：</strong>{' '}
                <code>
                  被替换词 =&gt; 替换词 &amp;&amp; 前定位词 &lt;&gt; 后定位词
                  &gt;&gt; 集偏移量
                </code>
              </li>
              <li>
                <strong>元数据替换：</strong>{' '}
                <code>
                  错误标题 =&gt; &#123;[tmdbid=12345;type=tv;s=1;e=1]&#125;
                </code>
              </li>
              <li>
                <strong>季度偏移：</strong>{' '}
                <code>
                  TX源某动画第9季 =&gt;
                  &#123;[source=tencent;season_offset=9&gt;13]&#125;
                </code>
              </li>
            </ul>
            <p className="mt-2">
              <strong>集数偏移支持运算：</strong> EP+1, 2*EP, 2*EP-1 等
            </p>
            <p className="mt-1">
              <strong>季度偏移支持格式：</strong> 9&gt;13(直接映射), 9+4(加法),
              9-1(减法), *+4(通用加法), *&gt;1(通用映射)
            </p>
          </div>
        </div>
        <Input.TextArea
          rows={12}
          value={text}
          onChange={value => setText(value.target.value)}
          placeholder="# 示例配置：
# 屏蔽词
预告
花絮

# 简单替换
奔跑吧 => 奔跑吧兄弟

# 集数偏移
第 <> 话 >> EP-1

# 复合格式
某动画 => 某动画正确名称 && 第 <> 话 >> EP-1

# 季度偏移
TX源某动画第9季 => {[source=tencent;season_offset=9>13]}
某动画第5季 => {[source=bilibili;season_offset=5+3]}"
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
