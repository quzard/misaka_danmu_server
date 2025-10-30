import React, { useState } from 'react';
import { Tabs } from 'antd';
import LibraryScan from './components/LibraryScan';

const MediaFetch = () => {
  const [activeTab, setActiveTab] = useState('library-scan');

  const items = [
    {
      key: 'library-scan',
      label: '媒体库读取',
      children: <LibraryScan />,
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <h1 style={{ marginBottom: '24px' }}>媒体获取</h1>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={items} />
    </div>
  );
};

export default MediaFetch;

