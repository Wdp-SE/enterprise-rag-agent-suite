# Rosbag 重放模拟

## 步骤

1. 下载并解压缩示例地图. `gdown-O~/autoware_map/`https://docs.google.com/uc?export=download&id=1A-8BvYRX3DhSzkAnOcGWFw5T30xTlwZI` unzip-d~/autoware_map/~/autoware_map/sample-map-rosbag.zip`
- 您也可以手动下载 [地图](https://drive.google.com/file/d/1A-8BvYRX3DhSzkAnOcGWFw5T30xTlwZI/view?usp=sharing) .
2. 下载示例 rosbag 文件. `gdown-O~/autoware_map/`https://docs.google.com/uc?export=download&id=1sU5wbxlXAfHIksuHjP3PyI2UVED8lZkP` unzip-d~/autoware_map/~/autoware_map/sample-rosbag.zip`
- 您也可以手动下载 [the rosbag files](https://drive.google.com/file/d/1sU5wbxlXAfHIksuHjP3PyI2UVED8lZkP/view?usp=sharing) .
3. 检查你是否有 `~/autoware_data` 文件夹和文件. `$cd~/autoware_data $ls-C-w30 image_projection_based_fusion lidar_apollo_instance_segmentation lidar_centerpoint tensorrt_yolo tensorrt_yolox traffic_light_classifier traffic_light_fine_detector traffic_light_ssd_fine_detector yabloc_pose_initializer` 如果没有,请按照 [手动下载工件](https://github.com/autowarefoundation/autoware/tree/main/ansible/roles/artifacts) 进行作.

### 注意

- 样本地图和rosbag：版权所有 2020 TIER IV, Inc.
- 出于隐私考虑,rosbag 不包含图片数据,这会导致：
- 无法使用此示例 rosbag 测试交通灯识别功能.
- 目标检测精度降低.

## 如何运行 rosbag 重放模拟

[使用 Autoware Launch GUI](#using-autoware-launch-gui)

如果您更喜欢使用图形用户界面 (GUI) 而不是命令行来启动和管理仿真,请参阅本文档末尾的 `使用 Autoware Launch GUI` 部分,以获取分步指南.

1. 启动 Autoware. `source~/autoware/install/setup.bash ros2launchautoware_launchlogging_simulator.launch.xmlmap_path:=$HOME/autoware_map/sample-map-rosbagvehicle_model:=sample_vehiclesensor_model:=sample_sensor_kit` 请注意,您不能在此处使用 `~` 而不是 `$HOME`. （图片说明：after-autoware-launch；未对图片像素执行 OCR） ⚠️ 在播放 `rosbag` 之前,您可能会在终端中遇到错误和警告消息.这是正常行为.一旦播放 `rosbag` 并进行适当的初始化,这些作就会停止
2. 播放示例 rosbag 文件. `source~/autoware/install/setup.bash ros2bagplay~/autoware_map/sample-rosbag/-r0.2-ssqlite3` 由于 `rosbag` 中的时间戳与当前系统时间戳之间存在差异,Autoware 可能会在终端中生成警告消息,提醒这种不匹配.这是正常行为. （图片说明：after-rosbag-play；未对图片像素执行 OCR）
3. 要将视图聚焦在自主车辆上,请将 RViz 视图面板中的 `Target Frame` 从 `viewer` 更改为 `base_link` . （图片说明：change-target-frame；未对图片像素执行 OCR）
4. 要将视图切换到 `Third Person Follower` 等,请在 RViz 视图面板中更改 `Type` . （图片说明：third-person-follower；未对图片像素执行 OCR）

[参考视频教程](https://drive.google.com/file/d/12D6aSC1Y3Kf7STtEPWG5RYynxKdVcPrc/view?usp=sharing)

## 使用 Autoware Launch GUI

本节提供了使用 Autoware Launch GUI 启动和管理 rosbag 重放模拟的分步指南.提供了上一节中提供的命令行说明的替代方法.

### Autoware Launch GUI 入门

1. **安装:** 确保您已安装 Autoware Launch GUI.[安装说明](https://github.com/autowarefoundation/autoware-launch-gui#installation).
2. **启动 GUI:** 从应用程序菜单中打开 Autoware Launch GUI. （图片说明：GUI_screenshot_for_launching；未对图片像素执行 OCR）

### 启动日志记录模拟

1. **设置 Autoware 路径:** 在 GUI 中,设置 Autoware 安装的路径. （图片说明：GUI_screenshot_for_setting_Autoware_path；未对图片像素执行 OCR）
2. **选择 Launch File(启动文件):** 选择 `logging_simulator.launch.xml` 作为车道行驶场景. （图片说明：GUI screenshot for selecting launch file；未对图片像素执行 OCR）
3. **自定义参数:** 根据需要调整 `map_path`、`vehicle_model` 和 `sensor_model` 等参数. （图片说明：GUI screenshot for customizing parameters；未对图片像素执行 OCR） （图片说明：GUI screenshot for customizing parameters；未对图片像素执行 OCR）
4. **开始模拟:** 单击启动按钮开始模拟并访问所有日志. （图片说明：GUI screenshot for starting simulation；未对图片像素执行 OCR）
5. **播放 Rosbag:** 移动到 `Rosbag` 选项卡并选择您要播放的 rosbag 文件. （图片说明：GUI screenshot for selecting rosbag file；未对图片像素执行 OCR）
6. **调整播放速度:** 根据需要调整播放速度和您希望自定义的任何其他参数. （图片说明：GUI screenshot for adjusting playback speed；未对图片像素执行 OCR）
7. **开始播放:** 单击播放按钮开始 rosbag 播放,并可以访问 `pause/play`、`stop` 和 `speed slider` 等设置5. （图片说明：GUI screenshot for starting playback；未对图片像素执行 OCR）
8. **查看模拟:** 移动到 `RViz` 窗口以查看模拟. （图片说明：after-rosbag-play；未对图片像素执行 OCR）
9. 要将视图聚焦在自我车辆上,请将 RViz 视图面板中的 `Target Frame` 从 `viewer` 更改为 `base_link`. （图片说明：change-target-frame；未对图片像素执行 OCR）
10. 要将视图切换到 `Third Person Follower` 等,请在 RViz 视图面板中更改 `Type`. （图片说明：third-person-follower；未对图片像素执行 OCR）
