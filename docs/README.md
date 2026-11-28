# 演示物料

`demo.gif` 是 README 首屏用的演示动图，**没有它按项目规则 8 不算发布完成**。

## 为什么必须你本人录

这个演示要真的按 `F9` 说话、真的出文字。沙箱里的进程读不到键盘、也控制不了桌面
（规则 4），所以这一步只能由你操作。其余步骤都不用你管。

## 三步

1. 打开一个**空白记事本**，把光标点进编辑区
2. 运行（倒计时 5 秒，这段时间切到记事本）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File ..\marketing\record-demo.ps1 -AutoCrop -Gif .\docs\demo.gif
   ```

3. 倒计时结束后的 14 秒里：**按住 F9 说一句话，松开**

脚本会自动裁到当前窗口（不会录到桌面、DSH 面板、任务栏），并直接产出 `docs/demo.gif`。
如果窗口标题里出现姓名、作业、学号之类的词，脚本会直接拒绝录制。

## 录完

```powershell
pwsh ..\_factory\gate.ps1 -RepoPath . -ForRelease
git add docs/demo.gif && git commit -m "补首屏演示动图" && git push
```

## 要求

- 900 px 宽、12 fps、200 KB ~ 3.5 MB（脚本会自己检查）
- 前 3 秒就能看出「按 F9 → 说话 → 文字出现」，不要铺垫
- 录完自己看一眼：`docs/demo.gif` 里不该出现桌面图标或 DSH 对话内容