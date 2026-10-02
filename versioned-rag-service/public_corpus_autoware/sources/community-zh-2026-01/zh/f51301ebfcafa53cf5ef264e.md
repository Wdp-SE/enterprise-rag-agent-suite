# 系统启动文件

## 概述

Autoware 系统堆栈启动 正如我们在 [Launch Autoware] 中提到的,以 `autoware_launch.xml` 启动(../index.md) 页面. `autoware_launch` 套餐包括 `tier4_system_component.launch.xml` 用于从 `autoware_launch.xml` 启动系统启动文件调用. 此图描述了 `autoware_launch` 和 `autoware_universe` 包中的一些 Autoware 系统启动文件流.

（图片说明：system-launch-flow；未对图片像素执行 OCR）

Autoware 系统启动流程图

注意

Autoware 项目是一个大型项目. 因此,当我们管理 Autoware 项目时,我们会使用特定的 参数. ROS 2 为这些启动文件提供了参数覆盖功能. 有关更多信息,请参阅 [官方 ROS 2 启动文档](https://docs.ros.org/en/humble/Tutorials/Intermediate/Launch/Using-ROS2-Launch-For-Large-Projects.html#parameter-overrides). 例如 如果我们在顶级启动中定义一个参数, 它将覆盖较低级别启动时的值.

如系统启动管道的流程图中所述, `tier4_system_launch` 包中的 `system.launch.xml` 直接启动以下包：

- [系统监视器](https://autowarefoundation.github.io/autoware_universe/main/system/system_monitor/)
- [组件接口工具](https://autowarefoundation.github.io/autoware_universe/main/common/component_interface_tools/)
- [组件状态监视器](https://autowarefoundation.github.io/autoware_universe/main/system/component_state_monitor/)
- [系统错误监视器](https://autowarefoundation.github.io/autoware_universe/main/system/system_error_monitor/)
- [紧急处理程序](https://autowarefoundation.github.io/autoware_universe/main/system/emergency_handler/)
- [重复的节点检查器](https://autowarefoundation.github.io/autoware_universe/main/system/duplicated_node_checker/)
- [MRM舒适停止操作](https://autowarefoundation.github.io/autoware_universe/main/system/mrm_comfortable_stop_operator/)
- [MRM紧急停止操作](https://autowarefoundation.github.io/autoware_universe/main/system/mrm_emergency_stop_operator/)
- [虚拟诊断发布器](https://autowarefoundation.github.io/autoware_universe/main/system/dummy_diag_publisher/)

我们在系统启动文件中没有很多修改选项 (因为参数包含在配置文件中), 但您可以修改 system_error_monitor 参数的文件路径. 例如,如果要更改 system_error_monitor.param.yaml 文件的路径, 您可以使用以下命令行参数运行 Autoware：

```
ros2 launch autoware_launch autoware.launch.xml ... system_error_monitor_param_path:=<YOUR-SYSTEM-ERROR-PARAM-PATH> ...
```

或者您可以在 `tier4_system_component.launch.xml` 启动文件中更改它：

```
- <arg name="system_error_monitor_param_path" default="$(find-pkg-share autoware_launch)/config/..."/>
+ <arg name="system_error_monitor_param_path" default="<YOUR-SYSTEM-ERROR-PARAM-PATH>"/>
```
