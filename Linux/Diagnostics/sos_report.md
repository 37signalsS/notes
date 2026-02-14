# `sos report` и `sosdiff`

## Определение

`sos report` — универсальный инструмент диагностики для Linux, написанный на Python. Предназначен для сбора исчерпывающих диагностических данных из системы Linux без внесения изменений в конфигурацию. Является стандартным инструментом, запрашиваемым службой поддержки Oracle для начала процесса устранения неполадок.

`sosdiff` — утилита для сравнения двух отчётов `sos report`. Позволяет выявлять различия между "рабочей" и "проблемной" системами, сравнивать конфигурации или отслеживать изменения на одном сервере во времени.

## Базовые концепции

### Назначение sos report

`sos report` собирает информацию из множества источников:

- Конфигурационные файлы из `/etc`
- Файлы журналов из `/var/log`
- Вывод десятков системных команд
- Данные о производительности (включая `sar`)
- Информацию об оборудовании
- Структуры данных ядра ( `/proc`, `/sys`)

### Структура полученного архива

После распаковки `sos report` создаётся директория с подкаталогами:

**Символические ссылки (удобный доступ к ключевой информации):**
- `cmdline` — команда загрузки ядра
- `date` — дата/время выполнения sos report
- `dmidecode` — информация об оборудовании
- `free` — информация о памяти
- `hostname` — имя системы
- `installed-rpms` — список установленных пакетов
- `last` — история входов и перезагрузок
- `lsmod` — загруженные модули ядра
- `lspci` — PCI-устройства
- `mount` — смонтированные файловые системы
- `uname` — версия ядра
- `uptime` — время работы и средняя нагрузка

**Каталоги:**
- `boot` — информация о Grub
- `etc` — конфигурация системы
- `proc` — структуры данных ядра
- `run` — информация о запущенных процессах
- `sos_commands` — вывод всех выполненных команд (79 подкаталогов на OL9)
- `sos_logs` — журналы работы sos report
- `sos_reports` — отчёты в форматах HTML, TXT, JSON
- `sys` — структуры данных ядра и устройств
- `usr` — информация из `/usr`
- `var` — журналы из `/var/log`

### Назначение sosdiff

`sosdiff` входит в состав Oracle Linux Enhanced Diagnostics (OLED) и запускается через `oled sosdiff`. Сравнивает два отчёта `sos report` по множеству модулей:

- `rpms.py` — сравнение установленных пакетов
- `kernel_modules.py` — сравнение загруженных модулей
- `sysctl.py` — сравнение параметров ядра
- `network_settings.py` — сравнение сетевых настроек
- `mounts.py` — сравнение точек монтирования
- `lscpu.py` — сравнение характеристик CPU
- `meminfo.py` — сравнение памяти
- И другие модули

## Практические сценарии

### Установка sos

**Oracle Linux 6 и 7:**
```bash
sudo yum install sos
```

**Oracle Linux 8 и 9:**
```bash
sudo dnf install sos
```

### Выполнение sos report

Рекомендуемые команды для получения полных данных:

**Oracle Linux 6 и 7:**
```bash
sudo sosreport --batch --all-logs -k sar.all_sar=on
```

**Oracle Linux 8:**
```bash
sudo sos report --batch --all-logs -k sar.all-sar=on
```

**Oracle Linux 9:**
```bash
sudo sos report --batch --all-logs -e sar -k sar.all-sar=on
```

**Параметры:**
- `--batch` — запуск без интерактивного ввода (имя хоста и timestamp автоматически)
- `--all-logs` — сбор полных версий файлов из `/var/log` (без этого некоторые файлы усекаются)
- `-k sar.all-sar=on` — сбор всех данных `sar` за весь период (не только за 14 дней)
- `-e sar` — включение плагина sar (в OL9 отключён по умолчанию)

### Просмотр доступных плагинов

```bash
sudo sos report -l
```

### Установка sysstat (для sar данных)

```bash
sudo dnf install sysstat
sudo systemctl enable --now sysstat
```

### Использование sosdiff

```bash
oled sosdiff <dir1> <dir2>
```

**Полезные опции:**
- `-d, --detail` — подробный вывод с полными значениями конфигурации
- `-o, --override` — принудительное сравнение при несовпадении версий ОС или архитектуры
- `-c, --color` — цветной вывод (использовать с `less -r`)

**Примеры сравнения:**
```bash
# Сравнение до и после перезагрузки
oled sosdiff sosreport-test-2025-04-21-hzasqne sosreport-test-2025-04-21-qvbwphy

# Сравнение разных систем (с override)
oled sosdiff --override sosreport-ol8 sosreport-ol9

# Сравнение физического сервера и VM
oled sosdiff --override sosreport-baremetal sosreport-vm
```

### Обфускация (маскирование) данных

Иногда требуется скрыть чувствительные данные перед отправкой отчёта.

**Oracle Linux 8 и 9 — обфускация при сборе:**
```bash
sudo sos report --clean --batch --keywords SecretApp --all-logs -e sar -k sar.all-sar=on
```

**Oracle Linux 8 и 9 — обфускация после сбора:**
```bash
sudo sos clean --batch --keywords SecretApp sosreport-name.tar.xz
```

**Oracle Linux 7 — последующая обфускация через soscleaner:**
```bash
sudo yum install soscleaner
sudo soscleaner sosreport-name.tar.xz
```

Создаётся обфускационная карта для обратного преобразования.

### Настройка через sos.conf

Параметры можно сохранить в `/etc/sos/sos.conf`:

```ini
[global]
batch = yes

[report]
enable-plugins = sar
all-logs = yes

[plugin_options]
sar.all_sar=on

[clean]
keywords = SecretApp
```

## Дополнительная информация

### Анализ данных из sos report

Пример использования для диагностики проблемы с сетевым соединением:

```bash
# Определение типа системы
cat uname
# Linux my-test 5.4.17-2136.315.5.el8uek.x86_64

# Информация об оборудовании
grep Product dmidecode
# Product Name: ORACLE SERVER X6-2L

# Поиск сообщений об ошибках
grep -i "link down" var/log/messages

# Определение типа карты по адресу PCI
grep "23:00.1" lspci
# 23:00.1 Fibre Channel [0c04]: Emulex Corporation...

# Проверка multipath
grep multipathd var/log/messages | grep "Jul 12" | grep mpathr
```

### Рекомендации по использованию

1. **Запускать как можно скорее** после возникновения проблемы
2. **Сохранять базовый снимок** перед внесением существенных изменений в систему
3. **Использовать последнюю версию** sos
4. **Всегда собирать с флагом `--all-logs`** для получения полных журналов
5. **Включать данные sar** для анализа исторической производительности

### Выходные файлы

По умолчанию `sos report` сохраняет архив в `/var/tmp`:
- `sosreport-hostname-YYYY-MM-DD-xxxxxx.tar.xz` — основной архив
- `sosreport-hostname-YYYY-MM-DD-xxxxxx.tar.xz.sha256` — контрольная сумма

### Ссылки

- [Документация Oracle Linux 9 — sos](https://docs.oracle.com/en/operating-systems/oracle-linux/9/sos/about_the_sos_command.html)
- [Блог: sos report — Universal Diagnostic Tool](https://blogs.oracle.com/linux/post/sos-report)
- [Блог: sosdiff — Compare Two Linux sos reports](https://blogs.oracle.com/linux/oled-sosdiff)
