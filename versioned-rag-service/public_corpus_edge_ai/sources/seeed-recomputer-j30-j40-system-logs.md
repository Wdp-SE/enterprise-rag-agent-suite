本wiki将以[reComputer J4012](https://www.seeedstudio.com/reComputer-J4012-p-5586.html)为例，演示如何通过Jetson串口检索设备的启动日志。

## 前提条件

- reComputer J4012/ J4011/ J3010 或 J3011
- [USB转串口(TTL)模块](https://www.seeedstudio.com/CH340G-USB-to-Serial-TTL-Module-Adapter-p-2359.html)
- 安装了串口调试工具的计算机

> 说明：您可以根据个人喜好下载并安装串口调试工具。我们推荐使用[PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/latest.html)、[XShell](https://www.netsarang.com/en/xshell/)或[MobaXterm](https://mobaxterm.mobatek.net/)。
本教程使用MobaXterm。

## 硬件连接

1. 将J15接口的相应引脚连接到USB2TTL模块。
2. 将USB2TTL模块连接到安装了串口调试工具的计算机。

  

  

## 获取系统日志

**步骤1.** 获取计算机识别的USB2TTL模块的标识号。

> 说明：如果您的计算机运行Windows，您可以在设备管理器中找到识别的标识号。

**步骤2.** 打开串口调试工具，配置串口号，并将波特率设置为`115200`。

  

**步骤3.** 给Jetson上电。如果一切正常工作，您应该能在串口调试工具窗口中看到系统启动日志。

## 技术支持与产品讨论

感谢您选择我们的产品！我们在这里为您提供不同的支持，以确保您使用我们产品的体验尽可能顺畅。我们提供多种沟通渠道，以满足不同的偏好和需求。
