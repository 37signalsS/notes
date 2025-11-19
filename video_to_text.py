import os
import sys
import json
import wave
import subprocess
import glob
from vosk import Model, KaldiRecognizer

# путь к модели(https://alphacephei.com/vosk/models) - используем более новую, если она есть
model_path = "vosk-model-ru-0.42"
if not os.path.exists(model_path):
    model_path = "vosk-model-ru-0.22"

# Проверяем, существует ли путь к модели
if not os.path.exists(model_path):
    print(f"Ошибка: Директория с моделью не найдена: {model_path}")
    print("Пожалуйста, убедитесь, что модель Vosk распакована в этой директории.")
    sys.exit(1)

model = Model(model_path)

def transcribe_audio(wav_file_path):
    """Транскрибирует аудиофайл и возвращает текст с отображением прогресса."""
    if not os.path.exists(wav_file_path):
        return None, "Аудиофайл не найден"

    try:
        wf = wave.open(wav_file_path, "rb")
    except wave.Error as e:
        return None, f"Не удалось открыть WAV файл: {e}"

    if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
        wf.close()
        return None, "Аудио должно быть в формате WAV, 16 бит PCM, моно."

    rec = KaldiRecognizer(model, wf.getframerate())
    rec.SetWords(True)

    total_frames = wf.getnframes()
    result_text = []
    
    # Начинаем отображение прогресса на новой строке
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        
        if rec.AcceptWaveform(data):
            part = json.loads(rec.Result())
            result_text.append(part.get("text", ""))
        
        current_frames = wf.tell()
        if total_frames > 0:
            progress = (current_frames / total_frames) * 100
            # Используем \r для перезаписи строки и flush для немедленного отображения
            print(f"\r  - Прогресс транскрибации: {progress:.2f}%", end="", flush=True)

    final = json.loads(rec.FinalResult())
    result_text.append(final.get("text", ""))
    
    wf.close()
    print() # Перевод строки после завершения прогресс-бара

    return "\n".join(result_text), None

def main():
    video_extensions = ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.flv", "*.webm"]
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(ext))

    total_files = len(video_files)
    if total_files == 0:
        print("Видеофайлы не найдены.")
        return

    print(f"Найдено {total_files} видеофайлов для обработки.")

    for i, video_file in enumerate(video_files):
        progress_percent = ((i + 1) / total_files) * 100
        print(f"\n--- Файл {i + 1} из {total_files} ({progress_percent:.2f}%) ---")
        print(f"Обработка: '{video_file}'")

        base_name, _ = os.path.splitext(video_file)
        txt_file = base_name + ".txt"
        wav_file = base_name + ".wav"
        lock_dir = base_name + ".lock"

        if os.path.exists(txt_file):
            print(f"Текстовый файл '{txt_file}' уже существует. Пропускаем.")
            continue

        try:
            os.mkdir(lock_dir)
        except FileExistsError:
            print(f"Не удалось получить блокировку, другой процесс уже работает. Пропускаем.")
            continue
        
        try:
            # --- Шаг 1: Конвертация видео в WAV ---
            if not os.path.exists(wav_file):
                print(f"  - Конвертация в WAV...")
                try:
                    # Скрываем вывод ffmpeg, чтобы не засорять консоль
                    subprocess.run(
                        ["ffmpeg", "-nostdin", "-i", video_file, "-ar", "16000", "-ac", "1", "-af", "dynaudnorm", wav_file],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    print("  - Конвертация завершена.")
                except subprocess.CalledProcessError as e:
                    print(f"  - Ошибка конвертации: {e}")
                    continue 
                except FileNotFoundError:
                    print("Ошибка: ffmpeg не найден. Убедитесь, что он установлен и доступен в PATH.")
                    break

            # --- Шаг 2: Транскрибация WAV в TXT ---
            transcription, error = transcribe_audio(wav_file)

            if error:
                print(f"  - Ошибка транскрибации: {error}")
                continue

            # --- Шаг 3: Сохранение результата и очистка ---
            with open(txt_file, "w", encoding="utf-8") as f:
                f.write(transcription)
            
            print(f"  - Транскрибация успешно сохранена в '{txt_file}'.")

            print(f"  - Очистка...")
            os.remove(video_file)
            os.remove(wav_file)
            print(f"  - Исходные файлы удалены.")

        finally:
            # --- Шаг 4: Снятие блокировки ---
            os.rmdir(lock_dir)


if __name__ == "__main__":
    main()
