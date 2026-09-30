# 雷达-相机 校准

## 概述

激光雷达-相机标定是自动驾驶和机器人技术领域的关键过程, 其中 LiDAR 传感器和照相机都用于感知.

校准的目标是, 准确对齐来自这些不同传感器的数据. 为了创建全面而连贯的环境表示, 通过将 LiDAR 点投影到相机图像上.

在本教程中, 我们将解释 [TIER IV 的交互式相机校准器](https://github.com/tier4/CalibrationTools/blob/tier4/universe/sensor/docs/how_to_extrinsic_interactive.md).

另外,如果您有用于校准的 aruco 标记板,另一种 [Lidar-Camera 校准方法](https://github.com/tier4/CalibrationTools/blob/tier4/universe/sensor/docs/how_to_extrinsic_tag_based.md) 包含在 TIER IV 的 CalibrationTools 存储库中.

提示

您需要先应用 [本征校准](../intrinsic-camera-calibration/) , 在开始 lidar-camera 外部校准过程之前.也 请从 [手动校准](../extrinsic-manual-calibration/) 部分. 这对于从此工具获得准确的结果至关重要. 我们将使用计算出的初始校准参数 在本教程的上一步中. 要在校准工具中应用这些初始值, 请在单个参数包中更新您的传感器校准文件.

您的 bag 文件必须包含校准激光雷达主题和照相机主题. 相机主题可以是压缩主题或原始主题,但请记住,我们将根据主题类型更新 Interactive Calibrator 启动参数 `use_compressed`.

??? 注意 我们校准过程的 ROS 2 bag 示例(仅安装一台相机)如果您有多台相机,请同时添加 camera_info 和 image 主题

```
```sh

Files:             rosbag2_2023_09_12-13_57_03_0.db3
Bag size:          5.8 GiB
Storage id:        sqlite3
Duration:          51.419s
Start:             Sep 12 2023 13:57:03.691 (1694516223.691)
End:               Sep 12 2023 13:57:55.110 (1694516275.110)
Messages:          2590
Topic information: 

Topic: /sensing/lidar/top/pointcloud_raw | Type: sensor_msgs/msg/PointCloud2 | Count: 515 | Serialization Format: cdr
Topic: /sensing/camera/camera0/image_raw | Type: sensor_msgs/msg/Image | Count: 780 | Serialization Format: cdr
Topic: /sensing/camera/camera0/camera_info | Type: sensor_msgs/msg/CameraInfo | Count: 780 | Serialization Format: cdr

```
```

## 雷达-相机 校准

### 创建启动文件

我们首先创建我们的车辆的 启动文件4, 例如 `Extrinsic Manual Calibration` 过程：

```
cd <YOUR-OWN-AUTOWARE-DIRECTORY>/src/autoware/calibration_tools/sensor
cd extrinsic_calibration_manager/launch
cd <YOUR-OWN-SENSOR-KIT-NAME> # 即对于我们的指南，它将 ve cd tutorial_vehicle_sensor_kit 这是在手动校准中创建的
touch interactive.launch.xml interactive_sensor_kit.launch.xml
```

### 根据您的传感器套件修改启动文件

我们将使用 TIER IV 的样品传感器套件aip_xx1修改这些 `interactive.launch.xml` 和 `interactive_sensor_kit.launch.xml` .

所以,您应该将这两个文件的内容从 [aip_xx1](https://github.com/tier4/CalibrationTools/tree/tier4/universe/sensor/extrinsic_calibration_manager/launch/aip_xx1) 复制到您创建的文件中.

然后,我们将继续将 vehicle_id 和 sensor model 名称添加到 `interactive.launch.xml`. (或者,值不重要.这些参数将被 launch 参数覆盖)

```
<arg name="vehicle_id" default="default"/>

  <let name="sensor_model" value="aip_x1"/>
  <?xml version="1.0" encoding="UTF-8"?>
  <launch>
-   <arg name="vehicle_id" default="default"/>
+   <arg name="vehicle_id" default="<YOUR_VEHICLE_ID>"/>
+
-   <arg name="sensor_model" default="aip_x1"/>
+   <let name="sensor_model" value="<YOUR_SENSOR_KIT_NAME>"/>
```

如果要使用串联点云作为输入云 (标定过程将启动测井模拟器，从而构建激光雷达管道并出现串联点云), 您必须将 `use_concatenated_pointcloud` 值设置为 `true`.

```
-   <arg name="use_concatenated_pointcloud" default="false"/>
+   <arg name="use_concatenated_pointcloud" default="true"/>
```

tutorial_vehicle 的文件 `interactive.launch.xml` 的最终版本应如下所示：

??? 注意 教程战车的样本 interactive.launch.xml 文件

```
```xml
<?xml version="1.0" encoding="UTF-8"?>
<launch>
  <arg name="vehicle_id" default="tutorial_vehicle"/>
  <let name="sensor_model" value="tutorial_vehicle_sensor_kit"/>
  <arg name="camera_name"/>
  <arg name="rviz" default="false"/>
  <arg name="use_concatenated_pointcloud" default="true"/>

  <group>
    <push-ros-namespace namespace="sensor_kit"/>
    <include file="$(find-pkg-share extrinsic_calibration_manager)/launch/$(var sensor_model)/interactive_sensor_kit.launch.xml" if="$(var rviz)">
      <arg name="vehicle_id" value="$(var vehicle_id)"/>
      <arg name="camera_name" value="$(var camera_name)"/>
    </include>
  </group>

<!-- 您可以更改配置文件路径 -->
<node pkg="rviz2" exec="rviz2" name="rviz2" output="screen" args="
-d $(find-pkg-share extrinsic_calibration_manager)/config/x2/extrinsic_interactive_calibrator.rviz" if="$(var rviz)"/>
</launch>

```
```

完成 interactive.launch.xml 文件后,我们将准备好为自己的传感器模型实现 interactive_sensor_kit.launch.xml.

(可选)(别忘了,这些参数将被 launch 参数覆盖) 您可以将 sensor_kit 和 vehicle_id 修改为此 XML 代码段的 `interactive.launch.xml`. 我们将校准 parent_frame 设置为 `sensor_kit_base_link`

交互式校准器的默认相机输入主题是压缩图像。如果您想使用原始图像而不是压缩图像，您需要更新相机传感器主题的 `image_topic` 变量.

```
...
-   <let name="image_topic" value="/sensing/camera/$(var camera_name)/image_raw"/>
+   <let name="image_topic" value="/sensing/camera/$(var camera_name)/image_compressed"/>
    ...
```

更新主题名称后，您需要设置 use_compressed 参数（默认值为 `true`）值为 `false` 到 interactive_calibrator 节点。

```
...
   <node pkg="extrinsic_interactive_calibrator" exec="interactive_calibrator" name="interactive_calibrator" output="screen">
     <remap from="pointcloud" to="$(var pointcloud_topic)"/>
     <remap from="image" to="$(var image_compressed_topic)"/>
     <remap from="camera_info" to="$(var camera_info_topic)"/>
     <remap from="calibration_points_input" to="calibration_points"/>
+    <param name="use_compressed" value="false"/>
   ...
```

然后，您可以为每个摄像机自定义点云主题。例如，如果您想用左激光雷达校准camera_1，那么你应该像这样更改启动文件：

```
<let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera0` &quot;)"/>
-   <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera1` &quot;)"/>
+   <let name="pointcloud_topic" value="/sensing/lidar/left/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera1` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera2` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera3` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera4` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera5` &quot;)"/>
    ...
```

tutorial_vehicle 的 interactive_sensor_kit.launch.xml 启动文件应为：

??? 注意 [interactive_sensor_kit.launch.xml](https://github.com/leo-drive/tutorial_vehicle_calibration_tools/blob/tutorial_vehicle/sensor/extrinsic_calibration_manager/launch/tutorial_vehicle_sensor_kit/interactive_sensor_kit.launch.xml) 代表 tutorial_vehicle

```
```xml
<?xml version="1.0" encoding="UTF-8"?>
<launch>
    <arg name="vehicle_id" default="tutorial_vehicle"/>
    <let name="sensor_model" value="tutorial_vehicle_sensor_kit"/>
    <let name="parent_frame" value="sensor_kit_base_link"/>

    <!-- extrinsic_calibration_client -->
    <arg name="src_yaml" default="$(find-pkg-share individual_params)/config/$(var vehicle_id)/$(var sensor_model)/sensor_kit_calibration.yaml"/>
    <arg name="dst_yaml" default="$(env HOME)/sensor_kit_calibration.yaml"/>


    <arg name="camera_name"/>

    <let name="image_topic" value="/sensing/camera/$(var camera_name)/image_raw"/>
    <let name="image_topic" value="/sensing/camera/traffic_light/image_raw" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <let name="use_compressed" value="false"/>

    <let name="image_compressed_topic" value="/sensing/camera/$(var camera_name)/image_raw/compressed"/>
    <let name="image_compressed_topic" value="/sensing/camera/traffic_light/image_raw/compressed" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <let name="camera_info_topic" value="/sensing/camera/$(var camera_name)/camera_info"/>
    <let name="camera_info_topic" value="/sensing/camera/traffic_light/camera_info" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera0` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera1` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera2` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera3` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera4` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `camera5` &quot;)"/>
    <let name="pointcloud_topic" value="/sensing/lidar/top/pointcloud_raw" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <let name="calibrate_sensor" value="false"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera0` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera1` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera2` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera3` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera4` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `camera5` &quot;)"/>
    <let name="calibrate_sensor" value="true" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <let name="camera_frame" value=""/>
    <let name="camera_frame" value="camera0/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera0` &quot;)"/>
    <let name="camera_frame" value="camera1/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera1` &quot;)"/>
    <let name="camera_frame" value="camera2/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera2` &quot;)"/>
    <let name="camera_frame" value="camera3/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera3` &quot;)"/>
    <let name="camera_frame" value="camera4/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera4` &quot;)"/>
    <let name="camera_frame" value="camera5/camera_link" if="$(eval &quot;`$(var camera_name)` == `camera5` &quot;)"/>
    <let name="camera_frame" value="traffic_light_left_camera/camera_link" if="$(eval &quot;`$(var camera_name)` == `traffic_light_left_camera` &quot;)"/>

    <node pkg="extrinsic_calibration_client" exec="extrinsic_calibration_client" name="extrinsic_calibration_client" output="screen" if="$(var calibrate_sensor)">
        <param name="src_path" value="$(var src_yaml)"/>
        <param name="dst_path" value="$(var dst_yaml)"/>
    </node>

    <!-- extrinsic_calibration_manager -->
    <node pkg="extrinsic_calibration_manager" exec="extrinsic_calibration_manager" name="extrinsic_calibration_manager" output="screen" if="$(var calibrate_sensor)">
        <param name="parent_frame" value="$(var parent_frame)"/>
        <param name="child_frames" value="
    [$(var camera_frame)]"/>
    </node>

    <!-- 交互式校准器 -->
    <group if="$(var calibrate_sensor)">
        <push-ros-namespace namespace="$(var parent_frame)/$(var camera_frame)"/>

        <node pkg="extrinsic_interactive_calibrator" exec="interactive_calibrator" name="interactive_calibrator" output="screen">
            <remap from="pointcloud" to="$(var pointcloud_topic)"/>
            <remap from="image" to="$(var image_topic)"/>
            <remap from="camera_info" to="$(var camera_info_topic)"/>
            <remap from="calibration_points_input" to="calibration_points"/>

            <param name="camera_parent_frame" value="$(var parent_frame)"/>
            <param name="camera_frame" value="$(var camera_frame)"/>
            <param name="use_compressed" value="$(var use_compressed)"/>
        </node>

        <include file="$(find-pkg-share intrinsic_camera_calibration)/launch/optimizer.launch.xml"/>
    </group>
</launch>

```
```

### 使用交互式相机-激光雷达校准器进行激光雷达-相机校准过程

完成 interactive.launch.xml 后 `interactive_sensor_kit.launch.xml` 自己的传感器套件启动文件;

现在我们准备好校准我们的激光雷达了. 首先,我们需要构建 extrinsic_calibration_manager 包：

```
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release --packages-select extrinsic_calibration_manager
```

因此,我们已经准备好启动和使用交互式激光雷达-相机校准器.

```
ros2 launch extrinsic_calibration_manager calibration.launch.xml mode:=interactive sensor_model:=<OWN-SENSOR-KIT> vehicle_model:=<OWN-VEHICLE-MODEL> vehicle_id:=<VEHICLE-ID> camera_name:=<CALIBRATION-CAMERA>
```

对于教程车辆：

```
ros2 launch extrinsic_calibration_manager calibration.launch.xml mode:=interactive sensor_model:=tutorial_vehicle_sensor_kit vehicle_model:=tutorial_vehicle vehicle_id:=tutorial_vehicle
```

然后,我们需要播放我们的 bag 文件.

```
ros2 bag play <rosbag_path> --clock -l -r 0.2 \
--remap /tf:=/null/tf /tf_static:=/null/tf_static # if tf is recorded
```

您将看到一个手动交互式校准器 rqt 窗口和 Rviz2.

您必须将激光雷达传感器点云添加到 Rviz2, 然后我们才能发布校准器的点云.

（图片说明：interactive-calibrator；未对图片像素执行 OCR）

- 之后,让我们从按 `Publish Point` 开始 按钮,然后选择点云上也包含在投影图像中的点. 然后,您需要单击与图像上投影的 LiDAR 点相对应的图像点. 您将看到匹配的校准点.

（图片说明：interactive-calibration-points.png；未对图片像素执行 OCR）

- 之后,您需要匹配最少 6 个点才能执行校准. 如果您的匹配项有误,只需单击它们即可删除此匹配项. 在影像和激光雷达上选择点后,您就可以进行校准了. 如果所选点匹配大小大于 6, 则将启用 `Calibrate extrinsic` 按钮. 单击此按钮并将 tf 源 `Initial /tf` 更改为 `Calibrator` 以查看校准结果.

（图片说明：interactive-calibrator-results.png；未对图片像素执行 OCR）

校准完成后, 您需要通过 `Save calibration` 按钮保存校准结果. 保存的格式为 json, 所以你需要更新 `individual_params` 和 `sensor_kit_description` 包上 `sensor_kit_calibration.yaml` 的校准参数.

```
{
    "header": {
        "stamp": {
            "sec": 1694776487,
            "nanosec": 423288443
        },
        "frame_id": "sensor_kit_base_link"
    },
    "child_frame_id": "camera0/camera_link",
    "transform": {
        "translation": {
            "x": 0.054564283153017916,
            "y": 0.040947512210503106,
            "z": -0.071735410952332
        },
        "rotation": {
            "x": -0.49984112274024817,
            "y": 0.4905405357176159,
            "z": -0.5086269994990131,
            "w": 0.5008267267391722
        }
    },
    "roll": -1.5517347113946862,
    "pitch": -0.01711459479043047,
    "yaw": -1.5694590141484235
}
```

这是用于演示 tutorial_vehicle 上的 LiDAR 相机校准过程的视频：
