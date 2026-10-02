# /api/perception/objects

## Status

- Latest Version: not released
- Method: realtime stream
- Data Type: [autoware_adapi_v1_msgs/msg/DynamicObjectArray](../../../../types/autoware_adapi_v1_msgs/msg/DynamicObjectArray/)

## Description

获取带有标签、形状、当前位置和预测路径的已识别对象数组 有关详细信息,请参阅 [感知](../../../../features/perception/).

## Message

| Name | Type | Description |
| --- | --- | --- |
| objects.id | unique_identifier_msgs/msg/UUID | 每个对象的 UUID |
| objects.existence_probability | float64 | 对象退出的概率 |
| objects.classification | autoware_adapi_v1_msgs/msg/ObjectClassification[] | 识别的对象类型和置信度 |
| objects.kinematics | autoware_adapi_v1_msgs/msg/DynamicObjectKinematics | 由对象姿势、扭曲、加速度和predicted_paths组成 |
| objects.shape | shape_msgs/msg/SolidPrimitive | 使用 dimension 和 polygon 指定对象的形状 |
