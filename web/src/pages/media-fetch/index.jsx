import { useState } from 'react';
import { Tabs } from 'antd';
import LibraryScan from './components/LibraryScan';
import LocalScan from './components/LocalScan';

const MediaFetch = () => {
  const [activeTab, setActiveTab] = useState('library-scan');

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
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} />
    </div>
  );
};

export default MediaFetch;

