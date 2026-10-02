# 将 JetPack OS 刷写到 J401 载板

J401 载板是一款功能强大的扩展板，支持 NVIDIA Jetson Orin NX/Nano 模组。它具有 1 个 GbE 接口、1 个用于数据传输的 CAN 接口、用于 SSD 的 M.2 Key M、用于 WiFi/BlueTooth 的 M.2 Key E、2 路 CSI 和 1 个用于高质量视频采集与显示的 HDMI。它还包含 4 个 USB 3.2 接口、风扇、RTC，以及灵活的 9-19V 电源输入。所有这些使其在构建强大的 AI 应用时，能够可靠地应用于各种工业自动化系统。

## 特性

- **卓越性能载板：** 支持 NVIDIA Jetson Orin NX/Nano 模组，利用强大的计算能力轻松应对艰巨任务
- **多样化连接：** 提供 1 个千兆以太网接口用于网络连接、4 个 USB 3.2 Type-A（10Gbps）接口、1 个 USB2.0 Type-C 接口、1 个用于高速数据传输的 CAN 接口
- **灵活的存储和无线扩展：** 搭载 1 个 M.2 Key M 2280 和 1 个 M.2 Key E 插槽，提供充足空间以灵活扩展存储和无线连接
- **支持高级外设：** 集成 2 个 15 针 CSI 摄像头接口、1 个 HDMI 2.1、1 个风扇、1 个 RTC，可连接多种外设
- **宽范围输入电压：** 支持 9-19V 直流电，为电源选择提供灵活性

## 规格参数

| 规格 | reComputer J3010 | reComputer J3011 | reComputer J4011 | reComputer J4012 |
| --- | --- | --- | --- | --- |
| 模组 | Jetson Orin Nano 4GB | Jetson Orin Nano 8GB | Jetson Orin NX 8GB | Jetson Orin NX 16GB |
| AI 性能 | 20 TOPS | 40 TOPS | 70 TOPS | 100 TOPS |
| GPU | 512 核 NVIDIA Ampere 架构 GPU，带 16 个 Tensor Core | 1024 核 NVIDIA Ampere 架构 GPU，带 32 个 Tensor Core | 1024 核 NVIDIA Ampere 架构 GPU，带 32 个 Tensor Core |  |
| GPU 最大频率 | 625 MHz |  | 765 MHz | 918 MHz |
| CPU | 6 核 Arm® Cortex®-A78AE v8.2 64 位 CPU 1.5MB L2 + 4MB L3 |  | 6 核 Arm® Cortex®-A78AE v8.2 64 位 CPU 1.5MB L2 + 4MB L3 | 8 核 Arm® Cortex®-A78AE v8.2 64 位 CPU 2MB L2 + 4MB L3 |
| CPU 最大频率 | 1.5 GHz |  | 2 GHz |  |
| 内存 | 4GB 64 位 LPDDR5 34 GB/s | 8GB 128 位 LPDDR5 68 GB/s | 8GB 128 位 LPDDR5 102.4GB/s | 16GB 128 位 LPDDR5 102.4GB/s |
| DL 加速器 | / |  | 1x NVDLA v2 | 2x NVDLA v2 |
| DLA 最大频率 | / |  | 614 MHz |  |
| 视觉加速器 | / |  | 1x PVA v2 |  |
| 存储 | 128GB NVMe SSD |  |  |  |
| 视频编码器 | 由 1-2 个 CPU 核心支持的 1080p30 |  | 1x 4K60（H.265）\| 3x 4K30（H.265） 6x 1080p60（H.265）\| 12x 1080p30（H.265） |  |
| 视频解码器 | 1x 4K60（H.265） 2x 4K30（H.265） 5x 1080p60（H.265） 11x 1080p30（H.265） |  | 1x 8K30（H.265）\| 2x 4K60（H.265）\| 4x 4K30（H.265） 9x 1080p60（H.265）\| 18x 1080p30（H.265） |  |
| 显示 | 1* HDMI 2.1 |  |  |  |
| CSI 摄像头 | 2* CSI（2-lane 15pin） |  |  |  |
| 网络 | 1* 千兆以太网（10/100/1000M） |  |  |  |
| USB | 4* USB 3.2 Type-A（10Gbps）；1* USB2.0 Type-C（设备模式） |  |  |  |
| M.2 Key M | 1* M.2 Key M |  |  |  |
| M.2 Key E | 1* M.2 Key E |  |  |  |
| 风扇 | 1* 4 针风扇连接器（5V PWM） |  |  |  |
| CAN | 1* CAN |  |  |  |
| 多功能接口 | 1* 40 针扩展排针，1* 12 针控制和 UART 排针 |  |  |  |
| RTC | RTC 2 针，RTC 座（支持 CR1220，但不包含） |  |  |  |
| 电源 | 9-19V |  |  |  |
| 电源适配器 | 不包含电源适配器 |  |  |  |
| 温度 | -10℃~60℃ |  |  |  |
| 机械尺寸 | 130mm x120mm x 58.5mm |  |  |  |

## 硬件概览

## 刷写 JetPack

在这里，我们将向你展示如何将 [Jetpack](https://developer.nvidia.com/embedded/jetpack) 刷写到连接在 reComputer J4012/ J4011/ J3010 和 J3011 上的 NVMe SSD。所有这些设备内部都搭载 J401 载板，刷写流程对所有设备都是相同的。

reComputer J40/ J30 系列在随附的 NVMe SSD 上预装了 JetPack 5.1.3，因此你不需要重新刷写。不过，如果你想重新刷写 JetPack，可以按照本指南进行操作。

### 支持的模组

- [NVIDIA® Jetson Orin™ Nano Module 4GB](https://www.seeedstudio.com/NVIDIA-JETSON-ORIN-NANO-4GB-Module-p-5554.html)
- [NVIDIA® Jetson Orin™ Nano Module 8GB](https://www.seeedstudio.com/NVIDIA-JETSON-ORIN-NANO-8GB-Module-p-5552.html)
- [NVIDIA® Jetson Orin™ NX Module 8GB](https://www.seeedstudio.com/NVIDIA-Jetson-Orin-NX-Module-8GB-p-5523.html)
- [NVIDIA® Jetson Orin™ NX Module 16GB](https://www.seeedstudio.com/NVIDIA-Jetson-Orin-NX-Module-16GB-p-5524.html)

### 前置条件

- Ubuntu 主机电脑
- reComputer J4012/ J4011/ J3010 或 J3011
- USB Type-C 数据传输线

> 说明：我们建议你使用物理 Ubuntu 主机设备，而不是虚拟机。
请参考下表准备主机设备。

| JetPack 版本 | Ubuntu 版本（主机电脑） |  |  |  |
| --- | --- | --- | --- | --- |
|  | 18.04 | 20.04 | 22.04 | 24.04 |
| JetPack 5.x | ✅ | ✅ |  |  |
| JetPack 6.x |  | ✅ | ✅ |  |
| JetPack 7.2 |  | ✅ | ✅ | ✅ |

Note: 对于 JetPack 7.2，Ubuntu 24.04 仅支持刷写和目标端组件安装。如果你需要主机端开发组件，请使用 Ubuntu 20.04 或 22.04。

### 进入强制恢复模式

> 说明：- 我们不建议使用虚拟机和 ARM 架构的 Ubuntu 进行刷写。
- 在继续安装步骤之前，我们需要确保开发板处于强制恢复模式。

 分步说明 

**步骤 1.** 使用跳线将 **FC REC** 引脚和 **GND** 引脚连接起来。

|  | 按键排针 | 描述 | 按键排针 | 描述 |
| --- | --- | --- | --- | --- |
|  | 1 | PWR BTN | 7 | AUTO ON |
|  | 2 | GND | 8 | DIS |
|  | 3 | FC REC | 9 | UART TXD |
|  | 4 | GND | 10 | UART RXD |
|  | 5 | SYS RET | 11 | LED + |
|  | 6 | GND | 12 | LED - |

**步骤 2.** 将电源适配器附带的电源线连接到 reComputer 以其上电，并使用 USB Type-C 数据传输线将该板连接到 Ubuntu 主机 PC

**步骤 3.** 在 Linux 主机 PC 上打开一个终端窗口并输入命令 `lsusb`。如果根据你使用的 Jetson SoM，返回的内容中包含以下输出之一，则说明该板已进入强制恢复模式。

- 对于 Orin NX 16GB：**0955:7323 NVidia Corp**
- 对于 Orin NX 8GB：**0955:7423 NVidia Corp**
- 对于 Orin Nano 8GB：**0955:7523 NVidia Corp**
- 对于 Orin Nano 4GB：**0955:7623 NVidia Corp**

下图为 Orin NX 16GB 的示例

**步骤 4.** 移除跳线

<!-- 
### Flash the device with a single command

 Flash the device with a single command. 

The reComputer Jetson J30/40 has launched a one-click flashing script, which supports flashing Jetpack 5.1.1, 5.1.2 , 6.0 , 6.1 and 6.2. Currently, the one-click flashing for Jetpack 6.1 and other series of reComputer Jetson is under testing and will be available to everyone in the near future.

```bash
wget -O ./flashing.sh https://files.seeedstudio.com/OSHW_Jetson/flashing.sh  && sudo chmod 777 ./flashing.sh && ./flashing.sh
```

:::caution
免责声明：一键刷机脚本旨在让 JetPack 刷机更快捷。目前版本为测试版，可能存在许多问题，敬请谅解。如果出现刷机问题，请按照下方的 `Flash The Device Step by Step` 操作，并在我们的 [Discord Jetson channel](https://discord.com/channels/862602258452578314/930732339624026152) 中反馈。我们会及时修复这些问题，并在不久的将来改进此功能。

 -->

### 按步骤为设备刷机

> 说明：在进行刷机之前，需要注意 Jetson Orin NX 模组仅支持 JetPack 5.1 及以上版本，而 Jetson Orin Nano 模组仅支持 JetPack 5.1.1 及以上版本。

首先，在刷写 JetPack 之前，请在 Ubuntu 主机 PC 上安装以下所需依赖。

```sh
sudo apt install qemu-user-static sshpass abootimg nfs-kernel-server libxml2-utils binutils -y
```

<!-- Code -->

:::caution
NVIDIA 已更新其模组中使用的 DRAM。为确保与新模组兼容，我们相应地更新了 JetPack。目前稳定且受支持的版本是 `JetPack 5.1.3`。
如果你模组上的 DRAM 来自 `Hynix`（可通过芯片封装上的标记识别），建议刷写 `JetPack 5.1.3`。

## JP5.1.1

这里我们将使用 NVIDIA L4T 35.3.1 在 reComputer 上安装 Jetpack 5.1.1

**步骤 1：** 在主机 PC 上[下载](https://developer.nvidia.com/embedded/jetson-linux-r3531) NVIDIA 驱动程序。所需驱动如下所示：

**步骤 2：** 通过进入包含这些文件的文件夹，解压 **Jetson_Linux_R35.3.1_aarch64** 和 **Tegra_Linux_Sample-Root-Filesystem_R35.3.1_aarch64**，应用更改并安装必要的前置依赖

```sh
tar xf Jetson_Linux_R35.3.1_aarch64
sudo tar xpf Tegra_Linux_Sample-Root-Filesystem_R35.3.1_aarch64 -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra/
sudo ./apply_binaries.sh
sudo ./tools/l4t_flash_prerequisites.sh
```

**步骤 3（可选）：** 配置你的用户名、密码和主机名，这样在设备完成启动后就不需要进入 Ubuntu 安装向导

```sh
sudo tools/l4t_create_default_user.sh -u {USERNAME} -p {PASSWORD} -a -n {HOSTNAME} --accept-license
```

例如（username:"nvidia", password:"nvidia", device-name:"nvidia-desktop"）：

```sh
sudo tools/l4t_create_default_user.sh -u nvidia -p nvidia -a -n nvidia-desktop --accept-license
```

**步骤 4：** 将系统刷写到 NVMe SSD

```sh
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 \
  -c tools/kernel_flash/flash_l4t_external.xml -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml" \
  --showlogs --network usb0 p3509-a02+p3767-0000 internal
```

如果刷机过程成功，你将看到如下输出

现在，你可以将鼠标、键盘和显示器连接到 Jetson 设备上。它已经可以使用了！

> 说明：如果你的 Jetson 设备打开桌面花费时间较长，请重新连接电源。

**步骤 5（可选）：** 安装 Nvidia Jetpack SDK

请在**Jetson 设备**上打开终端并执行以下命令：

```bash
sudo apt update
sudo apt install nvidia-jetpack
```

## JP5.1.2

这里我们将使用 NVIDIA L4T 35.4.1 在 reComputer 上安装 Jetpack 5.1.2

**步骤 1：** 在主机 PC 上[下载](https://developer.nvidia.com/embedded/jetson-linux-r3541) NVIDIA 驱动程序。所需驱动如下所示：

**步骤 2：** 通过进入包含这些文件的文件夹，解压 **Jetson_Linux_R35.4.1_aarch64** 和 **Tegra_Linux_Sample-Root-Filesystem_R35.4.1_aarch64**，应用更改并安装必要的前置依赖

```sh
tar xf Jetson_Linux_R35.4.1_aarch64.tbz2
sudo tar xpf Tegra_Linux_Sample-Root-Filesystem_R35.4.1_aarch64.tbz2 -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra/
sudo ./apply_binaries.sh
sudo ./tools/l4t_flash_prerequisites.sh
```

现在我们需要应用来自 NVIDIA 的一个补丁，该补丁是 JP5.1.2 所必需的，相关说明见官方 NVIDIA JetPack 发行说明第 4.2.3 节[此处](https://docs.nvidia.com/jetson/archives/r35.4.1/ReleaseNotes/Jetson_Linux_Release_Notes_r35.4.1.pdf)。

**步骤 3：** 进入以下目录

```sh
cd Linux_for_Tegra/bootloader/t186ref/BCT
```

**步骤 4：** 打开文件 **"tegra234-mb2-bct-scr-p3767-0000.dts"**，并在 **tfc** 部分下添加以下几行

```sh
tfc {
    reg@322 { /* GPIO_M_SCR_00_0 */
    exclusion-info = <2>;
    value = <0x38008080>;
    };
```

**步骤 5（可选）：** 进入 **"Linux_for_Tegra"** 目录，并输入以下命令来配置你的用户名、密码和主机名，这样在设备完成启动后就不需要进入 Ubuntu 安装向导

```sh
cd Linux_for_Tegra
sudo tools/l4t_create_default_user.sh -u {USERNAME} -p {PASSWORD} -a -n {HOSTNAME} --accept-license
```

例如（username:"nvidia", password:"nvidia", device-name:"nvidia-desktop"）：

```sh
sudo tools/l4t_create_default_user.sh -u nvidia -p nvidia -a -n nvidia-desktop --accept-license
```

**步骤 6：** 将系统刷写到 NVMe SSD

```bash

cp p3509-a02+p3767-0000.conf p3509-a02-p3767-0000.conf
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1   -c tools/kernel_flash/flash_l4t_nvme.xml -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml --no-systemimg"   --showlogs --network usb0 p3509-a02-p3767-0000 external

```

如果刷机过程成功，你将看到如下输出

现在，你可以将鼠标、键盘和显示器连接到 Jetson 设备上。它已经可以使用了！

> 说明：如果你的 Jetson 设备打开桌面花费时间较长，请重新连接电源。

**步骤 7（可选）：** 安装 Nvidia Jetpack SDK

请在**Jetson 设备**上打开终端并执行以下命令：

```bash
sudo apt update
sudo apt install nvidia-jetpack
```

## JP5.1.3

这里我们将在 reComputer 上安装 Jetpack 5.1.3。

**步骤 1：** 将与你所使用 Jetson 模组对应的系统镜像下载到 Ubuntu PC：

| Jetson Module | Download Link | SHA256 |
| --- | --- | --- |
| Orin NX 16GB | Download | 37F99E90A746D07242EE17E2A74A3336490E997457DE0E9FC15A1E35D347543B |
| Orin NX 8GB | Download | 4FDD5F05EE83F425AD1D8E2768BDF35FA68D3F1143B09C2FB9537CBFD1A9D5EC |
| Orin Nano 8GB | Download | 6A002620B6E40673A39710F0ECC1C56CB5750480B799F97BB7DE4A5B6F49C527 |
| Orin Nano 4GB | 下载 | 63A3D59185BDB286452CA7774DD528F5087249B8065D902C9181703010B7836A |

> 说明：为了验证下载固件的完整性，您可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明您下载的固件是完整且未损坏的。

**步骤 2：** 解压下载的镜像文件：

```bash
sudo tar xpf mfi_xxxx.tar.gz
# For example: sudo tar xpf mfi_recomputer-orin-nano-8g-j401-6.0-36.3.0-2024-06-07.tar.gz
```

**步骤 3：** 进入解压后的目录，并执行以下命令将 jetpack 系统烧录到 NVMe SSD：

```bash
cd mfi_xxxx
# For example: cd mfi_recomputer-orin-j401
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0  --showlogs
```

如果烧录过程成功，您将看到如下输出

> 说明：烧录命令可能会运行 2-10 分钟。

**步骤 4：** 使用板载的 HDMI 接口将 J401 连接到显示器，并完成初始配置设置。

> 说明：请根据您的需求完成 **System Configuration**。

## JP6.0

这里我们将使用 NVIDIA L4T 36.3 在 reComputer 上安装 Jetpack 6.0

**步骤 1：** 将与您所使用 Jetson 模组对应的系统镜像下载到 Ubuntu 电脑：

| Jetson 模组 | 下载链接 1 | 下载链接 2 | SHA256 |
| --- | --- | --- | --- |
| Orin NX 16GB | 下载 | 下载 | 20b38d9524327fd714c37cb293036006e070b5335d6b4f6978a862be51c3db52 |
| Orin NX 8GB | 下载 | 下载 | da966e7616ed86b45e184b6db9c3eb81e779a5f4524f6c3c5610e56c53532fe1 |
| Orin Nano 8GB | 下载 | 下载 | e0fa101c5df6f507d123c2332e9fedea0ac54f8a5253cb28e71fdff01147fa68 |
| Orin Nano 4GB | 下载 | 下载 | 80ebeac0a843baa2c3104ee6341d44f39a2cfab1c9c725e176c7b2a219b79dfc |

> 说明：为了验证下载固件的完整性，您可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明您下载的固件是完整且未损坏的。

**步骤 2：** 解压下载的镜像文件：

```bash
sudo tar xpf mfi_xxxx.tar.gz
# For example: sudo tar xpf mfi_recomputer-orin-nano-8g-j401-6.0-36.3.0-2024-06-07.tar.gz
```

**步骤 3：** 进入解压后的目录，并执行以下命令将 jetpack 系统烧录到 NVMe SSD：

```bash
cd mfi_xxxx
# For example: cd mfi_recomputer-orin-j401
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0  --showlogs
```

如果烧录过程成功，您将看到如下输出

> 说明：烧录命令可能会运行 2-10 分钟。

**步骤 4：** 使用板载的 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据您的需求完成 **System Configuration**。

**步骤 5：** 系统启动后，您需要执行以下命令以重新激活无线网卡驱动：

```bash
sudo rm /lib/modules/5.15.136-tegra/build
sudo ln -s /usr/src/linux-headers-5.15.136-tegra-ubuntu22.04_aarch64/3rdparty/canonical/linux-jammy/kernel-source/ /lib/modules/5.15.136-tegra/build
sudo apt install -y iwlwifi-modules
```

## JP6.1

这里我们将使用 NVIDIA L4T 36.4 在 reComputer 上安装 Jetpack 6.1

**步骤 1：** 将与您所使用 Jetson 模组对应的系统镜像下载到 Ubuntu 电脑：

| Jetson 模组 | 下载链接 | SHA256 |
| --- | --- | --- |
| Orin NX 16GB | 下载 | b848e327b87c408565b899a11c52022b42df6de4f3dce1e5470cb2a7baccc898 |
| Orin NX 8GB | 下载 | 3839c99fc9e2da1f35de824c42b7bb56f9660d8f4a6ce68b196c6cb50d5d4fb4 |
| Orin Nano 8GB | 下载 | a0863e7209351f9165cf6bd2d756a6a726b2e8fc1fa54b5d66279d5b136a3a33 |
| Orin Nano 4GB | 下载 | a40edfbcda9a7a07fbf72ca4e3149d171236f5ede2c4e3a5e243da77562f9b13 |

> 说明：为了验证下载固件的完整性，您可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明您下载的固件是完整且未损坏的。

**步骤 2：** 解压下载的镜像文件：

```bash
sudo tar xpf mfi_xxxx.tar.gz
# For example: sudo tar xpf mfi_recomputer-orin-nx-16g-j401-6.1-36.4.0-2026-02-07.tar.gz
```

**步骤 3：** 进入解压后的目录，并执行以下命令将 jetpack 系统烧录到 NVMe SSD：

```bash
cd mfi_xxxx
# For example: cd mfi_recomputer-orin-j401
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0  --showlogs
```

如果烧录过程成功，您将看到如下输出

> 说明：烧录命令可能会运行 2-10 分钟。

**步骤 4：** 使用板载的 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据您的需求完成 **System Configuration**。

## JP6.2

这里我们将使用 NVIDIA L4T 36.4.3 在 reComputer 上安装 Jetpack 6.2

> 说明：如果你正在使用 **Orin NX 16GB/8GB** 模块，**请不要启用 MAXN SUPER 模式**。
reComputer J401 载板的散热能力不足以支持该模式，强行启用可能会对模块造成永久性损坏。

**步骤 1：** 将与你所使用 Jetson 模块对应的系统镜像下载到 Ubuntu 电脑：

| Jetson 模块 | 下载链接 | SHA256 |
| --- | --- | --- |
| Orin NX 16GB | Download | b9529f008cf9a65460db3ee17736db971b8d110049f9f6ea8ecc8fe4d1691869 |
| Orin NX 8GB | Download | b7106b4f8c5835011040c071dd14e1144b5298af300f920e44517b99c183ed05 |
| Orin Nano 8GB | Download | c2247262dec1379fd4494def6a6ed2d4414605a8dcb902c6d6afbb94a5e48499 |
| Orin Nano 4GB | Download | 1d570b54853bba4ecc115789d1b03c5ba07b34344f7616dfa3c3772c9ff37e64 |

> 说明：为了验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上打开终端，运行命令 `sha256sum ` 获取下载文件的 SHA256 哈希值。如果结果与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

> 说明：请注意，由于启用 `super mode` 后功耗和发热量增加，[reComputer J4011](https://www.seeedstudio.com/reComputer-J4011-p-5585.html) 和 [reComputer J4012](https://www.seeedstudio.com/reComputer-J4012-p-5586.html?qid=eyJjX3NlYXJjaF9xdWVyeSI6Iko0MDEyIiwiY19zZWFyY2hfcmVzdWx0X3BvcyI6MiwiY190b3RhbF9yZXN1bHRzIjo4LCJjX3NlYXJjaF9yZXN1bHRfdHlwZSI6IlByb2R1Y3QiLCJjX3NlYXJjaF9maWx0ZXJzIjoic3RvcmVDb2RlOltyZXRhaWxlcl0ifQ%3D%3D) 无法在最高模式下稳定运行。因此，本次更新不包含这两款产品。
我们目前正在设计新版本的 reComputer，敬请期待！

**步骤 2：** 解压下载的镜像文件：

```bash
sudo tar xpf mfi_xxxx.tar.gz
# For example: sudo tar xpf mfi_recomputer-orin-nano-8g-j401-6.2-36.4.3-2025-04-07.tar.gz
```

**步骤 3：** 进入解压后的目录，执行以下命令将 jetpack 系统烧录到 NVMe SSD：

```bash
cd mfi_xxxx
# For example: cd mfi_recomputer-orin-j401
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0  --showlogs
```

如果烧录过程成功，你将看到如下输出

> 说明：烧录命令可能会运行 2-10 分钟。

**步骤 4：** 使用板载 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据你的需求完成 **System Configuration**。

## JP7.2

这里我们将使用 NVIDIA L4T 39.2.0 在 reComputer Classic 系列上安装 JetPack 7.2。

> 说明：如果你正在使用 **Orin NX 16GB/8GB** 模块，**请不要启用 MAXN SUPER 模式**。
reComputer J401 载板的散热能力不足以支持该模式，强行启用可能会对模块造成永久性损坏。

**步骤 1：** 将与你所使用 Jetson 模块对应的系统镜像下载到 Ubuntu 电脑：

| Jetson 模块 | 下载链接 | SHA256 |
| --- | --- | --- |
| Orin NX 16GB | Download | af580015dc79643e22e50a4d93dd4686066110ad1fd02b2f47bce7b6401e5a34 |
| Orin NX 8GB | Download | e734088d376fbbca403ba5d8afa9233869f6dcc2c5dde4ccb23efddd171060c1 |
| Orin Nano 8GB | Download | ac1175f73db4897c7d1e766231adacefd28fd6a329e05019d7550a7ae7b960f9 |
| Orin Nano 4GB | Download | 95ffcec87f0e7c8d440aa2da5202c4ed691d39df7560cdaf6e32131c686be74f |

> 说明：为了验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上打开终端，运行命令 `sha256sum ` 获取下载文件的 SHA256 哈希值。如果结果与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

**步骤 2：** 解压下载的镜像文件：

```bash
sudo tar xpf mfi_xxxx.tar.gz
# For example: sudo tar xpf mfi_recomputer-orin-nx-16g-j401-7.2.0-39.2.0-2026-08-28.tar.gz
```

**步骤 3：** 进入解压后的目录，执行以下命令将 jetpack 系统烧录到 NVMe SSD：

```bash
cd mfi_xxxx
# For example: cd mfi_recomputer-orin
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0  --showlogs
```

如果烧录过程成功，你将看到如下输出

> 说明：烧录命令可能会运行 2-10 分钟。

**步骤 4：** 使用板载 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据你的需求完成 **System Configuration**。

<!-- Code END -->

## 资源

- [reComputer J30x 规格书](https://files.seeedstudio.com/products/NVIDIA/reComputer-J301x-datasheet.pdf)
- [reComputer J40x 规格书](https://files.seeedstudio.com/products/NVIDIA/reComputer-J401x-datasheet.pdf)
- [reComputer J30/J40 原理图](https://files.seeedstudio.com/wiki/J401/reComputer_J401_SCH_V1.0.pdf)
- [reComputer J30/J40 3D 文件](https://files.seeedstudio.com/wiki/reComputer-J4012/reComputer-J4012.stp)
- [Seeed Jetson 系列目录](https://files.seeedstudio.com/wiki/Seeed_Jetson/Seeed-NVIDIA_Jetson_Catalog_V1.4.pdf)
- [Seeed Studio Edge AI 成功案例](https://www.seeedstudio.com/blog/wp-content/uploads/2023/07/Seeed_NVIDIA_Jetson_Success_Cases_and_Examples.pdf)
- [Seeed Jetson 系列对比](https://www.seeedstudio.com/blog/nvidia-jetson-comparison-nano-tx2-nx-xavier-nx-agx-orin/)
- [Seeed Jetson 设备一览](https://files.seeedstudio.com/wiki/Seeed_Jetson/Seeed-Jetson-one-pager.pdf)
- [Jetson 示例](https://github.com/Seeed-Projects/jetson-examples)
- [reComputer-Jetson-for-Beginners](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners)

## 技术支持与产品讨论

感谢你选择我们的产品！我们将为你提供多种支持，确保你在使用我们产品的过程中尽可能顺利。我们提供多种沟通渠道，以满足不同的偏好和需求。
