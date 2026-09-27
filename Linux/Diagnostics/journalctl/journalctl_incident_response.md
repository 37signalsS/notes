# Расследование инцидентов через journalctl

## Определения

**Расследование инцидентов (Incident Response)** — процесс выявления, анализа и устранения последствий инцидентов безопасности или сбоев в работе системы. Журналы journald являются ключевым источником доказательной базы, так как содержат структурированные метаданные (PID, UID, Boot ID,.timestamp), которые невозможно подделать из пользовательского пространства.

**Цепочка доказательств (Chain of Custody)** — последовательность действий по сохранению целостности доказательств: от момента обнаружения инцидента до передачи данных аудитору или правоохранительным органам. Нарушение цепочки доказательств делает логи юридически незначимыми.

**Timeline (Хронология)** — упорядоченная по времени последовательность событий, связанных с инцидентом. Восстановление точной хронологии — главная цель анализа логов при расследовании.

**Форензика (Digital Forensics)** — применение специализированных методов для извлечения, анализа и сохранения цифровых доказательств с соблюдением юридических стандартов.

## Основные концепции

### Почему journald критичен для расследований

1. **Неизменяемость метаданных:** Поля `_PID`, `_UID`, `_COMM`, `_EXE`, `_SYSTEMD_UNIT` заполняются ядром и systemd, а не приложением. Злоумышленник не может подменить отправителя.
2. **Boot ID:** Каждая перезагрузка помечается уникальным идентификатором, что позволяет отделить события текущей сессии от исторических.
3. **Курсоры (Cursors):** Уникальные указатели на конкретные записи, обеспечивающие точную навигацию без пропусков.
4. **FSS (Forward Secure Sealing):** Криптографическая защита от модификации прошлых записей.

### Методология расследования

```
1. Фиксация → 2. Сбор → 3. Анализ → 4. Хронология → 5. Выводы → 6. Отчёт
```

| Этап | Действия | Инструменты |
| :--- | :--- | :--- |
| **Фиксация** | Зафиксировать время начала инцидента, boot ID, состояние системы | `date`, `uptime`, `journalctl --list-boots` |
| **Сбор** | Экспорт логов за релевантный период | `journalctl`, `--show-cursor`, `--output=json` |
| **Анализ** | Фильтрация по сервисам, приоритетам, пользователям | `journalctl -u`, `-p`, `_UID=` |
| **Хронология** | Восстановление.timeline из событий | Сортировка по времени, корреляция Boot ID |
| **Выводы** | Определение корневой причины, компрометированных компонентов | Анализ паттернов, аномалий |
| **Отчёт** | Документация с доказательной базой | Экспорт в JSON, FSS-верификация |

### Сохранение доказательной базы

**Критически важно:** Не изменяйте оригинальные файлы журнала при расследовании. Все операции выполняйте с копиями.

```bash
# 1. Фиксация текущего состояния (timestamp)
echo "Incident start: $(date -u '+%Y-%m-%dT%H:%M:%SZ')" > /tmp/incident_$(date +%s).txt
echo "Boot ID: $(cat /proc/sys/kernel/random/boot_id)" >> /tmp/incident_*.txt

# 2. Ротация и синхронизация перед копированием
sudo journalctl --sync --rotate

# 3. Копирование директории журнала (не монтировать как rw!)
sudo cp -a /var/log/journal /evidence/journal-$(date +%F_%H%M%S)

# 4. Создание контрольной суммы (для доказательной целостности)
sudo sha256sum /evidence/journal-$(date +%F_%H%M%S)/*/*.journal* > /evidence/checksums-$(date +%F).sha256

# 5. Верификация FSS (если включена)
sudo journalctl --verify --verify-key=<key> 2>&1 | tee /evidence/fss_verify.log
```

### Построение хронологии (Timeline)

**Шаг 1: Определение временного окна**
```bash
# Найти.boot ID проблемной загрузки
journalctl --list-boots
# → 0  a1b2c3d4...  Mon 2024-05-01 10:00:00 — current
#   -1 e5f6a7b8...  Mon 2024-05-01 08:00:00 — Mon 2024-05-01 09:59:59

# Логи проблемной загрузки
journalctl -b -1 --since "08:00" --until "09:59" --no-pager > /tmp/timeline.txt
```

**Шаг 2: Фильтрация по критическим событиям**
```bash
# Ошибки и критические сообщения
journalctl -b -1 -p err --no-pager

# Все действия root-пользователя
journalctl -b -1 _UID=0 --no-pager

# Все неудачные попытки входа
journalctl -b -1 -u sshd | grep "Failed password"

# Создание/удаление пользователей
journalctl -b -1 -u useradd -u userdel --no-pager

# Запуск и останов сервисов
journalctl -b -1 | grep -E "Started|Stopped|Failed" | head -50
```

**Шаг 3: Корреляция событий**
```bash
# Все события в окне 5 минут вокруг предполагаемого времени компрометации
journalctl --since "09:15:00" --until "09:20:00" --no-pager

# События конкретного процесса (если известен PID)
journalctl _PID=1234 --no-pager

# Все sudo-вызовы за период
journalctl _COMM=sudo --since "08:00" --until "10:00" --no-pager
```

### Типичные сценарии расследований

#### Сценарий 1: Подозрительный вход по SSH

```bash
# 1. Все попытки входа по SSH за сутки
journalctl -u sshd --since yesterday --no-pager | grep -E "Accepted|Failed"

# 2. Успешные входы с подозрительных IP
journalctl -u sshd --since "2024-05-01" | grep "Accepted" | \
  awk '{print $NF}' | sort | uniq -c | sort -rn

# 3. Действия после входа (что делал пользователь)
journalctl _UID=1000 --since "2024-05-01 09:00" --until "2024-05-01 09:30" --no-pager

# 4. sudo-вызовы этого пользователя
journalctl _COMM=sudo _UID=1000 --since "2024-05-01 09:00" --no-pager

# 5. Запущенные/остановленные сервисы
journalctl --since "2024-05-01 09:00" --until "2024-05-01 09:30" | \
  grep -E "Started|Stopped|Failed"
```

#### Сценарий 2: DoS-атака или флуд

```bash
# 1. Подавленные сообщения (rate limiting сработал)
journalctl -u systemd-journald | grep -i "suppressed"

# 2. Всплеск ошибок за короткий период
journalctl -p err --since "09:00:00" --until "09:00:10" --no-pager | wc -l

# 3. Один процесс генерирует大量 ошибок
journalctl -p err --since "1 hour ago" -o json | \
  jq -r '._PID' | sort | uniq -c | sort -rn | head -5

# 4. Попытки brute-force (много failed login за короткий период)
journalctl -u sshd --since "10 min ago" | grep "Failed password" | wc -l
```

#### Сценарий 3: Нестабильность сервиса (crash loop)

```bash
# 1. Все failed-юниты за загрузку
journalctl -b --no-pager | grep "Failed"

# 2. Ошибки конкретного сервиса
journalctl -u myapp -p err --since "1 hour ago" --no-pager

# 3. Core dumps и segfault
journalctl -u myapp | grep -E "core dumped|segfault|signal"

# 4. Сравнение поведения между загрузками
diff <(journalctl -b -1 -u myapp --no-pager) \
     <(journalctl -b -2 -u myapp --no-pager)

# 5. Время от старта сервиса до падения
journalctl -u myapp -b --no-pager | \
  grep -E "Started|Failed" | head -10
```

#### Сценарий 4: Компрометация системы

```bash
# 1. Все события от root (UID=0)
journalctl -b -1 _UID=0 --no-pager

# 2. Изменения в системных файлах (если auditd настроен)
journalctl -u auditd -b -1 | grep -E "execve|chmod|chown"

# 3. Запуск подозрительных процессов
journalctl -b -1 -o json | \
  jq -r 'select(._EXE != null) | ._EXE' | sort -u

# 4. Новые пользователи и группы
journalctl -b -1 | grep -E "useradd|groupadd|usermod"

# 5. Изменения в crontab
journalctl -b -1 _COMM=crond --no-pager

# 6. Проверка целостности (FSS)
journalctl --verify --verify-key=<key> 2>&1
```

### Экспорт доказательной базы

```bash
# Полный экспорт за период в JSON (для парсинга и SIEM)
journalctl --since "2024-05-01 08:00" --until "2024-05-01 10:00" \
  -o json --no-pager > /evidence/journal_export.json

# Экспорт с курсорами (для воспроизведения)
journalctl --since "2024-05-01 08:00" --show-cursor --no-pager \
  > /evidence/journal_with_cursors.txt

# Экспорт конкретного сервиса
journalctl -u sshd --since "2024-05-01 08:00" --until "2024-05-01 10:00" \
  -o json --no-pager > /evidence/sshd_events.json

# Контрольные суммы экспорта
sha256sum /evidence/*.json /evidence/*.txt > /evidence/export_checksums.sha256
```

### Верификация целостности логов

Если включена FSS (Forward Secure Sealing), можно доказать, что логи не были изменены:

```bash
# Проверка текущих файлов
sudo journalctl --verify
# → PASS: /var/log/journal/.../system.journal

# Глубокая криптографическая проверка (требует Verification Key)
sudo journalctl --verify --verify-key=<ключ>
# → PASS: все записи не изменены с момента подписи

# Если обнаружена модификация:
# → FAIL: /var/log/journal/.../system.journal: Seal verification failed
# Это означает, что журнал был изменён после подписи — возможна компрометация
```

### Корреляция с другими источниками

| Источник | Команда | Что ищем |
| :--- | :--- | :--- |
| **auditd** | `ausearch -ts recent` | Syscalls, доступ к файлам |
| **wtmp** | `last -F` | История входов |
| **化进程** | `ps auxf` | Текущие процессы |
| **Cron** | `cat /var/spool/cron/*` | Задачи cron |
| **SSH keys** | `find / -name authorized_keys` | Добавленные ключи |
| **Suid-файлы** | `find / -perm -4000` | Новые suid-файлы |

```bash
# Комбинированный анализ: journalctl + auditd
journalctl -u sshd --since "09:00" --until "09:30" | grep "Accepted" | \
  while read line; do
    timestamp=$(echo "$line" | awk '{print $1, $2, $3}')
    ausearch -ts "$timestamp" -ui "$(echo "$line" | grep -oP 'for \K\w+')"
  done
```

## Дополнительная информация

### Юридические аспекты

- **PCI DSS v4.0.1:** Требует хранения логов аудита не менее 12 месяцев (3 месяца онлайн). Логи должны быть защищены от несанкционированного изменения.
- **ФЗ-152 (Россия):** Требует логирования доступа к персональным данным и действий администраторов. Сроки хранения определяются политикой безопасности.
- **Chain of Custody:** Для юридически значимого расследования необходимо зафиксировать: кто собрал логи, когда, каким методом, контрольные суммы.

### Автоматизация

```bash
# Скрипт быстрого реагирования
#!/bin/bash
# incident_snapshot.sh — моментальный снимок системы при инциденте

EVIDENCE_DIR="/evidence/incident_$(date +%F_%H%M%S)"
mkdir -p "$EVIDENCE_DIR"

# Фиксация времени
date -u > "$EVIDENCE_DIR/timestamp.txt"
cat /proc/sys/kernel/random/boot_id >> "$EVIDENCE_DIR/boot_id.txt"
uptime >> "$EVIDENCE_DIR/uptime.txt"

# Экспорт логов за последний час
journalctl --since "1 hour ago" -o json --no-pager > "$EVIDENCE_DIR/journal.json"

# Ошибки за текущую загрузку
journalctl -b -p err --no-pager > "$EVIDENCE_DIR/errors.txt"

# Failed-юниты
systemctl --failed > "$EVIDENCE_DIR/failed_units.txt"

# Процессы
ps auxf > "$EVIDENCE_DIR/ps.txt"

# Network connections
ss -tlnp > "$EVIDENCE_DIR/listening_ports.txt"
ss -tnp >> "$EVIDENCE_DIR/established_connections.txt"

# Контрольные суммы
sha256sum "$EVIDENCE_DIR"/* > "$EVIDENCE_DIR/checksums.sha256"

echo "Incident snapshot saved to: $EVIDENCE_DIR"
```

### Ограничения

- **Логи в volatile-режиме:** Если `Storage=volatile`, логи теряются после перезагрузки. Для расследований критично `Storage=persistent`.
- **Rate Limiting:** journald может подавить важные сообщения при флуде. Проверяйте `Suppressed X messages` в логах journald.
- **Временные метки:** Используйте `--utc` для единообразия при анализе в разных часовых поясах.
- **Версия systemd:** Некоторые функции (курсоры, пользовательские поля) доступны только в systemd 214+.

### См. также

- [journalctl: Обзор и концепции](./journalctl_overview.md)
- [Практическое использование journalctl](./journalctl_usage.md)
- [Аудит безопасности (auditd)](../../SystemAdministration/Logging/auditd.md)
- [Инцидент-реагирование в Linux](../../Security/Concepts/incident_response.md)
- [Расследование инцидентов в Kubernetes](../../../Kubernetes/Security/incident_response.md)
