# Диагностика и устранение неполадок логирования

## Definitions

**Logging Troubleshooting** — процесс выявления и устранения сбоев на всех этапах жизненного цикла логов: генерация (приложение/ядро) → сбор (journald/files) → транспорт (Fluent Bit/Vector) → хранение и индексация (Loki/Elasticsearch).

**Backpressure (Обратное давление)** — ситуация, при которой система хранения не успевает принимать логи, что приводит к переполнению буферов на стороне агента сбора и возможной потере данных.

**High Cardinality (Высокая кардинальность)** — избыточное количество уникальных комбинаций меток (labels), которое перегружает индекс хранилища (характерно для Loki).

---

## Practical Scenarios

### 1. Отсутствуют логи за временной интервал

**Симптомы:** В интерфейсе Grafana/Kibana «дыры» в данных, хотя сервис работал без сбоев.

**Диагностика:**
1. **Проверка локального журнала (journald):**
   ```bash
   journalctl --verify
   # → PASS: ...
   # → FAIL: /var/log/journal/.../system.journal: Corrupted (Требуется очистка)
   ```
2. **Поиск сообщений о подавлении (Rate Limiting):**
   ```bash
   journalctl -u systemd-journald | grep "Suppressed"
   # → systemd-journald: Suppressed 1000 messages from /user.slice/...
   ```
   *Решение:* Увеличьте `RateLimitIntervalSec` и `RateLimitBurst` в `/etc/systemd/journald.conf`.
3. **Проверка синхронизации времени (NTP):**
   Если время на сервере «уплыло», логи могут записываться в прошлое или будущее.
   ```bash
   timedatectl status | grep "System clock synchronized"
   # → System clock synchronized: yes
   ```

---

### 2. Переполнение диска (/var/log)

**Симптомы:** Ошибка «No space left on device», невозможность старта сервисов.

**Диагностика:**
1. **Анализ дискового пространства:**
   ```bash
   df -h /var/log
   # → Filesystem      Size  Used Avail Use% Mounted on
   # → /dev/sda1        20G   19G     0 100% /
   ```
2. **Поиск «виновников»:**
   ```bash
   sudo du -sh /var/log/* | sort -rh | head -n 5
   # → 12G   /var/log/journal
   # → 4.5G  /var/log/nginx
   ```

**Решение:**
- **Очистка journald:** `sudo journalctl --vacuum-size=1G`.
- **Проверка logrotate:** Убедитесь, что конфигурация корректна: `sudo logrotate -d /etc/logrotate.conf` (Dry run).
- **Deleted-but-open файлы:** Если файл удален, но место не освободилось:
   ```bash
   sudo lsof +L1 | grep deleted
   # → nginx  1234  root  5w  REG  8,1  4500000  (deleted) /var/log/nginx/access.log
   ```
   *Решение:* Перезапустите процесс (например, `systemctl reload nginx`).

---

### 3. Сбои удаленной доставки (Fluent Bit → Loki)

**Симптомы:** Логи есть в `journalctl`, но не доходят до центрального хранилища.

**Диагностика:**
1. **Проверка здоровья бэкенда:**
   ```bash
   curl -I http://loki.internal:3100/ready
   # → HTTP/1.1 200 OK
   ```
2. **Анализ ошибок агента:**
   ```bash
   journalctl -u fluent-bit -n 50 --no-pager
   # → [error] [output:loki:loki.0] http_status=429 (Too Many Requests)
   # → [warn] [input:tail:0] memory limit reached, pausing...
   ```
   *Интерпретация:* 429 ошибка означает срабатывание лимитов Loki (Ingestion Rate). Пауза `memory limit` указывает на Backpressure.

3. **База позиций (Tail DB):**
   Если Fluent Bit «застрял» на одном месте, возможно повреждена SQLite база:
   ```bash
   file /var/log/fluent-bit-positions.db
   # → /var/log/fluent-bit-positions.db: SQLite 3.x database
   ```
   *Решение:* При повреждении удалите файл и перезапустите агент (он начнет чтение заново).

---

### 4. Проблемы с метаданными и High Cardinality

**Симптомы:** Поиск в Loki работает крайне медленно или выдает ошибку «Limit exceeded».

**Причина:** Использование динамических данных (UUID, Timestamp, IP) в качестве меток (Labels).
**Диагностика:**
1. Проверьте список меток:
   ```bash
   curl -s http://loki:3100/loki/api/v1/labels | jq
   ```
2. Если среди меток есть `user_id` или `request_id` — это архитектурная ошибка.
*Решение:* Перенесите динамические данные из Labels в тело лога (Structured Metadata или просто JSON).

---

## Additional Information

### Чек-лист быстрой проверки
1.  **journald:** статус, лимиты, целостность.
2.  **Время:** корректность NTP.
3.  **Диск:** свободное место и `deleted` дескрипторы.
4.  **Агент:** логи ошибок (429, 5xx), сетевая доступность.
5.  **Бэкенд:** лимиты на прием данных.

### См. также
- [**Обзор логирования в Linux**](../../SystemAdministration/Logging/logging_overview.md)
- [**Использование journalctl**](../../Diagnostics/journalctl/journalctl_usage.md)
- [**logrotate: Ротация и сжатие**](../../SystemAdministration/Logging/logrotate.md)
- [**Диагностика дискового пространства**](../Filesystem/filesystem_and_disk_space_diagnostics.md)
