# Category lane

## 分类：小巷

---

### vm-01-01 Lanelet 基础

#### 在 toc 中省略的要求细节

道路的车道必须符合以下要求.

- *subtype：road*
- 位置：市区, 用于公共道路
- 将 Lanelet 的方向与车辆移动的方向对齐.(您可以使用 [Vector Map Builder](https://docs.web.auto/en/user-manuals/vector-map-builder/screen-layout#project-tab) 将车道方向可视化为箭头)
- 根据 [vm-01-02](#vm-01-02-allowance-for-lane-changes) 设置是否允许变道.
- 分别设置 Lanelet 的 left_bound 和 right_bound 的 Linestring ID.请参阅 [vm-01-03](#vm-01-03-linestring-sharing) .
- 标签 ： *one_way=yes* .Autoware 目前不支持 no.
- 将 Lanelet 连接到另一个 Lanelet,除非它位于开头或结尾.
- 将点 (x, y, z) 放置在 Lanelet 中,使其与 PCD Map 对齐,确保横向和仰角的准确性.Point 的高度应基于椭球体高度 (WGS84).请参阅 [vm-07-04](../category_others/#vm-07-04-ellipsoidal-height) .

#### 首选向量映射 toc 中省略

（图片说明：兰莱特；未对图片像素执行 OCR）

---

### vm-01-02 允许变道

#### 在 toc 中省略的要求细节

在 Lanelet 的 Linestring 中添加一个标签,表示变道权限或禁止.

- 许可证 *lane_change=yes*
- 禁止 *lane_change=no*

根据线条类型设置 Linestring *subtype*.

-*固体* -*虚线*

##### 引用自日本的道路交通法  在 toc 中省略

- 白色虚线 ：表示允许变道和超车.
- 白色实线 ：表示允许变道和超车.
- 黄色实线 ：表示不允许变道.

（图片说明：行；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [变道设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_lane_change_module/)
- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)
- [外道设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/motion_velocity_planner/autoware_motion_velocity_out_of_lane_module/)

---

### vm-01-03 线串共享

#### 在 toc 中省略的要求细节

在创建物理上相邻的 Lanelet 时共享 Linestring.

##### autoware 的行为 toc

如果与车辆行驶的 Lanelet 相邻的 Lanelet 共享 Linestring,则可能会出现以下行为：

- 车辆驶出车道以避开障碍物.
- 车辆转弯时略微伸出车道.
- 变道

（图片说明：行；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：行；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：行；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [变道设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_lane_change_module/)
- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)
- [外道设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/motion_velocity_planner/autoware_motion_velocity_out_of_lane_module/)

---

### vm-01-04 为对面交通共享车道中心线

#### 在 toc 中省略的要求细节

当车辆的车道和对面的车道实际接触时,道路中心线的线串 ID 必须在这两个车道之间共享.为此,这两个 Lanelets 的长度必须匹配.

##### Autoware 的行为： 在 toc  中省略

可以越过对面车道避障.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-05 车道几何

#### 在 toc 中省略的要求细节

道路车道的几何形状需要符合以下要求：

- 左侧和右侧线串必须遵循道路的边界线.
- Lanelet 的线条与其前后的 lanelet 连接,必须形成直线.
- 确保轮廓光滑,没有锯齿状或凹凸不平,L 形曲柄除外.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-06 行位置 (1)

#### 在 toc 中省略的要求细节

确保道路的中心线 Linestring 位于道路标记的正中间.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-07 行位置 (2)

#### 在 toc 中省略的要求细节

当道路外存在线条时,将 Linestring 放置在标记的中心.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### vm-01-08 行位置 (3)

#### 在 toc 中省略的要求细节

如果道路外侧没有线条,请将线串放置在距离道路边缘 0.5 m 的位置.

（图片说明：svg；未对图片像素执行 OCR）

##### 注意

宽度取决于您所在国家/地区的法律.

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### vm-01-09 限速

#### 在 toc 中省略的要求细节

在以下情况下,为车辆行驶的车道 (*subtype：road*) 添加限速 (*tag：speed_limit*),以公里/小时为单位.

- 存在限速路标.
- 您可以添加速度限制,例如,在狭窄的道路上.

请注意,以下是通过 Autoware 的设置和行为实现的.

- 无人机的最大速度
- 在需要减速的地方进行速度调整,例如弯道和下坡区域.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### vm-01-10 中心线

#### 在 toc 中省略的要求细节

Autoware 旨在通过从 Lanelet 的左右 Linestrings 计算的中点移动.

当由于某些情况需要将驾驶位置向左或向右移动时,为 Lanelet 创建一条中心线,确保中心线具有平滑的形状,以便驾驶.

（图片说明：svg；未对图片像素执行 OCR）

##### 注意

`中心线` 是与中央车道分割线(中心线)不同的概念.

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-11 中心线连接 (1)

#### 在 toc 中省略的要求细节

当中心线被添加到多个 Lanelet 时,它们应该被连接起来.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-12 中心线连接 (2)

#### 在 toc 中省略的要求细节

如果添加了中心线的 Lanelet 连接到没有中心线的 Lanelet,请确保添加的中心线的起点和终点位于 Lanelet 的中心.确保中心线具有光滑的形状,以便驾驶.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-13 没有中心线的道路 (1)

#### 在 toc 中省略的要求细节

当道路没有中心线但足够宽,车辆和迎面而来的车辆可以相互通过时,Lanelets 应位于道路中央彼此相邻的位置.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### vm-01-14 没有中心线的道路 (2)

#### 在 toc 中省略的要求细节

如果满足以下所有条件,则应用 (Apply)：

- 道路是一条没有中心线的单车道,对于车辆和迎面而来的车辆来说太窄了.
- 这是一个除自动驾驶汽车以外的车辆无法进入这条道路的环境.
- 该计划涉及在这条道路上来回行驶的自动驾驶汽车.

创建 Vector Map 的要求：

- 将两个 Lanelet 堆叠在一起.

##### 补充信息

- 此案例的适用取决于当地的运营政策和车辆规格,应与地图请求者讨论确定.
- 当前的 Autoware 不具备在共享车道上通过迎面而来的车辆的能力.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

（图片说明：svg；未对图片像素执行 OCR）

---

### vm-01-15 路肩

#### 在 toc 中省略的要求细节

如果道路旁边有路肩,则为道路路肩放置车道 (*subtype：road_shoulder*).但是,没有必要在 intersections 中创建此 URL.

路肩的 Lanelet 和人行道的 Lanelet 共享 Linestring (*subtype：road_border*).

一个 road shoulder Lanelet 旁边不能有一个 road shoulder Lanelet.

road Lanelet 必须紧挨着路肩 Lanelet.

##### autoware 的行为 toc

- Autoware 可以从 Shoulder 开始,也可以到达 Shoulder.
- 到达时移动到边缘的边距由 Autoware 参数_margin_from_boundary_确定.创建 Vector Map 时无需考虑.
- 如果 Autoware 与以下任何一项重叠,则不会将车停在道路路肩车道上：
- 标记为 *no_parking_area* 的 Polygon
- 标记为 *no_stopping_area* 的 Polygon
- 交叉路口附近和交叉路口内的区域 -人行横道

*tag：lane_change=yes* 在标记肩部边界的 Linestring 上不是必需的.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

不要为没有路肩的道路创建 road shoulder Lanelet.

（图片说明：svg；未对图片像素执行 OCR）

#### 相关 Autoware 模块

- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)
- [Goal Planner 设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_goal_planner_module/)

---

### vm-01-16 路肩线串共享

#### 在 toc 中省略的要求细节

道路路肩和相邻道路的 Lanelets 应具有公共 Linestring.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)
- [Goal Planner 设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_goal_planner_module/)

---

### vm-01-17 侧条

#### 在 toc 中省略的要求细节

将 Lanelet (*subtype：pedestrian_lane*) 放在侧边条上.但是,没有必要在 intersections 中创建此 URL.

侧边条的 Lanelet 必须在外面有 Linestring (*subtype：road_border*).

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### vm-01-18 侧边条线串共享

#### 在 toc 中省略的要求细节

侧带的 Lanelet 和相邻的道路 Lanelet 应该有一个公共的 Linestring.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

---

### VM-01-19 人行道

#### 在 toc 中省略的要求细节

必要时放置一条人行道 Lanelet (*subtype：walkway*).但是,仅当有人行横道与车道相交时才安装.如果没有交叉路口,请不要安装.

车道的长度 (*subtype：walkway*) 应该是与您的车道相交的区域,以及前后 3 米的额外区域.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [交集 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_intersection_module/)
- [人行道设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_walkway_module/)
