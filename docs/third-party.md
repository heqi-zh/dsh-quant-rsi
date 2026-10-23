# 第三方依赖与参考来源

Git 仓库仅提交 DQR 自有代码、配置和文档。第三方源码、已安装依赖、原始基金数据、生成报告、模型会话和个人开发讨论均由 `.gitignore` 排除。

## 运行依赖

|项目|来源|当前用途与获取方式|
|---|---|---|
|DeepSeek Harness|[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)|DSH 会话、模型和插件底座。通过 `package.json` / `pnpm-lock.yaml` 安装 `@deepseek-ai/dsh`，版本 `0.2.1-rc.2`。|
|vn.py|[vnpy/vnpy](https://github.com/vnpy/vnpy/tree/c6e231caf32b7fc97e6459817fff66458cf7e7c4)|Alpha 数值函数与 ArrayManager。准备脚本按固定提交下载所需文件，验证哈希；ArrayManager 保留原类，仅提取最小导入。|
|OpenEvolve|[algorithmicsuperintelligence/openevolve](https://github.com/algorithmicsuperintelligence/openevolve/tree/515d1bcb7b36ac64bbe028f8d83b5d08315ca4b5)|旧评测入口使用程序数据库归档。准备脚本调整导入命名空间、禁用嵌入搜索。每日筛选与周报不执行演化搜索。|

固定提交、上游文件路径、原始和适配后 SHA-256 见 [third-party.json](../configs/third-party.json)。该文件只保存来源元数据。DQR 的少量提取与适配规则见 [prepare-third-party.py](../scripts/prepare-third-party.py)。准备时许可证与源码一同下载，输出到被 Git 忽略的 `runtime/dqr/vendor/` 子目录。现有文件哈希不匹配会停止，避免覆盖本地修改。

```sh
# 从固定上游链接下载；仅准备文件，不安装或运行参考项目。
python3 scripts/prepare-third-party.py

# 已有同级参考仓库时可完全离线准备，仍逐文件校验固定版本哈希。
python3 scripts/prepare-third-party.py --source-root ..
```

Python 数值库由 [pyproject.toml](../pyproject.toml) 和 [requirements.lock.txt](../requirements.lock.txt) 声明，各依赖适用其上游许可证。本项目未捆绑这些库的源码。

## 设计参考

以下仓库用于源码调研，运行 DQR 无需克隆或安装：

- [dsh-quant-workspace](https://github.com/AllenCX/dsh-quant-workspace)：DSH 与 Python 的工具桥接。
- [dsh-quant](https://github.com/pengpengyi92/dsh-quant)：量化工具组织参考。
- [RD-Agent](https://github.com/microsoft/RD-Agent)：早期闭环调研，当前流程未接入。
- [xalpha](https://github.com/refraction-ray/xalpha)：场外基金处理调研，当前未接入。
- [AKShare](https://github.com/akfamily/akshare)：数据接口调研，当前使用项目自有下载器访问公开基金目录与净值接口。

参考项目应存放在本项目之外；请勿把整个参考仓库或其 `.git` 目录复制进来。
