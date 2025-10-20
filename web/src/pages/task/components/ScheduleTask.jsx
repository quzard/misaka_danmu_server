import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
} from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import {
  deleteScheduledTask,
  editScheduledTask,
  addScheduledTask,
  runTask,
  getAvailableScheduledJobs,
  getScheduledTaskList,
} from '../../../apis'
import { MyIcon } from '@/components/MyIcon.jsx'
import dayjs from 'dayjs'
import { useModal } from '../../../ModalContext'
import { useMessage } from '../../../MessageContext'
import { Cron } from 'react-js-cron'
import 'react-js-cron/dist/styles.css'
import cronstrue from 'cronstrue/i18n'

export const ScheduleTask = () => {
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [tasks, setTasks] = useState([])
  const [availableJobTypes, setAvailableJobTypes] = useState([])
  const [advancedMode, setAdvancedMode] = useState(false)

  const [form] = Form.useForm()
  const editid = Form.useWatch('taskId', form)
  const modalApi = useModal()
  const messageApi = useMessage()

  // 获取Cron表达式的人类可读描述
  const getCronDescription = (cronExpression) => {
    try {
      return cronstrue.toString(cronExpression, { locale: 'zh_CN' })
    } catch (error) {
      return '无效的Cron表达式'
    }
  }

  // 验证Cron表达式是否合法
  const validateCron = (cronExpression) => {
    if (!cronExpression) return false
    try {
      cronstrue.toString(cronExpression, { locale: 'zh_CN' })
      return true
    } catch (error) {
      return false
    }
  }

  const fetchData = async () => {
    try {
      setLoading(true)
      const [tasksRes, jobsRes] = await Promise.all([
        getScheduledTaskList(),
        getAvailableScheduledJobs(),
      ])
      setTasks(tasksRes.data || [])
      setAvailableJobTypes(jobsRes.data || [])
    } catch (error) {
      messageApi.error('获取定时任务信息失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 150,
    },
    {
      title: '类型',
      dataIndex: 'jobType',
      key: 'jobType',
      width: 200,
      render: (_, record) => {
        const jobType = availableJobTypes.find(
          job => job.jobType === record.jobType
        )
        return (
          <div className="flex items-center gap-2">
            <span>{jobType?.name || record.jobType}</span>
            {record.isSystemTask && (
              <Tag color="blue" size="small">系统任务</Tag>
            )}
          </div>
        )
      },
    },
    {
      title: 'Cron表达式',
      width: 150,
      dataIndex: 'cronExpression',
      key: 'cronExpression',
    },
    {
      title: '状态',
      dataIndex: 'isEnabled',
      key: 'isEnabled',
      width: 100,
      render: (_, record) => {
        return (
          <div>
            {record.isEnabled ? (
              <Tag color="green">启用</Tag>
            ) : (
              <Tag color="red">禁用</Tag>
            )}
          </div>
        )
      },
    },
    {
      title: '上次运行时间',
      dataIndex: 'lastRunAt',
      key: 'lastRunAt',
      width: 200,
      render: (_, record) => {
        return (
          <div>{dayjs(record.lastRunAt).format('YYYY-MM-DD HH:mm:ss')}</div>
        )
      },
    },
    {
      title: '下次运行时间',
      dataIndex: 'nextRunAt',
      key: 'nextRunAt',
      width: 200,
      render: (_, record) => {
        return (
          <div>{dayjs(record.nextRunAt).format('YYYY-MM-DD HH:mm:ss')}</div>
        )
      },
    },
    {
      title: '操作',
      width: 100,
      fixed: 'right',
      render: (_, record) => {
        const isSystemTask = record.isSystemTask || false

        // 系统任务不显示操作按钮
        if (isSystemTask) {
          return null
        }

        return (
          <Space>
            <span
              className="cursor-pointer hover:text-primary"
              onClick={() => handleRun(record)}
              title="立即运行"
            >
              <MyIcon icon="canshuzhihang" size={20}></MyIcon>
            </span>
            <span
              className="cursor-pointer hover:text-primary"
              onClick={() => {
                form.setFieldsValue({
                  ...record,
                })
                setAddOpen(true)
              }}
              title="编辑任务"
            >
              <MyIcon icon="edit" size={20}></MyIcon>
            </span>
            <span
              className="cursor-pointer hover:text-primary"
              onClick={() => handleDelete(record)}
              title="删除任务"
            >
              <MyIcon icon="delete" size={20}></MyIcon>
            </span>
          </Space>
        )
      },
    },
  ]

  const handleRun = async record => {
    try {
      await runTask({ id: record.taskId })
      messageApi.success('任务已触发运行，请稍后刷新查看运行时间。')
    } catch (error) {
      messageApi.error('任务触发失败，请稍后重试。')
    }
  }

  const handleAdd = async () => {
    const values = await form.validateFields()
    if (!!values.taskId) {
      try {
        setConfirmLoading(true)
        await editScheduledTask({ ...values, id: values.taskId })
        messageApi.success('任务编辑成功。')
        form.resetFields()
        fetchData()
        setAddOpen(false)
        setAdvancedMode(false)
      } catch (error) {
        messageApi.error(error?.detail ?? '任务编辑失败，请稍后重试。')
      } finally {
        setConfirmLoading(false)
      }
    } else {
      try {
        await addScheduledTask(values)
        messageApi.success('任务添加成功。')
        form.resetFields()
        fetchData()
        setAddOpen(false)
        setAdvancedMode(false)
      } catch (error) {
        messageApi.error(error?.detail ?? '任务添加失败，请稍后重试。')
      } finally {
        setConfirmLoading(false)
      }
    }
  }

  const handleDelete = async record => {
    modalApi.confirm({
      title: '删除任务',
      zIndex: 1002,
      content: <div>确定要删除这个定时任务吗？</div>,
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteScheduledTask({ id: record.taskId })
          messageApi.success('任务删除成功。')
          fetchData()
        } catch (error) {
          messageApi.error(error?.detail ?? '任务删除失败，请稍后重试。')
        }
      },
    })
  }

  return (
    <div className="my-6">
      <Card
        loading={loading}
        title="定时任务"
        extra={
          <Button
            type="primary"
            onClick={() => {
              setAddOpen(true)
            }}
          >
            添加定时任务
          </Button>
        }
      >
        <div className="mb-4">
          定时任务用于自动执行维护操作，例如自动更新和映射TMDB数据。使用标准的Cron表达式格式。
        </div>
        <Table
          pagination={false}
          size="small"
          dataSource={tasks}
          columns={columns}
          rowKey={'taskId'}
          scroll={{ x: '100%' }}
        />
      </Card>
      <Modal
        title={!!editid ? '编辑定时任务' : '添加定时任务'}
        open={addOpen}
        onOk={handleAdd}
        confirmLoading={confirmLoading}
        cancelText="取消"
        okText="确认"
        onCancel={() => {
          setAddOpen(false)
          setAdvancedMode(false)
        }}
        afterClose={() => {
          form.resetFields()
          setAdvancedMode(false)
        }}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            jobType: 'tmdbAutoMap',
            isEnabled: true,
            cronExpression: '0 2 * * *',
          }}
        >
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, message: '请输入任务名称' }]}
            className="mb-4"
          >
            <Input placeholder="例如：我的每日TMDB更新" />
          </Form.Item>
          <Form.Item
            name="jobType"
            label="任务类型"
            rules={[{ required: true, message: '请选择任务类型' }]}
            className="mb-4"
          >
            <Select>
              {availableJobTypes
                .filter(job => !job.isSystemTask) // 过滤掉系统任务
                .map(job => (
                  <Select.Option key={job.jobType} value={job.jobType}>
                    <Tooltip title={job.description} placement="right">
                      <span>{job.name}</span>
                    </Tooltip>
                  </Select.Option>
                ))}
            </Select>
          </Form.Item>
          <Form.Item
            name="cronExpression"
            label={
              <div className="flex items-center justify-between w-full">
                <span>Cron表达式</span>
                <Button
                  type="link"
                  size="small"
                  onClick={() => setAdvancedMode(!advancedMode)}
                  className="p-0"
                >
                  {advancedMode ? '可视化模式' : '高级模式'}
                </Button>
              </div>
            }
            rules={[{ required: true, message: '请输入Cron表达式' }]}
            className="mb-4"
          >
            {advancedMode ? (
              <Input
                placeholder="例如：0 2 * * *（每天凌晨2点）"
                suffix={
                  form.getFieldValue('cronExpression') ? (
                    validateCron(form.getFieldValue('cronExpression')) ? (
                      <CheckCircleOutlined
                        style={{ color: '#52c41a', fontSize: 16 }}
                      />
                    ) : (
                      <CloseCircleOutlined
                        style={{ color: '#ff4d4f', fontSize: 16 }}
                      />
                    )
                  ) : null
                }
              />
            ) : (
              <Cron
                value={form.getFieldValue('cronExpression') || '0 2 * * *'}
                setValue={(newValue) => {
                  form.setFieldsValue({ cronExpression: newValue })
                }}
                clearButton={false}
                locale={{
                  everyText: '每',
                  emptyMonths: '每月',
                  emptyMonthDays: '每天',
                  emptyMonthDaysShort: '天',
                  emptyWeekDays: '每周',
                  emptyWeekDaysShort: '周',
                  emptyHours: '每小时',
                  emptyMinutes: '每分钟',
                  emptyMinutesForHourPeriod: '每分钟',
                  yearOption: '年',
                  monthOption: '月',
                  weekOption: '周',
                  dayOption: '天',
                  hourOption: '小时',
                  minuteOption: '分钟',
                  rebootOption: '重启时',
                  prefixPeriod: '每',
                  prefixMonths: '在',
                  prefixMonthDays: '在',
                  prefixWeekDays: '在',
                  prefixWeekDaysForMonthAndYearPeriod: '和',
                  prefixHours: '在',
                  prefixMinutes: '在',
                  prefixMinutesForHourPeriod: '在',
                  suffixMinutesForHourPeriod: '分',
                  errorInvalidCron: '无效的Cron表达式',
                  weekDays: [
                    '星期日',
                    '星期一',
                    '星期二',
                    '星期三',
                    '星期四',
                    '星期五',
                    '星期六',
                  ],
                  months: [
                    '一月',
                    '二月',
                    '三月',
                    '四月',
                    '五月',
                    '六月',
                    '七月',
                    '八月',
                    '九月',
                    '十月',
                    '十一月',
                    '十二月',
                  ],
                  altWeekDays: [
                    '周日',
                    '周一',
                    '周二',
                    '周三',
                    '周四',
                    '周五',
                    '周六',
                  ],
                  altMonths: [
                    '1月',
                    '2月',
                    '3月',
                    '4月',
                    '5月',
                    '6月',
                    '7月',
                    '8月',
                    '9月',
                    '10月',
                    '11月',
                    '12月',
                  ],
                }}
              />
            )}
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {() => {
              const currentCron = form.getFieldValue('cronExpression')
              if (currentCron && !advancedMode) {
                return (
                  <div className="mb-4 p-3 bg-blue-50 rounded border border-blue-200">
                    <div className="text-sm text-gray-600">
                      <span className="font-medium">执行时间：</span>
                      {getCronDescription(currentCron)}
                    </div>
                  </div>
                )
              }
              return null
            }}
          </Form.Item>
          <Form.Item
            name="isEnabled"
            label="是否启用"
            valuePropName="checked"
            className="mb-4"
          >
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
          <Form.Item name="taskId" label="taskId" hidden>
            <Input disabled />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
