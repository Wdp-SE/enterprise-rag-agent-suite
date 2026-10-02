# 车辆接口

本页介绍了 Vehicle Interface 组件.请参考 [车辆接口设计文档](../../../autoware-architecture/vehicle/) 获取高级概念和数据流.

（图片说明：车辆接口图；未对图片像素执行 OCR）

`Vehicle Interface Component` 接收 `Vehicle commands` 并发布 `Vehicle status` . 它通过车辆特定协议与车辆通信.

可选的 `车辆命令适配器` 将通用控制命令(目标转向、转向率、速度、加速度)转换为特定于车辆的控制值(转向扭矩、车轮扭矩、电压、压力、加速踏板位置等).

## 与车辆通信

与车辆通信的接口因品牌和型号而异. 例如,特定于车辆的消息协议,如带有 ROS 2 接口的 CAN(控制器局域网)(例如 [pacmod](https://github.com/astuff/pacmod3)). 此外,通常需要特定于 Autoware 的接口(例如,[pacmod_interface](https://github.com/tier4/pacmod_interface/tree/main/pacmod_interface)).

## 车载适配器

Autoware 的基本控制命令以速度、加速度、转向角和转向率来表示车辆的目标运动. 这可能并不适合所有车辆,因此我们区分了两种类型的车辆.

- 类型 1：由速度、加速度、转向角和转向率子集直接控制的车辆.
- 类型 2：使用自定义命令(电机扭矩、电压、踏板压力等)的车辆.

对于 2 类车辆, 将 Autoware 控制命令转换为车辆特定命令需要车辆适配器. 有关示例,请参见 [raw_vehicle_cmd_converter](https://autowarefoundation.github.io/autoware_universe/main/vehicle/raw_vehicle_cmd_converter/) 它将目标速度和转向角转换为加速、转向和制动机械输入.

## 来自 Autoware 的输入

| 名字 | 主题 | 类型 | Description |
| --- | --- | --- | --- |
| 控制命令 | /control/command/control_cmd | autoware_control_msgs/msg/Control | Target controls of the vehicle (steering angle, velocity, ...) |
| 控制模式命令 | /control/control_mode_request | autoware_vehicle_msgs/srv/ControlModeCommand | Request to switch between manual and autonomous driving |
| 档位命令 | /control/command/gear_cmd | autoware_vehicle_msgs/msg/GearCommand | Target gear of the vehicle |
| 危险信号灯命令 | /control/command/hazard_lights_cmd | autoware_vehicle_msgs/msg/HazardLightsCommand | Target values of the hazard lights |
| 转向指示器命令 | /control/command/turn_indicators_cmd | autoware_vehicle_msgs/msg/TurnIndicatorsCommand | Target values of the turn signals |

## 输出到 Autoware

| 名字 | 主题 | 类型 | Optional ? | Description |
| --- | --- | --- | --- | --- |
| 驱动状态 | /vehicle/status/actuation_status | tier4_vehicle_msgs/msg/ActuationStatusStamped | Yes (vehicle with mechanical inputs) | Current acceleration, brake, and steer values reported by the vehicle |
| 控制模式 | /vehicle/status/control_mode | autoware_vehicle_msgs/msg/ControlModeReport |  | Current control mode (manual, autonomous, ...) |
| 按状态 | /vehicle/status/door_status | tier4_api_msgs/msg/DoorStatus | Yes | Current door status |
| 齿轮报告 | /vehicle/status/gear_status | autoware_vehicle_msgs/msg/GearReport |  | Current gear of the vehicle |
| 危险信号灯状态 | /vehicle/status/hazard_lights_status | autoware_vehicle_msgs/msg/HazardLightsReport |  | Current hazard lights status |
| 转向状态 | /vehicle/status/steering_status | autoware_vehicle_msgs/msg/SteeringReport |  | Current steering angle of the steering tire |
| 转向指示灯状态 | /vehicle/status/turn_indicators_status | autoware_vehicle_msgs/msg/TurnIndicatorsReport |  | Current state of the left and right turn indicators |
| 速度状态 | /vehicle/status/velocity_status | autoware_vehicle_msgs/msg/VelocityReport |  | Current velocities of the vehicle (longitudinal, lateral, heading rate) |
