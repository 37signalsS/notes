import os
import sys
import subprocess
import json
import wave
import glob
from pathlib import Path

# ---------------------------------------------------------
# 1. Автоматическое создание и активация виртуального окружения
# ---------------------------------------------------------

HOME = str(Path.home())
VENV_PATH = f"{HOME}/whisper-venv"
VENV_PYTHON = f"{VENV_PATH}/bin/python3"
VIDEO_DIR = os.getcwd()

def ensure_venv():
    """Создаёт виртуальное окружение и ставит зависимости.
       Если окружение уже есть — пропускает."""
    if not os.path.exists(VENV_PATH):
        print("Создаю виртуальное окружение...")
        subprocess.run([sys.executable, "-m", "venv", VENV_PATH], check=True)

    # Проверяем, установлен ли vosk
    try:
        subprocess.run(
            [VENV_PYTHON, "-c", "import vosk"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return
    except subprocess.CalledProcessError:
        pass

    print("Ставлю зависимости...")
    subprocess.run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([VENV_PYTHON, "-m", "pip", "install", "vosk"], check=True)


# Если запускаемся НЕ из окружения — создаём его и перезапускаем скрипт заново
if os.path.exists(VENV_PATH) and sys.executable.startswith(VENV_PATH):
    pass  # уже внутри venv — продолжаем работу
else:
    ensure_venv()
    print("Перезапуск внутри виртуального окружения...")
    os.execv(VENV_PYTHON, [VENV_PYTHON] + sys.argv)


# ---------------------------------------------------------
# 2. Основной функционал VOSK
# ---------------------------------------------------------

from vosk import Model, KaldiRecognizer

# Меняем рабочий каталог на ~/Video
os.chdir(VIDEO_DIR)
print(f"Рабочий каталог: {VIDEO_DIR}")

model_path = "en/vosk-model-en-us-0.22"

if not os.path.exists(model_path):
    print(f"Ошибка: директория с моделью не найдена: {model_path}")
    sys.exit(1)

model = Model(model_path)

def transcribe_audio(wav_file_path):
    if not os.path.exists(wav_file_path):
        return None, "Аудиофайл не найден"

    try:
        wf = wave.open(wav_file_path, "rb")
    except wave.Error as e:
        return None, f"Не удалось открыть WAV файл: {e}"

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
        wf.close()
        return None, "Аудио должно быть WAV 16-бит, моно."

    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    total_frames = wf.getnframes()
    result_text = []

    while True:
        data = wf.readframes(4000)
        if not data:
            break

        if rec.AcceptWaveform(data):
            part = json.loads(rec.Result())
            result_text.append(part.get("text", ""))

        progress = wf.tell() / total_frames * 100
        print(f"\r  - Прогресс транскрибации: {progress:.2f}%", end="", flush=True)

    final = json.loads(rec.FinalResult())
    result_text.append(final.get("text", ""))

    wf.close()
    print()

    return "\n".join(result_text), None


def main():
    video_extensions = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.flv", "*.webm"]
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(f"en/**/{ext}", recursive=True))

    if not video_files:
        print("Видеофайлы не найдены.")
        return

    print(f"Найдено {len(video_files)} видеофайлов.")

    for i, video_file in enumerate(video_files):
        print(f"\n--- Файл {i+1} из {len(video_files)} ---")
        print(f"Обработка: {video_file}")

        base, _ = os.path.splitext(video_file)
        txt_file = base + ".txt"
        wav_file = base + ".wav"
        lock_dir = base + ".lock"

        if os.path.exists(txt_file):
            print("TXT уже есть — пропуск.")
            continue

        try:
            os.mkdir(lock_dir)
        except FileExistsError:
            print("Блокировка занята — пропуск.")
            continue

        try:
            # Конвертация
            if not os.path.exists(wav_file):
                print("  - Конвертация в WAV...")
                subprocess.run(
                    ["ffmpeg", "-nostdin", "-i", video_file, "-ar", "16000", "-ac", "1", "-af", "dynaudnorm", wav_file],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
                print("  - Конвертация завершена.")

            # Транскрибация
            transcription, error = transcribe_audio(wav_file)
            if error:
                print(f"Ошибка: {error}")
                continue

            with open(txt_file, "w", encoding="utf-8") as f:
                f.write(transcription)

            print(f"  - Транскрипт сохранён: {txt_file}")

            print("  - Очистка...")
            os.remove(video_file)
            os.remove(wav_file)

        finally:
            os.rmdir(lock_dir)


if __name__ == "__main__":
    main()
