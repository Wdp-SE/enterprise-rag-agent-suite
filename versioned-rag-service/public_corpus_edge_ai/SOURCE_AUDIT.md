# 来源许可、固定快照与适用范围审计

## 语料范围

活动语料限定为 Seeed reComputer Industrial / Jetson 边缘 AI 设备的中文工程文档：硬件型号与接口、系统刷写、JetPack/L4T 基线、BSP、OTA、备份恢复、故障诊断及边缘 AI 部署。快照固定在 Seeed-Studio/wiki-documents 的 `docusaurus-version` 分支提交 `1eadc6584f962b6efdbdb3e49b2b4ce30c85be08`；本地原文、归一化文本和哈希均纳入版本控制，避免上游页面后续变化影响复现。

固定仓库快照日期：2026-10-03。页面自己的 `updatedAt` 另列，不等同于语料快照时间或设备软件版本。源仓库 commit 是唯一内容版本标识。

## 许可与归属

Seeed Studio Wiki 的[中文许可说明](https://wiki.seeedstudio.com/cn/License/)将产品文档和教程标为 CC BY-SA 4.0；文档中嵌入的演示软件和代码示例默认采用 MIT，第三方材料则各自适用其许可。当前纳入源是 Wiki Markdown 文档，按 Seeed Studio Wiki 与原始页面归属，并在原许可下分享。原文快照保留；索引副本只做格式归一化、移除站点导航与图片引用，不重写工程事实。

本次未复制页面引用的图片、数据手册 PDF、参考指南 PDF、原理图、二进制固件或 3D 文件；这些外部资源保留为来源链接，因未逐个确认对应文件许可而不进入语料正文。`link_only` 不是可检索证据。对文档代码块保留上游页面许可说明；如果某个代码块显式标注不同许可，需在未来更新时逐项复核。

## 纳入来源

| 来源 ID | 页面 | 页面更新日 | 内容类型 | 适用范围 | 文件 SHA-256 |
| --- | --- | --- | --- | --- | --- |
| `seeed-jetson-supported-devices` | [支持的设备](https://wiki.seeedstudio.com/cn/jetson_developtool_supported_devices/) | 2026-05-27 | support_matrix | 设备：*；基线：* | `3e11210d3d892ba6fbdf6abd500eaff2fe963176681edccee45c0d3450b9000a` |
| `seeed-jetson-flash-firmware` | [刷写固件](https://wiki.seeedstudio.com/cn/jetson_developtool_flash_firmware/) | 2026-05-27 | firmware | 设备：*；基线：* | `9869b1c119f39550c16cc7d68085a87026e70fdbb78aeb095791e4d410ca9c44` |
| `seeed-recomputer-industrial-getting-started` | [reComputer Industrial 入门指南](https://wiki.seeedstudio.com/cn/reComputer_Industrial_Getting_Started/) | 2026-06-27 | hardware_software_baseline | 设备：reComputer Industrial J4012、reComputer Industrial J4011、reComputer Industrial J3011、reComputer Industrial J3010、reComputer Industrial J2012、reComputer Industrial J2011；基线：* | `5bfffa73e8ae2f0f22c08515a0b32b1c900c10fb251b1d50678d5a78726b80fb` |
| `seeed-recomputer-industrial-j40-j30-interfaces` | [reComputer Industrial J40, J30 硬件和接口使用说明](https://wiki.seeedstudio.com/cn/reComputer_Industrial_J40_J30_Hardware_Interfaces_Usage/) | 2026-03-24 | hardware_interface | 设备：reComputer Industrial J4012、reComputer Industrial J4011、reComputer Industrial J3011、reComputer Industrial J3010；基线：JetPack 5.x、JetPack 6.x | `981839d0ee800a6c2a3cae2040cd771162a49c8328fbc816303692956fe3e83a` |
| `seeed-recomputer-industrial-j20-interfaces` | [reComputer Industrial J20 硬件和接口使用说明](https://wiki.seeedstudio.com/cn/reComputer_Industrial_J20_Hardware_Interfaces_Usage/) | 2026-01-07 | hardware_interface | 设备：reComputer Industrial J2012、reComputer Industrial J2011；基线：* | `9b4ce32373467e01e3a9495b37b8c2676293acd172df1d4d486843ce85991ea5` |
| `seeed-j4012-flash-jetpack` | [刷写 Jetpack](https://wiki.seeedstudio.com/cn/reComputer_J4012_Flash_Jetpack/) | 2026-09-22 | firmware | 设备：*；基线：* | `96cb3db1383476fe77adc29fba1305d2d2ad391c6a2af011b6db062a983d417f` |
| `seeed-jetpack-jetson-version-relations` | [JetPack与Jetson关系概述](https://wiki.seeedstudio.com/cn/overview_of_the_relationship_between_jetpack_and_jetson/) | 2025-09-15 | software_baseline | 设备：*；基线：* | `d47f88856a5633fd9060cf01450c38465f112c5ae4b239fc1df4817cd99ed88e` |
| `seeed-recomputer-j30-j40-system-logs` | [如何获取reComputer J30/J40的系统日志？](https://wiki.seeedstudio.com/cn/get_the_system_log_of_recomputer_j30_and_j40/) | 2025-10-11 | diagnostics | 设备：reComputer Industrial J4012、reComputer Industrial J4011、reComputer Industrial J3011、reComputer Industrial J3010；基线：* | `258454d92c615a357fed46d6689b5e08939a74f72ac7f4681edc0c915a562f89` |
| `seeed-recomputer-backup-restore` | [在 reComputer 上创建备份与恢复](https://wiki.seeedstudio.com/cn/create_backup_and_restore_on_recomputer/) | 2026-05-08 | backup_restore | 设备：reComputer Industrial J3011、reComputer Industrial J4011、reComputer Industrial J4012；基线：JetPack 5.1.3、JetPack 6.2 | `9a694c59ca375e25c2468cf50b308c4588b420cf761ba3503b77ce42ab7e848d` |
| `seeed-jetson-flashing-troubleshooting` | [常见刷机错误及解决方法](https://wiki.seeedstudio.com/cn/usb_timeout_during_flash/) | 2026-03-18 | diagnostics | 设备：*；基线：JetPack 5.x、JetPack 6.x | `ffa62c3263ea668dc4030f64bb85729fe31799b356e21da00f889373c6baea2a` |
| `seeed-recomputer-ota` | [在 reComputer 上部署 OTA](https://wiki.seeedstudio.com/cn/deploy_ota_on_recomputer/) | 2025-12-09 | ota_upgrade | 设备：reComputer Industrial J4012、reComputer Industrial J4011、reComputer Industrial J3011、reComputer Industrial J3010；基线：JetPack 5.1.3、JetPack 6.2 | `dd07a99ea2d8f68c7965e20db041f232ecfd2442a59e4edb51b0a4c615652934` |
| `seeed-jetson-bsp-build` | [如何为 Seeed 的 Jetson BSP 构建源代码项目](https://wiki.seeedstudio.com/cn/how_to_build_the_source_code_project_for_seeed_jetson_bsp/) | 2025-09-23 | bsp_build | 设备：*；基线：JetPack 5.x、JetPack 6.x | `cf67dd2d4e7ba63133c490dc921c80843bc761930c9431d4434a5b199ba0d6c8` |
| `seeed-recomputer-flash-jetpack-wsl2` | [使用 WSL2 刷写 JetPack](https://wiki.seeedstudio.com/cn/ai_robotics_flash_jetpack_with_wsl2/) | 2026-04-15 | firmware | 设备：*；基线：JetPack 4.x、JetPack 5.x、JetPack 6.x | `c234c4ba0a614c5407b8077b3272e60f0f416a161d0038a4e613c2a6024939fe` |
| `seeed-jetson-package-upgrade-guidance` | [为Jetson升级软件包](https://wiki.seeedstudio.com/cn/upgrade_software_packages_for_jetson/) | 2025-09-15 | software_update | 设备：*；基线：* | `2481aef58add512068b59267a8ac8dadb9c286d3a591de26f13ac9b3118f1ddf` |
| `seeed-industrial-vision-monitoring` | [工业场景下的工业视觉监控](https://wiki.seeedstudio.com/cn/industrial_vision_monitoring_on_industrial/) | 2026-07-14 | ai_deployment_validation | 设备：reComputer Industrial J4012；基线：JetPack 7.2 (L4T 39.2.0) | `2c495a409dc5288dde4b7ba1251cb3e33637cac9d959e51e64dd76a2de63c4ac` |
| `seeed-recomputer-jetson-deepseek-mlc` | [使用MLC在reComputer Jetson上部署DeepSeek](https://wiki.seeedstudio.com/cn/deploy_deepseek_on_jetson_with_mlc/) | 2025-10-11 | ai_deployment | 设备：reComputer Industrial J4012；基线：JetPack 5.1.1+ | `0ba51e42f921bb7f1bb79abf301b1f9ea39f71620d130a9d5112d5b79dc00673` |
| `seeed-recomputer-preempt-rt-jp621` | [在搭载 JetPack 6.2.1 的 Seeed reComputer Jetson 上烧录 PREEMPT_RT Linux 实时内核](https://wiki.seeedstudio.com/cn/flash_preempt_rt_kernel_on_recomputer_jetson_jetpack_6_2_1/) | 2026-07-02 | kernel_upgrade | 设备：reComputer Industrial J4012、reComputer Industrial J4011、reComputer Industrial J3011、reComputer Industrial J3010；基线：JetPack 6.2.1 (L4T 36.4.4) | `c1c0aae12520ade56952f1eb0e3d18f5baa40796040bc223996ab0823b103388` |
| `seeed-jetpack5-ssd-boot-troubleshooting` | [解决 JetPack5 无法从某些 SSD 启动的问题](https://wiki.seeedstudio.com/cn/issue_of_jetpack5_failing_to_boot_from_certain_ssd/) | 2025-09-17 | diagnostics | 设备：*；基线：JetPack 5.x | `ef14bb341a3077b7ea1dca96ad2547edad4d70eb93805b2e25161ba1ea9c9092` |

共纳入 18 份 Markdown 页面。`*` 表示来源对该维度的泛化说明或页面没有按型号细分；它只用于检索适用范围，不表示已验证的硬件兼容关系。兼容关系必须由 `supported_configurations` 中的精确配置和原始证据共同证明。没有来源明确支持的设备、模组 SKU、载板与软件组合，不得从多个列表做笛卡尔积推导。

归一化清单 `source_import_manifest.json` 逐页记录原始 SHA-256、归一化 SHA-256、页面标题、格式和被省略的图像引用数。归一化输出共省略 334 个图片引用；图片内文字没有 OCR，也没有作为已检索证据。版本 Tab 标签和 HTML/MDX 表格在清洗时转换为 Markdown 标题/表格，以保留其版本和列关系。

## 明确排除

- Seeed Wiki 中标注为“规划占位、并非已验证端到端迁移流程”的 JetPack 6 到 7 migration playbook：会误导设备升级结论，不进入索引。
- 页面引用的 Datasheet、Reference Guide、原理图、图片、固件包和 3D 文件：没有逐个确认再分发许可，只保留源页面链接，不复制内容。
- Autoware、DolphinScheduler、旧双语翻译语料和合成企业工单：不属于当前边缘 AI 设备业务，不能进入新 manifest、索引、工作台或 Render 部署包。
- reComputer Super 等不属于本次 Industrial 演示范围的专属页面：不作为活动资料；通用 Jetson 文档只有在服务于 Industrial 设备流程且不会声称产品支持时才纳入。

## 适用限制

这些是单一公开产品生态的技术文档快照，不等于任何公司的内部 CR、BOM、PLM、测试报告或交付数据。本语料能用于演示“按版本检索公开研发/交付资料，并基于证据整理设备变更影响候选”，不能据此声称完成真实企业变更审批、硬件实验验证或全型号兼容认证。
