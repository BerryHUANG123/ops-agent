# OpsAgent — 自动化运维监控智能 Agent

> 无人值守运维监控智能体：数据感知、故障推理、自动处置、报表输出

## 核心能力

- **数据采集** — 硬件状态、服务进程、系统日志、网络指标
- **异常判别** — 智能阈值 + 趋势分析，识别宕机/卡顿/过载
- **故障溯源** — 自主分析根因，归类故障类型
- **自动处置** — 重启服务、清理日志、权限修正等合规修复
- **巡检报表** — 定时生成可视化报告与风险提示
- **记忆复盘** — 记录故障案例，优化后续处理策略

## 快速开始

```bash
cd ops-agent
pip install -r requirements.txt
python -m src.main
```

## 目录结构

```
ops-agent/
├── docs/              # 项目文档
├── src/
│   ├── collectors/    # 数据采集模块
│   ├── detectors/     # 异常判别模块
│   ├── analyzers/     # 故障分析模块
│   ├── remediators/   # 自动处置模块
│   ├── reporters/     # 巡检报表模块
│   ├── memory/        # 记忆复盘模块
│   └── main.py        # 主入口
├── tests/             # 测试用例
├── config/            # 配置文件
└── scripts/           # 部署脚本
```

## 技术栈

- Python 3.10+
- psutil (系统指标)
- SQLite (状态/记忆存储)
- Jinja2 (报表模板)
- systemd (服务管理)
