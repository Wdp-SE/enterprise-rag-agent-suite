# reComputer Industrial 入门指南

reComputer industrial 系列提供包含 NVIDIA Jetson™ Xavier NX / Orin Nano / Orin NX 模组的完整系统，AI 性能范围从 20 TOPS 到 100 TOPS。预装 Jetpack 5.1.3，reComputer industrial 简化了开发流程，非常适合构建视频分析、目标检测、自然语言处理、医学影像和机器人等应用，为智慧城市、安全、工业自动化、智能工厂等行业带来数字化转型。

reComputer industrial 配备被动散热片并采用无风扇设计，非常适合在严苛环境中使用。被动散热片无需风扇即可实现高效散热，降低因灰尘或其他污染物导致元器件故障的风险。无风扇设计还可降低噪声水平和功耗，适用于对噪声敏感的环境，同时最大限度减少能源成本。

reComputer industrial 具有 2 个 RJ45 GbE 接口，其中一个是 PoE PSE 接口，可为 IP 摄像头等设备提供以太网供电。这消除了单独电源的需求，使在缺乏现成电源插座的区域部署网络设备更加容易。另一个 GbE 接口用于连接到网络交换机或路由器，从而实现与网络中其他设备的通信并访问互联网。

> 说明：可定制选项：Logo 品牌定制、包装和固件烧录。

## 特性

- **无风扇紧凑型 PC：** 热设计参考，支持更宽温度范围 -20 ~ 60°C（0.7m/s 气流）
- **为工业接口而设计：** 2x RJ-45 GbE（1 个用于 POE-PSE 802.3 af）；1x RS-232/RS-422/RS-485；4x DI/DO；1x CAN；3x USB3.2；1x TPM2.0（可选模组）
- **混合连接：** 支持 5G/4G/LTE/LoRaWAN®（可选模组），带 1x Nano SIM 卡槽
- **灵活安装：** 桌面、DIN 导轨、壁挂、VESA
- **认证：** FCC、CE、RoHS、UKCA

## 规格参数

| 产品名称 |  | reComputer Industrial J4012 | reComputer Industrial J4011 | reComputer Industrial J3011 | reComputer Industrial J3010 | reComputer Industrial J2012 | reComputer Industrial J2011 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVIDIA Jetson 模组 |  | Orin NX 16GB | Orin NX 8GB | Orin Nano 8GB | Orin Nano 4GB | Xavier NX 16GB | Xavier NX 8GB |
| SKU |  | 110110191 | 110110190 | 110110193 | 110110192 | 110110189 | 110110188 |
| 处理器系统 | AI 性能 | 100 TOPS | 70 TOPS | 40 TOPS | 20 TOPS | 21 TOPS |  |
|  | GPU | 1024 核 NVIDIA Ampere 架构 GPU，带 32 个 Tensor Core |  |  | 512 核 NVIDIA Ampere 架构 GPU，带 16 个 Tensor Core | 384 核 NVIDIA Volta™ GPU，带 48 个 Tensor Core |  |
|  | CPU | 8 核 Arm® Cortex®-A78AE v8.2 64 位 CPU 2MB L2 + 4MB L3 | 6 核 Arm® Cortex®-A78AE v8.2 64 位 CPU 1.5MB L2 + 4MB L3 |  |  | 6 核 NVIDIA Carmel ARM®v8.2 64 位 CPU，6MB L2 + 4MB L3 |  |
|  | 内存 | 16GB 128-bit LPDDR5 102.4GB/s | 8GB 128-bit LPDDR5 102.4GB/s | 8GB 128-bit LPDDR5 68 GB/s | 4GB 64-bit LPDDR5 34 GB/s | 16GB 128-bit LPDDR4x 59.7GB/s | 8GB 128-bit LPDDR4x 59.7GB/s |
|  | 视频编码 | 1*4K60 (H.265) \| 3*4K30 (H.265) \| 6*1080p60 (H.265) \| 12*1080p30 (H.265) |  | 由 1-2 个 CPU 核心支持 1080p30 |  | 2*4K60 \| 4*4K30 \| 10*1080p60 \| 22*1080p30 (H.265) 2*4K60 \| 4*4K30 \| 10*1080p60 \| 20*108p30 (H.264) |  |
|  | 视频解码 | 1×8K30 (H.265) \| 2×4K60 (H.265) \| 4×4K30 (H.265) \| 9×1080p60 (H.265) \| 18×1080p30 (H.265) |  | 1*4K60 (H.265) \| 2*4K30 (H.265) \| 5*1080p60 (H.265) \| 11*1080p30 (H.265) |  | 2*8K30 \| 6*4K60 \| 12*4K30 \| 22*1080p60 \| 44*1080p30 (H.265) 2*4K60 \| 6*4K30 \| 10*1080p60 \| 22*1080p30 (H.264) |  |
| 存储 | eMMC | - | - | - | - | 16GB eMMC 5.1 |  |
|  | 扩展 | M.2 Key M PCIe Gen4.0 SSD（包含 M.2 NVMe 2280 SSD 128G） |  |  |  |  |  |
| I/O | 网络 | 1* LAN1 RJ45 GbE PoE（PSE 802.3 af 15 W） 1* LAN2 RJ45 GbE (10/100/1000Mbps) |  |  |  |  |  |
|  | USB | 3* USB3.2 Gen1，1* USB2.0 Type C（设备模式），1* USB2.0 Type C 用于 Debug UART 和 RP2040 |  |  |  |  |  |
|  | DI/DO | 4*DI，4*DO，3*GND_DI，2*GND_DO，1*GND_ISO，1*CAN |  |  |  |  |  |
|  | COM | 1* DB9（RS232/RS422/RS485） |  |  |  |  |  |
|  | 显示 | 1*HDMI 2.0 Type A |  |  |  |  |  |
|  | SIM | 1* Nano SIM 卡槽 |  |  |  |  |  |
| 扩展 | Mini PCIe | Mini PCIe 用于 4G/LoRaWAN® （可选模组） |  |  |  |  |  |
|  | Wi-Fi | 支持贴片 Wi-Fi/Bluetooth（可选模组） |  |  |  |  |  |
|  | M.2 Key B | M.2 Key B 支持 4G/5G（可选模组） |  |  |  |  |  |
|  | 风扇 | 无风扇，被动散热片 1* 风扇连接器（5V PWM） |  |  |  |  |  |
|  | TPM | 1* TPM 2.0 接口（可选模组） |  |  |  |  |  |
|  | RTC | 1* RTC 座（含 CR1220），1* RTC 2 针 |  |  |  |  |  |
|  | 摄像头 | 2* CSI（2-lane 15pin） |  |  |  |  |  |
| 电源 | 电源输入 | DC 12V-24V 2 针端子 |  |  |  |  |  |
|  | 电源适配器 | 19V 电源适配器（不含电源线） |  |  |  |  |  |
| 机械结构 | 尺寸（宽 x 深 x 高） | 159mm×155mm×57mm |  |  |  |  |  |
|  | 重量 | 1.57kg |  |  |  |  |  |
|  | 安装方式 | 桌面、DIN 导轨、壁挂、VESA |  |  |  |  |  |
| 环境 | 工作温度 | -20 ~ 60°C，0.7m/s |  |  |  |  |  |
|  | 工作湿度 | 95% @ 40 °C（无冷凝） |  |  |  |  |  |
|  | 振动 | 3 Grms @ 5 ~ 500 Hz，随机，1 小时/轴 |  |  |  |  |  |
|  | 冲击 | 50G 峰值加速度（11 ms） |  |  |  |  |  |
| 操作系统 |  | 预装 Jetpack 5.1（及以上）（提供带有板级支持包的 Linux 操作系统） |  |  |  |  |  |
| 认证 |  | FCC、CE、RoHS、UKCA |  |  |  |  |  |
| 质保 |  | 2 年 |  |  |  |  |  |

## 硬件概览

### 完整系统

### 载板

## 刷写 JetPack

reComputer Industrial 预装了 JetPack 5.1.3 于 128GB SSD 上，并包含必要的驱动程序。这其中包括 CUDA、CUDNN 和 TensorRT 等 SDK 组件。不过，如果你想将 Jetpack 重新刷写到随附 SSD 或新的 SSD 上，可以按照以下步骤进行。

> 说明：如果你想在 reComputer Industrial 上使用 SSD，我们仅推荐你选择 Seeed 提供的 [128GB](https://www.seeedstudio.com/M-2-2280-SSD-128GB-p-5332.html)、[256GB](https://www.seeedstudio.com/NVMe-M-2-2280-SSD-256GB-p-5333.html) 和 [512GB](https://www.seeedstudio.com/NVMe-M-2-2280-SSD-512GB-p-5334.html) 版本。

### 前置准备

在开始使用 reComputer Industrial 之前，你需要准备以下硬件

- reComputer Industrial
- 随机附带的带电源线电源适配器（[US version](https://www.seeedstudio.com/AC-US-p-5122.html) 或 [EU version](https://www.seeedstudio.com/AC-EU-p-5121.html)）
- Ubuntu 主机电脑
- USB Type-C 数据传输线
- 外接显示器
- HDMI 线
- 键盘和鼠标

> 说明：我们建议你使用物理的 Ubuntu 主机设备，而不是虚拟机。
请参考下表来准备主机设备。

| JetPack 版本 | Ubuntu 版本（主机电脑） |  |  |  |
| --- | --- | --- | --- | --- |
|  | 18.04 | 20.04 | 22.04 | 24.04 |
| JetPack 5.x | ✅ | ✅ |  |  |
| JetPack 6.x |  | ✅ | ✅ |  |
| JetPack 7.2 |  | ✅ | ✅ | ✅ |

Note: 对于 JetPack 7.2，Ubuntu 24.04 仅支持用于烧录和目标端组件安装。如果你需要主机端开发组件，请使用 Ubuntu 20.04 或 22.04。

### 进入强制恢复模式

现在你需要让 reComputer Industrial 板进入恢复模式，以便对设备进行烧录。

1. 使用 USB Type-C 线连接 **USB2.0 DEVICE** 接口和你的电脑。
2. 使用一根针插入 **RECOVERY** 小孔按下恢复按键，并保持按住。
3. 将附带的 **2-Pin 端子电源连接器** 连接到板上的电源接口，并连接附带的电源适配器和电源线以开启开发板。
4. 松开恢复按键。

> 说明：请确保在按住 RECOVERY 按键的同时给设备上电，否则将无法进入恢复模式

在 Ubuntu 主机电脑上，打开一个终端窗口并输入命令 **lsusb**。如果返回的内容中根据你所使用的 Jetson SoM 出现以下任一输出，则说明开发板已进入强制恢复模式。

- 对于 Orin NX 16GB：**0955:7323 NVidia Corp**
- 对于 Orin NX 8GB：**0955:7423 NVidia Corp**
- 对于 Orin Nano 8GB：**0955:7523 NVidia Corp**
- 对于 Orin Nano 4GB：**0955:7623 NVidia Corp**

### 烧录到 Jetson

<!-- Code -->

## JetPack 5.1.1

这里我们提供 2 种不同的烧录方法。

1. 下载我们已经准备好的完整系统镜像，其中包含 NVIDIA JetPack、硬件外设驱动并烧录到设备
2. 下载官方 NVIDIA L4T，使用随附的硬件外设驱动并烧录到设备

> 说明：第一种方法下载大小约为 14GB，第二种方法下载大小约为 3GB。

## Method 1

- **步骤 1：** 将与你所使用开发板对应的系统镜像下载到 Ubuntu 电脑

  | 设备 | 镜像链接 1 | 镜像链接 2 | SHA256 |
| --- | --- | --- | --- |
| reComputer Industrial J4012 | Download | Download | F6623A277E538F309999107297405E1 378CF3791EA9FD19F91D263E3B4C88333 |
| reComputer Industrial J4011 | Download | Download | 414DFE16703D0A2EE972DF1C77FCE2E 8B44BC71726BB6EE4B1439C2D0F19A653 |
| reComputer Industrial J3011 | Download | Download | 347AB7247ED83286BDFAEF84B49B84C 5F5B871AEE68192339EDE4773149D8737 |
| reComputer Industrial J3010 | Download | Download | 860EC8EB3245CB91E7C5C321B26333B 59456A3418731FEF73AE0188DF655EE46 |
| reComputer Industrial J2012 | Download | Download | 821CF92AF1FE8A785689FAF4751615A A30E7F0770B4FA23327DFAF2C8B53FDD7 |
| reComputer Industrial J2011 | Download | Download | DAB8FC069E4C62434C77AE3A6BA13EE FB30003C9A14BFE82DE879B88ACDD85FA |

  * 来自 Download1 和 Download2 的镜像文件是相同的。你可以选择下载速度更快的链接。

> 说明：为了验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

上述镜像的源代码可以在[这里](https://github.com/Seeed-Studio/Linux_for_Tegra)找到

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 进入之前解压得到的目录，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在将开始把系统镜像烧录到开发板。如果烧录成功，你会看到如下输出

- **步骤 4：** 使用板载 HDMI 接口将开发板连接到显示器，并完成初始配置设置

之后，开发板会重启并准备就绪，可以开始使用了！

  

## Method 2

**下载并准备 NVIDIA L4T 和 rootfs**

```sh
wget https://developer.nvidia.com/downloads/embedded/l4t/r35_release_v3.1/release/jetson_linux_r35.3.1_aarch64.tbz2
wget https://developer.nvidia.com/downloads/embedded/l4t/r35_release_v3.1/release/tegra_linux_sample-root-filesystem_r35.3.1_aarch64.tbz2
tar xf jetson_linux_r35.3.1_aarch64.tbz2
sudo tar xpf tegra_linux_sample-root-filesystem_r35.3.1_aarch64.tbz2 -C Linux_for_Tegra/rootfs/
cd Linux_for_Tegra/
sudo ./apply_binaries.sh
sudo ./tools/l4t_flash_prerequisites.sh
```

**下载并准备驱动**

- **步骤 1：** 将与你所使用开发板对应的驱动文件下载到 Ubuntu 电脑

| Jetson 模组 | 下载链接 | JetPack 版本 | L4T 版本 |
| --- | --- | --- | --- |
| Jetson Orin NX 8GB/ 16GB, Orin Nano 8GB | 下载 | 5.1.1 | 35.3.1 |
|  |  |  |  |
| Jetson Orin Nano 4GB | 下载 |  |  |
| Jetson Xavier NX 8GB/ 16GB | 下载 |  |  |

- **步骤 2：** 将下载的外设驱动程序移动到与 **Linux_For_Tegra** 目录相同的文件夹中

- **步骤 3：** 解压下载的驱动程序 .zip 文件。这里我们另外安装用于解压 .zip 文件所需的 **unzip** 软件包

```sh
sudo apt install unzip
sudo unzip xxxx.zip # Replace xxxx with the driver file name
```

此时会询问是否替换文件。输入 A 并按 ENTER 键以替换必要的文件

- **步骤 4：** 进入 **Linux_for_Tegra** 目录并按如下方式执行烧录命令

```sh
cd Linux_for_Tegra

# For Orin NX and Orin Nano
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_nvme.xml -S 80GiB  -p "-c bootloader/t186ref/cfg/flash_t234_qspi.xml --no-systemimg" --network usb0 recomputer-orin-industrial external

# For Xavier NX
sudo ADDITIONAL_DTB_OVERLAY_OPT="BootOrderNvme.dtbo" ./tools/kernel_flash/l4t_initrd_flash.sh --external-device nvme0n1p1 -c tools/kernel_flash/flash_l4t_nvme.xml -S 80GiB  -p "-c bootloader/t186ref/cfg/flash_l4t_t194_qspi_p3668.xml --no-systemimg" --network usb0  recomputer-xavier-nx-industrial external
```

现在将开始向板卡烧录系统镜像。如果烧录成功，你会看到如下输出

- **步骤 5：** 使用板载 HDMI 接口将板卡连接到显示器，并完成初始配置设置

之后，板卡会重启，你将看到如下界面

- **步骤 6：** 在设备中打开一个终端窗口，执行以下命令，设备将重启并准备就绪！

```sh
systemctl disable nvgetty.service
sudo depmod -a
sudo reboot
```

此外，如果你想安装 CUDA、cuDNN、TensorRT 等 SDK 组件，请执行以下命令

```sh
sudo apt update
sudo apt install nvidia-jetpack -y
```

  

  

---

## JetPack 5.1.3

- **步骤 1：** 将与你所使用板卡对应的系统镜像下载到 Ubuntu 电脑上

| 设备 | 链接 | SHA256 |
| --- | --- | --- |
| reComputer Industrial J4012 | 下载 | 436017DA6FBA2EF910F5F6C5D80749FB53029EC5108A461101CA3A69C1F8CEC3 |
| reComputer Industrial J4011 | 下载 | 9c590665723aa8847898f976070ecc120b936474262b360459627342c4c0c6f1 |
| reComputer Industrial J3011 | 下载 | fe3fe9b275156ddd9cde2b4fcf628122bf4a66e1ff1184cf6769be81ba6e4942 |
| reComputer Industrial J3010 | 下载 | 75de6440ca1c04f08b4356fee0d8e4a4ba1cb858f9fabb5bbc0eebd3c387c81d |
| reComputer Industrial J2012 | 下载 | B54CF2545A8ED8BFE115C439B0B427112BD882F03292B9F5C03AB55746C707C1 |
| reComputer Industrial J2011 | 下载 | 11BDB47D06CA8409CFCEA109B8BACD9BB79A54A275D2664D6CF492BFEAD31131 |

> 说明：要验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

> 说明：上述镜像的源代码可以在[此处](https://github.com/Seeed-Studio/Linux_for_Tegra)找到。

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 进入之前解压得到的文件目录，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在将开始向板卡烧录系统镜像。如果烧录成功，你会看到如下输出

- **步骤 4：** 使用板载 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据你的需求完成 **System Configuration**。

## JetPack 6.0

- **步骤 1：** 将与你所使用板卡对应的系统镜像下载到 Ubuntu 电脑上

| 设备 | 链接 | SHA256 |
| --- | --- | --- |
| reComputer Industrial J4012 | 下载 | 6c1e5abbdd60f771cd5c1a6e82f4ce7dfd0448018af94926d0240b853badbaf0 |
| reComputer Industrial J4011 | 下载 | 79c16c25602ebefa239402c23d0dcdae5ddc3eb23fdadb90654fbc34a1aa44dd |
| reComputer Industrial J3011 | 下载 | 7221185ba7f499d837b046e6f8b73c1c9f4e28cc76eb2068719370e00dcd3f42 |
| reComputer Industrial J3010 | 下载 | 7b997786317b518f9762e0828a0ac411ef984bd9927a9eeb5f8a900b185627ba |

> 说明：要验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

> 说明：上述镜像的源代码可以在[此处](https://github.com/Seeed-Studio/Linux_for_Tegra)找到。

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 导航到之前解压得到的文件，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在将开始把系统镜像烧录到板卡上。如果烧录成功，你会看到如下输出

- **步骤 4：** 使用板载的 HDMI 接口将板卡连接到显示器，并完成初始配置设置

之后，板卡会重启并准备就绪，可以开始使用！

## JetPack 6.1

- **步骤 1：** 将与你所使用板卡对应的系统镜像下载到 Ubuntu 电脑上

| 设备 | 链接 | SHA256 |
| --- | --- | --- |
| reComputer Industrial J4012 | Download | 6A2B3A71EE77E7000034351020FBF9A5260F944FB30B5DE672BF7897DEE87B5A |
| reComputer Industrial J4011 | Download | EC94A1F9E10D07CE2C78D8C1B742575A84DA543CCD95564D8E0BEC823C0CA514 |
| reComputer Industrial J3011 | Download | 547E541E40A133A2CDEB3FAC399850ABC108325BBF109771420DDBCAF19E5E29 |
| reComputer Industrial J3010 | Download | B7F400C225423C8BC4C00A5915C3C634D2D7B15145FE0735479E6AD7613D07E5 |

> 说明：为了验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上打开终端，运行命令 `sha256sum ` 获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

> 说明：上述镜像的源代码可以在[这里](https://github.com/Seeed-Studio/Linux_for_Tegra)找到。

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 导航到之前解压得到的文件，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在将开始把系统镜像烧录到板卡上。如果烧录成功，你会看到如下输出

- **步骤 4：** 使用板载的 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据你的需求完成 **System Configuration**。

## JetPack 6.2

> 说明：如果你使用的是 **Orin NX 16GB/8GB** 模块，**请不要启用 MAXN SUPER 模式**。
J4011/J4012 的散热能力不足以支持该模式，强行启用可能会对模块造成永久性损坏。

- **步骤 1：** 将与你所使用板卡对应的系统镜像下载到 Ubuntu 电脑上

| 设备 | 链接 | SHA256 |
| --- | --- | --- |
| reComputer Industrial J4012 | Download | adf524fa3c77f32da9a12bb875ec4b24 8da9dad4e4cce9c51641e1cabca4ab88 |
| reComputer Industrial J4011 | Download | 5a2fbb379bf4b62b82fa67cfba1d804b d78feafa7d854c18bcc9fcb05719f633 |
| reComputer Industrial J3011 | Download | 38c8a5cbf2df922725824503e76605d4 43111e7ffec1db9eb3de4fccc7d54c21 |
| reComputer Industrial J3010 | Download | 2bd6ebb246f5b967a64b0fb10a4e85ac 4de9e40951d1fdde9fc69025525d8d5a |

> 说明：为了验证下载固件的完整性，你可以对比 SHA256 哈希值。
在 Ubuntu 主机上打开终端，运行命令 `sha256sum ` 获取下载文件的 SHA256 哈希值。如果得到的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明你下载的固件是完整且未损坏的。

> 说明：上述镜像的源代码可以在[这里](https://github.com/Seeed-Studio/Linux_for_Tegra)找到。

> 说明：请注意，由于启用 `super mode` 后功耗和发热量增加，[reComputer Industrial J4011](https://www.seeedstudio.com/reComputer-Industrial-J4011-p-5681.html) 和 [reComputer Industrial J4012](https://www.seeedstudio.com/reComputer-Industrial-J4012-p-5684.html) 在 JetPack 6.2 下无法在最高模式下稳定运行。请不要在这些设备上启用 MAXN SUPER 模式。

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 导航到之前解压得到的文件，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在将开始把系统镜像烧录到板卡上。如果烧录成功，你会看到如下输出

- **步骤 4：** 使用板载的 HDMI 接口将板卡连接到显示器，并完成初始配置设置

> 说明：请根据你的需求完成 **System Configuration**。

- **步骤 4：** 使用板载的 HDMI 接口将 J401 连接到显示器，并完成初始配置设置：

> 说明：请根据你的需求完成 **System Configuration**。

## JetPack 7.2

- **步骤 1：** 将与你所使用板卡对应的系统镜像下载到 Ubuntu 电脑上

| 设备 | 链接 | SHA256 |
| --- | --- | --- |
| reComputer Industrial J4012 | Download | 51035f2fee6a383a973250f1efcc2ea7 7c083dc4f3e7661541c5fdc579bc9f9d |
| reComputer Industrial J4011 | Download | dd03129ba599101972eb2ea75eaa2e5e 3b203d04130dbf6aaf4683461587945f |
| reComputer Industrial J3011 | Download | 2bacc1a2577819630702901f2200e2e38 a905eb292a71e63532b5056a9e73f87 |
| reComputer Industrial J3010 | Download | b0a1466b3b0c7582a9d398109f53e507 92a6526fc51b5b1b9ddb1c04bdb52692 |

> 说明：为了验证下载的固件完整性，您可以比较 SHA256 哈希值。
在 Ubuntu 主机上，打开终端并运行命令 `sha256sum ` 以获取下载文件的 SHA256 哈希值。如果生成的哈希值与 wiki 中提供的 SHA256 哈希值一致，则说明您下载的固件是完整且未被篡改的。

> 说明：上述镜像的源代码可以在[这里](https://github.com/Seeed-Studio/Linux_for_Tegra)找到。

- **步骤 2：** 解压生成的文件

```sh
sudo tar -xvf <file_name>.tar.gz
```

- **步骤 3：** 进入之前解压得到的文件目录，并按如下方式执行烧录命令

```sh
cd mfi_xxxx
sudo ./tools/kernel_flash/l4t_initrd_flash.sh --flash-only --massflash 1 --network usb0 --showlogs
```

现在系统镜像将开始烧录到板卡上。如果烧录成功，您会看到如下输出

- **步骤 4：** 使用板载 HDMI 接口将板卡连接到显示器，并完成初始配置设置

> 说明：请根据您的需求完成 **System Configuration**。

<!-- Code END -->

## 硬件与接口使用

若想进一步了解如何使用 reComputer Industrial 板上的所有硬件和接口，我们建议您参考我们准备的相关 wiki 文档。

- [reComputer Industrial J20 硬件与接口使用](https://wiki.seeedstudio.com/cn/reComputer_Industrial_J20_Hardware_Interfaces_Usage)
- [reComputer Industrial J40、J30 硬件与接口使用](https://wiki.seeedstudio.com/cn/reComputer_Industrial_J40_J30_Hardware_Interfaces_Usage)

## 资源

- [reComputer Industrial 规格书](https://files.seeedstudio.com/products/NVIDIA/reComputer-Industrial-datasheet.pdf)
- [reComputer Industrial 参考指南](https://files.seeedstudio.com/products/NVIDIA/reComputer-Industrial-Reference-Guide.pdf)
- [NVIDIA Jetson 设备与载板对比](https://files.seeedstudio.com/products/NVIDIA/NVIDIA-Jetson-Devices-and-carrier-boards-comparision.pdf)
- [reComputer Industrial 3D 文件](https://files.seeedstudio.com/products/NVIDIA/Industrial/reComputer-Industrial.stp)
- [Seeed Jetson 产品系列目录](https://files.seeedstudio.com/wiki/Seeed_Jetson/Seeed-NVIDIA_Jetson_Catalog_V1.4.pdf)
- [Seeed Studio Edge AI 成功案例](https://www.seeedstudio.com/blog/wp-content/uploads/2023/07/Seeed_NVIDIA_Jetson_Success_Cases_and_Examples.pdf)
- [Seeed Jetson 产品系列对比](https://www.seeedstudio.com/blog/nvidia-jetson-comparison-nano-tx2-nx-xavier-nx-agx-orin/)
- [Seeed Jetson 设备一页概览](https://files.seeedstudio.com/wiki/Seeed_Jetson/Seeed-Jetson-one-pager.pdf)

## 技术支持与产品讨论

感谢您选择我们的产品！我们将为您提供多种支持，以确保您在使用我们产品的过程中尽可能顺利。我们提供多种沟通渠道，以满足不同的偏好和需求。
