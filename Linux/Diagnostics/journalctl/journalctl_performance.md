# Производительность и масштабирование journalctl

## Определения

**Throughput (Пропускная способность)** — максимальное количество сообщений в секунду, которое journald способен обрабатывать без потерь. Зависит от производительности диска, размера сообщений и настроек rate limiting.

**Backpressure (Обратное давление)** — ситуация, при которой потребитель логов (rsyslog, Promtail, journald-remote) не успевает обрабатывать входящий поток, что приводит к замедлению записи или потере данных.

**IOPS (Input/Output Operations Per Second)** — количество операций чтения/записи в секунду. Ключевая метрика для оценки влияния journald на подсистему хранения.

**Кардинальность полей (Field Cardinality)** — количество уникальных значений в поле журнала. Высококардинальные поля (REQUEST_ID, _PID) увеличивают размер индексов и объем хранилища.

## Основные концепции

### Архитектурные ограничения производительности

journald — это однопоточный демон, использующий `mmap()` для записи в файлы журнала. Ключевые узкие места:

| Компонент | Ограничение | Влияние |
| :--- | :--- | :--- |
| **Запись на диск** | Зависит от IOPS хранилища (HDD: ~100 IOPS, SSD: ~10K IOPS, NVMe: ~100K IOPS) | Задержка записи при высоком throughput |
| **Индексация** | Каждое поле индексируется отдельно | Увеличение размера с ростом количества полей |
| **Rate Limiting** | `RateLimitBurst` × `RateLimitIntervalSec` | Подавление сообщений при превышении лимита |
| **mmap()** | Активный файл не может быть удалён до ротации | Риск заполнения диска без ротации |
| **Сжатие** | LZ4/XZ для архивных файлов | CPU-нагрузка при чтении старых архивов |

### Ориентировочные метрики производительности

На типичном production-сервере (NVMe SSD, systemd 252+):

| Сценарий | Throughput | CPU | Диск |
| :--- | :--- | :--- | :--- |
| **Малый сервис** (100 msg/s, 100 байт) | 100 msg/s | <1% | ~1 MB/час |
| **Веб-сервер** (1K msg/s, 200 байт) | 1K msg/s | 1-2% | ~10 MB/час |
| **Высоконагруженный API** (10K msg/s, 300 байт) | 10K msg/s | 3-5% | ~100 MB/час |
| **Flood/DoS** (100K msg/s) | ~50K msg/s (ограничен rate limit) | 10-15% | ~1 GB/час |

**Важно:** Эти значения ориентировочные и зависят от конкретного железа, размера сообщений и количества полей.

### Когда journald становится bottleneck

**Симптомы:**
- `journalctl --disk-usage` показывает быстрый рост
- `systemctl status systemd-journald` показывает высокий CPU
- `Suppressed X messages` появляется регулярно
- Приложение пишет логи с задержкой (blocking I/O)
- `journalctl --since` работает медленно на больших архивах

**Диагностика:**
```bash
# Проверка нагрузки на диск
iostat -x 1 5

# Проверка размера журнала
journalctl --disk-usage

# Проверка rate limiting
journalctl -u systemd-journald | grep -i "suppressed"

# Проверка I/O latency
dstat --disk-util -d 1 5

# Проверка размера активного файла
ls -lh /var/log/journal/*/*.journal
```

### Оптимизация записи

**1. Настройка rate limiting:**
```ini
# /etc/systemd/journald.conf
[Journal]
# Для высоконагруженных серверов
RateLimitIntervalSec=10s
RateLimitBurst=50000

# Для отладочных сред (временно)
RateLimitIntervalSec=0
```

**2. Ограничение уровня логирования:**
```ini
[Journal]
# Сохранять только warning и выше (отсечь info/debug)
MaxLevelStore=warning

# Пересылать в syslog только error и выше
MaxLevelSyslog=err
```

**3. Оптимизация через unit-файлы:**
```ini
# /etc/systemd/system/noisy-app.service
[Service]
# Ограничение уровня логирования на уровне systemd
LogLevelMax=warning
# Или отключение вывода в journald полностью
# StandardOutput=null
# StandardError=null
```

**4. Принудительная ротация:**
```bash
# Ротация активного файла для снижения размера mmap
sudo journalctl --rotate

# Немедленная очистка старых архивов
sudo journalctl --vacuum-size=500M
```

### Оптимизация чтения

**1. Всегда используйте фильтры по метаданным:**
```bash
# БЫСТРО (индексированные поля)
journalctl -u nginx -p err --since "1 hour ago"

# МЕДЛЕННО (полнотекстовый поиск)
journalctl --grep "error" --since "1 hour ago"
```

**2. Ограничивайте временной диапазон:**
```bash
# Правильно
journalctl -u nginx --since "2024-05-01 12:00" --until "2024-05-01 13:00"

# Неправильно (полное сканирование)
journalctl -u nginx | grep "2024-05-01 12:00"
```

**3. Используйте оптимальные форматы вывода:**
```bash
# Быстрый (минимальные накладные расходы)
journalctl -u nginx --output=cat

# Парсимый (для jq)
journalctl -u nginx --output=json

# Медленный (избегайте в скриптах)
journalctl -u nginx --output=short-precise
```

**4. Кэширование результатов:**
```bash
# Для повторяющихся запросов — экспорт в файл
journalctl -u nginx --since "today" -o json > /tmp/nginx_logs.json
# Дальнейший анализ через jq (без повторного чтения journal)
jq '.MESSAGE' /tmp/nginx_logs.json | grep "error"
```

### Масштабирование: когда нужна альтернатива

**Пороговые значения для перехода на агент-based подход:**

| Метрика | Порог | Рекомендация |
| :--- | :--- | :--- |
| **Объем логов** | >10 GB/час | Переход на Vector/Fluent Bit |
| **Количество серверов** | >50 хостов | Централизованный сбор через агент |
| **Retention** | >30 дней | Вынос в Loki/Elasticsearch |
| **Корреляция** | Межсервисная | Централизованное хранилище |
| **Поиск** | Полнотекстовый | Индексируемое хранилище |

**Архитектура при масштабировании:**
```
[Сервер 1] → journald → Vector/Fluent Bit → ─┐
[Сервер 2] → journald → Vector/Fluent Bit → ─┤→ Loki/Elasticsearch
[Сервер N] → journald → Vector/Fluent Bit → ─┘         ↓
                                              Grafana / Kibana
```

**Сравнение подходов:**

| Критерий | journalctl (локально) | journald-remote | Vector/Fluent Bit | rsyslog |
| :--- | :--- | :--- | :--- | :--- |
| **Простота настройки** | Максимальная | Средняя | Средняя | Низкая |
| **Производительность** | Зависит от диска | Зависит от сети | Высокая | Высокая |
| **Фильтрация** | Мощная (индексы) | Ограниченная | Гибкая (transform) | Гибкая |
| **Retention** | Локальный диск | Центральный сервер | Определяется хранилищем | Файлы |
| **Масштабируемость** | Локальная | Хорошая | Высокая | Средняя |
| **Корреляция** | Одна машина | Несколько хостов | Глобальная | Несколько хостов |

### Мониторинг производительности journald

```bash
#!/bin/bash
# journal_perf_check.sh — проверка производительности journald

echo "=== Journald Performance Report ==="
echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo ""

# 1. Размер журнала
echo "--- Disk Usage ---"
journalctl --disk-usage
echo ""

# 2. Количество файлов
echo "--- File Count ---"
ls /var/log/journal/*/*.journal* 2>/dev/null | wc -l
echo ""

# 3. Активный файл
echo "--- Active Journal File ---"
ls -lh /var/log/journal/*/*.journal 2>/dev/null
echo ""

# 4. Rate limiting
echo "--- Rate Limiting ---"
journalctl -u systemd-journald --since "1 hour ago" | grep -i "suppressed" | tail -5
echo "(empty = no rate limiting triggered)"
echo ""

# 5. CPU и Memory
echo "--- Systemd-journald Resource Usage ---"
systemctl status systemd-journald --no-pager | head -15
echo ""

# 6. Storage mode
echo "--- Storage Mode ---"
systemctl show systemd-journald --property=Storage
echo ""

# 7. I/O на разделе /var/log
echo "--- I/O on /var/log ---"
iostat -x $(df /var/log --output=source | tail -1) 1 1 2>/dev/null || echo "iostat not available"
```

### Настройка для разных сценариев

**Маленький сервер (512 MB RAM, HDD):**
```ini
[Journal]
Storage=persistent
SystemMaxUse=200M
MaxRetentionSec=7day
MaxFileSec=1day
RateLimitIntervalSec=5s
RateLimitBurst=5000
Compress=yes
MaxLevelStore=info
```

**Высоконагруженный API-сервер (64 GB RAM, NVMe):**
```ini
[Journal]
Storage=persistent
SystemMaxUse=4G
SystemKeepFree=10G
SystemMaxFileSize=500M
MaxRetentionSec=30day
MaxFileSec=1day
RateLimitIntervalSec=10s
RateLimitBurst=100000
Compress=yes
MaxLevelStore=info
SyncIntervalSec=1m
LineMax=64K
```

**Сервер с контейнерами (Docker/Kubernetes node):**
```ini
[Journal]
Storage=persistent
SystemMaxUse=2G
MaxRetentionSec=14day
MaxFileSec=1day
RateLimitIntervalSec=5s
RateLimitBurst=50000
Compress=yes
# Не отключайте ForwardToSyslog, если rsyslog используется для централизации
ForwardToSyslog=no
```

### Оптимизация для чтения при большом объеме

```bash
# 1. Используйте --output=json и jq вместо grep
journalctl -u myapp --since "1h ago" -o json | jq 'select(.PRIORITY <= 3)'

# 2. Предварительная фильтрация по ближайшему индексу
# Сначала по времени (использует временной индекс), затем по полям
journalctl --since "1 hour ago" --until "1 hour ago" -u nginx -p err

# 3. Избегайте --grep на больших объемах
# Вместо: journalctl --grep "error" (полное сканирование)
# Используйте: journalctl -p err (индексированный приоритет)

# 4. Для анализа — экспорт и кэширование
journalctl --since "today" -o json > /tmp/today.json
# Анализ через jq (без повторного чтения journal)
jq -r 'select(.MESSAGE | test("error"; "i")) | .MESSAGE' /tmp/today.json | wc -l
```

## Дополнительная информация

### Влияние сжатия

| Алгоритм | Скорость сжатия | Коэффициент сжатия | CPU-нагрузка |
| :--- | :--- | :--- | :--- |
| **LZ4** | Быстрый | 2:1 – 3:1 | Низкая |
| **XZ** | Медленный | 3:1 – 5:1 | Высокая |

По умолчанию journald использует LZ4 для архивных файлов. Для снижения нагрузки на CPU при чтении старых архивов можно отключить сжатие (`Compress=no`), но это увеличит расход диска.

### Влияние SplitMode

| Режим | Количество файлов | Управление | Vacuum |
| :--- | :--- | :--- | :--- |
| `uid` | Много (по числу пользователей) | Сложное | Затрагивает все файлы |
| `machine` | Мало (1 системный + few user) | Простое | Предсказуемое |
| `none` | Минимум | Максимально простое | Максимально простое |

Для серверов с >100 сервисами рекомендуется `SplitMode=machine` для снижения количества файлов и упрощения мониторинга.

### Влияние версии systemd

| Версия | Улучшение производительности |
| :--- | :--- |
| **235+** | Оптимизированная индексация |
| **240+** | Улучшенное управление памятью |
| **245+** | Пространства имён (изоляция логов) |
| **248+** | Ускоренная компактификация |
| **250+** | Оптимизация mmap для больших файлов |
| **252+** | Улучшенная параллельная запись |

### Рекомендации для собеседований

**Вопрос:** "Логи заполняют диск. Что делаете?"
**Ответ:** Сначала `journalctl --disk-usage` для оценки, затем `journalctl --rotate && journalctl --vacuum-size=500M` для немедленного решения, потом настройка `SystemMaxUse` и `MaxRetentionSec` в `journald.conf` для профилактики.

**Вопрос:** "Какой throughput может обработать journald?"
**Ответ:** Зависит от железа. На NVMe SSD — до 50K msg/s при умеренном размере сообщений. На HDD — порядка 1K msg/s. Rate limiting по умолчанию — 10000 сообщений за 5 секунд.

**Вопрос:** "Когда стоит переходить от journalctl к Vector/Loki?"
**Ответ:** Когда нужна межсервисная корреляция, retention >30 дней, полнотекстовый поиск в web-интерфейсе, или объем логов >10 GB/час.

### См. также

- [journalctl: Обзор и концепции](./journalctl_overview.md)
- [Управление хранением и ротацией](./journalctl_management.md)
- [Конфигурация journald](../../SystemAdministration/Logging/journald.md)
- [Мониторинг сети через Prometheus](../../Diagnostics/Networking/network_monitoring_prometheus.md)
