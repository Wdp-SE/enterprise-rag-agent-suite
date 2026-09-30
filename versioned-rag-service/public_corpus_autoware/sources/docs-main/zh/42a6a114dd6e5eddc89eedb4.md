# /api/local/command/turn_indicators

## 状态

- 最后版本: not released
- 方法: notification
- 数据类型: [autoware_adapi_v1_msgs/msg/TurnIndicatorsCommand](../../../../../types/autoware_adapi_v1_msgs/msg/TurnIndicatorsCommand/)

## 描述

发送在本地作模式下使用的转向指示灯命令. 如需使用此 API,请按照 [手动控制](../../../../../features/manual-control/).

## 消息

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| stamp | builtin_interfaces/msg/Time | 发送此消息时的时间戳. |
| command | autoware_adapi_v1_msgs/msg/TurnIndicators | 目标转向指示灯状态. |
