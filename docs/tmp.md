src/coding_agent/cli.py (line 71)
看 _run_from_args()：命令行参数怎么变成 CreateAgentSessionOptions，然后怎么 create_agent_session()，最后怎么 run()。

src/coding_agent/factory.py (line 115)
这是“装配中心”：解析模型、加载 .xingclaw 配置、创建内置工具、加载 MCP/skills/extensions、拼 system prompt，最后返回 AgentSession。

src/coding_agent/agent_session.py (line 48)
这是应用层会话对象。重点看 prompt() (line 142)：它本质上是在做持久化、重试、上下文压缩，然后调用 self.agent.prompt(...)。

src/agent_core/agent.py (line 82)
这里才是你当前打开的文件。先只看三个点：AgentOptions 是配置，Agent.prompt() 把字符串变成 UserMessage，_start_run() 创建 AgentLoopConfig 并进入主循环。

src/agent_core/agent_loop.py (line 149)
这是核心。重点看 _run_loop()：
请求模型 -> 得到 AssistantMessage -> 检查 ToolCall -> 执行工具 -> 追加 ToolResultMessage -> 再请求模型。

src/coding_agent/builtin_tools.py (line 82)
等你理解“模型为什么会产生 ToolCall”之后，再来看工具怎么定义、怎么执行。

最后再看 src/ai/types.py (line 112) 和 src/ai/stream.py (line 35)。
这时你会知道 UserMessage、AssistantMessage、ToolCall、Context 是干嘛的，它们就不再是孤立变量了。