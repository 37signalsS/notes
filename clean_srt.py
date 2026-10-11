#!/usr/bin/env python3
"""
Скрипт для очистки SRT-файлов из shorts_subtitles/ от временных меток, номеров субтитров и дублей.
Удаляет:
- Номера субтитров (строка из цифры)
- Временные метки вида: 00:00:00,160 --> 00:00:03,030
- Пустые строки между субтитрами
- Дублирующиеся строки текста
Оставляет только чистый текст субтитров.
"""

import re
import sys
from pathlib import Path


def clean_srt(input_file: str, output_file: str = None) -> None:
    """Очистка SRT-файла от временных меток и служебных строк."""

    if output_file is None:
        output_file = Path(input_file).with_suffix('.clean.txt')

    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    cleaned_lines = []

    # Паттерн для временных меток SRT: 00:00:00,160 --> 00:00:03,030
    timestamp_pattern = re.compile(
        r'^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}.*$'
    )

    # Паттерн для строки-номера субтитра (только цифра)
    number_pattern = re.compile(r'^\d+$')

    for line in lines:
        # Пропускаем номера субтитров
        if number_pattern.match(line.strip()):
            continue

        # Пропускаем временные метки
        if timestamp_pattern.match(line):
            continue

        # Пропускаем пустые строки
        if line.strip() == '':
            continue

        cleaned_lines.append(line.strip())

    # Удаляем дубликаты подряд идущих строк
    final_lines = []
    prev_line = None

    for line in cleaned_lines:
        if line != prev_line:
            final_lines.append(line)
            prev_line = line

    # Записываем результат
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(final_lines))

    print(f"Очищенный файл сохранён: {output_file}")
    print(f"Строк обработано: {len(final_lines)}")

    Path(input_file).unlink()
    print(f"Удалён исходный файл: {input_file}")


if __name__ == '__main__':
    # Если переданы аргументы — обрабатываем их (обратная совместимость)
    if len(sys.argv) > 1:
        input_files = sys.argv[1:]
        output_file = None

        # Если последний аргумент похож на output файл (не .srt), используем его как output
        if len(input_files) > 1 and not input_files[-1].endswith('.srt'):
            output_file = input_files.pop()

        for input_file in input_files:
            clean_srt(input_file, output_file)
    else:
        # Автоматический поиск всех .srt файлов в директории shorts_subtitles
        search_dir = Path(__file__).parent / 'shorts_subtitles'
        if not search_dir.exists():
            search_dir = Path('shorts_subtitles')
        if not search_dir.exists():
            search_dir = Path('.')

        srt_files = sorted(search_dir.glob('*.srt'))

        if not srt_files:
            print('SRT-файлы не найдены в директории shorts_subtitles')
            sys.exit(0)

        print(f'Найдено SRT-файлов: {len(srt_files)}')
        print('-' * 60)

        for srt_file in srt_files:
            print(f'\nОбработка: {srt_file.name}')
            clean_srt(str(srt_file))
            print('-' * 60)

        print(f'\nОбработано файлов: {len(srt_files)}')
