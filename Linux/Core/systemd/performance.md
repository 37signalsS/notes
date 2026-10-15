# systemd-analyze: Анализ производительности и диагностика

## Определения

* **`systemd-analyze`** — это комплексная системная утилита в составе `systemd`, предназначенная для профилирования процесса загрузки, аудита безопасности юнитов, верификации конфигурации и отладки внутренних механизмов менеджера служб.
* **Критическая цепь (Critical Chain)** — направленный ациклический граф (DAG) зависимостей, определяющий минимальное время, необходимое для достижения конкретного целевого состояния (таргета). Задержка любого юнита в этой цепи напрямую увеличивает общее время старта системы.
* **Уровень подверженности (Exposure Level)** — числовая оценка (от 0.0 до 10.0), отражающая поверхность атаки сервиса. Вычисляется на основе применяемых механизмов песочницы (Sandboxing) и ограничений привилегий.
* **Юнит (Unit)** — основной объект управления в systemd: служба (`service`), точка монтирования (`mount`), сокет (`socket`), таймер (`timer`), устройство (`device`), таргет (`target`) и др.
* **Таргет (Target)** — специальный юнит, группирующий другие юниты и определяющий состояние системы (аналог runlevel в SysVinit). `multi-user.target` — аналог runlevel 3, `graphical.target` — аналог runlevel 5.
* **Песочница (Sandboxing)** — совокупность директив unit-файла, изолирующих сервис от остальной системы: `ProtectSystem`, `PrivateTmp`, `RestrictAddressFamilies`, `NoNewPrivileges` и др.

## Основные концепции

### Архитектура и принцип работы

`systemd-analyze` не является отдельным демоном — это frontend-утилита, которая извлекает данные из трёх основных источников:
1. **Журнал загрузки (journald)** — временные метки (timestamps) начала и завершения каждого юнита, записанные во время загрузки.
2. **D-Bus интерфейс менеджера** — актуальное состояние юнитов, их зависимости и статус.
3. **Метаданные unit-файлов** — директивы `After=`, `Before=`, `Wants=`, `Requires=`, таймауты и параметры запуска.

Утилита работает в двух режимах:
- **Offline-анализ** — используется при загрузке из LiveCD/initramfs для анализа чужой системы (флаг `--root=` или `--image=`).
- **Online-анализ** — работа с текущей запущенной системой (режим по умолчанию).

### Фазы загрузки системы

`systemd-analyze` разделяет процесс старта на четко разграниченные этапы, что позволяет локализовать проблемы:
* **Firmware (UEFI/BIOS)** — время инициализации оборудования перед передачей управления загрузчику. Не видимо в `systemd-analyze`, но влияет на общее время загрузки.
* **Загрузчик (Bootloader)** — время работы GRUB/systemd-boot до передачи управления ядру. Включает чтение конфигурации и decompression ядра.
* **Ядро (Kernel)** — время от инициализации загрузчиком до запуска процесса PID 1. Включает распаковку ядра и инициализацию базового оборудования.
* **initrd** — время работы начальной файловой системы в ОЗУ. Здесь происходит монтирование корневой ФС, настройка LVM/RAID и расшифровка разделов (LUKS).
* **Пользовательское пространство (Userspace)** — время от старта PID 1 до завершения активации `default.target`. Именно на этом этапе администратор может влиять напрямую через оптимизацию юнитов.

### Внутренние механизмы сбора данных

* **Journald markers:** systemd записывает в журнал специальные сообщения с временными метками для каждого юнита. `systemd-analyze` читает эти метки для построения временной шкалы.
* **CGroup accounting:** для юнитов с включенным `CPUAccounting=yes` и `MemoryAccounting=yes` доступна детальная статистика по ресурсам.
* **sd-bus introspection:** live-запросы к менеджеру через D-Bus для получения текущего состояния, количества запусков и таймаутов.

### Анализ безопасности и «песочницы»

Современный `systemd` (v250+) предоставляет мощные средства статического анализа безопасности:
* **Exposure Level:** Оценка `9.6 (UNSAFE)` означает практически отсутствие изоляции, тогда как `<3.0 (OK)` свидетельствует о применении строгих ограничений (`PrivateDevices`, `ProtectControlGroups`, `RestrictAddressFamilies` и др.).
* **Inspect-ELF:** (v253+) Инспекция исполняемых файлов на наличие метаданных, совместимости с архитектурой и соответствия политике безопасности.
* **Security hardening scoring:** Каждая директива песочницы имеет вес. Например, `ProtectSystem=strict` снижает рейтинг на 0.5, а `PrivateNetwork=yes` — на 0.3. Цель — довести рейтинг ниже 3.0 для production-сервисов.

## Команды и их назначение

### Сводка и общее время

| Команда | Назначение | Пример вывода |
| :--- | :--- | :--- |
| `systemd-analyze` | Общее время загрузки по фазам | `Startup finished in 2.5s (kernel) + 10.2s (userspace) = 12.7s` |
| `systemd-analyze time` | Детальная временная шкала early userspace | `Finish: time=1.2s` |
| `systemd-analyze blame` | Список юнитов по времени запуска (от самых медленных) | `7.345s network-manager.service` |

### Визуализация

| Команда | Назначение | Примечание |
| :--- | :--- | :--- |
| `systemd-analyze critical-chain [UNIT]` | Критическая цепь зависимостей | Показывает только последовательные зависимости, влияющие на общее время |
| `systemd-analyze plot [> boot.svg]` | Диаграмма Ганта загрузки в SVG | Требует установленного `graphviz` |
| `systemd-analyze dot --require [PATTERN]` | Граф зависимостей только с `Requires=` (без `Wants=`) | Позволяет увидеть жёсткие (обязательные) зависимости, отсеивая optional. | `systemd-analyze dot --require | dot -Tsvg > boot.svg` |

### Безопасность и верификация

| Команда | Назначение | Версия systemd |
| :--- | :--- | :--- |
| `systemd-analyze security [UNIT]` | Рейтинг безопасности юнита | v246+ |
| `systemd-analyze verify [UNIT...]` | Проверка синтаксиса и логических ошибок | — |
| `systemd-analyze inspect-elf BINARY` | Инспекция ELF-бинарника | v253+ |
| `systemd-analyze pcrlock` | Состояние PCR-блокировок TPM | v255+ |

### Вспомогательные команды

| Команда | Назначение |
| :--- | :--- |
| `systemd-analyze unit-paths` | Пути поиска unit-файлов |
| `systemd-analyze calendar "SPEC"` | Проверка синтаксиса и расчёт следующего срабатывания `OnCalendar` |
| `systemd-analyze exit-status CODE` | Расшифровка кода выхода процесса |
| `systemd-analyze fdstore [UNIT]` | Файловые дескрипторы, переданные в fdstore |
| `systemd-analyze dump [UNIT]` | Дамп внутреннего состояния юнита (свойства, зависимости, таймауты) |
| `systemd-analyze list-dependencies [UNIT]` | Рекурсивный список зависимостей юнита |

## Практические сценарии

### 1. Анализ времени и узких мест загрузки

Важно понимать разницу между `blame` и `critical-chain`: `blame` показывает длительность работы юнита, но не учитывает параллелизм.

```bash
# Общая сводка времени старта
systemd-analyze
# → Startup finished in 3.2s (kernel) + 1.5s (initrd) + 12.1s (userspace) = 16.8s

# Список служб по времени запуска (blame)
# ВНИМАНИЕ: Долгая работа службы не всегда замедляет общую загрузку, если она выполняется параллельно.
systemd-analyze blame
# → 7.345s network-manager.service
# → 2.120s dev-sda2.device

# Визуализация критической цепочки (истинные виновники задержки)
systemd-analyze critical-chain multi-user.target
# → multi-user.target @12.185s
# → └─nginx.service @10.500s +1.685s
```

#### Интерпретация critical-chain

```
multi-user.target @12.185s
├─nginx.service @10.500s +1.685s
│ └─network-online.target @8.200s +2.300s
│   └─NetworkManager-wait-online.service @6.800s +1.400s
```

В этом примере `NetworkManager-wait-online.service` — истинная причина задержки. `nginx.service` ждёт сеть, а сеть ждёт `NetworkManager`. Для ускорения загрузки можно:
- Отключить `NetworkManager-wait-online.service` на серверах без необходимости ожидания сети.
- Переключиться на `systemd-networkd` с более быстрым `wait-online`.
- Добавить `After=network.target` вместо `network-online.target`, если приложение может стартовать до полного поднятия маршрутов.

### 2. Глубокий аудит безопасности

```bash
# Общий рейтинг безопасности всех запущенных сервисов
systemd-analyze security

# Детальный разбор директив для конкретного юнита
systemd-analyze security nginx.service
# → Выведет таблицу с каждой директивой (например, CapabilityBoundingSet) и её влиянием на рейтинг.

# Проверка исполняемого файла на соответствие стандартам (v253+)
systemd-analyze inspect-elf /usr/bin/nginx
```

#### Интеграция с CI/CD

В конвейерах доставки можно валидировать security-рейтинг новых образов:

```bash
# Проверка всех юнитов в каталоге
systemd-analyze security /etc/systemd/system/*.service

# Fail-стратегия: прервать деплой, если Exposure Level > 5.0
for unit in /etc/systemd/system/*.service; do
  score=$(systemd-analyze security "$unit" | awk '/Exposure/ {print $2}')
  if (( $(echo "$score > 5.0" | bc -l) )); then
    echo "FAIL: $unit имеет Exposure Level $score"
    exit 1
  fi
done
```

### 3. Отладка конфигурации и окружения

```bash
# Проверка синтаксиса юнит-файлов (поиск опечаток и логических ошибок)
systemd-analyze verify /etc/systemd/system/myapp.service

# Поиск путей, где systemd ищет юниты
systemd-analyze unit-paths

# Проверка корректности календарного расписания
systemd-analyze calendar "Mon..Fri *-*-* 03:00:00"

# Преобразование числового кода выхода в понятное имя
systemd-analyze exit-status 226
# → 226 NAMESPACE
```

#### Верификация перед деплоем

```bash
# Проверить все юниты в каталоге
find /etc/systemd/system -name '*.service' -exec systemd-analyze verify {} +

# Или через glob
systemd-analyze verify /etc/systemd/system/*.service /etc/systemd/system/*.timer
```

### 4. Детальный анализ времени (systemd-analyze time)

Команда показывает точные временные метки начала и завершения early userspace, полезная для отладки initrd:

```bash
# Детальная временная метрика
systemd-analyze time
# → Finish: time=1.2s
# → Startup finished in 1.2s (kernel) + 0.8s (initrd) + 5.4s (userspace) = 7.4s
```

### 5. Визуализация графов и диаграмм

```bash
# Диаграмма Ганта загрузки (нужен graphviz)
systemd-analyze plot > boot.svg

# Граф зависимостей всех таргетов
systemd-analyze dot --to-pattern='*.target' --from-pattern='*.target' | dot -Tsvg > targets.svg

# Граф зависимостей конкретного сервиса
systemd-analyze dot nginx.service | dot -Tsvg > nginx-deps.svg
```

#### Интерпретация диаграммы Ганта

В SVG-файле:
- **Горизонтальные полосы** — юниты, длина = длительность.
- **Вертикальное выравнивание** — параллельное выполнение.
- **Критическая цепь** — самые длинные «падающие» полосы от нижнего таргета к верхнему.
- **Простои (gaps)** — пробелы между полосами указывают на незанятые ядра CPU.

### 6. Работа с внутренними структурами

```bash
# Просмотр содержимого хранилища файловых дескрипторов (fdstore)
# Позволяет проверить дескрипторы, которые сервис передал системе для сохранения при перезапуске.
systemd-analyze fdstore nginx.service

# Проверка состояния PCR (Platform Configuration Registers) через TPM (v255+)
systemd-analyze pcrlock

# Дамп внутреннего состояния юнита (свойства, зависимости, таймауты)
systemd-analyze dump nginx.service

# Рекурсивный список зависимостей юнита
systemd-analyze list-dependencies nginx.service
```

### 7. Анализ производительности сервисов (Runtime)

`systemd-analyze` полезен не только при загрузке. С его помощью можно анализировать поведение работающих сервисов:

```bash
# Проверка, сколько раз сервис перезапускался (индикатор нестабильности)
systemd-analyze dump nginx.service | grep NRestarts

# Просмотр таймаутов и лимитов
systemd-analyze dump nginx.service | grep -E 'Timeout|Limit'

# Проверка fdstore для отслеживания утечек дескрипторов
systemd-analyze fdstore nginx.service
```

### 8. Системный подход к оптимизации загрузки

#### Методология

1. **Измерьте baseline:** `systemd-analyze` и `systemd-analyze plot > boot-before.svg`.
2. **Выявите критическую цепь:** `systemd-analyze critical-chain default.target`.
3. **Определите параллелизм:** Проверьте, можно ли заменить `Requires=` на `Wants=` для не критических зависимостей.
4. **Удалите лишнее:** Отключите неиспользуемые сервисы: `systemctl disable --now <service>`.
5. **Ускорьте sequential-цепочки:** Используйте `socket-activation` и `dbus-activation` для отложенного запуска.
6. **Измерьте результат:** Сравните `systemd-analyze` после каждого изменения.

#### Практические паттерны ускорения

```bash
# Отключение ожидания сети (для серверов, где это не требуется)
sudo systemctl disable NetworkManager-wait-online.service
sudo systemctl mask systemd-networkd-wait-online.service

# Использование socket-activation вместо постоянного сервиса
sudo systemctl enable --now sshd.socket  # sshd запустится при первом подключении

# Уменьшение DefaultTimeoutStopSec для быстрого выключения
sudo systemctl set-property global DefaultTimeoutStopSec=5s
```

### 9. Автоматизация и мониторинг

#### Отслеживание динамики загрузки

```bash
# Логирование времени загрузки в файл
echo "$(date +%Y-%m-%d) $(systemd-analyze | grep 'Startup finished' | awk '{print $4}')" >> /var/log/boot-times.log

# Сравнение boot.svg между перезагрузками (нужен graphviz)
systemd-analyze plot > /var/www/boot-$(date +%Y%m%d).svg
```

#### Интеграция с Prometheus (node_exporter)

```bash
# systemd-analyze не экспортирует метрики напрямую, но можно использовать:
# 1. node_boot_time_seconds (из node_exporter)
# 2. Кастомный textfile collector:

cat <<'EOF' > /etc/node_exporter/textfile_collectors/systemd.prom
systemd_boot_seconds_total 16.8
systemd_kernel_seconds_total 3.2
systemd_initrd_seconds_total 1.5
systemd_userspace_seconds_total 12.1
EOF
```

#### CI-проверка регрессии загрузки

```bash
#!/bin/bash
# check-boot-regression.sh
THRESHOLD=15.0
CURRENT=$(systemd-analyze | grep 'Startup finished' | awk '{print $4}' | sed 's/s//')
if (( $(echo "$CURRENT > $THRESHOLD" | bc -l) )); then
  echo "REGRESSION: boot time $CURRENT > $THRESHOLD"
  exit 1
fi
echo "OK: boot time $CURRENT"
```

### 10. Работа с initrd и early boot

```bash
# Анализ компонентов initrd
lsinitramfs /boot/initrd.img | grep systemd

# Проверка размера initrd (меньше = быстрее загрузка)
ls -lh /boot/initrd.img

# Пересоздание минимального initrd (ускоряет загрузку)
sudo dracut -H --no-host-only --no-early-microcode /boot/initrd.img $(uname -r)
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `critical-chain` показывает длинную цепь | Serial-зависимости (`After=` без `Wants=`) | Замените `Requires=` на `Wants=` для не критических сервисов; используйте socket-activation. |
| `blame` показывает долгий сервис, но `critical-chain` чистый | Сервис выполняется параллельно и не влияет на критический путь | Можно игнорировать; оптимизация не даст ускорения загрузки. |
| `systemd-analyze time` показывает большой initrd | Медленная decompression или медленный storage | Используйте `lsinitramfs` для анализа; перейдите на faster storage (NVMe) или уменьшите initrd. |
| High Exposure Level (> 7.0) | Отсутствуют директивы sandboxing | Добавьте `ProtectSystem=strict`, `PrivateDevices=yes`, `NoNewPrivileges=yes`. |
| Сервис долго стартует после загрузки | Медленный DNS, зависание на подключении к БД | Используйте `systemd-analyze critical-chain <service>`; добавьте `ExecStartPre=` с таймаутом. |
| Boot time растёт после обновления | Новые сервисы или увеличенные зависимости | `systemd-delta` для просмотра переопределений; `systemd-analyze blame` для сравнения. |
| `plot` не генерирует SVG | `graphviz` не установлен | `sudo apt install graphviz` (Debian/Ubuntu) или `sudo dnf install graphviz` (RHEL). |

## Рекомендации по эксплуатации

1. **Измеряйте регулярно:** Ведите журнал `systemd-analyze` после каждого изменения. Рост времени на 10% — сигнал к аудиту.
2. **Визуализируйте:** `systemd-analyze plot > boot.svg` даёт больше информации, чем числовой вывод. Сохраняйте SVG в репозиторий для исторического сравнения.
3. **Критическая цепь vs blame:** Всегда анализируйте `critical-chain`, а не только `blame`. Долгий параллельный сервис не замедляет загрузку.
4. **Версионирование unit-файлов:** Храните конфигурацию в Git. Перед коммитом запускайте `systemd-analyze verify` в pre-commit hook.
5. **Socket activation:** Для инфраструктурных сервисов (ssh, dbus) предпочитайте socket-activation. Это убирает их из критической цепи.
6. **Ограничьте таймауты:** Устанавливайте `TimeoutStartSec=5s` для сервисов, которые могут стартовать быстро. По умолчанию 90s — слишком много.
7. **Песочница по умолчанию:** Создавайте шаблон unit-файла с базовыми директивами (`ProtectSystem=full`, `PrivateTmp=yes`, `NoNewPrivileges=yes`) и наследуйте его.
8. **Исключайте не нужное из initrd:** Удаляйте ненужные модули и утилиты из initrd через `/etc/dracut.conf` или `/etc/mkinitcpio.conf`.
9. **Мониторинг в production:** Настройте алерты на рост времени загрузки (>15s) и на появление новых юнитов в critical-chain.
10. **Документируйте изменения:** Любое изменение `systemd-analyze`-показателей должно быть связано с изменениями в конфигурации (ticket, commit).

## Ограничения и особенности

* `systemd-analyze` работает только с journald. Если логирование перенаправлено в syslog или отсутствует, временные метки могут быть недоступны.
* В контейнерах без systemd (Docker с `--pid=host` и без systemd) многие команды возвращают пустой вывод или ошибки.
* `systemd-analyze critical-chain` показывает только пути, влияющие на время. Если все зависимости параллельны, цепь будет короткой, даже если общее время загрузки большое.
* `systemd-analyze time` работает только для текущей загрузки. Для анализа прошлых загрузок используйте `journalctl --list-boots`.
* `inspect-elf` доступен только на архитектурах с ELF (x86, ARM, RISC-V). Не работает на macOS или Windows.
* Графы `dot` для систем с сотнями юнитов могут быть нечитаемыми. Используйте фильтры `--to-pattern` и `--from-pattern`.
* `systemd-analyze dump` выводит огромный объём данных. Направляйте его в `less` или фильтруйте через `grep`.
* В системах с `systemd` < 230 некоторые команды (`calendar`, `inspect-elf`, `pcrlock`) отсутствуют.

## Дополнительная информация

### Визуализация и экспорт

* **Диаграмма Ганта загрузки:** `systemd-analyze plot > boot.svg`. Самый наглядный способ увидеть перекрывающиеся процессы и простои.
* **Граф зависимостей:** `systemd-analyze dot --to-pattern='*.target' --from-pattern='*.target' | dot -Tsvg > targets.svg`. Позволяет увидеть связи между таргетами в формате Graphviz.

### См. также
* [Юниты, таргеты и зависимости](./systemd_units_overview.md) — основы структуры объектов.
* [Управление службами (systemctl)](./service_management.md) — базовые команды управления.
* [Диагностика загрузки](./boot_troubleshooting.md) — решение проблем при невозможности старта.
* [Таймеры systemd](./timers.md) — отладка расписаний и планировщика.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — анализ логов выполнения.
* [DNS-резолвер (systemd-resolved)](./systemd_resolved.md) — влияние DNS на время загрузки.
