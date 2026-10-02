# /api/vehicle/doors/layout

## Status

- Latest Version: v1.2.0
- Method: function call
- Data Type: [autoware_adapi_v1_msgs/srv/GetDoorLayout](../../../../../types/autoware_adapi_v1_msgs/srv/GetDoorLayout/)

## Description

获取门布局.它是每个门的一系列角色和描述.

## Request

None

## Response

| Name | Type | Description |
| --- | --- | --- |
| status | autoware_adapi_v1_msgs/msg/ResponseStatus | 响应状态 |
| doors.roles | uint8[] | 门在车辆提供的服务中的角色. |
| doors.description | string | 要在界面中显示的门的描述. |
