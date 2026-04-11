启动流程：
1. 从 `workplace/runtime/config/settings.json` 和环境变量加载配置。
2. 从 `workplace/runtime/` 加载引导 Markdown 文件。
3. 从 `workplace/runtime/skills/` 加载技能。
4. 从 JSONL 恢复会话历史。
5. 运行工具调用模型循环，直到生成最终的助手回复。
