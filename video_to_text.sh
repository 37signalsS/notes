#!/bin/bash

# Define the LD_LIBRARY_PATH for whisper.cpp
WHISPER_LD_LIBRARY_PATH="/home/q/whisper.cpp/build/src:/home/q/whisper.cpp/build/ggml/:/home/q/whisper.cpp/build/ggml/src"

# Define the whisper-cli executable path
WHISPER_CLI_PATH="/home/q/whisper.cpp/build/bin/whisper-cli"

# Define the whisper model path
WHISPER_MODEL_PATH="/home/q/whisper.cpp/models/ggml-small.bin"

# --- Step 1: Convert all video files to WAV ---
echo "--- Starting video to WAV conversion ---"
find . -type f \( -name "*.mp4" -o -name "*.mkv" -o -name "*.avi" -o -name "*.mov" -o -name "*.flv" -o -name "*.webm" \) | while read -r f; do
  wav_file="${f%.*}.wav"
  lock_dir="${f%.*}.lock"

  # If wav file already exists, skip conversion.
  if [ -f "$wav_file" ]; then
    echo "WAV file '$wav_file' already exists. Skipping conversion."
    continue
  fi

  # Attempt to acquire lock for conversion
  if mkdir "$lock_dir" 2>/dev/null; then
    # Ensure lock is removed on script exit
    trap 'rmdir "$lock_dir"; exit' INT TERM EXIT

    echo "Acquired lock for '$f'. Converting to '$wav_file'..."
    ffmpeg -i "$f" -af dynaudnorm "$wav_file"

    # Release the lock
    rmdir "$lock_dir"
    trap - INT TERM EXIT
  else
    echo "Could not acquire lock for '$f', another process is likely converting it. Skipping."
  fi
done
echo "--- Finished video to WAV conversion ---"

# --- Step 2: Transcribe all WAV to TXT ---
echo "--- Starting WAV to TXT transcription ---"
find . -type f -name "*.wav" | while read -r wav_file; do
  whisper_output_prefix="${wav_file%.wav}"
  txt_file="${whisper_output_prefix}.txt"
  lock_dir="${whisper_output_prefix}.lock"

  # If txt file already exists, skip transcription.
  if [ -f "$txt_file" ]; then
    echo "TXT file '$txt_file' already exists. Skipping transcription."
    continue
  fi

  # Attempt to acquire lock for transcription
  if mkdir "$lock_dir" 2>/dev/null; then
    # Ensure lock is removed on script exit
    trap 'rmdir "$lock_dir"; exit' INT TERM EXIT

    echo "Acquired lock for '$wav_file'. Transcribing..."
    # Run whisper-cli and delete files on success
    if LD_LIBRARY_PATH="$WHISPER_LD_LIBRARY_PATH" "$WHISPER_CLI_PATH" \
      -m "$WHISPER_MODEL_PATH" \
      -f "$wav_file" \
      -l ru -ng -otxt -of "$whisper_output_prefix"
    then

      echo "Transcription successful for '$wav_file'."

      # Find and delete original video file
      base_name="${wav_file%.wav}"
      original_video_file=""
      for ext in mp4 mkv avi mov flv webm; do
          if [ -f "${base_name}.${ext}" ]; then
              original_video_file="${base_name}.${ext}"
              break
          fi
      done

      if [ -n "$original_video_file" ]; then
          echo "Deleting original video file: '$original_video_file'"
          rm "$original_video_file"
      else
          echo "Could not find original video file for '$wav_file' to delete."
      fi

      echo "Deleting WAV file: '$wav_file'"
      rm "$wav_file"
    else
      echo "Transcription failed for '$wav_file'. Files will not be deleted."
    fi

    # Release the lock
    rmdir "$lock_dir"
    trap - INT TERM EXIT
  else
    echo "Could not acquire lock for '$wav_file', another process is likely transcribing it. Skipping."
  fi
done
echo "--- Finished WAV to TXT transcription ---"

