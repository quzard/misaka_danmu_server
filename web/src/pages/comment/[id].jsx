import { useEffect, useState, useRef } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { getDanmakuDetail, getEpisodes } from '../../apis'
import { Breadcrumb, Card, Empty } from 'antd'
import { HomeOutlined } from '@ant-design/icons'

export const CommentDetail = () => {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const episodeId = searchParams.get('episodeId')

  const [loading, setLoading] = useState(true)
  const [commentList, setCommentList] = useState([])
  const [episode, setEpisode] = useState({})
  const [loadingMore, setLoadingMore] = useState(false)
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 100,
    total: 0,
  })

  const navigate = useNavigate()

  /**
   * 获取弹幕详情
   * @param {boolean} isLoadMore - 是否为加载更多操作
   */
  const getDetail = async (isLoadMore = false) => {
    try {
      if (isLoadMore) {
        setLoadingMore(true)
      } else {
        setLoading(true)
      }

      const [episodeRes, commentRes] = await Promise.all([
        getEpisodes({
          sourceId: Number(episodeId),
        }),
        getDanmakuDetail({
          id: Number(id),
          page: pagination.current,
          pageSize: pagination.pageSize,
        }),
      ])

      if (isLoadMore) {
        // 加载更多时追加数据
        setCommentList(prev => [...prev, ...(commentRes.data?.comments || [])])
      } else {
        // 刷新时替换数据
        setCommentList(commentRes.data?.comments || [])
      }

      setEpisode(
        episodeRes?.data?.list?.filter(
          it => it.episodeId === Number(id)
        )?.[0] || {}
      )

      setPagination(prev => ({
        ...prev,
        total: commentRes.data?.count || 0,
      }))

      setLoading(false)
      setLoadingMore(false)
    } catch (error) {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  /**
   * 处理滚动事件，检测是否需要加载更多
   */
  const handleScroll = () => {
    if (loadingMore || commentList.length >= pagination.total) {
      return
    }

    const { scrollTop, scrollHeight, clientHeight } = document.documentElement
    // 当滚动到距离底部100px时触发加载更多
    if (scrollTop + clientHeight >= scrollHeight - 100) {
      setPagination(prev => ({
        ...prev,
        current: prev.current + 1,
      }))
    }
  }

  useEffect(() => {
    const isLoadMore = pagination.current > 1
    getDetail(isLoadMore)
  }, [pagination.current])

  useEffect(() => {
    if (!commentList.length || !pagination.total) return
    window.addEventListener('scroll', handleScroll)
    return () => {
      window.removeEventListener('scroll', handleScroll)
    }
  }, [loadingMore, commentList.length, pagination.total])

  return (
    <div className="my-6">
      <Breadcrumb
        className="!mb-4"
        items={[
          {
            title: (
              <Link to="/">
                <HomeOutlined />
              </Link>
            ),
          },
          {
            title: <Link to="/library">弹幕库</Link>,
          },
          {
            title: <Link to="javascript:void(0)">分集列表</Link>,
            onClick: () => navigate(-1),
          },
          {
            title: '弹幕列表',
          },
        ]}
      />
      <Card loading={loading} title={`弹幕列表: ${episode?.title ?? ''}`}>
        <div>
          {!!commentList?.length ? (
            <>
              {commentList?.map((it, index) => (
                <div key={index}>
                  <div className="my-1">
                    <pre>
                      {it.p} | {it.m}
                    </pre>
                  </div>
                </div>
              ))}
              {loadingMore && (
                <div
                  style={{
                    textAlign: 'center',
                    marginTop: 12,
                    height: 32,
                    lineHeight: '32px',
                    color: '#999',
                  }}
                >
                  正在加载更多...
                </div>
              )}
              {!loadingMore && commentList.length < pagination.total && (
                <div
                  style={{
                    textAlign: 'center',
                    marginTop: 12,
                    height: 32,
                    lineHeight: '32px',
                    color: '#999',
                  }}
                >
                  下拉加载更多
                </div>
              )}
            </>
          ) : (
            <Empty description="暂无弹幕" />
          )}
        </div>
      </Card>
    </div>
  )
}
