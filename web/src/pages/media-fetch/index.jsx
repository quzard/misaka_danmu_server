import React, { useState } from 'react';
import { Tabs } from 'antd';
import LibraryScan from './components/LibraryScan';

const { TabPane } = Tabs;

const MediaFetch = () => {
  const [activeTab, setActiveTab] = useState('library-scan');

  return (
    <div style={{ padding: '24px' }}>
      <h1 style={{ marginBottom: '24px' }}>媒体获取</h1>
      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="媒体库读取" key="library-scan">
          <LibraryScan />
        </TabPane>
      </Tabs>
    </div>
  );
};

export default MediaFetch;

