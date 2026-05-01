import os
import subprocess
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import whisper
from deep_translator import GoogleTranslator

BOT_TOKEN = "8433956217:AAHiWI8xphZQ-mm5TqRYX0_znjr2pLxBKJ0"
WHISPER_MODEL = "base"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

print("Loading Whisper model...")
model = whisper.load_model(WHISPER_MODEL)
print("Model loaded!")

LANGUAGES = {
    "🇸🇦 العربية": "ar",
    "🇺🇸 English": "en",
    "🇫🇷 Français": "fr",
    "🇩🇪 Deutsch": "de",
    "🇪🇸 Español": "es",
    "🇮🇹 Italiano": "it",
    "🇷🇺 Русский": "ru",
    "🇨🇳 中文": "zh-CN",
    "🇯🇵 日本語": "ja",
    "🇰🇷 한국어": "ko",
    "🇹🇷 Türkçe": "tr",
    "🇮🇳 हिन्दी": "hi",
    "🇧🇷 Português": "pt",
}

def language_keyboard():
    buttons = []
    items = list(LANGUAGES.items())
    for i in range(0, len(items), 2):
        row = [InlineKeyboardButton(items[i][0], callback_data=f"lang_{items[i][1]}")]
        if i + 1 < len(items):
            row.append(InlineKeyboardButton(items[i+1][0], callback_data=f"lang_{items[i+1][1]}"))
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def seconds_to_srt_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def create_srt(segments, target_lang):
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        start = seconds_to_srt_time(seg["start"])
        end = seconds_to_srt_time(seg["end"])
        text = seg["text"].strip()
        try:
            translated = GoogleTranslator(source="auto", target=target_lang).translate(text)
        except Exception:
            translated = text
        srt_lines.append(f"{i}\n{start} --> {end}\n{translated}\n")
    return "\n".join(srt_lines)

def burn_subtitles(video_path, srt_path, output_path):
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf",
        f"subtitles={srt_escaped}:force_style='FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,Outline=2,Shadow=1,Alignment=2,MarginV=20'",
        "-c:v", "libx264", "-c:a", "copy", "-preset", "fast",
        output_path, "-y"
    ]
    subprocess.run(cmd, capture_output=True, check=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 *مرحباً! أنا بوت ترجمة الفيديو*\n\n"
        "1️⃣ اختر لغة الترجمة: /language\n"
        "2️⃣ أرسل أي فيديو\n"
        "3️⃣ استقبل الفيديو مترجم مثل الأفلام! 🎬",
        parse_mode="Markdown"
    )

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌍 *اختر لغة الترجمة:*",
        reply_markup=language_keyboard(),
        parse_mode="Markdown"
    )

async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang_code = query.data.replace("lang_", "")
    context.user_data["target_lang"] = lang_code
    lang_name = next((k for k, v in LANGUAGES.items() if v == lang_code), lang_code)
    await query.edit_message_text(
        f"✅ تم اختيار: *{lang_name}*\n\nأرسل الفيديو الآن 🎬",
        parse_mode="Markdown"
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    target_lang = context.user_data.get("target_lang", None)

    if not target_lang:
        await msg.reply_text("⚠️ اختر لغة الترجمة أولاً:", reply_markup=language_keyboard())
        return

    video = msg.video or msg.document
    if video and video.file_size and video.file_size > 50 * 1024 * 1024:
        await msg.reply_text("❌ الفيديو كبير جداً! الحد الأقصى 50MB.")
        return

    status_msg = await msg.reply_text("⏳ جاري تحميل الفيديو...")
    user_id = update.effective_user.id
    input_path = f"/tmp/{user_id}_input.mp4"
    audio_path = f"/tmp/{user_id}_audio.wav"
    srt_path = f"/tmp/{user_id}_subs.srt"
    output_path = f"/tmp/{user_id}_output.mp4"

    try:
        file = await video.get_file()
        await file.download_to_drive(input_path)

        await status_msg.edit_text("🔊 جاري استخراج الصوت...")
        subprocess.run(["ffmpeg", "-i", input_path, "-ar", "16000", "-ac", "1", audio_path, "-y"], capture_output=True, check=True)

        await status_msg.edit_text("🧠 جاري التعرف على الكلام...")
        result = model.transcribe(audio_path)
        segments = result.get("segments", [])
        detected_lang = result.get("language", "unknown")

        if not segments:
            await status_msg.edit_text("❌ لم يتم التعرف على كلام في الفيديو.")
            return

        await status_msg.edit_text(f"🌍 جاري الترجمة من {detected_lang}...")
        srt_content = create_srt(segments, target_lang)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        await status_msg.edit_text("🎬 جاري دمج الترجمة في الفيديو...")
        burn_subtitles(input_path, srt_path, output_path)

        lang_name = next((k for k, v in LANGUAGES.items() if v == target_lang), target_lang)
        await status_msg.edit_text("📤 جاري الإرسال...")

        with open(output_path, "rb") as f:
            await msg.reply_video(
                video=f,
                caption=f"✅ *مترجم إلى {lang_name}*\n🎙️ اللغة الأصلية: {detected_lang}",
                parse_mode="Markdown",
                supports_streaming=True
            )
        await status_msg.delete()

    except subprocess.CalledProcessError as e:
        await status_msg.edit_text("❌ خطأ في معالجة الفيديو.")
    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ حدث خطأ: {str(e)}")
    finally:
        for p in [input_path, audio_path, srt_path, output_path]:
            try:
                os.remove(p)
            except Exception:
                pass

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("language", choose_language))
    app.add_handler(CallbackQueryHandler(language_selected, pattern="^lang_"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    print("Bot is running!")
    app.run_polling()

if __name__ == "__main__":
    main()
