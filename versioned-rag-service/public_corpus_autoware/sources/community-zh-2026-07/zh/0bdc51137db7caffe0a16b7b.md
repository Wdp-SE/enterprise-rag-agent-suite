# 创建 Lanelet

在这个页面上,我们将解释如何在你的点云地图上创建一个简单的 lanelet. 如果您之前没有点云地图, 请检查 并按照 [LIO-SAM 映射页面](../../open-source-slam/lio-sam/) 了解如何为 Autoware 创建点云地图.

## 创建 Lanelet2

首先,我们需要将点云地图导入 Vector Map Builder 工具：

1. 请点击 `文件` .
2. 然后,单击 `导入 PCD` .
3. 单击 `浏览` 并选择您的 .pcd 文件.

上传完成后,您将在 Vector Map Builder 工具上显示点云：

（图片说明：pointcloud-map；未对图片像素执行 OCR）

在 Vector Map Builder 上上传了点云地图文件

现在,我们准备在我们的点云地图上创建 lanelet2 地图：

1. 请点击 `创建` .
2. 然后,点击 `Create Lanelet2Maps` .
3. 请填写您的地图名称
4. 请填写您的 MGRS 区域.(tutorial_vehicle 时,MGRS 网格区：35T - MGRS 100,000 平方米：PF)
5. 点击 `创建` .

### 创建简单的 lanelet

为了在您的地图上创建一个简单的 lanelet,请按照以下步骤作：

1. 点击吧台上的 `Lanelet2Maps`
2. 通过选择 `Lanelet` 启用 Lanelet 模式.
3. 然后,您可以单击 pointcloud 地图来创建 lanelet.
4. 如果您的 lanelet 已完成,您可以禁用 `Lanelet` .
5. 如果要更改 lanelet 宽度,请点击 `lanelet` --> `Change Lanelet Width` ,然后就可以输入通道宽度了.

视频演示：

### 连接两个通道

要加入两个 lanelet,请按照以下步骤作：

1. 请创建两个不同的 lanelet.
2. 选择一个 lanelet,然后按 `Shift` 并选择其他 lanelet.
3. 现在,您可以看到 `加入 Lanelets` 按钮,只需按下它.
4. 这些 lanelet 将被连接起来.

视频演示：

### 加入多个 lanelets

如需将两个或多个 lanelet 添加(连接)到另一个 lanelet,请按照以下步骤作：

1. 创建多个 lanelet.
2. 您可以像前面的步骤一样加入前两个 lanelet.
3. 请检查第一个 lanelet 的端点 ID.
4. 然后你需要用 third lanelet 的 start point 来改变这些 id.(请选择 lanelet 的线串更改)
5. 您将看到第一个 lanelet 的下一个 2 个车道将出现.

视频演示：

### 更改 Lanelet 的速度限制

要更改 lanelet 的限速,请按照以下步骤作：

1. 选择将更改限速的车道
2. 在右侧面板上设置 `限速` .

### 使用场景仿真器测试 Lanelet

创建 lanelet 完成后,我们需要保存它. 为此,请单击 `文件` --> `导出 Lanelet2Maps` ,然后下载.

下载完成后, 我们需要将 lanelet2 map 和 pointcloud map 放在同一个位置. 目录结构应如下所示：

```
<YOUR-MAP-DIRECTORY>/
 ├─ pointcloud_map.pcd
 └─ lanelet2_map.osm
```

如果您的 .osm 或 .pcd 映射文件的名称与这些名称不同,则 您需要更新 autoware.launch.xml：

```
<!-- Map -->
-  <arg name="lanelet2_map_file" default="lanelet2_map.osm" description="lanelet2 map file name"/>
+  <arg name="lanelet2_map_file" default="<YOUR-LANELET-MAP-NAME>.osm" description="lanelet2 map file name"/>
-  <arg name="pointcloud_map_file" default="pointcloud_map.pcd" description="pointcloud map file name"/>
+  <arg name="pointcloud_map_file" default="<YOUR-POINTCLOUD-MAP-NAME>.pcd" description="pointcloud map file name"/>
```

现在我们准备启动场景仿真器：

```
ros2 launch autoware_launch planning_simulator.launch.xml map_path:=<YOUR-MAP-FOLDER-DIR> vehicle_model:=<YOUR-VEHICLE-MODEL> sensor_model:=<YOUR-SENSOR-KIT>
```

tutorial_vehicle示例：

```
ros2 launch autoware_launch planning_simulator.launch.xml map_path:=$HOME/Files/autoware_map/tutorial_map/ vehicle_model:=tutorial_vehicle sensor_model:=tutorial_vehicle_sensor_kit vehicle_id:=tutorial_vehicle
```

1. 单击 rviz 上的 `2D Pose Estimate` 按钮或按 `P` 并给出初始化姿势.
2. 点击 rviz 上的 `2D 目标姿势` 按钮或按 `G` 并给出目标点的姿势.

（图片说明：planning-simulator-test；未对图片像素执行 OCR）

使用场景仿真器测试我们创建的矢量图
