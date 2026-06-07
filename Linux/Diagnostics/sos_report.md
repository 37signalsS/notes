# Диагностика системы: sos report и sosdiff

## Определение

**`sos report`** — универсальный инструмент диагностики для Linux, написанный на языке Python. Предназначен для сбора исчерпывающих диагностических данных из системы без внесения изменений в конфигурацию. Является стандартом для службы поддержки Oracle Linux (OL) при начале процесса устранения неполадок.

**`sosdiff`** — утилита для сравнения двух отчётов `sos report`. Позволяет выявлять различия между "рабочей" и "проблемной" системами, сравнивать конфигурации или отслеживать изменения на одном сервере во времени.

## Базовые концепции

### Назначение sos report

Инструмент собирает информацию из множества источников:

- Конфигурационные файлы из `/etc`
- Файлы журналов (логи) из `/var/log`
- Вывод системных команд
- Данные о производительности `sar (System Activity Reporter)`
- Информацию об оборудовании
- Структуры данных ядра (`/proc`, `/sys`)

### Структура полученного архива

После распаковки архива создаётся директория с подкаталогами и файлами. Ключевая информация доступна через символические ссылки:

- `cmdline` — параметры загрузки ядра
- `date` — дата и время запуска сбора данных
- `dmidecode` — подробная информация об оборудовании (BIOS, CPU, Memory)
- `free` — состояние оперативной памяти
- `hostname` — сетевое имя системы
- `installed-rpms` — список установленных пакетов `RPM (Red Hat Package Manager)`
- `last` — история входов пользователей и перезагрузок
- `lsmod` — список загруженных модулей ядра
- `lspci` — информация о шине и устройствах `PCI (Peripheral Component Interconnect)`
- `mount` — список смонтированных файловых систем
- `uname` — версия ядра и архитектура
- `uptime` — время работы и средняя нагрузка (Load Average)

**Основные каталоги:**

- `etc/` — копия конфигурационных файлов системы
- `sos_commands/` — структурированный вывод всех выполненных команд
- `sos_reports/` — сформированные отчёты в форматах HTML, TXT, JSON
- `var/log/` — системные и прикладные журналы

### Назначение sosdiff

Утилита входит в состав пакета Oracle Linux Enhanced Diagnostics (OLED) и запускается через `oled sosdiff`. Она выполняет посекционное сравнение двух архивов по различным модулям:

- `rpms.py` — различия в версиях установленных пакетов
- `kernel_modules.py` — несовпадения в загруженных модулях ядра
- `sysctl.py` — различия в параметрах `sysctl`
- `network_settings.py` — сравнение конфигурации сети
- `mounts.py` — различия в точках монтирования
- `meminfo.py` — сравнение характеристик памяти

## Практические сценарии

### Установка инструментов

**Oracle Linux 6 и 7:**

```bash
sudo yum install sos
```

**Oracle Linux 8 и 9:**

```bash
sudo dnf install sos
```

### Выполнение сбора данных

Для получения наиболее полной информации рекомендуется использовать следующие команды в зависимости от версии ОС:

**Oracle Linux 6 и 7:**

```bash
sudo sosreport --batch --all-logs -k sar.all_sar=on
# → /var/tmp/sosreport-hostname-YYYY-MM-DD-xxxxxx.tar.xz
```

**Oracle Linux 8:**

```bash
sudo sos report --batch --all-logs -k sar.all-sar=on
# → /var/tmp/sosreport-hostname-YYYY-MM-DD-xxxxxx.tar.xz
```

**Oracle Linux 9:**

```bash
sudo sos report --batch --all-logs -e sar -k sar.all-sar=on
# → /var/tmp/sosreport-hostname-YYYY-MM-DD-xxxxxx.tar.xz
```

**Описание ключевых параметров:**

- `--batch` — запуск в неинтерактивном режиме (имя хоста и метка времени подставляются автоматически)
- `--all-logs` — сбор журналов без ограничения по размеру (по умолчанию длинные файлы могут усекаться)
- `-k sar.all-sar=on` — сбор данных `sar` за весь доступный период (вместо стандартных последних суток)
- `-e sar` — принудительное включение плагина `sar` (в OL9 плагин может быть отключён по умолчанию)

### Управление плагинами

Просмотр всех доступных модулей сбора данных:

```bash
sudo sos report -l
# → [plugin]          [status]      [description]
#   ata               active        ATA controllers and drives
#   block             active        Block devices and subsystems
#   ...
```

### Интеграция с sysstat

Для корректного сбора данных `sar` в системе должен быть настроен пакет `sysstat`. Подробную инструкцию см. в разделе [Установка и настройка sysstat](./Performance/sar.md#установка-и-настройка-sysstat).

### Сравнение отчётов (sosdiff)

```bash
oled sosdiff <каталог_1> <каталог_2>
```

**Полезные опции:**

- `-d, --detail` — детальный вывод (показывает полные значения изменившихся параметров)
- `-o, --override` — игнорирование различий в версиях ОС или архитектурах при сравнении
- `-c, --color` — включение цветовой разметки (рекомендуется просматривать через `less -r`)

**Примеры использования:**

```bash
# Сравнение состояния системы до и после инцидента
oled sosdiff report_before/ report_after/

# Сравнение физического сервера и виртуальной машины (с игнорированием различий платформ)
oled sosdiff --override report_baremetal/ report_vm/
```

### Обфускация (анонимизация) данных

Маскирование чувствительных данных (IP-адреса, пароли, ключевые слова) перед передачей архива третьим лицам.

**OL 8 и 9 — маскирование в процессе сбора:**

```bash
sudo sos report --clean --batch --keywords MySecretKey --all-logs
```

**OL 8 и 9 — очистка уже существующего архива:**

```bash
sudo sos clean --batch --keywords MySecretKey sosreport-file.tar.xz
# → /var/tmp/sosreport-file-obfuscated.tar.xz
```

**OL 7 — использование внешней утилиты:**

```bash
sudo yum install soscleaner
sudo soscleaner sosreport-file.tar.xz
```

### Конфигурация по умолчанию

Постоянные параметры можно зафиксировать в файле `/etc/sos/sos.conf`:

```ini
[global]
batch = yes

[report]
all-logs = yes
enable-plugins = sar

[plugin_options]
sar.all-sar=on
```

## Дополнительная информация

### Анализ собранных данных

Пример извлечения ключевой информации из распакованного архива:

```bash
# Определение версии ядра
cat uname
# → Linux my-test 5.4.17-2136.315.5.el8uek.x86_64

# Получение модели оборудования
grep Product dmidecode
# → Product Name: ORACLE SERVER X6-2L

# Поиск критических ошибок в системном журнале
grep -i "link down" var/log/messages

# Идентификация устройства по адресу шины PCI
grep "23:00.1" lspci
# → 23:00.1 Fibre Channel [0c04]: Emulex Corporation...

# Проверка событий службы multipath
grep multipathd var/log/messages | grep "Jul 12" | grep mpathr
```

### Рекомендации по эксплуатации

1. **Оперативность:** собирайте отчёт как можно быстрее после обнаружения инцидента.
2. **Эталон:** сохраняйте "чистый" отчёт (`sos report`) исправной системы для последующего сравнения через `sosdiff`.
3. **Полнота:** всегда используйте флаг `--all-logs` для предотвращения усечения важных журналов.
4. **Актуальность:** регулярно обновляйте пакет `sos` для поддержки новых плагинов и форматов.
5. **Контекст:** включайте сбор данных `sar` для анализа ретроспективной нагрузки на ресурсы.

### Полезные ссылки

- [Официальная документация Oracle Linux 9 по sos](https://docs.oracle.com/en/operating-systems/oracle-linux/9/sos/about_the_sos_command.html)
- [Статья Oracle: sos report — Universal Diagnostic Tool](https://blogs.oracle.com/linux/post/sos-report)
- [Статья Oracle: sosdiff — Compare Two Linux sos reports](https://blogs.oracle.com/linux/oled-sosdiff)
