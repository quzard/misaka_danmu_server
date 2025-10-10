import { ErrorBoundary } from 'react-error-boundary'
import { ErrorFallback } from '../components/ErrorFallback.jsx'
import { Outlet } from 'react-router-dom'
import { useEffect } from 'react'
import { Header } from './Header.jsx'
import { useAtomValue, useSetAtom } from 'jotai'
import { isMobileAtom, userinfoAtom } from '../../store/index.js'
import { getUserInfo } from '../apis/index.js'
import classNames from 'classnames'
import Cookies from 'js-cookie'

export const Layout = () => {
  const setUserinfo = useSetAtom(userinfoAtom)
  const isMobile = useAtomValue(isMobileAtom)
  useEffect(() => {
    const token = Cookies.get('danmu_token')
    if (!token) {
      window.location.href = '/login'
    } else {
      getUserInfo()
        .then(res => {
          if (!res.data || !res.data.username) {
            Cookies.remove('danmu_token', { path: '/' })
            window.location.href = '/login'
          } else {
            setUserinfo(res.data)
          }
        })
        .catch(err => {
          // Cookies.remove('danmu_token', { path: '/' })
          window.location.href = '/login'
        })
    }
  }, [])

  return (
    <ErrorBoundary FallbackComponent={ErrorFallback}>
      <Header />
      <div
        className={classNames({
          'w-full min-h-screen px-4 pb-22 pt-14': isMobile,
          'max-w-[1200px] min-h-screen mx-auto pt-18 pb-10 px-8': !isMobile,
        })}
      >
        <Outlet />
      </div>
    </ErrorBoundary>
  )
}
