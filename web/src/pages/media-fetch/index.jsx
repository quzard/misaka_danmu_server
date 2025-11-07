import { useState } from 'react';
import { Tabs } from 'antd';
import LibraryScan from './components/LibraryScan';
import LocalScan from './components/LocalScan';
import { MobileTabs } from '@/components/MobileTabs';
import { useAtomValue } from 'jotai';
import { isMobileAtom } from '../../../store/index.js';

const MediaFetch = () => {
  const [activeTab, setActiveTab] = useState('library-scan');
  const isMobile = useAtomValue(isMobileAtom);

  const items = [
    {
      key: 'library-scan',
      label: '媒体库读取',
      children: <LibraryScan />,
    },
    {
      key: 'local-scan',
      label: '本地扫描',
      children: <LocalScan />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <div className="my-6">
        <h1 className="text-2xl font-bold mb-6">媒体获取</h1>
        {isMobile ? (
          <MobileTabs
            items={items}
            defaultActiveKey={activeTab}
            onChange={setActiveTab}
          />
        ) : (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            items={items}
          />
        )}
      </div>
    </div>
  );
};

export default MediaFetch;