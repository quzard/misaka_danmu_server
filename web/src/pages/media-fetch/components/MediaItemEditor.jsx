import React, { useEffect } from 'react';
import { Modal, Form, Input, InputNumber, Select, message } from 'antd';
import { updateMediaItem } from '../../../apis';

const { Option } = Select;

const MediaItemEditor = ({ visible, item, onClose, onSaved }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = React.useState(false);

  useEffect(() => {
    if (visible && item) {
      form.setFieldsValue({
        title: item.title,
        mediaType: item.mediaType,
        season: item.season,
        episode: item.episode,
        year: item.year,
        tmdbId: item.tmdbId,
        tvdbId: item.tvdbId,
        imdbId: item.imdbId,
        posterUrl: item.posterUrl,
      });
    }
  }, [visible, item, form]);

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      await updateMediaItem(item.id, values);
      message.success('更新成功');
      onSaved();
    } catch (error) {
      if (error.errorFields) {
        message.warning('请填写所有必填字段');
      } else {
        message.error('更新失败: ' + (error.message || '未知错误'));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="编辑媒体项"
      open={visible}
      onCancel={onClose}
      onOk={handleSubmit}
      confirmLoading={loading}
      width={600}
    >
      <Form
        form={form}
        layout="vertical"
      >
        <Form.Item
          label="标题"
          name="title"
          rules={[{ required: true, message: '请输入标题' }]}
        >
          <Input />
        </Form.Item>

        <Form.Item
          label="类型"
          name="mediaType"
          rules={[{ required: true, message: '请选择类型' }]}
        >
          <Select>
            <Option value="movie">电影</Option>
            <Option value="tv_series">电视剧</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="季度"
          name="season"
        >
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="集数"
          name="episode"
        >
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="年份"
          name="year"
        >
          <InputNumber min={1900} max={2100} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="TMDB ID"
          name="tmdbId"
        >
          <Input placeholder="例如: 12345" />
        </Form.Item>

        <Form.Item
          label="TVDB ID"
          name="tvdbId"
        >
          <Input placeholder="例如: 67890" />
        </Form.Item>

        <Form.Item
          label="IMDB ID"
          name="imdbId"
        >
          <Input placeholder="例如: tt1234567" />
        </Form.Item>

        <Form.Item
          label="海报URL"
          name="posterUrl"
        >
          <Input placeholder="https://..." />
        </Form.Item>
      </Form>
    </Modal>
  );
};

export default MediaItemEditor;

