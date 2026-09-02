# SunLogin Home Assistant

将贝锐向日葵智能插座接入 Home Assistant 的自定义集成。

当前重点支持云端扫码登录和 C4 系列插座，也保留了原有型号及本地 IP 直连能力。

## 功能

- 使用向日葵官方 App 扫码登录
- 从向日葵云端自动发现智能插座
- 查看插座开关状态
- 查看实时电压、电流和功率
- 控制插座开关
- 获取设备固件版本
- 支持本地 IP 直连模式
- 云端模式定期刷新访问令牌

## 支持型号

代码中包含以下型号路由：

- C1
- C1-2
- C1Pro
- C1Pro-BLE
- C2
- C2-BLE
- C4
- C4-V1
- C4-V2
- P1
- P1Pro
- P2
- P4
- P8
- P8Pro

其中 C4-V2（C4 4G）已经验证。其他型号沿用项目原有协议实现，具体能力可能取决于设备固件和向日葵云端接口，尚未逐型号实机验证。

## 安装

### HACS

在 HACS 中添加自定义仓库：

```text
https://github.com/Gaimoydev/sunlogin
```

仓库类型选择 `Integration`，安装后重启 Home Assistant。

也可以使用下面的快捷按钮：

[![通过 HACS 添加集成](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Gaimoydev&repository=sunlogin&category=integration)

### 手动安装

1. 下载本仓库。
2. 将 `custom_components/sunlogin` 文件夹复制到 Home Assistant 配置目录下的 `custom_components` 目录。
3. 重启 Home Assistant。

最终目录结构应类似：

```text
config/
└── custom_components/
    └── sunlogin/
        ├── __init__.py
        ├── config_flow.py
        ├── manifest.json
        └── ...
```

## 添加集成

1. 打开 **设置 -> 设备与服务**。
2. 点击 **添加集成**，搜索 `SunLogin`。
3. 选择 **扫码登录**。账号密码登录当前标记为不可用。
4. 使用向日葵官方 App 扫描页面中的二维码并确认授权。
5. 等待集成获取设备列表，然后选择需要接入的设备。

也可以使用快捷入口：

[![添加 SunLogin 集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=sunlogin)

### 本地 IP 模式

如果 Home Assistant 与插座处于同一局域网，可以选择 **使用 IP 添加设备**。该模式不依赖云端 token，但只能访问局域网内的设备。

## 登录与令牌

- 二维码登录是当前推荐方式。
- `access_token` 会过期，云端模式会定期使用 `refresh_token` 自动续签。
- 如果刷新令牌失效，集成会要求重新认证，此时再次使用二维码登录即可。

## 故障排查

### 添加成功但没有设备

- 确认扫码时使用的是绑定插座的向日葵账号。
- 在向日葵官方 App 中确认设备可正常显示。
- 删除集成后重新添加，让它重新获取设备列表。
- 查看 Home Assistant 日志中的 `sunlogin` 相关错误。

### 设备显示不可用

- 云端模式需要 Home Assistant 能访问向日葵 API。
- 检查 DNS、代理和服务器防火墙设置。
- 等待一次状态刷新；连续失败达到重试阈值后实体才会标记为不可用。

## 相关链接

- 原始项目仓库：[cx3Y/sunlogin](https://github.com/cx3Y/sunlogin)
- Home Assistant 自定义集成文档：https://www.home-assistant.io/integrations/
- 向日葵官网：https://sunlogin.oray.com/

## 许可

本项目遵循仓库中的 [LICENSE.txt](LICENSE.txt) 许可。
