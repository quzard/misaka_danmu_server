import React from 'react'

/**
 * 中止任务确认内容组件
 */
const StopConfirmContent = ({ selectList, forceStopRef }) => {
  const [force, setForce] = React.useState(false)

  const hasStuckTasks = selectList.some(task =>
    task.status === 'PAUSED' || task.status === 'RUNNING'
  )

  // 更新 ref 值
  React.useEffect(() => {
    forceStopRef.current = force
  }, [force, forceStopRef])

  return (
    <div>
      <div>您确定要中止任务吗？</div>
      <div className="max-h-[310px] overflow-y-auto mt-3">
        {selectList.map((it, i) => (
          <div key={it.taskId}>
            {i + 1}、{it.title}
            {(it.status === 'PAUSED' || it.status === 'RUNNING') && (
              <span className="text-orange-500 ml-2">({it.status})</span>
            )}
          </div>
        ))}
      </div>

      {/* 强制中止复选框 */}
      <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded">
        <label className="flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
            className="mr-2"
          />
          <span className="text-sm">
            强制中止
            <span className="text-gray-500 ml-1">
              (直接标记为失败状态，适用于卡住的任务)
            </span>
          </span>
        </label>
        {force && (
          <div className="mt-2 text-xs text-orange-600">
            ⚠️ 强制中止将直接标记任务为失败状态
          </div>
        )}
      </div>

      {hasStuckTasks && !force && (
        <div className="mt-3 p-2 bg-yellow-50 border border-yellow-200 rounded">
          <div className="text-sm text-yellow-700">
            💡 检测到运行中或暂停的任务，如果正常中止失败可勾选"强制中止"
          </div>
        </div>
      )}
    </div>
  )
}

export default StopConfirmContent
