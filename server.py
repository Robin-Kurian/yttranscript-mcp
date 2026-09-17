from mcp.server.mcpserver import MCPServer

from transcription import transcribe_video

mcp = MCPServer("YouTube Transcript")


@mcp.tool()
def transcribe_youtube_video(
    url_or_video_id: str,
    language: str = "",
    include_timestamps: bool = False,
) -> str:
    """
    Returns a summary first, then the full transcript for a YouTube video.
    Pass a watch URL, youtu.be link, Shorts URL, music.youtube.com URL, or an
    11-character video ID. Captions are fetched from YouTube, then yt-dlp, then
    Whisper if there are no captions. The summary is written with Groq, then
    OpenAI. Optional language is a code like en, es, hi.
    """
    try:
        return transcribe_video(
            url_or_video_id,
            language=language or None,
            include_timestamps=include_timestamps,
            summarize=True,
        )
    except Exception as e:
        return f"Failed to transcribe '{url_or_video_id}': {e}"


if __name__ == "__main__":
    mcp.run()
