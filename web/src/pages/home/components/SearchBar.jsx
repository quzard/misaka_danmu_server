import { getSearchResult, clearSearchCache } from '../../../apis'
import { useEffect, useRef, useState } from 'react'
import {
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Progress,
  Tag,
} from 'antd'
import { useAtom, useAtomValue } from 'jotai'
import {
  isMobileAtom,
  lastSearchResultAtom,
  searchHistoryAtom,
  searchLoadingAtom,
} from '../../../../store'
import { useModal } from '../../../ModalContext'
import { useMessage } from '../../../MessageContext'

export const SearchBar = () => {
  const [loading, setLoading] = useAtom(searchLoadingAtom)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [form] = Form.useForm()
  const season = Form.useWatch('season', form)
  const episode = Form.useWatch('episode', form)
  const keyword = Form.useWatch('keyword', form)
  const [percent, setPercent] = useState(0)
  const timer = useRef(0)

  const isMobile = useAtomValue(isMobileAtom)
  const [searchHistory, setSearchHistory] = useAtom(searchHistoryAtom)

  //开启精确搜索
  const [exactSearch, setExactSearch] = useState(false)

  const [, setLastSearchResultData] = useAtom(lastSearchResultAtom)

  const modalApi = useModal()
  const messageApi = useMessage()

  const onInsert = () => {
    if (!season) {
      messageApi.destroy()
      messageApi.error('请输入季数')
      return
    }
    let formatted = ` S${String(season).padStart(2, '0')}`
    if (episode) {
      formatted += `E${String(episode).padStart(2, '0')}`
    }
    form.setFieldValue('keyword', `${keyword}${formatted}`)
  }

  const onSearch = async values => {
    try {
      if (loading) return
      setLoading(true)
      setSearchHistory(history => {
        if (history.includes(values.keyword)) return history
        return [values.keyword, ...history].slice(0, 10)
      })

      timer.current = window.setInterval(() => {
        setPercent(p => (p <= 90 ? p + Math.ceil(Math.random() * 5) : 95))
      }, 200)

      const res = await getSearchResult(
        {
          keyword: values.keyword,
        },
        onProgress
      )

      setLastSearchResultData({
        ...(res?.data || {}),
        keyword: values.keyword,
      })
    } catch (error) {
      console.error(`搜索失败: ${error.message || error}`)
    } finally {
      setLoading(false)
      setPercent(0)
      clearInterval(timer.current)
    }
  }

  const onProgress = progressEvent => {
    clearInterval(timer.current)
    if (progressEvent.lengthComputable) {
      const percent = Math.round(
        (progressEvent.loaded / progressEvent.total) * 100
      )
      setPercent(percent)
    }
  }

  const onClearCache = () => {
    modalApi.confirm({
      title: '清除缓存',
      zIndex: 1002,
      content: (
        <div>
          您确定要清除所有缓存吗？
          <br />
          这将清除所有搜索结果和分集列表的临时缓存，下次访问时需要重新从网络获取。
        </div>
      ),
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          setCacheLoading(true)
          const res = await clearSearchCache()
          messageApi.destroy()
          messageApi.success(res.data.message || '缓存已成功清除！')
        } catch (err) {
          messageApi.destroy()
          messageApi.error(`清除缓存失败: ${error.message || error}`)
        } finally {
          setCacheLoading(false)
        }
      },
    })
  }

  useEffect(() => {
    return () => {
      clearInterval(timer.current)
    }
  }, [])

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="text-lg font-semibold">搜索番剧</div>
        <Button type="primary" loading={cacheLoading} onClick={onClearCache}>
          清除缓存
        </Button>
      </div>

      <Form form={form} onFinish={onSearch}>
        <div className="flex items-center gap-3 mb-4">
          <Form.Item
            name="keyword"
            className="flex-1 mb-0"
            rules={[{ required: true, message: '请输入番剧名称' }]}
          >
            <Input.Search
              placeholder="请输入番剧名称"
              size="large"
              enterButton="搜索"
              loading={loading}
              onSearch={value => {
                if (value) {
                  form.setFieldValue('keyword', value)
                  form.submit()
                }
              }}
            />
          </Form.Item>
        </div>

        {loading && (
          <div className="mb-4">
            <Progress percent={percent} />
          </div>
        )}

        <div className="flex items-center gap-3 flex-wrap">
          <Checkbox
            checked={exactSearch}
            onChange={e => setExactSearch(e.target.checked)}
          >
            精确搜索
          </Checkbox>

          <Form.Item name="season" label="季" className="mb-0 flex items-center">
            <InputNumber min={0} placeholder="季数" disabled={!exactSearch} style={{ width: 80 }} />
          </Form.Item>
          <Form.Item name="episode" label="集" className="mb-0 flex items-center">
            <InputNumber min={1} placeholder="集数" disabled={!exactSearch || !season} style={{ width: 80 }} />
          </Form.Item>
          <Button type="primary" onClick={onInsert} size="small" disabled={!exactSearch}>
            插入
          </Button>
          {!isMobile && (
            <span className={`text-xs ${exactSearch ? 'text-gray-500' : 'text-gray-300'}`}>
              填写季、集后可插入到名称中
            </span>
          )}
        </div>
      </Form>

      {!!searchHistory.length && (
        <div className="flex items-center flex-wrap gap-2 mt-4">
          {searchHistory.map((it, index) => (
            <Tag
              key={index}
              closable
              className="cursor-pointer"
              onClick={() => {
                form.setFieldsValue({ keyword: it })
                onSearch({ keyword: it })
              }}
              onClose={e => {
                e.preventDefault()
                setSearchHistory(history => history.filter(o => o !== it))
              }}
            >
              {it}
            </Tag>
          ))}
        </div>
      )}
    </div>
  )
}
