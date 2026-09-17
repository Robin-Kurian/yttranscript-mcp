import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - optional until requirements are installed
    YoutubeDL = None

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PATH_MARKERS = {"embed", "shorts", "live", "v", "watch"}
VTT_TAG_RE = re.compile(r"<[^>]+>")
WHISPER_MAX_BYTES = 24 * 1024 * 1024
SUMMARY_MAX_CHARS = 24_000
GROQ_SUMMARY_MODELS = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
)
SUBTITLE_EXTS = ("json3", "srv3", "vtt", "srv2", "srv1", "ttml")
ROOT_DIR = os.path.dirname(__file__)
ENV_FILE = os.path.join(ROOT_DIR, ".env")
SUMMARY_SYSTEM = (
    "You summarize YouTube transcripts that were already fetched from captions "
    "or speech-to-text. Write in English. Start with one or two sentences on "
    "what the video is (genre and topic), then the plot or argument, then "
    "notable jokes or beats. Do not invent names, quotes, or events that are "
    "not in the transcript. If it is a comic dub, sketch, recap, or song, say "
    "that up front. Prefer a short paragraph plus 3-6 bullets when there are "
    "multiple scenes."
)


@dataclass
class Snippet:
    text: str
    start: float
    duration: float = 0.0


@dataclass
class TranscriptResult:
    video_id: str
    language: str
    language_code: str
    is_generated: bool
    source: str
    snippets: list[Snippet]


def load_env_file(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(
                key.strip(), value.strip().strip("'").strip('"')
            )


def parse_video_id(url_or_id: str) -> str:
    value = (url_or_id or "").strip()
    if not value:
        raise ValueError("A YouTube URL or video ID is required.")
    if VIDEO_ID_RE.fullmatch(value):
        return value

    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    candidates = query.get("v") or []
    path_parts = [part for part in parsed.path.split("/") if part]

    host = (parsed.hostname or "").lower()
    if host == "youtu.be" or host.endswith(".youtu.be"):
        if path_parts:
            candidates.append(path_parts[0])

    for index, part in enumerate(path_parts):
        if part in PATH_MARKERS and index + 1 < len(path_parts):
            candidates.append(path_parts[index + 1])
    if path_parts:
        candidates.append(path_parts[-1])

    for candidate in candidates:
        video_id = candidate.split("?")[0].split("&")[0]
        if VIDEO_ID_RE.fullmatch(video_id):
            return video_id

    raise ValueError(
        f"Could not parse a YouTube video ID from '{url_or_id}'. "
        "Pass a watch URL, youtu.be link, Shorts URL, or an 11-character video ID."
    )


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_transcript_text(snippets: list[Snippet], include_timestamps: bool) -> str:
    lines: list[str] = []
    for snippet in snippets:
        text = " ".join((snippet.text or "").replace("\n", " ").split())
        if not text:
            continue
        if include_timestamps:
            lines.append(f"[{format_timestamp(snippet.start)}] {text}")
        else:
            lines.append(text)
    if include_timestamps:
        return "\n".join(lines)
    return " ".join(lines)


def render_transcript(
    result: TranscriptResult,
    include_timestamps: bool = False,
    summary: str | None = None,
    summary_source: str | None = None,
) -> str:
    kind = "auto-generated" if result.is_generated else "manual"
    body = format_transcript_text(result.snippets, include_timestamps)
    if not body:
        raise RuntimeError(f"Transcript for {video_url(result.video_id)} was empty.")

    header = (
        f"{video_url(result.video_id)}\n"
        f"Language: {result.language} ({result.language_code}, {kind})\n"
        f"Captions: {result.source}"
    )
    if summary_source:
        header += f"\nSummarizer: {summary_source}"
    if summary:
        return f"{header}\n\nSummary\n{summary}\n\nTranscript\n{body}"
    return f"{header}\n\n{body}"


def available_languages(transcript_list) -> str:
    labels = []
    for transcript in transcript_list:
        kind = "auto-generated" if transcript.is_generated else "manual"
        labels.append(f"{transcript.language_code} ({transcript.language}, {kind})")
    return ", ".join(labels) if labels else "none"


def select_transcript(transcript_list, language: str | None):
    preferred: list[str] = []
    if language:
        preferred.append(language)
    if "en" not in preferred:
        preferred.append("en")

    try:
        return transcript_list.find_transcript(preferred)
    except NoTranscriptFound:
        pass

    target = language or "en"
    for transcript in transcript_list:
        if not transcript.is_translatable:
            continue
        try:
            return transcript.translate(target)
        except YouTubeTranscriptApiException:
            continue

    for transcript in transcript_list:
        return transcript

    raise NoTranscriptFound(
        getattr(transcript_list, "video_id", ""),
        preferred,
        transcript_list,
    )


def fetch_via_youtube_transcript_api(
    video_id: str, language: str | None
) -> TranscriptResult:
    api = YouTubeTranscriptApi()
    try:
        transcript_list = api.list(video_id)
        transcript = select_transcript(transcript_list, language)
        fetched = transcript.fetch()
    except TranscriptsDisabled as exc:
        raise RuntimeError("Captions are disabled.") from exc
    except NoTranscriptFound as exc:
        try:
            languages = available_languages(api.list(video_id))
        except YouTubeTranscriptApiException:
            languages = "unknown"
        raise RuntimeError(f"No transcript found. Available languages: {languages}.") from exc
    except YouTubeTranscriptApiException as exc:
        raise RuntimeError(str(exc)) from exc

    snippets = [
        Snippet(text=item.text, start=item.start, duration=item.duration)
        for item in fetched
    ]
    return TranscriptResult(
        video_id=fetched.video_id,
        language=fetched.language,
        language_code=fetched.language_code,
        is_generated=fetched.is_generated,
        source="YouTube captions (youtube-transcript-api)",
        snippets=snippets,
    )


def _ydl_base_opts() -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 2,
        "extractor_retries": 2,
        "socket_timeout": 20,
        "skip_download": True,
    }


def _rank_subtitle_langs(tracks: dict, language: str | None) -> list[str]:
    keys = list(tracks)
    ranked: list[str] = []
    seen: set[str] = set()
    wanted: list[str] = []
    if language:
        wanted.append(language)
        wanted.append(language.split("-")[0])
    wanted.extend(["en", "en-US", "en-GB"])
    for prefix in wanted:
        for key in keys:
            if key in seen:
                continue
            base = key.split("-")[0]
            if key == prefix or key.startswith(f"{prefix}-") or base == prefix:
                ranked.append(key)
                seen.add(key)
    for key in keys:
        if key not in seen:
            ranked.append(key)
    return ranked


def _pick_subtitle_format(formats: list[dict]) -> dict | None:
    by_ext = {item.get("ext"): item for item in formats if item.get("url")}
    for ext in SUBTITLE_EXTS:
        if ext in by_ext:
            return by_ext[ext]
    return next((item for item in formats if item.get("url")), None)


def _vtt_timestamp_to_seconds(value: str) -> float:
    stamp = value.strip().split()[0].replace(",", ".")
    parts = stamp.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    minutes, seconds = parts
    return int(minutes) * 60 + float(seconds)


def parse_json3_subtitles(payload: dict) -> list[Snippet]:
    snippets: list[Snippet] = []
    for event in payload.get("events") or []:
        segs = event.get("segs") or []
        text = "".join(seg.get("utf8", "") for seg in segs)
        text = " ".join(text.replace("\n", " ").split())
        if not text:
            continue
        snippets.append(
            Snippet(
                text=text,
                start=event.get("tStartMs", 0) / 1000.0,
                duration=event.get("dDurationMs", 0) / 1000.0,
            )
        )
    return snippets


def parse_vtt_subtitles(payload: str) -> list[Snippet]:
    snippets: list[Snippet] = []
    blocks = re.split(r"\n\s*\n", payload.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith("WEBVTT") or lines[0].startswith("NOTE"):
            continue
        timing = next((line for line in lines if "-->" in line), None)
        if not timing:
            continue
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        text = " ".join(
            VTT_TAG_RE.sub("", line)
            for line in lines
            if "-->" not in line and not line.strip().isdigit()
        )
        text = " ".join(text.split())
        if not text:
            continue
        start = _vtt_timestamp_to_seconds(start_raw)
        end = _vtt_timestamp_to_seconds(end_raw)
        if snippets and snippets[-1].text == text:
            continue
        snippets.append(Snippet(text=text, start=start, duration=max(0.0, end - start)))
    return snippets


def _parse_subtitle_payload(ext: str, raw: bytes) -> list[Snippet]:
    text = raw.decode("utf-8", errors="replace")
    if ext == "json3":
        return parse_json3_subtitles(json.loads(text))
    if ext in {"vtt", "ttml", "srv1", "srv2", "srv3"}:
        if ext == "vtt" or "WEBVTT" in text[:32]:
            return parse_vtt_subtitles(text)
        try:
            return parse_json3_subtitles(json.loads(text))
        except json.JSONDecodeError:
            return parse_vtt_subtitles(text)
    raise RuntimeError(f"Unsupported subtitle format '{ext}'.")


def fetch_via_ytdlp(video_id: str, language: str | None) -> TranscriptResult:
    if YoutubeDL is None:
        raise RuntimeError("yt-dlp is not installed.")

    url = video_url(video_id)
    with YoutubeDL(_ydl_base_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
        manual = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}
        title_language = (info.get("language") or "").replace("_", "-")

        for tracks, generated in ((manual, False), (automatic, True)):
            for lang_key in _rank_subtitle_langs(tracks, language or title_language):
                chosen = _pick_subtitle_format(tracks.get(lang_key) or [])
                if not chosen:
                    continue
                ext = chosen.get("ext") or "vtt"
                with ydl.urlopen(chosen["url"]) as response:
                    raw = response.read()
                snippets = _parse_subtitle_payload(ext, raw)
                if not snippets:
                    continue
                return TranscriptResult(
                    video_id=video_id,
                    language=chosen.get("name") or lang_key,
                    language_code=lang_key,
                    is_generated=generated,
                    source="YouTube captions (yt-dlp)",
                    snippets=snippets,
                )

    raise RuntimeError("yt-dlp found no usable captions.")


def _chat_candidates() -> list[tuple[str, str, str, str]]:
    """Groq first (developer models), then OpenAI. Used for summaries, not captions."""
    candidates: list[tuple[str, str, str, str]] = []
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if groq_key:
        models: list[str] = []
        override = os.environ.get("GROQ_SUMMARY_MODEL", "").strip()
        if override:
            models.append(override)
        for model in GROQ_SUMMARY_MODELS:
            if model not in models:
                models.append(model)
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        for model in models:
            candidates.append(("Groq", groq_key, groq_url, model))
    if openai_key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4o-mini")
        candidates.append(("OpenAI", openai_key, f"{base}/chat/completions", model))
    return candidates


def _extract_chat_text(payload: dict) -> str:
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if str(text).strip():
                    parts.append(str(text).strip())
        if parts:
            return "\n".join(parts)
    return ""


def summarize_transcript(result: TranscriptResult) -> tuple[str, str]:
    candidates = _chat_candidates()
    if not candidates:
        raise RuntimeError(
            "No summary key set. Add GROQ_API_KEY or OPENAI_API_KEY to .env."
        )

    body = format_transcript_text(result.snippets, include_timestamps=False)
    if len(body) > SUMMARY_MAX_CHARS:
        body = body[:SUMMARY_MAX_CHARS] + "\n[transcript truncated]"

    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Video: {video_url(result.video_id)}\n"
                f"Language: {result.language}\n"
                f"Source: {result.source}\n\n"
                f"Transcript:\n{body}"
            ),
        },
    ]

    errors: list[str] = []
    for provider, api_key, endpoint, model in candidates:
        request: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }
        if "groq.com" in endpoint:
            request["max_completion_tokens"] = 800
        else:
            request["max_tokens"] = 800
        try:
            response = requests.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request,
                timeout=90,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"{model} HTTP {response.status_code}: {response.text[:300]}"
                )
            text = _extract_chat_text(response.json())
            if not text:
                raise RuntimeError(f"{model} returned an empty summary.")
            return text, f"{provider}, {model}"
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    raise RuntimeError("All summarizers failed. " + " ".join(errors))


def _whisper_config() -> tuple[str, str, str] | None:
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if openai_key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
        return openai_key, f"{base}/audio/transcriptions", model
    if groq_key:
        model = os.environ.get("GROQ_TRANSCRIBE_MODEL", "whisper-large-v3")
        return groq_key, "https://api.groq.com/openai/v1/audio/transcriptions", model
    return None


def _download_audio(video_id: str, directory: str) -> str:
    if YoutubeDL is None:
        raise RuntimeError("yt-dlp is not installed.")
    outtmpl = os.path.join(directory, "%(id)s.%(ext)s")
    opts = _ydl_base_opts()
    opts.update(
        {
            "skip_download": False,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": outtmpl,
        }
    )
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video_url(video_id), download=True)
        filename = ydl.prepare_filename(info)
    if os.path.exists(filename):
        return filename
    matches = [
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.startswith(video_id)
    ]
    if not matches:
        raise RuntimeError("Audio download finished but no file was written.")
    return matches[0]


def fetch_via_whisper(video_id: str, language: str | None) -> TranscriptResult:
    config = _whisper_config()
    if config is None:
        raise RuntimeError(
            "No speech-to-text key set. Add OPENAI_API_KEY or GROQ_API_KEY to .env "
            "to transcribe videos that have no captions."
        )
    api_key, endpoint, model = config

    with tempfile.TemporaryDirectory(prefix="ytmusic-transcript-") as tmpdir:
        audio_path = _download_audio(video_id, tmpdir)
        size = os.path.getsize(audio_path)
        if size > WHISPER_MAX_BYTES:
            raise RuntimeError(
                f"Audio is {size // (1024 * 1024)}MB; Whisper APIs cap uploads near 25MB."
            )
        with open(audio_path, "rb") as audio_file:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (os.path.basename(audio_path), audio_file)},
                data={
                    "model": model,
                    "response_format": "verbose_json",
                    **({"language": language} if language else {}),
                },
                timeout=300,
            )
    if response.status_code >= 400:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:400]}")

    payload = response.json()
    snippets = [
        Snippet(
            text=item.get("text", ""),
            start=float(item.get("start") or 0),
            duration=max(
                0.0,
                float(item.get("end") or 0) - float(item.get("start") or 0),
            ),
        )
        for item in payload.get("segments") or []
    ]
    if not snippets and payload.get("text"):
        snippets = [Snippet(text=payload["text"], start=0.0)]

    if "groq.com" in endpoint:
        provider = "Groq"
    elif "openai.com" in endpoint:
        provider = "OpenAI"
    else:
        provider = "OpenAI-compatible"

    language_code = payload.get("language") or language or "und"
    return TranscriptResult(
        video_id=video_id,
        language=language_code,
        language_code=language_code,
        is_generated=True,
        source=f"Whisper audio ({provider}, {model})",
        snippets=snippets,
    )


def fetch_transcript(url_or_id: str, language: str | None = None) -> TranscriptResult:
    load_env_file(ENV_FILE)
    video_id = parse_video_id(url_or_id)
    language_code = (language or "").strip().lower() or None
    errors: list[str] = []

    fetchers = (
        fetch_via_youtube_transcript_api,
        fetch_via_ytdlp,
        fetch_via_whisper,
    )
    for fetch in fetchers:
        try:
            return fetch(video_id, language_code)
        except Exception as exc:
            errors.append(f"{fetch.__name__.removeprefix('fetch_via_')}: {exc}")

    raise RuntimeError(
        f"Failed to transcribe {video_url(video_id)}.\n"
        + "\n".join(f"- {item}" for item in errors)
    )


def transcribe_video(
    url_or_id: str,
    language: str | None = None,
    include_timestamps: bool = False,
    summarize: bool = True,
) -> str:
    result = fetch_transcript(url_or_id, language)
    summary = None
    summary_source = None
    if summarize:
        try:
            summary, summary_source = summarize_transcript(result)
        except Exception as exc:
            summary_source = f"unavailable ({exc})"
    return render_transcript(
        result,
        include_timestamps=include_timestamps,
        summary=summary,
        summary_source=summary_source,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch a YouTube transcript: summary first, then captions. Uses yt-dlp and Whisper fallbacks."
    )
    parser.add_argument("url", help="YouTube URL or 11-character video ID")
    parser.add_argument(
        "-l",
        "--language",
        default="",
        help="Language code such as en, es, or hi. Defaults to English, then any available captions.",
    )
    parser.add_argument(
        "-t",
        "--timestamps",
        action="store_true",
        help="Prefix each caption line with a timestamp.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the Groq/OpenAI summary and print captions only.",
    )
    args = parser.parse_args(argv)

    try:
        print(
            transcribe_video(
                args.url,
                language=args.language or None,
                include_timestamps=args.timestamps,
                summarize=not args.no_summary,
            )
        )
    except (ValueError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
