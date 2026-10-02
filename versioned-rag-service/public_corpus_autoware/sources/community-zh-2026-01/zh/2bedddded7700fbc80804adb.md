# Category intersection

## 分类：交集

---

### vm-03-01 交集标准

#### 在 toc 中省略的要求细节

建造十字路口的基本标准：

- 用多边形 ( *type：intersection_area* ) 圈出交叉点处的可驾驶区域.
- 为交叉口的所有 Lanelets 添加_turn_direction_.
- 确保交叉路口中的所有小通道都已标记：
- *key：intersection_area*
- *value：Polygon 的 ID*
- 将 *right_of_way* 附加到必要的 Lanelet.
- 此外,有必要适当设置交通信号灯、人行横道和停车线.

有关详细信息,请参阅此页面上的相应要求.

##### Autoware 模块 toc  中省略

- *turn_direction* 和 *right_of_way* 的要求与交叉路口模块有关,该模块在考虑交通信号灯指示的情况下规划速度以避免与其他车辆发生碰撞.
- _intersection_area_的要求与避让模块有关,该模块规划通过偏离十字路口车道来规避的路线.

#### 首选向量映射 toc 中省略

没有特别的.

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)
- [盲点设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_blind_spot_module/)
- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)

---

### vm-03-02 Lanelet 的转弯方向和虚拟线串

#### 在 toc 中省略的要求细节

在路口的 Lanelets 中添加以下标签：

- turn_direction ： 直线
- turn_direction ： 左
- turn_direction ： 右

此外,如果交叉点处 Lanelets 的左侧或右侧线串缺少道路绘制,请将它们指定为 *type：virtual*.

##### Autoware 的行为： toc  中省略

Autoware 将在 turn_direction 标记的 Lanelet 之前默认开始闪烁转向信号灯(闪光灯)30 米.如果您更改闪烁时间,请添加以下标签：

- 键： *turn_signal_distance*
- 值：数值 (m)

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)
- [盲点设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_blind_spot_module/)
- [behavior_velocity_planner virtual_traffic_light - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_virtual_traffic_light_module/)

---

### vm-03-03 路口车道宽度

#### 需求细节：  toc 中省略

交叉路口的 Lanelet 应具有一致的宽度.此外,绘制具有平滑曲线的 Linestrings.

此曲线的形状必须由 Vector Map 创建器确定.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-03-04 在路口创建 lanelet

#### 在 toc 中省略的要求细节

在交叉路口创建所有 Lanelet,包括非车辆驾驶的 Lanelet.此外,将停车线和交通信号灯适当地连接到 Lanelets.

另请参阅创建范围 [vm-07-01](../category_others/#vm-07-01-vector-map-creation-range)

##### autoware 的行为 toc

Autoware 使用小车道来预测其他车辆的运动并相应地规划车辆的速度.因此,有必要在交叉口创建所有 lanelet.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-05 路口车道划分

#### 在 toc 中省略的要求细节

将 Lanelets 在交叉路口创建为单个对象,而不分割它们.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-06 十字路口的引导线

#### 在 toc 中省略的要求细节

如果交叉口有引导线,则绘制跟随它们的 Lanelet.

在 Lanelets 分支的情况下,从引导线的末尾开始分支.但是,没有必要在 Lanelets 之间共享点或线串.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-07 十字路口的多个小车道

#### 在 toc 中省略的要求细节

当在一个交叉路口用 Lanelets 连接多个车道时,这些 Lanelet 应该彼此相邻,不要交叉.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-08 交集面积范围

#### 在 toc 中省略的要求细节

用多边形 (*type：intersection_area*) 圈出交叉路口的可行驶区域.此交集的 Polygon 的边界应由下面的对象定义.

- 线串 ( *subtype：road_border* )
- 交叉口小通道连接点处的直线.

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)
- [盲点设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_blind_spot_module/)
- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)

---

### vm-03-09 路口小巷的范围

#### 在 toc 中省略的要求细节

根据停止线的位置确定交叉口(以下简称 lanelet 连接的边界)中 lanelet 的起点和终点位置.

- 对于带有涂漆停止线的情况：
- 停止线的 linestring ( *type：stop_line* ) 位置必须与 lanelet 的 start 对齐.
- 将车道的末端延伸到对面车道的停止线所在位置.
- 没有涂漆的停止线：
- 使用绘制的线串 ( *type：stop_line* ) 建立位置,就像有绘制的停止线一样.

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-10 通行权(带信号)

#### 在 toc 中省略的要求细节

为满足以下所有条件的 Lanelets 设置监管元素 `right_of_way` ：

- *turn_direction_为 _right* 或 *left* 的交叉路口中的车道.
- 与车辆的 lanelet 相交的 lanelet.
- 十字路口有红绿灯.

将交叉路口中与车辆车道相交的那些小道设置为 *yield*,并将那些与车辆不共享相同信号变化时序的车道设置为 *yield*.此外,如果车辆左转,请将对面车辆的右转车道设置为 *yield*.无需为车辆直行的车道设置 *yield* (*turn_direction：straight*).

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

##### 车辆左转省略 toc

（图片说明：svg；未对图片像素执行 OCR）

##### 车辆右转省略 toc

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-11 通行权(无信号)

#### 在 toc 中省略的要求细节

为满足以下所有条件的 Lanelets 设置监管元素 `right_of_way` ：

- *turn_direction_为 _right* 或 *left* 的交叉路口中的车道.
- 与车辆的 lanelet 相交的 lanelet.
- 十字路口有 **没有** 红绿灯.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

##### (1) 优先车道上的车辆 toc

（图片说明：svg；未对图片像素执行 OCR）

##### (2) 非优先车道上的车辆 toc

监管元素不是必需的.但是,当车辆直行时,它比从对面非优先道路右转的其他车辆具有相对优先权.因此,在这种情况下,需要设置 *right_of_way* 和 *yield*.

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-12 通行权补充

#### 在 toc 中省略的要求细节

##### 为什么需要在 toc 中配置 `right_of_way` 省略

如果没有 `right_of_way` 设置,Autoware 会将与其路径相交的其他车道解释为具有优先权.因此,只要过马路车道上还有其他车辆,无论信号指示如何,Autoware 都无法进入十字路口.

问题示例：即使我们的信号允许继续行驶,如果其他车辆正在对向车道与右转车道相交的红灯处等待,我们的车辆也会提前等待.

#### 首选向量映射 toc 中省略

没有特别的.

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-13 从私人区域、人行道合并

#### 在 toc 中省略的要求细节

为 private property 中的 Lanelets 设置 *location=private*.

当进入或离开私有财产的道路与人行道相交时,为该人行道创建一个 Lanelet (*subtype：walkway*).

##### Autoware 的行为： toc  中省略

- 车辆在进入人行道之前暂时停止.
- 车辆在并入公共道路之前停下来.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-14 路标

#### 在 toc 中省略的要求细节

如果交叉口的引导线前方有停止线,请确保满足以下条件：

- 为参考线创建一个 Lanelet.
- 指南的 Lanelet 引用了监管元素 ( *subtype：road_marking* ).
- Regulatory Element 是指 *stop_line* 的 Linestring.

请参阅 [Web.Auto 文档 - 监管元素的创建](https://docs.web.auto/en/user-manuals/vector-map-builder/how-to-use/edit-maps#creation-of-regulatory-element) 以了解 Vector Map Builder 中的创建方法.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)

---

### vm-03-15 专用自行车道

#### 在 toc 中省略的要求细节

如果存在专用自行车道,请创建一个 Lanelet (*subtype：road*).与道路相邻的路段应共享一个 Linestring.对于交叉路口的自行车道,在与车辆左转车道相交的车道 _right_of_way*下方分配一个 yield*lane 名称.(有关right_of_way,请参阅 [vm-03-10](./#vm-03-10-right-of-way-with-signal) 和 [vm-03-11](./#vm-03-11-right-of-way-without-signal).

此外,将 *lane_change = no* 设置为 OptionalTags.

##### Autoware 的行为： toc  中省略

盲点(纠缠检查)功能验证车道(subtype：road)并决定车辆是否可以继续行驶.

（图片说明：png；未对图片像素执行 OCR）

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [盲点设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_blind_spot_module/)
