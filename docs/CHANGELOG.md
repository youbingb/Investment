# CHANGELOG

每行记录一次有意义的改动。文档微调（typo、格式）不入此表。

## 2026-05-26

- 初始化项目骨架：`pyproject.toml` + `requirements.txt` + `.env.example` + `.gitignore`
- 建立 `src/investment/` 子包目录（data / indicators / signals / notifier / runner）
- 建立 `config/symbols.yaml`（默认 BTC-USDT、ETH-USDT @ 1H+4H）与 `config/signals.yaml` 占位
- 建立 `docs/` 8 份文档（PROGRESS / STAGES / ARCHITECTURE / AGENT_HANDOFF / EXTERNAL_APIS / PINE_SCRIPT_MAPPING / CHANGELOG）
- 修复 `.gitignore` 把 `data/cache/.gitkeep` 也屏蔽掉的小问题
