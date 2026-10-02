# /api/local/command/turn_indicators

## Status

- Latest Version: not released
- Method: notification
- Data Type: [autoware_adapi_v1_msgs/msg/TurnIndicatorsCommand](../../../../../types/autoware_adapi_v1_msgs/msg/TurnIndicatorsCommand/)

## Description

发送在本地作模式下使用的转向指示灯命令. 如需使用此 API,请按照 [手动控制](../../../../../features/manual-control/).

## Message

| Name | Type | Description |
| --- | --- | --- |
| stamp | builtin_interfaces/msg/Time | 发送此消息时的时间戳. |
| command | autoware_adapi_v1_msgs/msg/TurnIndicators | 目标转向指示灯状态. |
