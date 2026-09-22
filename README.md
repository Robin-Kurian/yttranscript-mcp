![YT Music Manager](https://res.cloudinary.com/itsrobin/image/upload/v1790092965/youtube_transcript_pm6tru.png)

# YouTube Transcript

A local MCP server that fetches a YouTube transcript and returns a summary first, then the full caption text. You clone it, add optional Groq/OpenAI keys, then point an AI coding tool at `server.py`.

There is no hosted app. Keys stay on your machine.

It talks to any MCP host that can start a local process (stdio). That includes Cursor, Codex, Antigravity, Claude, VS Code Copilot, Gemini CLI, and Windsurf. Only the config file changes.

This is a sibling of [ytmusic-mcp](https://github.com/Robin-Kurian/ytmusic-mcp). Playlist tools stay there. Transcription lives here.

## What it can do

- **`transcribe_youtube_video`** returns a summary, then the full transcript, for a YouTube URL or video ID (watch, youtu.be, Shorts, music.youtube.com).

Once it is connected, prompts like these work:

- Transcribe https://www.youtube.com/watch?v=dQw4w9WgXcQ
- Transcribe and summarise https://youtu.be/MGboSWeEpLk
- Transcribe this Shorts URL in Hindi

## What you need

- Python 3.10 or newer
- An editor or CLI that can run MCP servers over stdio
- Optional: a Groq and/or OpenAI key for summaries, and for Whisper when a video has no captions

## Setup (once)

Do this in a terminal before you touch Cursor, Codex, or anything else.

### 1. Clone and install

```bash
cd yttranscript-mcp
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API keys (optional, but needed for summaries and Whisper)

Captions themselves do not need a Google OAuth client. The free YouTube caption path runs first.

```bash
cp .env.example .env
```

Put keys in `.env`:

```
GROQ_API_KEY=your-groq-key
OPENAI_API_KEY=your-openai-key
```

Do not commit `.env`. It is already in `.gitignore`.

## Connect it to an editor

Every client needs the same two things:

| | macOS / Linux | Windows |
| --- | --- | --- |
| **command** | `/absolute/path/to/yttranscript-mcp/.venv/bin/python` | `C:\absolute\path\to\yttranscript-mcp\.venv\Scripts\python.exe` |
| **args** | `["/absolute/path/to/yttranscript-mcp/server.py"]` | `["C:\\absolute\\path\\to\\yttranscript-mcp\\server.py"]` |

Use the venv Python, not the system `python`. The packages live in the venv. Relative paths often fail because the editor's working directory is not this repo.

`server.py` looks for `.env` next to `transcription.py`, so you do not need extra env vars in the MCP config if that file is already in place.

A copy of the Cursor-style JSON lives in `mcp.json.example`.

### Cursor

You can add it in the UI or with a file. Same result.

**UI**

1. Open **Cursor Settings**, then **MCP** (sometimes labeled **Tools & MCP**).
2. Add a new server.
3. Transport: stdio (a local command).
4. Paste the `command` and `args` from the table above.
5. Save, then reload MCP if Cursor does not pick it up on its own.

**File**

Project-only: `.cursor/mcp.json` in this repo.

Everywhere in Cursor: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "/absolute/path/to/yttranscript-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/yttranscript-mcp/server.py"]
    }
  }
}
```

You should see **YouTube Transcript** with `transcribe_youtube_video`. If the server shows an error, open Output in Cursor and pick **MCP Logs**.

**Restart after you change tools.** Cursor caches the tool list.

1. Fully quit Cursor (**Cursor → Quit Cursor**, or `Cmd+Q` on macOS). Closing the window is not enough.
2. Reopen this project.
3. Open **Cursor Settings → Tools & MCP** and confirm **YouTube Transcript** lists `transcribe_youtube_video`.
4. If the new tool is toggled off, turn it on.
5. Start a **new chat** and ask again. The current chat will still see the old tools.

### Codex (CLI, IDE extension, ChatGPT desktop)

Codex does not use `mcp.json` for this. It uses TOML, shared across the Codex CLI, the IDE extension, and the ChatGPT desktop app.

Fastest:

```bash
codex mcp add youtube-transcript -- /absolute/path/to/yttranscript-mcp/.venv/bin/python /absolute/path/to/yttranscript-mcp/server.py
```

Then `codex mcp list` to confirm.

Or edit `~/.codex/config.toml` (user-wide) or `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.youtube-transcript]
command = "/absolute/path/to/yttranscript-mcp/.venv/bin/python"
args = ["/absolute/path/to/yttranscript-mcp/server.py"]
```

The table key is `mcp_servers` with an underscore. Pasting Cursor's JSON into this file will not work.

In ChatGPT desktop or the Codex IDE extension: Settings → MCP servers → Add server → STDIO, then the same command and args. Restart the extension after you save.

### Antigravity

This is a custom stdio server, so skip the MCP Store and edit the config.

1. In the agent side panel, open **…** → **MCP Servers**.
2. **Manage MCP Servers** → **View raw config**.
3. Add the block below.

Global file: `~/.gemini/config/mcp_config.json`

This workspace only: `.agents/mcp_config.json`

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "/absolute/path/to/yttranscript-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/yttranscript-mcp/server.py"]
    }
  }
}
```

Use the full path to the venv Python. Antigravity does not always inherit your shell PATH, so a bare `python` often fails. Save, then refresh MCP in the panel.

This file is not the same as Gemini CLI's `~/.gemini/settings.json`.

### Other MCP hosts

Same `command` and `args`. Different file, sometimes a different JSON key.

**Claude Code**

```bash
claude mcp add --transport stdio youtube-transcript -- /absolute/path/to/yttranscript-mcp/.venv/bin/python /absolute/path/to/yttranscript-mcp/server.py
```

Or put the Cursor-style `mcpServers` JSON in `.mcp.json` (this project) or under `mcpServers` in `~/.claude.json` (your user). Claude Code does not read `~/.claude/settings.json` for MCP.

**Claude Desktop**

Same JSON as Cursor, inside:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Restart Claude Desktop.

**VS Code / GitHub Copilot**

Workspace file: `.vscode/mcp.json`

The root key is `servers`, not `mcpServers`:

```json
{
  "servers": {
    "youtube-transcript": {
      "type": "stdio",
      "command": "/absolute/path/to/yttranscript-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/yttranscript-mcp/server.py"]
    }
  }
}
```

Use Agent mode in Copilot Chat or the tools list stays empty. Command palette: **MCP: Open User Configuration** for a user-wide file.

**Gemini CLI**

`~/.gemini/settings.json` or `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "youtube-transcript": {
      "command": "/absolute/path/to/yttranscript-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/yttranscript-mcp/server.py"]
    }
  }
}
```

Or: `gemini mcp add youtube-transcript /absolute/path/to/yttranscript-mcp/.venv/bin/python /absolute/path/to/yttranscript-mcp/server.py`

**Windsurf (Cascade)**

`~/.codeium/windsurf/mcp_config.json` (Windows: `%USERPROFILE%\.codeium\windsurf\mcp_config.json`). Same `mcpServers` JSON as Cursor. Refresh Cascade after you save.

**Anything else**

If the tool can run a local MCP server, give it that Python binary and `server.py`. If it wants a URL, this repo is not that. It only speaks stdio. It does not start an HTTP server.

## How captions and summaries actually work

Video transcripts do not use the YouTube Data API.

1. YouTube captions first (`youtube-transcript-api`).
2. The same caption tracks through `yt-dlp` if that gets blocked.
3. If the video has no captions at all, audio is transcribed with Whisper when `OPENAI_API_KEY` or `GROQ_API_KEY` is in `.env`. OpenAI `whisper-1` is tried first, then Groq `whisper-large-v3`. Whisper is not used when captions already exist.

Groq `openai/gpt-oss-20b` (then `120b`), then OpenAI, writes a summary from that text. The tool returns the summary first, then the full transcript. Llama 3 on Groq is enterprise-only, so developer keys must use gpt-oss.

You can also run it from a terminal without an editor:

```bash
source .venv/bin/activate
python transcription.py https://youtu.be/dQw4w9WgXcQ
python transcription.py --no-summary -t https://youtu.be/dQw4w9WgXcQ
```

## If it does not start

| What you see | Likely cause |
| --- | --- |
| `No summary key set` | No `.env` next to `transcription.py`, or neither `GROQ_API_KEY` nor `OPENAI_API_KEY` is set. Captions can still work; the summary is skipped. |
| `No speech-to-text key set` | The video has no captions, and Whisper needs an API key. |
| Server never appears | Relative path, system Python without the packages, or JSON/TOML in the wrong file. |
| `yt-dlp is not installed` | The venv is missing `yt-dlp`. Re-run `pip install -r requirements.txt`. |

Do not run `python server.py` in a normal terminal to "test" it. It waits on stdin for MCP traffic and looks hung. If you want a sanity check before wiring an editor:

```bash
source .venv/bin/activate
python -c "from transcription import parse_video_id; print(parse_video_id('https://youtu.be/dQw4w9WgXcQ'))"
```

## Private files

| File | What it is |
| --- | --- |
| `.env` | Optional Groq/OpenAI keys for summaries and Whisper |

Keep `.env` off GitHub.

## License

Hobby project. Use at your own risk. YouTube captions, yt-dlp, Groq, and OpenAI have their own terms. This is an unofficial client.
