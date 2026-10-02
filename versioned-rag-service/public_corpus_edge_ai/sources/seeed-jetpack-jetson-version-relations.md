本wiki简要介绍了JetPack的组成部分，帮助您快速了解JetPack与Jetson之间的关系，并回答一些最常见的问题。

## 1. JetPack由什么组成？
JetPack是一个软件包集合，包含两个主要组件：

**① L4T (Linux for Tegra)。** L4T是为Jetson硬件平台定制的中间件Linux发行版。它包含：

- Ubuntu根文件系统

- Linux内核（带有NVIDIA补丁）

- 驱动程序（GPU、ISP、CSI、I2C等）

- 固件（Bootloader、UEFI、U-Boot、initrd）

- BSP（板级支持包），包括设备树、启动配置和刷写工具

- 等等

**② JetPack SDK。** 这是上层软件层，主要提供应用程序开发工具，包括：

- CUDA Toolkit

- cuDNN（深度学习库）

- TensorRT（AI模型推理引擎）

- 等等

## 2. JetPack与Ubuntu之间是什么关系？

如上面第一个答案所述，Ubuntu是JetPack的一部分。每个JetPack版本都包含特定版本的Ubuntu。我们的JetPack版本包含以下Ubuntu版本：

| JetPack版本 | L4T版本 | Ubuntu版本 |
|------------------|--------------|-----------------|
| JetPack 6.2      | L4T 36.4.3   | Ubuntu 22.04    |
| JetPack 6.1      | L4T 36.4.0   | Ubuntu 22.04    |
| JetPack 6.0      | L4T 36.3.0   | Ubuntu 22.04    |
| JetPack 5.1.3    | L4T 35.5.0   | Ubuntu 20.04    |
| JetPack 5.1.1    | L4T 35.3.1   | Ubuntu 20.04    |
| JetPack 4.6.6    | L4T 32.7.6   | Ubuntu 18.04    |

## 3. 我们产品支持的Jetpack版本？
我们目前可用产品支持的JetPack版本可以在以下链接中找到：

[seeed的jetpack版本](https://docs.google.com/spreadsheets/d/1Sf7IdmVkKTAUH95XwxHK0ojV5aFq3ItKZ-iT28egzIk/edit?pli=1&gid=0#gid=0)

## 4. JetPack 6.2与Super Mode之间的关系

刷写了JetPack 6.2的设备支持激活Super Mode。但是，请注意Super Mode目前仅在选定的Seeed产品上可用。

## 5. 如何查找每个JetPack版本的内容？

您可以参考NVIDIA发布的官方资源。详情请参见以下链接：

[每个jetpack的内容](https://developer.nvidia.com/embedded/jetpack-archive)

## 资源

- [Seeed的L4T源代码](https://github.com/Seeed-Studio/Linux_for_Tegra)

## 技术支持与产品讨论

感谢您选择我们的产品！我们在这里为您提供不同的支持，以确保您使用我们产品的体验尽可能顺畅。我们提供多种沟通渠道，以满足不同的偏好和需求。
