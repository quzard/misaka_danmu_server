import { useEffect, useState } from 'react';
import { getRateLimitStatus } from '../../../apis';
import { Alert, Card, Progress, Spin, Tooltip } from 'antd';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import 'dayjs/locale/zh-cn';

dayjs.extend(relativeTime);
dayjs.locale('zh-cn');

const getPeriodText = (period) => {
  const map = { second: '秒', minute: '分钟', hour: '小时', day: '天' };
  return map[period] || period;
};

const RateLimitItem = ({ item, isGlobal, isDisabled }) => {
  const percent = item.limit > 0 ? (item.requestCount / item.limit) * 100 : 0;
  const title = isGlobal ? '全局流控' : item.providerName;

  const itemContent = (
    <div className={isDisabled ? 'opacity-50' : ''}>
      <div className="flex justify-between items-center mb-1">
        <span className="font-semibold">{title}</span>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          {item.requestCount} / {item.limit > 0 ? item.limit : '∞'} (每 {item.limit > 0 ? `${item.periodSeconds / 3600 >= 1 ? item.periodSeconds / 3600 : item.periodSeconds / 60}` : ''} {getPeriodText(item.period)})
        </span>
      </div>
      <Progress
        percent={percent}
        showInfo={false}
        strokeColor={percent > 80 ? '#f5222d' : '#1890ff'}
      />
      <div className="text-right text-xs text-gray-400 dark:text-gray-500 mt-1">
        重置于: {dayjs(item.lastResetTime).fromNow()}
      </div>
    </div>
  );

  if (isDisabled) {
    return (
      <Tooltip title="全局流控已开启，此规则当前遵循全局设置。">
        {itemContent}
      </Tooltip>
    );
  }

  return itemContent;
};

export const RateLimitPanel = () => {
  const [statusData, setStatusData] = useState({ globalEnabled: false, providers: [] });
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    try {
      const res = await getRateLimitStatus();
      setStatusData(res.data);
    } catch (error) {
      console.error('获取流控状态失败:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const globalStatus = statusData.providers.find(p => p.providerName === '__global__');
  const providerStatus = statusData.providers.filter(p => p.providerName !== '__global__');

  return (
    <div className="my-6">
      <Card title="下载流控状态">
        <Spin spinning={loading}>
          <div className="mb-4">
            这里显示了每个启用了速率限制的下载源的当前状态。计数器会在每个周期开始时自动重置。
          </div>
          {statusData.globalEnabled && (
            <Alert
              message="全局流控已开启"
              description="所有下载源共享同一个速率限制。下方未独立设置的源将遵循全局规则。"
              type="info"
              showIcon
              className="mb-4"
            />
          )}
          <div className="space-y-4">
            {globalStatus && <RateLimitItem item={globalStatus} isGlobal />}
            {providerStatus.map(item => (
              <RateLimitItem key={item.providerName} item={item} isDisabled={statusData.globalEnabled && item.limit === 0} />
            ))}
            {!statusData.providers.length && !loading && (
              <div className="text-center text-gray-500 dark:text-gray-400 py-4">
                没有正在进行的流控或未启用任何流控规则。
              </div>
            )}
          </div>
        </Spin>
      </Card>
    </div>
  );
};