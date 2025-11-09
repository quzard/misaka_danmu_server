import React, { useState, useEffect } from 'react';
import { Modal, Form, Input, Select, Switch, Button, message } from 'antd';
import { EyeOutlined, EyeInvisibleOutlined } from '@ant-design/icons';
import { createMediaServer, updateMediaServer, testMediaServerConnection, deleteMediaServer } from '../../../apis';

const { Option } = Select;

const ServerConfigPanel = ({ visible, server, onClose, onSaved }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    if (visible) {
      if (server) {
        // 编辑模式
        form.setFieldsValue({
          name: server.name,
          providerName: server.providerName,
          url: server.url,
          apiToken: server.apiToken,
          isEnabled: server.isEnabled,
        });
      } else {
        // 新增模式
        form.resetFields();
        form.setFieldsValue({
          isEnabled: true,
          providerName: 'emby',
        });
      }
    }
  }, [visible, server, form]);

  const handleTest = async () => {
    try {
      const values = await form.validateFields(['url', 'apiToken', 'providerName']);

      setTesting(true);

      // 统一使用临时保存然后测试的方式
      try {
        let tempServer;
        if (server && server.id) {
          // 编辑模式: 先临时更新服务器配置
          tempServer = await updateMediaServer(server.id, { ...values, isEnabled: false });
        } else {
          // 新增模式: 先临时保存服务器
          tempServer = await createMediaServer({ ...values, isEnabled: false });
        }

        const res = await testMediaServerConnection(tempServer.data.id);
        const result = res.data;
        if (result.success) {
          message.success('连接成功!');
        } else {
          message.error('连接失败: ' + (result.message || '未知错误'));
        }

        // 如果是新增模式，删除临时服务器
        if (!server || !server.id) {
          await deleteMediaServer(tempServer.data.id);
        }
      } catch (tempError) {
        message.error('测试失败: ' + (tempError.message || '未知错误'));
      }
    } catch (error) {
      if (error.errorFields) {
        message.warning('请先填写必填字段');
      } else {
        message.error('测试失败: ' + (error.message || '未知错误'));
      }
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      if (server) {
        // 更新
        await updateMediaServer(server.id, values);
        message.success('服务器配置已更新');
      } else {
        // 创建
        await createMediaServer(values);
        message.success('服务器已添加');
      }

      onSaved();
    } catch (error) {
      if (error.errorFields) {
        message.warning('请填写所有必填字段');
      } else {
        message.error('保存失败: ' + (error.message || '未知错误'));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title={server ? '编辑媒体服务器' : '添加媒体服务器'}
      open={visible}
      onCancel={onClose}
      width={600}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="test" onClick={handleTest} loading={testing}>
          测试连接
        </Button>,
        <Button key="submit" type="primary" onClick={handleSubmit} loading={loading}>
          保存
        </Button>,
      ]}
    >
      <Form
        form={form}
        layout="vertical"
      >
        <Form.Item
          label="服务器名称"
          name="name"
          rules={[{ required: true, message: '请输入服务器名称' }]}
        >
          <Input placeholder="例如: 我的Emby服务器" />
        </Form.Item>

        <Form.Item
          label="服务器类型"
          name="providerName"
          rules={[{ required: true, message: '请选择服务器类型' }]}
        >
          <Select placeholder="请选择">
            <Option value="emby">Emby</Option>
            <Option value="jellyfin">Jellyfin</Option>
            <Option value="plex">Plex</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="服务器地址"
          name="url"
          rules={[
            { required: true, message: '请输入服务器地址' },
            { type: 'url', message: '请输入有效的URL' }
          ]}
        >
          <Input placeholder="http://localhost:8096" />
        </Form.Item>

        <Form.Item
          label="API Token"
          name="apiToken"
          rules={[{ required: true, message: '请输入API Token' }]}
        >
          <Input
            placeholder="请输入API Token"
            type={showToken ? 'text' : 'password'}
            suffix={
              showToken ? (
                <EyeOutlined onClick={() => setShowToken(false)} style={{ cursor: 'pointer' }} />
              ) : (
                <EyeInvisibleOutlined onClick={() => setShowToken(true)} style={{ cursor: 'pointer' }} />
              )
            }
          />
        </Form.Item>

        <Form.Item
          label="启用状态"
          name="isEnabled"
          valuePropName="checked"
        >
          <Switch checkedChildren="启用" unCheckedChildren="禁用" />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default ServerConfigPanel;
