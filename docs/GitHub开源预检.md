# GitHub 开源预检

检查日期：2026-10-13。用户已选择完整整合包并授权新建公共仓库和推送。仓库已创建并设为 Public：<https://github.com/fejxc/codex-kaogong-agent>。`main` 首发提交为 `5e5e5c23bc77fdba8cad5746ef4759b0b9e38aa9`。

## 公开对象

候选仓库名：`codex-kaogong-agent`。

仓库自有内容是 Codex 路由规则、暂定考点目录、考试元数据、幂等日报写入器、测试与文档。项目中另外包含两个上游 Skill：

- `.agents/skills/kaogong/`：KeWang0622 上游项目，MIT；原 `LICENSE` 保留。
- `.agents/skills/xingce-review-pro/`：liuyuexi1987 上游项目，GPL-3.0-only；原 `LICENSE`、`NOTICE` 和完整 Skill 包保留。

这两个 Skill 不是本项目原创。用户级朱批录没有复制进仓库；花生十三资料因缺少实际 LICENSE 文件没有复制。

## 公开前必须完成

1. **许可证映射已写入。** 项目自有文件使用 `LICENSE-MIT.txt`；两个上游 Skill 保留各自 LICENSE；范围见 `LICENSES.md`。GitHub 可能无法在仓库首页显示单一许可证，因为仓库包含多种许可证。[GitHub 许可说明](https://docs.github.com/en/enterprise-cloud@latest/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)
2. **个人数据排除项已核对。** `.gitignore` 排除 `data/profile.md`、题目材料、日报和 `data/复盘引擎/`；profile 未进入暂存区。扫描暂存文件未发现本机绝对路径、常见 GitHub Token 格式或个人邮箱。
3. **本机信息已脱敏。** 审查报告使用通用路径表述，暂存内容中没有本机绝对路径。
4. **已按用户选择捆绑完整整合包。** `kaogong` 与 `xingce-review-pro` 文件及其 MIT / GPL-3.0-only 许可分别保留；朱批录和花生十三未作为 Skill 包复制。
5. **GitHub 发布已完成。** 公共仓库 `fejxc/codex-kaogong-agent` 的 `main` 分支已推送；公开页面已核验显示首发提交、Skills 目录和项目文件。

## 当前清理结果

- 本地 Git 仓库的 `origin` 指向公开仓库；项目中没有个人学习事件或旧提交历史。
- `data/profile.md` 只是空白模板副本，并已被 `.gitignore` 排除。
- 验收夹具均为原创合成题；它们不作为真实学习记录或真题发布。
- 没有用户上传截图、题库或课程讲义。
