# fail2ban

## Определения

### Общее определение

**fail2ban** — специализированный сервис (демон) для защиты сервера от brute-force атак, DDoS на уровне приложения и других автоматизированных угроз. Он анализирует системные логи и логи приложений в реальном времени, выявляет подозрительную активность (многократные ошибки аутентификации, поиск эксплойтов, сканирование портов) и автоматически блокирует IP-адреса нарушителей на уровне сетевого экрана (firewall).

**Классификация инструмента:** fail2ban относится к категории **интеллектуальных систем лог-анализа** (Intelligent Log Analysis). Он не является просто «ограждением» (firewall wrapper), а представляет собой систему обнаружения вторжений на основе правил (Signature-based IDS), работающую в режиме реального времени.

**Связано:** [brute-force атаки](../../../Security/Concepts/brute_force_attacks.md)

### Текущая версия и совместимость (2026)

| Версия fail2ban | Совместимость | Примечания |
| :--- | :--- | :--- |
| 0.11.x | Debian 12, Ubuntu 22.04+, RHEL 9, Alpine 3.18+ | Стабильная ветка, рекомендуется для production |
| 0.10.x | Debian 11, Ubuntu 20.04, RHEL 8 | Устаревшая, но ещё поддерживается |
| ≤ 0.9 | Debian 10 и старше | Не рекомендуется — уязвимости без патчей |

**Совместимость с nftables:** начиная с версии 0.11 рекомендуется `banaction = nftables-multiport`. Ранее доминировал `iptables-multiport` с `ipset`. Драйвер `ufw` остаётся рабочим, но считается устаревшим паттерном.

### Роль в DevOps / SRE / SysAdmin контексте

fail2ban — это не просто «сервис безопасности», а **инструмент автоматизации реагирования** (Automated Response), который вписывается в типовую SRE-архитектуру:

1.  **Детекция (Detection):** fail2ban читает логи (syslog, journald, application logs) и выявляет аномалии.
2.  **Автоматизация (Automation):** При превышении порога — IP блокируется без участия человека.
3.  **Связь с мониторингом (Observability):** fail2ban пишёт в `/var/log/fail2ban.log`, публикует метрики (через `fail2ban-client` или скрипты), которые могут быть переданы в **Prometheus**, **Zabbix**, **Datadog**, **Nagios**.
4.  **Интеграция с runbook:** Типичный SRE-runbook включает проверку `fail2ban-client status`, анализ банов, разблокировку ложных срабатываний (false positives).

**Критически важно для SRE:** fail2ban предотвращает «log flooding» (засорение логов) и «exhaustion of resources» (истощение ресурсов) при DDoS-атаках. Он — часть layered defense (многоуровневой защиты), наряду с WAF, rate limiting на приложении и CDN.

### Архитектурные компоненты

#### 1. Демон (fail2ban-server)

Центральный процесс, отвечающий за:
- Парсинг файлов журналов (через бэкенд)
- Применение фильтров (failregex)
- Подсчет нарушений и управление порогами
- Вызов действий (banaction) при превышении порога
- Сохранение состояния в базу данных

**Дополнительно (SRE-контекст):** fail2ban-server запускается как systemd-служба. Типичные параметры запуска:
- `--nofork` — запуск в переднем плане (для отладки)
- `--debug` — увеличение уровня детализации логов
- `--max-retries` — количество попыток переподключения к БД

**Важно:** Демон работает в многопоточном режиме. Каждый jail обрабатывается отдельным потоком, что позволяет одновременно мониторировать десятки источников логов. При высокой нагрузке (например, сканирование 1000+ IP в секунду) критически важно использовать `ipset`/`nftables sets` — иначе производительность упадёт из-за O(n) проверки правил.

#### 2. Клиент (fail2ban-client)

Интерфейс командной строки для управления демоном:
- Запрос статуса и информации
- Ручные операции блокировки/разблокировки
- Перезагрузка конфигурации
- Проверка фильтров

**Расширенные возможности (SRE/SysAdmin):**
```bash
# Проверка соответствия фильтра лог-файлу (тест regex)
sudo fail2ban-regex /var/log/auth.log /etc/fail2ban/filter.d/sshd.conf

# Проверка всех активных jail
sudo fail2ban-client status

# Подробный статус с количеством bans
sudo fail2ban-client status sshd --verbose

# Экспорт статистики bans в JSON (для мониторинга)
sudo fail2ban-client banned --json 2>/dev/null || true

# Проверить, не блокирован ли конкретный IP
sudo fail2ban-client banned 192.0.2.100
```

#### 3. Фильтры (filters)

Файлы с регулярными выражениями, определяющие паттерны подозрительной активности:
- Встроенные фильтры: `sshd`, `nginx-http-auth`, `apache-auth` и др.
- Пользовательские фильтры: создаются в `/etc/fail2ban/filter.d/`

#### 4. Действия (actions)

Сценарии выполнения блокировки:
- Базовые действия: `iptables-multiport`, `nftables-multiport`
- Расширенные действия: `iptables-ipset-protoall`, `ufw`, `firewallcmd-ipset`
- Пользовательские действия: создются в `/etc/fail2ban/action.d/`

#### 5. База данных состояния

SQLite-хранилище по умолчанию: `/var/lib/fail2ban/fail2ban.sqlite3`
- Хранит историю банов (таблица `bans`)
- Хранит текущее состояние failed-попыток (таблица `states`)
- Обеспечивает персистентность блокировок после перезагрузки

**Дополнительно (SRE-контекст):**
- SQLite-БД может достигать значительных размеров при высокой активности атак. Регулярная чистка старых записей:
  ```bash
  sudo sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 "DELETE FROM bans WHERE datetime < datetime('now', '-30 days');"
  ```
- Альтернатива: можно использовать PostgreSQL или MySQL, изменив параметр `db_path` в `jail.local`. Это важно для масштабируемости в крупных инфраструктурах.
- Структура таблиц:
  - `bans` — ip, jail, time_of_ban, time_of_unban, fail_count
  - `states` — name (jail), position, fail_count, last_updated

## Базовые концепции

### Архитектура и принцип работы

1.  **Мониторинг (Jail)**: Концепция «тюрьмы» (jail) объединяет фильтр (регулярные выражения для поиска в логах) и действие (команды для блокировки).
2.  **Обнаружение (Filter)**: Использует регулярные выражения (failregex) для поиска паттернов в файлах логов или системном журнале.
3.  **Действие (Action)**: Выполняет команды при достижении порога нарушений (блокировка через iptables, nftables, firewalld, обновление списков Cloudflare WAF, отправка уведомлений).
4.  **База данных**: Fail2ban хранит историю банов и текущее состояние в SQLite (`/var/lib/fail2ban/fail2ban.sqlite3`), что позволяет сохранять блокировки после перезагрузки сервиса.

### Ключевые параметры конфигурации

| Параметр | Описание | Значение по умолчанию | SRE-рекомендация |
| :--- | :--- | :--- | :--- |
| `bantime` | Длительность блокировки IP | 10m (600с) | 1h для production, 1w для рецидивистов |
| `findtime` | Временное окно для подсчета попыток | 10m (600с) | Чем короче, тем агрессивнее защита |
| `maxretry` | Количество попыток до срабатывания бана | 5 | 3 для SSH, 5 для HTTP |
| `backend` | Метод получения логов (`auto`, `systemd`, `polling`, `pyinotify`) | `auto` | `systemd` для modern distros |
| `banaction` | Действие для блокировки (интеграция с firewall) | `iptables-multiport` | `nftables-multiport` или `iptables-ipset-protoall` |
| `ignoreip` | Список доверенных IP (белый список) | `127.0.0.1/8 ::1` | Добавить корпоративные подсети |

### Цикл обработки нарушения (Flow)

```
[Лог-файл] → [Backend] → [Filter (failregex)] → [Подсчет попыток] → [Превышение maxretry?]
                                                              ↓ Yes
                                                    [BanAction] → [Блокировка IP]
                                                              ↓
                                                    [Сохранение в БД]
                                                              ↓
                                                    [Откат через bantime]
```

**Объяснение для SRE:** Fail2ban работает по принципу «state machine». Каждый IP имеет счётчик failed-попыток. При каждом новом failregex-совпадении счётчик увеличивается. Если счётчик достиг `maxretry` в течение `findtime` — IP банится на `bantime`. По истечении `bantime` IP разблокируется, но если нарушение повторилось в течении `findtime` — счётчик не сбрасывается, а накапливается (в версиях 0.10+). Это реализует **incremental banning**.

### Бэкенды мониторинга (Backend)

-   **systemd**: чтение напрямую из journald (рекомендуется для современных дистрибутивов). Преимущества: интеграция с journalctl, автоматическая ротация, поддержка приоритетов.
-   **pyinotify**: Использование событий ядра для отслеживания изменений в файлах логов (эффективнее polling). Требует установки `python3-pyinotify`.
-   **polling**: Периодическая проверка файлов (используется, если другие методы недоступны). По умолчанию интервал 5 секунд. Подходит для старых систем или файловых систем без inotify.

**SRE-совет:** Используйте `systemd` для всех служб, логирующих в journald (sshd, nginx с `systemd`-unit). Для приложений, пишущих в файлы (например, custom apps), используйте `pyinotify` для минимизации задержки обнаружения.

### Бэкенды фаервола (Banaction)

-   **iptables-ipset**: Использование `ipset` для эффективной блокировки большого количества адресов. Проверка принадлежности — O(1). Критически важен для DDoS-защиты.
-   **nftables-multiport**: Нативная поддержка `nftables` (использует динамические наборы `sets`). Рекомендуется для RHEL 9+, Debian 12+.
-   **firewalld**: Интеграция через `firewall-cmd`. Удобно, если система уже использует firewalld.
-   **cloudflare**: Обновление правил Firewall/WAF на стороне Cloudflare через API. Позволяет блокировать атакующих на уровне CDN/прокси.
-   **ufw**: Интеграция с UFW. Устаревший паттерн, не рекомендуется для production.
-   **hostsdeny**: Использование `/etc/hosts.deny`. Очень старый метод, не эффективен для высоких нагрузок.

**SRE-рекомендация:** Выбирайте `nftables-multiport` или `iptables-ipset-protoall` для production. Избегайте `ufw` и `hostsdeny` — они не масштабируемы.

### Инкрементальная блокировка (Incremental Banning)

Современные версии fail2ban поддерживают «рецидивную» схему. Если IP-адрес блокируется повторно в течение короткого времени, срок бана увеличивается экспоненциально (настраивается через `bantime.multipliers`). Это эффективно против ботов, которые возвращаются сразу после разблокировки.

## Практические сценарии

### Установка

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install fail2ban ipset

# RHEL / AlmaLinux / Rocky
sudo dnf install fail2ban fail2ban-firewalld
sudo systemctl enable --now fail2ban

# Alpine Linux
sudo apk add fail2ban
```

**Проверка версии:**
```bash
sudo fail2ban-server --version
# → fail2ban 0.11.2
```

**Требования к системе:**
- Python 3.6+ (для fail2ban 0.10+)
- Доступ к ядерным механизмам: `inotify` (для pyinotify), `journald` (для systemd backend)
- Права root для управления firewall

### Приоритет конфигурации

Всегда используйте файл `jail.local` или файлы в `jail.d/` для переопределения настроек, чтобы избежать потери данных при обновлении пакета.
1. `/etc/fail2ban/jail.conf` — не редактировать (файл по умолчанию, переписывается при обновлении).
2. `/etc/fail2ban/jail.local` — основные правки (имеет приоритет над jail.conf).
3. `/etc/fail2ban/jail.d/` — можно создавать отдельные файлы для каждого jail (например, `sshd.conf`, `nginx.conf`). Это рекомендуемый подход для large-scale конфигураций, так как позволяет разделить ответственность.

**Порядок загрузки (от высокого к низкому приоритету):**
1. `jail.conf` (базовый шаблон)
2. `jail.local` (переопределяет jail.conf)
3. `jail.d/*.conf` (дополнительные переопределения, загружаются в алфавитном порядке)

**SRE-совет:** Используйте `jail.d/` для модульности. Например, `sshd.conf`, `nginx.conf`, `recidive.conf`. Это упрасняет аудит и откат конфигурации.

### Базовая настройка (`/etc/fail2ban/jail.local`)

```ini
[DEFAULT]
# Игнорировать локальный хост и доверенную сеть
ignoreip = 127.0.0.1/8 ::1 192.168.1.0/24 10.0.0.0/8

# Базовые параметры бана (1 час)
bantime  = 1h
findtime = 10m
maxretry = 3

# Использование системного журнала по умолчанию
backend = systemd

# Выбор действия (для nftables)
banaction = nftables-multiport

# Логи fail2ban
destemail = admin@example.com
sender = fail2ban@host.example.com
action = %(name)s
```

**Пояснение параметров:**
- `ignoreip` — белый список. Важно добавить внутренние подсети, чтобы не заблокировать себя.
- `bantime = 1h` — блокировка на 1 час. Для production рекомендуется 1h-24h.
- `findtime = 10m` — окно для подсчета попыток. Меньшее значение = более агрессивная защита.
- `maxretry = 3` — количество срабатываний. Для SSH обычно 3, для HTTP — 5.
- `backend = systemd` — использование journald. Альтернатива: `pyinotify`.
- `banaction = nftables-multiport` — рекомендуется для современных дистрибутивов.

### Активация защитных модулей (Jails)

#### Защита SSH
```ini
[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
maxretry = 3
backend = systemd
banaction = nftables-multiport
```

**Дополнительно для SSH:**
- Если SSH слушает на нестандартном порту (например, 2222), укажите `port = 2222`.
- Для логов, находящихся не в стандартном месте: `logpath = /var/log/auth.log`.
- Проверка: `sudo fail2ban-client status sshd`.

#### Защита от рецидивистов (Recidive)
Блокирует на длительный срок те IP, которые часто попадают в бан в других модулях.
```ini
[recidive]
enabled  = true
logpath  = /var/log/fail2ban.log
banaction = %(banaction_allports)s
bantime  = 1w
findtime = 1d
maxretry = 5
```
**Принцип работы:** Recidive анализирует логи fail2ban自身. Если IP был забанен в других jail'ах (например, sshd) и при этом появляется в `/var/log/fail2ban.log` повторно — он банится на 1 неделю на всех портах.

#### Интеграция с Nginx и Rate Limiting
Блокировка IP, превышающих лимиты Nginx.
```ini
[nginx-limit-req]
enabled = true
port    = http,https
filter  = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 5
bantime = 1h
```

**Дополнительные Nginx-jails:**
```ini
[nginx-http-auth]
enabled = true
port    = http,https
filter  = nginx-http-auth
logpath = /var/log/nginx/error.log
maxretry = 3
bantime = 1h

[nginx-badbots]
enabled = true
port    = http,https
filter  = nginx-badbots
logpath = /var/log/nginx/access.log
maxretry = 2
bantime = 1w
```

#### Защита Apache
```ini
[apache-auth]
enabled = true
port    = http,https
filter  = apache-auth
logpath = /var/log/apache2/error.log
maxretry = 3
```

#### Защита MySQL / MariaDB
```ini
[mysqld-auth]
enabled = true
port    = 3306
filter  = mysqld-auth
logpath = /var/log/mysql/error.log
maxretry = 3
```

#### Защита Postfix
```ini
[postfix]
enabled = true
port    = smtp
filter  = postfix
logpath = /var/log/mail.log
maxretry = 5
```

#### Интеграция с WordPress (пример)
```ini
[wp-auth]
enabled = true
port    = http,https
filter  = wp-auth
logpath = /var/log/nginx/access.log
maxretry = 3
bantime = 1h
```

### Создание кастомного фильтра

Пример для блокировки попыток доступа к `wp-login.php`.
1. Создайте `/etc/fail2ban/filter.d/wp-auth.conf`:
```ini
[Definition]
failregex = ^<HOST> -.*"POST /wp-login.php.*" 200
ignoreregex =
```
2. Проверьте фильтр на реальном логе:
```bash
sudo fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/wp-auth.conf
```

**Расширенный пример с игнорированием:**
```ini
[Definition]
# Банить за POST-запросы к wp-login.php с кодом 200 (успешная авторация)
failregex = ^<HOST> -.*"POST /wp-login.php.*" 200

# Игнорировать локальные IP и прокси
ignoreregex = ^192\.168\..* ^10\..* ^127\.0\.0\.1

# Паттерн для поиска (опционально)
journalmatch = _SYSTEMD_UNIT=nginx.service
```

**Другие примеры фильтров:**

Для блокировки сканирования портов:
```ini
[Definition]
failregex = ^<HOST> -.*"GET /phpmyadmin.*" 403
```

Для блокировки попыток exploitation:
```ini
[Definition]
failregex = .*<HOST>.*(\[|\{).*(select|union|drop|insert|update|exec|script).*(\]|\})
```

**SRE-совет:** Проверяйте фильтры регулярно с помощью `fail2ban-regex`. Если фильтр не срабатывает — вы терезаете защиту. Используйте `--print-common-misses` для анализа пропущенных строк.

### Интеграция с nftables

В современных ОС (Debian 11+, RHEL 8+) рекомендуется использовать `nftables`. Fail2ban создает таблицу `f2b-table`.

Просмотр заблокированных адресов в nftables:
```bash
nft list set inet f2b-table addr-set-sshd
```

**Проверка интеграции:**
```bash
# Убедитесь, что f2b-table существует
sudo nft list ruleset | grep f2b

# Проверить наборы (sets)
sudo nft list set inet f2b-table

# Проверить цепочки (chains)
sudo nft list chain inet f2b-chain INPUT
```

**Настройка nftables вручную (если fail2ban не справляется):**
```bash
# Создать таблицу вручную (если не создана)
sudo nft add table inet f2b-table

# Создать набор для SSH
sudo nft add set inet f2b-table addr-set-sshd '{ type ipv4_addr; flags interval; timeout 3600; }'

# Добавить правило
sudo nft add chain inet f2b-chain input '{ type filter hook input priority 0; policy accept; }'
sudo nft add rule inet f2b-chain input ip saddr @addr-set-sshd drop
```

### Управление через CLI (fail2ban-client)

```bash
# Проверка общего статуса
sudo fail2ban-client status

# Статус конкретной тюрьмы и список заблокированных IP
sudo fail2ban-client status sshd

# Ручная блокировка IP
sudo fail2ban-client set sshd banip 1.2.3.4

# Ручная разблокировка IP
sudo fail2ban-client set sshd unbanip 1.2.3.4

# Разблокировать IP во всех тюрьмах сразу
sudo fail2ban-client unban 1.2.3.4

# Перезагрузить конфигурацию
sudo fail2ban-client reload

# Перезагрузить конкретный jail
sudo fail2ban-client reload sshd

# Проверка конфигурации (syntax check)
sudo fail2ban-client --test

# Остановка демона
sudo fail2ban-client shutdown

# Принудительное обновление состояния (sync)
sudo fail2ban-client flush
```

**Диагностика через fail2ban-client:**
```bash
# Проверить, какие jail активны
sudo fail2ban-client status

# Проверить количество заблокированных IP
sudo fail2ban-client status sshd | grep -c " banned IP:"

# Проверить логи fail2ban
sudo tail -f /var/log/fail2ban.log
```

## Мониторинг и интеграция с Observability-системами (SRE/DevOps)

### Prometheus-экспортер (fail2ban_exporter)

Для интеграции fail2ban с Prometheus используется сторонний экспортер `fail2ban_exporter`. Установка:

```bash
# Скачать и запустить экспортер (пример для Linux/amd64)
wget https://github.com/zeepho/fail2ban_exporter/releases/download/v0.1.1/fail2ban_exporter-0.1.1.linux-amd64
chmod +x fail2ban_exporter-0.1.1.linux-amd64
sudo mv fail2ban_exporter-0.1.1.linux-amd64 /usr/local/bin/fail2ban_exporter

# Создать systemd-службу
sudo tee /etc/systemd/system/fail2ban_exporter.service <<'EOF'
[Unit]
Description=Fail2ban Prometheus Exporter
After=network.target fail2ban.service

[Service]
Type=simple
ExecStart=/usr/local/bin/fail2ban_exporter --fail2ban-url http://127.0.0.1:9519
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now fail2ban_exporter
```

**Настройка fail2ban для экспортера:**
```ini
# /etc/fail2ban/jail.local
[DEFAULT]
# Включить HTTP API
enabled = true
```

**Метрики для Prometheus:**
```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'fail2ban'
    static_configs:
      - targets: ['localhost:9537']
```

### Альтернатива: скрипты для Zabbix/Nagios

Для систем мониторинга без Prometheus используется подход на основе скриптов:

**Zabbix userparameter:**
```bash
# /etc/zabbix/zabbix_agent2.d/fail2ban.conf
UserParameter=fail2ban.status[*],sudo fail2ban-client status $1
UserParameter=fail2ban.banned[*],sudo fail2ban-client status $1 | grep -c "banned IP:"
```

**Nagios-проверка:**
```bash
#!/bin/bash
# check_fail2ban.sh
JAIL=$1
COUNT=$(sudo fail2ban-client status $JAIL | grep -oP '\d+(?= banned IP:)')
if [ "$COUNT" -gt 0 ]; then
  echo "CRITICAL: $COUNT IPs banned in $JAIL"
  exit 2
else
  echo "OK: No bans in $JAIL"
  exit 0
fi
```

### Интеграция с Alertmanager / PagerDuty

Для SRE-комуанд критично получать алерты при всплеске банов. Типичный пайплайн:

1.  **Метрика:** `fail2ban_banned_total{jail="sshd"} > 50` за 5 минут.
2.  **Алерт:** Prometheus Rule → Alertmanager → PagerDuty / Slack / Email.
3.  **Runbook:** Проверить `/var/log/fail2ban.log`, определить source IP, проверить false positive.

**Пример PrometheusRule:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: fail2ban-alerts
spec:
  groups:
  - name: fail2ban
    rules:
    - alert: Fail2banHighBanRate
      expr: |
        sum by (jail) (increase(fail2ban_banned_total[5m])) > 50
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "High ban rate in jail {{ $labels.jail }}"
        description: "{{ $value }} IPs banned in the last 5 minutes"
```

### Syslog и SIEM-интеграция

Fail2ban по умолчанию логирует в `/var/log/fail2ban.log`. Для централизованного логирования:

**Forwarding в syslog:**
```ini
# /etc/fail2ban/jail.local
[DEFAULT]
# Перенаправление логов в syslog
destsyslog = local0
```

**Интеграция с Wazuh/Splunk/ELK:**
- Wazuh: использовать rules для детекции `fail2ban` логов.
- Splunk: настроить `inputs.conf` для чтения `/var/log/fail2ban.log`.
- ELK: Filebeat → Logstash → Elasticsearch.

**Ключевые события для SIEM:**
- `Ban` — IP заблокирован.
- `Unban` — IP разблокирован.
- `Fail2Ban FAILED` — фильтр не сработал (возможная проблема с regex).

## Дополнительная информация

### Оптимизация производительности

-   **Использование ipset**: При использовании iptables обязательно включайте `banaction = iptables-ipset-protoall` для работы с тысячами заблокированных IP без деградации производительности. Проверка принадлежности в ipset — O(1), тогда как в стандартных iptables-правилах — O(n).
-   **Мониторинг SQLite**: База `/var/lib/fail2ban/fail2ban.sqlite3` может расти. Просмотр статистики:
    ```bash
    sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 "SELECT count(*) FROM bans;"
    ```
-   **Регулярная чистка БД**: Старые записи (>30 дней) удаляются автоматически при перезапуске демона. Для ручной чистки:
    ```bash
    sudo sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 "DELETE FROM bans WHERE datetime < datetime('now', '-30 days');"
    sudo sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 "VACUUM;"
    ```
-   **Настройка backend**: Для высоконагруженных систем используйте `pyinotify` вместо `polling`. Используйте `systemd` для служб, логирующих в journald.
-   **Лимиты ресурсов**: При большом количестве jail'ов ограничьте количество одновременно обрабатываемых через `maxthreads` (по умолчанию — количество ядер).

### Автоматизация (Ansible, Puppet, Chef)

**Ansible-плейб для развертывания fail2ban:**
```yaml
# playbook-fail2ban.yml
---
- name: Установка и настройка fail2ban
  hosts: webservers
  become: yes
  vars:
    fail2ban_bantime: "1h"
    fail2ban_maxretry: 3
    fail2ban_ignoreip: "127.0.0.1/8 ::1 192.168.1.0/24"
  
  tasks:
    - name: Установка fail2ban (Debian/Ubuntu)
      apt:
        name: fail2ban
        state: present
        update_cache: yes
      when: ansible_distribution == "Debian"

    - name: Установка fail2ban (RHEL)
      dnf:
        name: fail2ban
        state: present
      when: ansible_distribution in ["RedHat", "CentOS", "AlmaLinux", "Rocky"]

    - name: Копирование jail.local
      template:
        src: templates/jail.local.j2
        dest: /etc/fail2ban/jail.local
        owner: root
        group: root
        mode: '0644
      notify: restart fail2ban

    - name: Копирование кастомных фильтров
      copy:
        src: "files/filter.d/{{ item }}"
        dest: "/etc/fail2ban/filter.d/{{ item }}"
        owner: root
        group: root
        mode: '0644
      with_items:
        - custom.conf
      notify: reload fail2ban

  handlers:
    - name: restart fail2ban
      systemd:
        name: fail2ban
        state: restarted
        daemon_reload: yes

    - name: reload fail2ban
      systemd:
        name: fail2ban
        state: reloaded
```

**Puppet-манифест:**
```puppet
# manifest/fail2ban.pp
class fail2ban {
  package { 'fail2ban':
    ensure => installed,
  }
  
  file { '/etc/fail2ban/jail.local':
    ensure  => file,
    owner   => 'root',
    group   => 'root',
    mode    => '0644',
    content => template('fail2ban/jail.local.erb'),
    require => Package['fail2ban'],
    notify  => Service['fail2ban'],
  }
  
  service { 'fail2ban':
    ensure    => running,
    enable    => true,
    subscribe => File['/etc/fail2ban/jail.local'],
  }
}
```

### Типичные ошибки

1.  **Конфликт backend**: Если указан `backend = systemd`, но `logpath` ведет на несуществующий файл, сервис может не запуститься. Проверьте существование файлов логов перед настройкой.
2.  **Время (Timezone)**: Несоответствие часовых поясов в логах приложения и системы приводит к тому, что fail2ban игнорирует события как "устаревшие". Обязательно синхронизируйте NTP.
3.  **Прокси (X-Forwarded-For)**: Если сервер за Nginx-прокси, fail2ban увидит IP прокси. Требуется настройка `real_ip` в Nginx и соответствующих фильтров.
4.  **False positives (ложные срабатывания)**: При чрезмерно агрессивных настройках (например, `maxretry = 1`) можно заблокировать легитимных пользователей. Всегда проверяйте логи перед изменением параметров.
5.  **Блокировка через fail2ban собственного IP**: Проверяйте `ignoreip` перед включением jail'ов. Если вы заблокировали себя — используйте консоль или VNC-доступ для разблокировки.
6.  **Слишком длинные regex**: Сложные регулярные выражения могут замедлять обработку логов. Используйте `fail2ban-regex` для тестирования производительности.
7.  **Конфигурация не загружается**: Проверяйте `/var/log/fail2ban.log` на наличие ошибок. Используйте `sudo fail2ban-client --test` для проверки синтаксиса.

### Связанные темы

-   [SSH hardening](../../ssh/server/ssh_hardening_best_practices.md) — комплексная защита SSH.
-   [nftables: практические сценарии](../../Networking/Settings/tools/nftables/practical_scenarios.md) — современная фильтрация.
-   [DDoS/WAF обзор](../../../Security/ApplicationSecurity/ddos_overview.md) — многоуровневая защита.
-   [Linux security механизмы](../Linux_Security_Mechanisms_Overview.md) — контекст безопасности системы.
-   [Brute-force атаки](../../../Security/Concepts/brute_force_attacks.md) — теория атак.
-   [Мониторинг и Observability](../../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md) — методологии мониторинга.

### SRE-runbook: Типичные сценарии реагирования

**Сценарий 1: Всплеск bans в SSH (DoS-атака)**
```bash
# 1. Проверить количество bans
sudo fail2ban-client status sshd | grep "banned IP"

# 2. Определить топ-5 атакующих IP
sudo sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 \
  "SELECT ip, count(*) FROM bans WHERE jail='sshd' GROUP BY ip ORDER BY count(*) DESC LIMIT 5"

# 3. Проверить логи fail2ban
sudo tail -50 /var/log/fail2ban.log | grep sshd

# 4. При необходимости — разблокировать все IP (если атака закончилась)
sudo fail2ban-client set sshd unbanip --all

# 5. Усилить защиту
# /etc/fail2ban/jail.local
# [sshd]
# maxretry = 1
# bantime = 24h
```

**Сценарий 2: Ложное срабатывание (legitимный IP заблокирован)**
```bash
# 1. Проверить, кто заблокирован
sudo fail2ban-client status sshd

# 2. Разблокировать конкретный IP
sudo fail2ban-client set sshd unbanip 192.168.1.100

# 3. Проверить логи на причину
sudo grep "192.168.1.100" /var/log/fail2ban.log

# 4. Добавить IP в белый список (на будущее)
# /etc/fail2ban/jail.local
# ignoreip = 127.0.0.1/8 192.168.1.100
```

**Сценарий 3: Проверка работоспособности fail2ban (Health Check)**
```bash
#!/bin/bash
# health_check_fail2ban.sh
# Используется в Zabbix/Nagios для мониторинга доступности fail2ban

if ! systemctl is-active --quiet fail2ban; then
  echo "CRITICAL: fail2ban service is not running"
  exit 2
fi

if ! sudo fail2ban-client status &>/dev/null; then
  echo "CRITICAL: fail2ban-client не отвечает"
  exit 2
fi

echo "OK: fail2ban is running"
exit 0
```

### Лучшие практики

1.  **Используйте jail.local**: Никогда не редактируйте `jail.conf` напрямую.
2.  **Эффективные действия**: Используйте `ipset` или `nftables` для минимизации нагрузки на ядро.
3.  **Белый список**: Всегда добавляйте свои IP/подсети в `ignoreip`.
4.  **Регулярный аудит**: Периодически проверяйте `tail -f /var/log/fail2ban.log`.
5.  **Официальная документация**: [fail2ban.org](https://www.fail2ban.org).
6.  **Тестирование фильтров**: Перед развертыванием проверяйте regex с помощью `fail2ban-regex`.
7.  **Мониторинг метрик**: Интегрируйте fail2ban с Prometheus/Zabbix для отслеживания всплесков банов.
8.  **Runbook-документация**: Держите под рукой сценарии разблокировки и диагностики.
9.  **Резервное копирование конфигурации**: Регулярно копируйте `/etc/fail2ban/` в систему версионирования (например, Ansible, git).
10. **Обновления**: Следите за обновлениями безопасности fail2ban — уязвимости в нём могут быть критическими.
