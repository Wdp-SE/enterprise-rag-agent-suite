# /api/vehicle/doors/layout

## 状态

- 最后版本: v1.2.0
- 方法: function call
- 数据类型: [autoware_adapi_v1_msgs/srv/GetDoorLayout](../../../../../types/autoware_adapi_v1_msgs/srv/GetDoorLayout/)

## 描述

获取门布局.它是每个门的一系列角色和描述.

## 请求

None

## 响应

| 名称 | 类型 | 描述 |
| --- | --- | --- |
| status | autoware_adapi_v1_msgs/msg/ResponseStatus | 响应状态 |
| doors.roles | uint8[] | 门在车辆提供的服务中的角色. |
| doors.description | string | 要在界面中显示的门的描述. |
