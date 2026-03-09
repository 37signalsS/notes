#!/usr/bin/env python3
"""
Скрипт для проверки и обновления ссылок в файлах проекта согласно index.md
"""

import re
import os
from pathlib import Path
from typing import Set, Dict, List, Tuple

BASE_DIR = Path("/home/q/notes")
INDEX_FILE = BASE_DIR / "index.md"

def load_valid_files() -> Set[str]:
    """Загрузить список всех валидных файлов из index.md"""
    valid_files = set()
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('---'):
                # Убираем возможные лишние символы
                file_path = line.strip()
                if file_path.endswith('.md'):
                    valid_files.add(file_path)
    return valid_files

def find_markdown_links(content: str) -> List[Tuple[str, int]]:
    """
    Найти все markdown ссылки на локальные .md файлы
    Возвращает список кортежей (ссылка, номер_строки)
    """
    # Паттерн для markdown ссылок: [text](path)
    pattern = r'\[([^\]]*)\]\(([^)]+)\)'
    links = []
    
    lines = content.split('\n')
    for line_num, line in enumerate(lines, 1):
        matches = re.finditer(pattern, line)
        for match in matches:
            link = match.group(2)
            # Проверяем только ссылки на .md файлы
            if '.md' in link and not link.startswith('http://') and not link.startswith('https://'):
                links.append((link, line_num, line.strip()))
    
    return links

def resolve_link_path(current_file: str, link: str) -> str:
    """
    Разрешить относительный путь ссылки относительно текущего файла
    """
    current_dir = os.path.dirname(current_file)
    
    # Обрабатываем относительные пути
    if link.startswith('./'):
        link = link[2:]
    
    # Объединяем путь
    resolved = os.path.normpath(os.path.join(current_dir, link))
    
    # Убираем ведущий слэш если есть
    if resolved.startswith('/'):
        resolved = resolved[1:]
    
    return resolved

def check_link_exists(resolved_path: str, valid_files: Set[str]) -> bool:
    """Проверить, существует ли файл в списке валидных"""
    return resolved_path in valid_files

def find_correct_path(target_filename: str, valid_files: Set[str]) -> str:
    """
    Найти правильный путь к файлу по имени файла
    Используется когда ссылка битая, но файл существует в index.md
    """
    # Ищем файлы с таким же именем
    matches = [f for f in valid_files if os.path.basename(f) == target_filename]
    
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        # Если несколько совпадений, возвращаем первое
        return matches[0]
    
    return None

def process_file(file_path: str, valid_files: Set[str]) -> Dict:
    """
    Обработать один файл и проверить все ссылки в нём
    """
    full_path = BASE_DIR / file_path
    
    if not full_path.exists():
        return {
            'file': file_path,
            'status': 'error',
            'message': 'Файл не существует',
            'links_checked': 0,
            'links_updated': 0,
            'issues': []
        }
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    links = find_markdown_links(content)
    
    result = {
        'file': file_path,
        'status': 'ok',
        'links_checked': len(links),
        'links_updated': 0,
        'issues': [],
        'updates': []  # Список обновлений для применения
    }
    
    for link, line_num, line_content in links:
        # Разрешаем путь
        resolved = resolve_link_path(file_path, link)
        
        # Проверяем, существует ли в valid_files
        if not check_link_exists(resolved, valid_files):
            # Ссылка не ведёт на валидный файл
            # Пытаемся найти правильный путь
            target_filename = os.path.basename(link).split('#')[0]  # Убираем якорь
            
            if target_filename.endswith('.md'):
                correct_path = find_correct_path(target_filename, valid_files)
                
                if correct_path:
                    # Нашли правильный путь
                    result['issues'].append({
                        'type': 'wrong_path',
                        'line': line_num,
                        'old_link': link,
                        'new_link': correct_path,
                        'context': line_content
                    })
                    result['updates'].append({
                        'old': link,
                        'new': correct_path
                    })
                    result['links_updated'] += 1
                else:
                    # Файл не найден в index.md
                    result['issues'].append({
                        'type': 'missing',
                        'line': line_num,
                        'link': link,
                        'resolved': resolved,
                        'context': line_content
                    })
            else:
                result['issues'].append({
                    'type': 'missing',
                    'line': line_num,
                    'link': link,
                    'resolved': resolved,
                    'context': line_content
                })
    
    return result

def apply_updates(file_path: str, updates: List[Dict]) -> bool:
    """
    Применить обновления к файлу
    """
    if not updates:
        return False
    
    full_path = BASE_DIR / file_path
    
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    for update in updates:
        old = update['old']
        new = update['new']
        # Заменяем только полные вхождения ссылки
        content = content.replace(f']({old})', f']({new})')
    
    if content != original_content:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    
    return False

def main():
    print("Загрузка списка валидных файлов из index.md...")
    valid_files = load_valid_files()
    print(f"Найдено {len(valid_files)} валидных файлов")
    
    # Получаем список всех файлов для проверки
    files_to_check = list(valid_files)
    
    total_checked = 0
    total_updated = 0
    total_issues = 0
    modified_files = []
    
    print("\nНачинаю проверку файлов...")
    
    for file_path in files_to_check:
        result = process_file(file_path, valid_files)
        
        if result['status'] == 'error':
            continue
        
        total_checked += result['links_checked']
        total_updated += result['links_updated']
        total_issues += len(result['issues'])
        
        if result['updates']:
            # Применяем обновления
            if apply_updates(file_path, result['updates']):
                modified_files.append({
                    'file': file_path,
                    'updates': result['updates'],
                    'issues': result['issues']
                })
    
    print(f"\n=== ОТЧЁТ ===")
    print(f"Проверено ссылок: {total_checked}")
    print(f"Обновлено ссылок: {total_updated}")
    print(f"Всего проблем найдено: {total_issues}")
    print(f"Изменено файлов: {len(modified_files)}")
    
    if modified_files:
        print("\n=== ИЗМЕНЁННЫЕ ФАЙЛЫ ===")
        for item in modified_files[:20]:  # Показываем первые 20
            print(f"\n{item['file']}:")
            for issue in item['issues']:
                if issue['type'] == 'wrong_path':
                    print(f"  Строка {issue['line']}: {issue['old_link']} -> {issue['new_link']}")
                else:
                    print(f"  Строка {issue['line']}:Missing link: {issue.get('link', 'N/A')}")
        
        if len(modified_files) > 20:
            print(f"\n... и ещё {len(modified_files) - 20} файлов")
    
    # Сохраняем полный отчёт
    report_file = BASE_DIR / "links_update_report.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write("# Отчёт об обновлении ссылок\n\n")
        f.write(f"- **Дата:** 2026-03-09\n")
        f.write(f"- **Проверено ссылок:** {total_checked}\n")
        f.write(f"- **Обновлено ссылок:** {total_updated}\n")
        f.write(f"- **Всего проблем найдено:** {total_issues}\n")
        f.write(f"- **Изменено файлов:** {len(modified_files)}\n\n")
        
        if modified_files:
            f.write("## Изменённые файлы\n\n")
            for item in modified_files:
                f.write(f"### {item['file']}\n\n")
                for issue in item['issues']:
                    if issue['type'] == 'wrong_path':
                        f.write(f"- Строка {issue['line']}: `{issue['old_link']}` → `{issue['new_link']}`\n")
                    else:
                        f.write(f"- Строка {issue['line']}: Missing link: `{issue.get('link', 'N/A')}`\n")
                f.write("\n")
    
    print(f"\nПолный отчёт сохранён в {report_file}")

if __name__ == '__main__':
    main()
