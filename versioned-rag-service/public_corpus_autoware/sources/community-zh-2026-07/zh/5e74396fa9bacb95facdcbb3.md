# 规划

本页提供了有关 Planning 组件接口的具体规范.请参考 [规划架构设计文档](../../../autoware-architecture/planning/) 获取高级概念和数据流.

**TODO： 详细定义(每个主题中包含的元素的含义)尚未描述,需要更新.

## 输入

（图片说明：规划输入；未对图片像素执行 OCR）

### 来自地图组件

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| Vector Map | /map/vector_map | autoware_map_msgs/msg/LaneletMapBin | 规划进行环境的地图. |

### 从 Localization 组件

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| 车辆运动学状态 | /localization/kinematic_state | nav_msgs/msg/Odometry | 自我的当前位置、方向和速度. |
| 车辆加速度 | /localization/acceleration | geometry_msgs/msg/AccelWithCovarianceStamped | 自我的当前加速. |

**TODO**：加速度信息应合并到运动学状态中.

### 从 感知组件(Perception component)

| 名字 | 主题 | 类型 | Description |
| --- | --- | --- | --- |
| 对象 | /perception/object_recognition/objects | autoware_perception_msgs/msg/PredictedObjects | 在规划轨迹时需要避免或遵循的围绕自我的感知对象集.它包含语义信息,例如对象类(例如车辆、行人等)或对象的形状. |
| 障碍 | /perception/obstacle_segmentation/pointcloud | sensor_msgs/msg/PointCloud2 | 在规划轨迹时需要避免或遵循的围绕自我的一组感知障碍.这仅包含障碍物的原始信息.没有形状或速度信息. |
| 占用网格图 | /perception/occupancy_grid_map/map | nav_msgs/msg/OccupancyGrid | 包含障碍物的存在和盲点信息(表示为 UNKNOWN). |
| 交通信号 | /perception/traffic_light_recognition/traffic_signals | autoware_perception_msgs::msg::TrafficLightGroupArray | 包含交通信号信息,例如颜色(绿色、黄色、读取)和箭头(右、左、直). |

**TODO**： `障碍物` 信息的类型不应取决于特定的传感器消息类型(现在是 `PointCloud` ).它需要被修复.

### 从 API

| 名字 | 主题 | 类型 | Description |
| --- | --- | --- | --- |
| 最大速度 | /planning/scenario_planning/max_velocity_default | autoware_adapi_v1_msgs/srv/SetRoutePoints | 指示车速计划的最大值 |
| 作模式 | /system/operation_mode/state | autoware_adapi_v1_msgs/msg/OperationModeState | 指示当前运行模式(自动/手动等). |
| 路径集 | /planning/mission_planning/set_route | autoware_adapi_v1_msgs/srv/SetRoute | 表示在车辆停止时设置路线. |
| 路径点设置 | /planning/mission_planning/set_route_points | autoware_adapi_v1_msgs/srv/SetRoutePoints | 表示在车辆停止时设置带点的路线. |
| 路线变更 | /planning/mission_planning/change_route | autoware_adapi_v1_msgs/srv/SetRoute | 表示在车辆移动时改变路线. |
| 路线点更改 | /planning/mission_planning/change_route_points | autoware_adapi_v1_msgs/srv/SetRoutePoints | 表示在车辆移动时用点更改路线. |
| 路线清除 | /planning/mission_planning/clear_route | autoware_adapi_v1_msgs/srv/ClearRoute | 指示清除路由信息. |
| MRM 路由设置点 | /planning/mission_planning/mission_planner/srv/set_mrm_route | autoware_adapi_v1_msgs/srv/SetRoutePoints | 指示设置紧急路线. |
| MRM 路由清除 | /planning/mission_planning/mission_planner/srv/clear_mrm_route | autoware_adapi_v1_msgs/srv/SetRoutePoints | 表示清除紧急路线. |

## 输出

（图片说明：计划输出；未对图片像素执行 OCR）

### 控制

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| 弹道 | /planning/trajectory | autoware_planning_msgs/msg/Trajectory | 控制器要遵循的空间、速度和加速度点序列. |
| 转向指示灯 | /planning/turn_indicators_cmd | autoware_vehicle_msgs/msg/TurnIndicatorsCommand | 车辆应跟随的转向指示灯信号. |
| 危险信号灯 | /planning/hazard_lights_cmd | autoware_vehicle_msgs/msg/HazardLightsCommand | 车辆应跟随危险信号灯. |

### To System

| 名字 | 主题 | 类型 | Description |
| --- | --- | --- | --- |
| 诊断 | /planning/hazard_lights_cmd | diagnostic_msgs/msg/DiagnosticArray | 向 System 组件报告的 Planning 组件的诊断状态. |

### To API

| 名字 | 主题 | 类型 | Description |
| --- | --- | --- | --- |
| 路径候选者 | /planning/path_candidate/* | autoware_planning_msgs/msg/Path | Autoware 即将走的路.用户可以根据路径候选信息中断作. |
| 转向系数 | /planning/steering_factor/* | autoware_adapi_v1_msgs/msg/SteeringFactorArray | 有关 Autoware 执行的转向作的信息(例如,向右转向右转等) |
| 速度因子 | /planning/velocity_factors/* | autoware_adapi_v1_msgs/msg/VelocityFactorArray | 有关 Autoware 执行的速度机动的信息(例如,因障碍物而停止等) |

## 规划内部接口

本节介绍了 [规划架构设计](../../../autoware-architecture/planning/#high-level-architecture)的

（图片说明：规划内部；未对图片像素执行 OCR）

### 从任务规划到情景规划

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| 路线 | /planning/mission_planning/route | autoware_planning_msgs/msg/LaneletRoute | Lanelet 地图上从起点到目的地的车道 ID 序列. |

### 从行为规划到运动规划

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| 路径 | /planning/scenario_planning/lane_driving/behavior_planning/path | autoware_planning_msgs/msg/Path | 用于驾驶的车辆大致位置序列,以及有关最高速度和可驾驶区域的信息.收到此消息的模块应在可行驶区域和最大速度的约束范围内更改路径,从而生成所需的最终轨迹. |

### From Scenario Planning to Validation

| 名字 | 主题 | 类型 | 描述 |
| --- | --- | --- | --- |
| 弹道 | /planning/scenario_planning/trajectory | autoware_planning_msgs/msg/Trajectory | 驾驶所需的一系列精确的车辆位置、速度和加速度.预计车辆将遵循这一轨迹. |
