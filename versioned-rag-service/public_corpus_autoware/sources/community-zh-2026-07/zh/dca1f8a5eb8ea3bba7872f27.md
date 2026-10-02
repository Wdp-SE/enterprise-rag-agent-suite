# Category area

## 分类：区域

---

### vm-06-01 缓冲区

#### 在 toc 中 省略的要求细节

在路面上绘制缓冲区(也称为斑马线区域)时,创建多边形 (*type：hatched_road_markings*).

- 如果 Buffer Zone 位于 Lanelet 旁边,则在它们之间共享 Points.
- 如果缓冲区位于交叉点,则将缓冲区的多边形与交叉点的多边形 (intersection_area) 重叠.

##### Autoware 的行为： toc  中省略

为了避开障碍物,Autoware 将缓冲区视为可驾驶区域并继续穿过它.

##### 注意

- 车辆不得通过安全区.区分缓冲区和安全区很重要.- 不要在存在静态对象(如电线杆)且车辆无法通过的区域为缓冲区创建多边形,即使表面上绘制了缓冲区也是如此.缓冲区应仅在车辆通行可行的区域建立.

（图片说明：svg；未对图片像素执行 OCR）

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [静电避免 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_static_obstacle_avoidance_module/)
- [动态避障 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_dynamic_obstacle_avoidance_module/)

---

### vm-06-02 禁止停车标志

#### 在 toc 中省略的要求细节

创建 Vector Map 时,您可以禁止在特定区域停车,同时允许临时停车.

创建从 Lanelet (*subtype：road*) 到 Regulatory Element (*subtype：no_parking_area*) 的引用,并让该 Regulatory Element 引用多边形 (*type：no_parking_area*).

请参阅 [Web.Auto 文档 - 创建无停车区](https://docs.web.auto/en/user-manuals/vector-map-builder/how-to-use/edit-maps#creation-of-no-parking-area) 以了解 Vector Map Builder 中的创建方法.

##### Autoware 的行为： toc  中省略

由于 *no_parking_area* 不允许设定目标,因此 Autoware 无法将车辆停在那里.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [Goal Planner 设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_goal_planner_module/)

---

### vm-06-03 禁止停车标志

#### 在 toc 中省略的要求细节

创建 Vector Map 时,您可以禁止在特定区域停车,但允许临时停车.

创建从 Lanelet (*subtype：road*) 到 Regulatory Element (*subtype：no_parking_area*) 的引用,并让该 Regulatory Element 引用多边形 (*type：no_parking_area*).

请参阅 [Web.Auto 文档 - 创建无停车区](https://docs.web.auto/en/user-manuals/vector-map-builder/how-to-use/edit-maps#creation-of-no-parking-area) 以了解 Vector Map Builder 中的创建方法.

##### Autoware 的行为： toc  中省略

由于 *no_parking_area* 不允许设定目标,因此 Autoware 无法将车辆停在那里.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### Incorrect vector map  omit in toc

没有特别的.

#### 相关 Autoware 模块

- [Goal Planner 设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_path_planner/autoware_behavior_path_goal_planner_module/)

---

### vm-06-04 禁止停止部分

#### 在 toc 中省略的要求细节

虽然车辆可能会因信号或交通拥堵而停在道路上,但在创建 Vector Map 时,您可以禁止在特定区域进行任何形式的停车(临时停车、停车、怠速).

创建从 Lanelet (*subtype：road*) 到 Regulatory Element (*subtype：no_stopping_area*) 的引用,并让该 Regulatory Element 引用多边形 (*type：no_stopping_area*).

请参阅 [Web.Auto 文档 - 创建无停止区域](https://docs.web.auto/en/user-manuals/vector-map-builder/how-to-use/edit-maps#creation-of-no-stopping-area) 以了解 Vector Map Builder 中的创建方法.

##### Autoware 的行为： toc  中省略

车辆不会在 *no_stopping_area* 临时停车.由于无法在 *no_stopping_area* 中设定目标,因此车辆不能停在那里.

（图片说明：svg；未对图片像素执行 OCR）

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [No Stopping Area 设计 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_no_stopping_area_module/)

---

### vm-06-05 探测区域

#### 在 toc 中省略的要求细节

Autoware 通过检测检测区域中的点云来识别障碍物,从而在停止线处停止,并保持该停止状态,直到障碍物移开.要启用此响应,请将 Detection Area 元素合并到 Vector Map 中.

创建从 Lanelet (*subtype：road*) 到 Regulatory Element (*subtype：detection_area*) 的引用,并让该 Regulatory Element 引用多边形 (*type：detection_area*) 和线串 (*type：stop_line*).

请参阅 [Web.Auto 文档 - 创建检测区域](https://docs.web.auto/en/user-manuals/vector-map-builder/how-to-use/edit-maps#creation-of-detection-area) 以了解 Vector Map Builder 中的创建方法.

#### 首选向量映射 toc 中省略

（图片说明：svg；未对图片像素执行 OCR）

#### 在 toc 中省略了错误的矢量映射

没有特别的.

#### 相关 Autoware 模块

- [检测区域 - Autoware Universe 文档](https://autowarefoundation.github.io/autoware_universe/main/planning/behavior_velocity_planner/autoware_behavior_velocity_detection_area_module/)
