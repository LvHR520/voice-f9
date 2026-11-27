# 演示物料

`demo.gif` 是 README 首屏用的演示动图，**没有它按项目规则 8 不算发布完成**。

## 怎么产出

录制脚本在工作区的 `marketing/record-demo.ps1`（不进本仓库），不需要手写 ffmpeg 命令：

```powershell
# 只录目标窗口那块（推荐）：x,y,宽,高
powershell -ExecutionPolicy Bypass -File ..\marketing\record-demo.ps1 -Seconds 12 -Crop "200,150,1000,600"
```

**不要录整个桌面**——桌面上的文件名可能含真实姓名、学号（规则 7）。

## 录完放这里

```powershell
Copy-Item ..\marketing\out\demo-*.gif .\docs\demo.gif
```

然后跑闸门确认：

```powershell
pwsh ..\_factory\gate.ps1 -RepoPath . -ForRelease
```

## 要求

- 900 px 宽，12 fps，控制在 3 MB 以内
- 前 3 秒就能看出「按住 F9 → 说话 → 文字出现」，别放铺垫