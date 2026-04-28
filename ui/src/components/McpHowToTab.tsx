import { useCallback, useState } from 'react';

type ClientId =
  | 'claude-code'
  | 'claude-desktop'
  | 'cursor'
  | 'continue'
  | 'cline'
  | 'windsurf'
  | 'goose'
  | 'inspector'
  | 'generic';

const CLIENTS: { id: ClientId; label: string; tagline: string }[] = [
  { id: 'claude-code',    label: 'Claude Code',     tagline: 'CLI / IDE — auto-loads .mcp.json' },
  { id: 'claude-desktop', label: 'Claude Desktop',  tagline: 'macOS / Windows desktop app' },
  { id: 'cursor',         label: 'Cursor',          tagline: 'Cursor IDE — Settings → MCP' },
  { id: 'continue',       label: 'Continue',        tagline: 'VS Code / JetBrains extension' },
  { id: 'cline',          label: 'Cline',           tagline: 'VS Code extension (formerly Claude Dev)' },
  { id: 'windsurf',       label: 'Windsurf',        tagline: 'Codeium IDE' },
  { id: 'goose',          label: 'Goose',           tagline: 'Block / Square open-source agent' },
  { id: 'inspector',      label: 'MCP Inspector',   tagline: 'debug tool — see raw JSON-RPC' },
  { id: 'generic',        label: 'Generic / Other', tagline: 'any MCP-compatible client' },
];

const TOOLS = [
  { name: 'get_health',          purpose: 'Backend health (admin, uptime, capture stats, log dir)' },
  { name: 'list_processes',      purpose: 'Snapshot of running OS processes' },
  { name: 'list_sessions',       purpose: 'All tracker sessions' },
  { name: 'get_session',         purpose: 'One session by id' },
  { name: 'start_session',       purpose: 'Start tracking by pid or exe_path' },
  { name: 'stop_session',        purpose: 'Stop a session' },
  { name: 'query_events',        purpose: 'Filter + paginate events (cursor-based)' },
  { name: 'search_events',       purpose: 'Substring search across path / target / operation / details' },
  { name: 'tail_events',         purpose: 'Poll-based live tail (max_wait_seconds)' },
  { name: 'export_session',      purpose: 'Streaming CSV / JSONL → ~/Downloads' },
  { name: 'get_capture_stats',   purpose: 'Per-session ETW stats' },
  { name: 'emit_event',          purpose: 'Inject annotation event (gated by MCP_TRACKER_ALLOW_EMIT=1)' },
  { name: 'summarize_session',   purpose: 'Client-side rollup: kind histogram, top paths / pids, time bounds' },
  { name: 'get_metrics',         purpose: 'Raw Prometheus metrics' },
];

const RESOURCES = [
  'tracker://health',
  'tracker://sessions',
  'tracker://sessions/{session_id}',
  'tracker://sessions/{session_id}/events?limit=200',
  'tracker://sessions/{session_id}/summary',
  'tracker://processes',
];

const PROMPTS = [
  { name: 'analyze_session(session_id)',                    purpose: 'Forensic classification of one session' },
  { name: 'find_files_modified(session_id, path_pattern?)', purpose: 'Write / delete / rename grouped by directory' },
  { name: 'compare_sessions(session_a, session_b)',         purpose: 'Diff kinds + paths + parents between two sessions' },
  { name: 'start_and_watch(exe_path, duration_seconds=60)', purpose: 'Start → tail → summarize → stop in one prompt' },
];

const ENV_VARS = [
  { name: 'MCP_TRACKER_URL',          def: 'http://127.0.0.1:8000', purpose: 'Backend URL' },
  { name: 'MCP_TRACKER_TIMEOUT',      def: '10.0',                  purpose: 'HTTP timeout (seconds)' },
  { name: 'MCP_TRACKER_DOWNLOAD_DIR', def: '~/Downloads',           purpose: 'Where export_session writes' },
  { name: 'MCP_TRACKER_ALLOW_EMIT',   def: '0',                     purpose: 'Set to 1 to enable emit_event' },
  { name: 'MCP_TRACKER_LOG_LEVEL',    def: 'INFO',                  purpose: 'Logged to stderr only' },
];

function CodeBlock({ children, language = 'json' }: { children: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = useCallback(() => {
    navigator.clipboard.writeText(children).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => undefined,
    );
  }, [children]);
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950 px-4 py-3 text-xs leading-relaxed text-slate-200">
        <code data-lang={language}>{children}</code>
      </pre>
      <button
        type="button"
        onClick={onCopy}
        className="absolute right-2 top-2 rounded-md border border-slate-700 bg-slate-900/80 px-2 py-1 text-[10px] text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-cyan-300">{title}</h3>
      {children}
    </section>
  );
}

const STDIO_CONFIG_JSON = `{
  "mcpServers": {
    "activity-tracker": {
      "command": "python",
      "args": ["-m", "mcp_tracker"],
      "env": { "MCP_TRACKER_URL": "http://127.0.0.1:8000" }
    }
  }
}`;

const STDIO_CONFIG_BUNDLED_PY = `{
  "mcpServers": {
    "activity-tracker": {
      "command": "C:\\\\path\\\\to\\\\release\\\\python\\\\python.exe",
      "args": ["-m", "mcp_tracker"],
      "env": { "MCP_TRACKER_URL": "http://127.0.0.1:8000" }
    }
  }
}`;

function ClientPanel({ id }: { id: ClientId }) {
  switch (id) {
    case 'claude-code':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Claude Code auto-loads <code className="rounded bg-slate-800 px-1">.mcp.json</code> from the project root.
            The release zip already ships this file at the top level — open the release folder in Claude Code, then
            type <code className="rounded bg-slate-800 px-1">/mcp</code> to list the 14 activity-tracker tools.
          </p>
          <p className="text-xs text-slate-400">
            If you cloned the repo instead, the same <code className="rounded bg-slate-800 px-1">.mcp.json</code> sits at the repo root.
          </p>
          <CodeBlock>{STDIO_CONFIG_JSON}</CodeBlock>
          <p className="text-xs text-slate-400">
            Or via CLI: <code className="rounded bg-slate-800 px-1">claude mcp add activity-tracker -- python -m mcp_tracker</code>
          </p>
        </div>
      );
    case 'claude-desktop':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Edit <code className="rounded bg-slate-800 px-1">%APPDATA%\Claude\claude_desktop_config.json</code> (Windows)
            or <code className="rounded bg-slate-800 px-1">~/Library/Application Support/Claude/claude_desktop_config.json</code> (macOS):
          </p>
          <CodeBlock>{STDIO_CONFIG_JSON}</CodeBlock>
          <p className="text-xs text-slate-400">
            Restart Claude Desktop. The MCP indicator appears in the chat composer when the server is connected.
          </p>
          <p className="text-xs text-slate-400">
            Want to use the bundled Python from the release zip (so you don&apos;t have to install Python)? Use the
            absolute path:
          </p>
          <CodeBlock>{STDIO_CONFIG_BUNDLED_PY}</CodeBlock>
        </div>
      );
    case 'cursor':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Open <strong>Settings → Cursor Settings → MCP</strong> and click <strong>Add new MCP server</strong>.
          </p>
          <ul className="ml-4 list-disc text-sm text-slate-300">
            <li><strong>Type:</strong> stdio</li>
            <li><strong>Command:</strong> <code className="rounded bg-slate-800 px-1">python</code></li>
            <li><strong>Args:</strong> <code className="rounded bg-slate-800 px-1">-m mcp_tracker</code></li>
            <li><strong>Env:</strong> <code className="rounded bg-slate-800 px-1">MCP_TRACKER_URL=http://127.0.0.1:8000</code></li>
          </ul>
          <p className="text-xs text-slate-400">Or paste the JSON form directly (Cursor accepts the same shape):</p>
          <CodeBlock>{STDIO_CONFIG_JSON}</CodeBlock>
        </div>
      );
    case 'continue':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Edit <code className="rounded bg-slate-800 px-1">~/.continue/config.json</code> and add
            an <code className="rounded bg-slate-800 px-1">mcpServers</code> block:
          </p>
          <CodeBlock>{`{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "python",
          "args": ["-m", "mcp_tracker"]
        },
        "env": { "MCP_TRACKER_URL": "http://127.0.0.1:8000" }
      }
    ]
  }
}`}</CodeBlock>
          <p className="text-xs text-slate-400">
            Reload the extension. The tools appear under @-mention.
          </p>
        </div>
      );
    case 'cline':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Open the Cline panel in VS Code, click the <strong>MCP Servers</strong> icon at the top, then
            <strong> Configure MCP Servers</strong>. The settings file uses the standard shape:
          </p>
          <CodeBlock>{STDIO_CONFIG_JSON}</CodeBlock>
          <p className="text-xs text-slate-400">
            Cline auto-discovers the tools after the file is saved.
          </p>
        </div>
      );
    case 'windsurf':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Open Windsurf settings and search for <strong>MCP</strong>. Use the same JSON shape:
          </p>
          <CodeBlock>{STDIO_CONFIG_JSON}</CodeBlock>
        </div>
      );
    case 'goose':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Run the configurator and add a custom <strong>stdio</strong> extension:
          </p>
          <CodeBlock language="bash">{`goose configure
# pick: Add Extension → Command-Line Extension
# name:    activity-tracker
# command: python -m mcp_tracker
# env:     MCP_TRACKER_URL=http://127.0.0.1:8000`}</CodeBlock>
        </div>
      );
    case 'inspector':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            The MCP Inspector shows the raw JSON-RPC traffic — useful when a tool call fails silently in another client.
          </p>
          <CodeBlock language="bash">{`npx @modelcontextprotocol/inspector python -m mcp_tracker`}</CodeBlock>
          <p className="text-xs text-slate-400">
            Opens a browser UI where you can call each tool by hand.
          </p>
        </div>
      );
    case 'generic':
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Any client speaking the Model Context Protocol over stdio works. Configure with:
          </p>
          <ul className="ml-4 list-disc text-sm text-slate-300">
            <li><strong>Transport:</strong> stdio</li>
            <li><strong>Command:</strong> <code className="rounded bg-slate-800 px-1">python</code></li>
            <li><strong>Args:</strong> <code className="rounded bg-slate-800 px-1">["-m", "mcp_tracker"]</code></li>
            <li><strong>Env:</strong> <code className="rounded bg-slate-800 px-1">MCP_TRACKER_URL=http://127.0.0.1:8000</code></li>
          </ul>
          <p className="text-xs text-slate-400">
            Logs go to <strong>stderr only</strong> (stdout is reserved for JSON-RPC framing).
          </p>
        </div>
      );
  }
}

export function McpHowToTab() {
  const [active, setActive] = useState<ClientId>('claude-code');

  return (
    <main className="mx-auto max-w-5xl space-y-6 p-3 sm:p-4 md:p-6">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <h2 className="text-xl font-semibold text-slate-100">Use Activity Tracker from any AI client</h2>
        <p className="mt-2 text-sm text-slate-300">
          Activity Tracker ships an{' '}
          <strong>MCP (Model Context Protocol)</strong> server — a small stdio bridge that exposes the
          backend&apos;s 14 tools, 6 resources, and 4 prompts to any MCP-compatible client. Pick yours below.
        </p>
        <p className="mt-2 text-xs text-slate-400">
          Backend (this app) must be running and reachable on <code className="rounded bg-slate-800 px-1">http://127.0.0.1:8000</code> before
          the client can call any tool.
        </p>
      </div>

      <Section title="Pick your client">
        <div className="flex flex-wrap gap-2">
          {CLIENTS.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setActive(c.id)}
              className={`rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                active === c.id
                  ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
                  : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200'
              }`}
            >
              <div className="font-semibold">{c.label}</div>
              <div className="mt-0.5 text-[10px] text-slate-400">{c.tagline}</div>
            </button>
          ))}
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
          <ClientPanel id={active} />
        </div>
      </Section>

      <Section title="Tools (14)">
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">#</th>
                <th className="px-4 py-2 text-left">Name</th>
                <th className="px-4 py-2 text-left">Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {TOOLS.map((t, i) => (
                <tr key={t.name} className="bg-slate-950/40">
                  <td className="px-4 py-2 text-slate-500">{i + 1}</td>
                  <td className="px-4 py-2 font-mono text-cyan-200">{t.name}</td>
                  <td className="px-4 py-2 text-slate-300">{t.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Resources (6)">
        <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
          <ul className="space-y-1 font-mono text-xs text-slate-300">
            {RESOURCES.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      </Section>

      <Section title="Prompts (4)">
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">Name</th>
                <th className="px-4 py-2 text-left">Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {PROMPTS.map((p) => (
                <tr key={p.name} className="bg-slate-950/40">
                  <td className="px-4 py-2 font-mono text-cyan-200">{p.name}</td>
                  <td className="px-4 py-2 text-slate-300">{p.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Environment variables">
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">Variable</th>
                <th className="px-4 py-2 text-left">Default</th>
                <th className="px-4 py-2 text-left">Purpose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {ENV_VARS.map((v) => (
                <tr key={v.name} className="bg-slate-950/40">
                  <td className="px-4 py-2 font-mono text-cyan-200">{v.name}</td>
                  <td className="px-4 py-2 font-mono text-slate-400">{v.def}</td>
                  <td className="px-4 py-2 text-slate-300">{v.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Quick smoke test">
        <p className="text-sm text-slate-300">
          Want to confirm the server runs before wiring it into your client? Open a terminal in the release folder and run:
        </p>
        <CodeBlock language="bash">{`# Make sure the backend is running, then:
python -m mcp_tracker
# the process waits for JSON-RPC on stdin; press Ctrl+C to exit.`}</CodeBlock>
        <p className="text-xs text-slate-400">
          For interactive poking, use the MCP Inspector (see &quot;MCP Inspector&quot; in the client list above).
        </p>
      </Section>

      <Section title="Common issues">
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-2 text-left">Symptom</th>
                <th className="px-4 py-2 text-left">Fix</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              <tr><td className="px-4 py-2 text-slate-300"><code>Tracker is not reachable</code></td><td className="px-4 py-2 text-slate-300">Start the backend (this app), then call the tool again.</td></tr>
              <tr><td className="px-4 py-2 text-slate-300"><code>No session with id …</code></td><td className="px-4 py-2 text-slate-300">Call <code>list_sessions</code> first to get a valid id.</td></tr>
              <tr><td className="px-4 py-2 text-slate-300">Tool calls fail silently</td><td className="px-4 py-2 text-slate-300">Check the client&apos;s MCP stderr panel — Python errors land there.</td></tr>
              <tr><td className="px-4 py-2 text-slate-300"><code>command not found: python</code></td><td className="px-4 py-2 text-slate-300">Use the absolute path to the bundled <code>release\\python\\python.exe</code> (see Claude Desktop snippet).</td></tr>
              <tr><td className="px-4 py-2 text-slate-300">Wrong port</td><td className="px-4 py-2 text-slate-300">Update <code>MCP_TRACKER_URL</code> if you set <code>TRACKER_PORT</code>.</td></tr>
            </tbody>
          </table>
        </div>
      </Section>
    </main>
  );
}
