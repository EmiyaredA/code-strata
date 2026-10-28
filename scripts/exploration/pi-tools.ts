// Loaded explicitly by the Pi adapter; no target-project extension is installed.
export default function (pi: any) {
  const tools = JSON.parse(process.env.CODE_STRATA_TOOL_DEFINITIONS || '[]');
  for (const tool of tools) {
    pi.registerTool({
      name: tool.name, label: tool.name, description: tool.description,
      annotations: tool.annotations,
      parameters: tool.inputSchema,
      async execute(_id: string, args: unknown, signal: AbortSignal) {
        const response = await fetch(`${process.env.CODE_STRATA_TOOL_URL}/api/explore/tools`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Code-Strata-Run': process.env.CODE_STRATA_TOOL_TOKEN! },
          body: JSON.stringify({ runId: process.env.CODE_STRATA_RUN_ID, name: tool.name, arguments: args }), signal,
        });
        const value = await response.json();
        return { content: [{ type: 'text', text: JSON.stringify(value) }], details: {}, isError: !response.ok };
      },
    });
  }
}
