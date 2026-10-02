# 路由

## 相关 API

- [/api/routing/state](../../list/api/routing/state/)
- [/api/routing/route](../../list/api/routing/route/)
- [/api/routing/clear_route](../../list/api/routing/clear_route/)
- [/api/routing/set_route_points](../../list/api/routing/set_route_points/)
- [/api/routing/set_route](../../list/api/routing/set_route/)
- [/api/routing/change_route_points](../../list/api/routing/change_route_points/)
- [/api/routing/change_route](../../list/api/routing/change_route/)

## 描述

此 API 管理目的地和航点.请注意,航点不像停靠点,只是经过的点. 换句话说,Autoware 不支持有多个停靠点的路线,应用程序需要将其拆分并切换它们. 有两种方法可以设置路由.一个是使用 pose 的通用方法,另一个是依赖于 map 的方法.

## 状态

（图片说明：路由状态；未对图片像素执行 OCR）

| 州 | 描述 |
| --- | --- |
| 取消设置 | 路线未设置.正在等待路由请求. |
| 套装 | 路线已设置. |
| 已到达 | 车辆已到达目的地. |
| 更改 | 尝试更改路线. |

## 选项

路由集和更改 API 具有路由选项,允许应用程序选择有关路由规划的多种行为. 有关支持的选项和详细信息,请参阅以下部分.

### allow_goal_modification

**[v1.1.0]** 当目标无法达到时(例如,当给定目标上存在障碍物时),Autoware 会尝试寻找替代目标.从 API 设置路线时,应用程序可以选择是否允许 Autoware 在这种情况下调整目标姿势.当设置为 false 时,Autoware 可能会卡住,直到达到给定的目标.
