# Capa: Автоматизированный анализ возможностей исполняемых файлов

## Определения

**Capa** — open-source инструмент от команды Mandiant FLARE (в составе Google Cloud), предназначенный для автоматической идентификации функциональных возможностей (capabilities) в исполняемых файлах. Инструмент реализует статический анализ для ответа на вопрос: «Что эта программа может делать?», сопоставляя признаки внутри бинарного файла с базой экспертных правил.

- **Репозиторий:** [mandiant/capa](https://github.com/mandiant/capa)
- **База правил:** [mandiant/capa-rules](https://github.com/mandiant/capa-rules)
- **Лицензия:** Apache 2.0
- **Язык реализации:** Python (с поддержкой нативных бинарных сборок)

## Основные концепции

### Идентификация возможностей

Capa определяет функционал программы через статический анализ без её фактического запуска. Основные выявляемые категории:
- **Сетевое взаимодействие:** HTTP, DNS, TCP/UDP, работа с WinHTTP/WinInet.
- **Взаимодействие с хостом:** Работа с файловой системой, реестром Windows, службами.
- **Управление процессами:** Инъекции кода, создание потоков, перечисление процессов.
- **Анти-анализ:** Обнаружение песочниц, виртуальных сред (VM-detection) и отладчиков.
- **Вредоносная активность:** Признаки бэкдоров, кейлоггеров, кражи учетных данных (включая Cloud-credentials AWS/Cloudflare).

### Поддерживаемые форматы и архитектуры

- **Форматы:** PE (Windows EXE/DLL), ELF (Linux), .NET сборки (C#, VB.NET).
- **Архитектуры:** x86, x64, ARM64 (нативная поддержка с 2025 года).
- **Режимы анализа:**
    - **Статический:** Анализ бинарного файла через бэкенды дизассемблирования.
    - **Динамический:** Обработка отчетов из песочниц (DRAKVUF, VirusTotal, Cape Sandbox).

### Аналитические бэкенды (Engines)

Capa использует различные движки для извлечения признаков:
- **Vivisect:** Дефолтный бэкенд для PE-файлов, обеспечивающий глубокий анализ потока управления.
- **SMDA:** Быстрый бэкенд для восстановления функций, часто применяемый в автоматизированных пайплайнах.
- **PyGhidra (v9.4+):** Современная интеграция с Ghidra для высококачественного анализа и декомпиляции.
- **dnfile / Net-Inspect:** Специализированные инструменты для глубокого разбора .NET метаданных и байт-кода.

### Интеграция с MITRE ATT&CK и MBC

Результаты сопоставляются с глобальными базами знаний:
- **MITRE ATT&CK:** Классификация по тактикам (Execution, Persistence и др.) и техникам.
- **Malware Behavior Catalog (MBC):** Детальное описание специфических техник вредоносного ПО.

### Правила Capa (Rules Engine)

Анализ основан на YAML-правилах. Логика строится на операторах `and`, `or`, `not`, `some`, `range`, `optional`.
**Типы признаков (Features):**
- `api`: Вызовы функций (например, `kernel32.CreateProcessA`).
- `string`: Текстовые строки (поддерживаются регулярные выражения).
- `number`: Числовые константы (например, магические числа криптоалгоритмов).
- `bytes`: Байтовые последовательности (сигнатуры).
- `import` / `export`: Функции в таблицах импорта/экспорта.
- `characteristic`: Свойства (например, наличие манифеста или секций).
- `match`: Рекурсивная ссылка на результаты выполнения других правил.

## Практические сценарии

### Установка

```bash
# Установка через pip (рекомендуется Python 3.10+)
pip install flare-capa

# Загрузка нативных бинарных файлов (Windows/Linux/macOS)
# https://github.com/mandiant/capa/releases
```

### Базовое использование CLI

```bash
# Стандартный анализ PE-файла
capa malware.exe

# Анализ ELF-файла с использованием бэкенда SMDA
capa -b smda suspicious_binary.elf

# Анализ .NET приложения (автоопределение)
capa dotnet_app.exe

# Вывод детальной информации (verbose) с указанием адресов срабатывания
capa -vv malware.exe

# Сохранение результатов в JSON для автоматизации
capa malware.exe -j > results.json
```

### Пример интерпретации вывода

```text
+------------------------+-------------------------------------------------------------
| ATT&CK Tactic          | ATT&CK Technique
|------------------------+-------------------------------------------------------------
| DEFENSE EVASION        | Obfuscated Files or Information [T1027]
| DISCOVERY              | Query Registry [T1012]
| EXECUTION              | Command and Scripting Interpreter [T1059]
+------------------------+-------------------------------------------------------------

+------------------------+-------------------------------------------------------------
| CAPABILITY             | NAMESPACE
|------------------------+-------------------------------------------------------------
| run command            | host-interaction/cli
| read registry value    | host-interaction/registry
| create process         | host-interaction/process
| check for sandbox      | anti-analysis/sandbox/vm-detection
| contain obfuscated data| data-manipulation/obfuscation
+------------------------+-------------------------------------------------------------
```

### Использование кастомных правил

Вы можете использовать собственные наборы правил для поиска специфических угроз:

```bash
# Запуск со своим набором правил (отключает стандартные)
capa malware.exe --rules /path/to/my-rules/

# Добавление кастомных правил к стандартным
capa malware.exe --rules ./standard-rules/ --rules ./my-private-rules/
```

### Анализ динамических отчетов

```bash
# Анализ отчета DRAKVUF (агентный анализ гипервизора)
capa --format drakvuv-report sandbox_report.json

# Анализ JSON-отчета VirusTotal
capa --format vtcap-report vt_report.json
```

### Интеграция в пайплайны (Python API)

Пример скрипта для триажа:

```python
import capa.main
import capa.rules

# Инициализация правил
rules = capa.rules.RuleSet(capa.main.get_default_rules())
# Выбор экстрактора (автоопределение бэкенда)
extractor = capa.main.get_extractor("./malware.exe", "vivisect", "auto")

# Поиск возможностей
capabilities, counts = capa.main.find_capabilities(rules, extractor)

for rule_name, matches in capabilities.items():
    if rules[rule_name].meta.get("att&ck"):
        print(f"[!] Обнаружена техника ATT&CK: {rule_name}")
```

## Дополнительная информация

### Интеграция с инструментами RE

- **IDA Pro:** Плагин Capa Explorer (Qt-интерфейс, поддержка через репозиторий плагинов).
- **Ghidra:** Интеграция через PyGhidra, позволяющая использовать движок Ghidra для CLI-анализа.
- **Binary Ninja:** Плагин для визуализации результатов непосредственно в графе управления.
- **Capa Explorer Web:** Веб-интерфейс для визуализации JSON-отчетов без установки тяжелого ПО.

### Создание собственных правил

Пример правила для обнаружения инъекции в удаленный поток:

```yaml
rule:
  meta:
    name: Create Remote Thread
    namespace: host-interaction/process/create
    authors:
      - analyst@company.com
    scopes:
      static: function
      dynamic: process
    att&ck:
      - Execution::Command and Scripting Interpreter [T1059]
    mbc:
      - Execution::Remote Thread Creation [F0018]
    examples:
      - suspicious_sample.exe:0x401000
  features:
    - or:
      - api: kernel32.CreateRemoteThread
      - api: ntdll.NtCreateThreadEx
```

### Оптимизация и Troubleshooting

#### Низкая скорость анализа
- **Byte Pre-filtering:** В версиях 2025+ включено по умолчанию, пропускает нерелевантные функции.
- **Кэширование:** Vivisect сохраняет `.viv` файлы для ускорения повторного анализа.
- **Ограничение функций:** Используйте `--function 0xADDR` для точечного анализа.

#### Ошибка "No capabilities found"
1. **Упаковка:** Проверьте наличие упаковщиков (UPX, Themida). Используйте `-vv` для поиска правила "file is packed". Распакуйте перед анализом.
2. **Тип файла:** Убедитесь, что файл является поддерживаемым бинарным форматом, а не текстовым скриптом или ресурсом.
3. **Обновление:** Синхронизируйте версии инструмента и правил: `pip install --upgrade flare-capa`.

### См. также

- **[FLOSS](https://github.com/mandiant/flare-floss)** — Извлечение обфусцированных строк.
- **[YARA](https://github.com/VirusTotal/yara)** — Сигнатурный поиск по паттернам.
- **[MITRE ATT&CK](https://attack.mitre.org/)** — Справочник техник атак.
- [Инструменты безопасности](./security_tools.md) — Общий индекс.

### Ресурсы

- **Rules Browser:** [mandiant.github.io/capa/rules](https://mandiant.github.io/capa/rules)
- **Документация по формату правил:** [capa-rules spec](https://github.com/mandiant/capa-rules/blob/master/doc/format.md)
