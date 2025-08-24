import { message, Spin } from 'antd'
import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { bangumiAuthOauth2 } from '../../apis'

export const BangumiAuth = () => {
  const [searchParams] = useSearchParams()
  const code = searchParams.get('code')
  const state = searchParams.get('state')
  const navigate = useNavigate()

  const getAuth = async () => {
    try {
      await bangumiAuthOauth2({
        code,
        state,
      })
      navigate('/setting?key=bangumi')
    } catch (error) {
      message.error('授权失败')
      navigate('/setting?key=bangumi')
    }
  }

  useEffect(() => {
    getAuth()
  })

  return (
    <div className="my-6 text-center">
      <Spin></Spin>
      <div className="mt-3">Bangumi授权中</div>
    </div>
  )
}
