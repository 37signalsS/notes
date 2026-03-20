#!/usr/bin/env python3
"""
Скрипт для очистки VTT-файлов от временных меток и служебных строк.
Удаляет:
- Временные метки вида: 00:00:10.400 --> 00:00:12.830 align:start position:0%
- Пустые строки между субтитрами
- Дублирующиеся строки текста
Оставляет только текст субтитров.
"""

import re
import sys
from pathlib import Path


def clean_vtt(input_file: str, output_file: str = None) -> None:
    """Очистка VTT-файла от временных меток."""
    
    if output_file is None:
        output_file = Path(input_file).with_suffix('.clean.txt')
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Удаляем заголовок WEBVTT и метаданные
    lines = content.split('\n')
    cleaned_lines = []
    skip_header = True
    
    # Паттерн для временных меток
    timestamp_pattern = re.compile(
        r'^\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*$'
    )
    
    # Паттерн для тегов времени внутри текста <00:00:00.000>
    inline_timestamp_pattern = re.compile(r'<\d{2}:\d{2}:\d{2}\.\d{3}>')
    
    # Паттерн для тегов <c> и </c>
    c_tag_pattern = re.compile(r'</?c>')
    
    in_header = True
    
    for line in lines:
        # Пропускаем заголовок WEBVTT
        if in_header:
            if line.strip() == '' or line.startswith('WEBVTT') or line.startswith('Kind:') or line.startswith('Language:'):
                continue
            in_header = False
        
        # Пропускаем временные метки
        if timestamp_pattern.match(line):
            continue
        
        # Пропускаем пустые строки
        if line.strip() == '':
            continue
        
        # Очищаем строку от inline-тегов времени
        cleaned_line = inline_timestamp_pattern.sub('', line)
        cleaned_line = c_tag_pattern.sub('', cleaned_line)
        
        # Пропускаем строки, которые содержат только теги
        if cleaned_line.strip() == '':
            continue
        
        cleaned_lines.append(cleaned_line.strip())
    
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


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Использование: python clean_vtt.py <input_file> [output_file]")
        print("Пример: python clean_vtt.py 'Разбор резюме на позицию DevОps. Часть 1 [K5xl_UFNr7s].ru.vtt'")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    clean_vtt(input_file, output_file)
