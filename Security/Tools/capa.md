# Capa

## Definitions

**Capa** — open-source инструмент от Mandiant FLARE team для анализа возможностей исполняемых файлов. Определяет, что программа может делать (сетевое взаимодействие, работа с реестром, обфускация и т.д.), помогая аналитикам malware и reverse engineers быстро понимать поведение неизвестных бинарных файлов.

- **Репозиторий:** [mandiant/capa](https://github.com/mandiant/capa)
- **Лицензия:** Apache 2.0
- **Язык реализации:** Python

## Basic Concepts

### Идентификация возможностей

Capa определяет функциональные возможности программы через статический анализ бинарных файлов:
- Сетевое взаимодействие (HTTP, DNS, TCP/UDP)
- Работа с файловой системой и реестром
- Создание процессов и потоков
- Техники уклонения от обнаружения
- Признаки бэкдоров и кейлоггеров

### Форматы файлов и режимы анализа

- **Поддерживаемые форматы:** PE (Windows), ELF (Linux), .NET сборки
- **Статический анализ:** Анализ бинарных файлов без запуска
- **Динамический анализ:** Обработка отчетов из песочниц (VirusTotal, DRAKVU)

### Интеграция с MITRE ATT&CK

Все обнаруженные возможности автоматически сопоставляются с тактиками и техниками матрицы MITRE ATT&CK, что позволяет:
- Классифицировать поведение по стандартной таксономии
- Сравнивать образцы с известными семействами malware
- Генерировать отчеты для threat intelligence

### Интеграции с reverse engineering инструментами

- **IDA Pro:** Плагин capa Explorer (доступен через репозиторий плагинов IDA)
- **Ghidra:** Плагин для интеграции результатов анализа в интерфейс Ghidra
- **CLI:** Автономное использование через командную строку

### Правила Capa

Анализ основан на правилах из репозитория [mandiant/capa-rules](https://github.com/mandiant/capa-rules):

- **Формат правил:** YAML-подобный синтаксис с логическими операторами (`and`, `or`, `not`, `some`, `range`)
- **Типы признаков:**
  - API вызовы: `api: kernel32.CreateProcessA`
  - Строки: `string: "cmd.exe"`
  - Числовые константы: `number: 0x1000`
  - Байтовые последовательности: `bytes: 55 8B EC`
  - Импорт/экспорт: `import: msvcrt.system`
  - Ссылки на другие правила: `match: create process`
- **Namespace:** Правила организованы по категориям (`host-interaction/process`, `anti-analysis/sandbox`, `data-manipulation/obfuscation`)

## Practical Scenarios

### Установка

```bash
# Установка через pip
pip install capa

# Или скачать готовый бинарник с GitHub Releases
# https://github.com/mandiant/capa/releases
```

### Базовый анализ исполняемого файла

```bash
# Анализ PE файла (Windows)
capa malware.exe

# Анализ ELF файла (Linux)
capa suspicious_binary.elf

# Анализ .NET сборки
capa dotnet_app.exe

# Вывод в JSON формате (для автоматизации)
capa malware.exe -j > results.json

# Вывод в verbose режиме (детальная информация)
capa malware.exe -v
```

### Пример вывода

```
+------------------------+-------------------------------------------------------------
| ATT&CK Tactic          | ATT&CK Technique
|------------------------+-------------------------------------------------------------
| DEFENSE EVASION        | Obfuscated Files or Information [T1027]
| DISCOVERY              | Query Registry [T1012]
| EXECUTION              | Command and Scripting Interpreter: Windows Command Shell [T1059.003]
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

**Интерпретация:** Файл умеет выполнять команды, работать с реестром, создавать процессы, содержит обфусцированные данные и пытается обнаружить песочницу.

### Анализ с кастомными правилами

```bash
# Использовать собственный набор правил
capa malware.exe --rules /path/to/custom-rules/

# Объединить стандартные и кастомные правила
capa malware.exe --rules /opt/capa-rules/ --rules /home/user/my-rules/
```

### Интеграция в CI/CD pipeline для malware triage

```bash
#!/bin/bash
# Автоматический анализ новых образцов
for file in /samples/new/*.exe; do
    capa "$file" -j | jq '.attack[]' >> threat_intel_report.json
done
```

### Динамический анализ через отчеты песочниц

```bash
# Анализ отчета DRAKVU sandbox
capa --format drakvuv-report sandbox_report.json

# Анализ отчета VirusTotal
capa --format vtcap-report vt_report.json
```

## Additional Information

### Создание собственных правил

Аналитики могут создавать кастомные правила для обнаружения специфических техник или семейств вредоносного ПО:

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
    mbc:
      - Execution::Remote Thread Creation [F0018]
    att&ck:
      - Execution::Command and Scripting Interpreter [T1059]
    references:
      - https://example.com/technique
    examples:
      - suspicious_sample.exe:0x401000
  features:
    - or:
      - api: kernel32.CreateRemoteThread
      - api: ntdll.NtCreateThreadEx
```

**Документация по созданию правил:** [capa-rules documentation](https://github.com/mandiant/capa-rules/blob/master/doc/format.md)

### Troubleshooting

#### Капсуляция "No capabilities found"

**Причина:** Файл не распознан или не содержит анализируемых признаков.

**Решение:**
- Проверьте формат файла (поддерживаются PE, ELF, .NET)
- Убедитесь, что файл не упакован (upx, themida и т.д.) — распакуйте перед анализом
- Используйте флаг `-v` для детальной диагностики

#### Медленный анализ больших файлов

**Решение:**
- Ограничьте анализ конкретными функциями: `capa file.exe --function 0x401000`
- Используйте кэширование результатов

#### Конфликт версий правил

**Причина:** Версия capa не соответствует версии набора правил.

**Решение:**
- Убедитесь, что версии capa и capa-rules синхронизированы
- Обновите оба компонента: `pip install --upgrade capa && git pull` в capa-rules

### Связанные инструменты

- **[DRAKVUF](https://github.com/tklengyel/drakvuf)** — Hypervisor-based agentless malware analysis
- **[YARA](https://github.com/VirusTotal/yara)** — Pattern matching для malware analysis
- **[FLOSS](https://github.com/mandiant/flare-floss)** — Извлечение обфусцированных строк из бинарных файлов

### Ресурсы

- **Официальная документация:** [capa documentation](https://github.com/mandiant/capa/wiki)
- **База правил:** [mandiant/capa-rules](https://github.com/mandiant/capa-rules)
- **MITRE ATT&CK:** [attack.mitre.org](https://attack.mitre.org/)
