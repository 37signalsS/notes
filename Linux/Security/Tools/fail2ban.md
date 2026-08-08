# fail2ban

## Определения

**fail2ban** — специализированный сервис (демон) для защиты сервера от brute-force атак, DDoS на уровне приложения и других автоматизированных угроз. Он анализирует системные логи и логи приложений в реальном времени, выявляет подозрительную активность (многократные ошибки аутентификации, поиск эксплойтов, сканирование портов) и автоматически блокирует IP-адреса нарушителей на уровне сетевого экрана (firewall).

Связано: [brute-force атаки](../../../Security/Concepts/brute_force_attacks.md)

## Базовые концепции

### Архитектура и принцип работы

1.  **Мониторинг (Jail)**: Концепция «тюрьмы» (jail) объединяет фильтр (регулярные выражения для поиска в логах) и действие (команды для блокировки).
2.  **Обнаружение (Filter)**: Использует регулярные выражения (failregex) для поиска паттернов в файлах логов или системном журнале.
3.  **Действие (Action)**: Выполняет команды при достижении порога нарушений (блокировка через iptables, nftables, firewalld, обновление списков Cloudflare WAF, отправка уведомлений).
4.  **База данных**: Fail2ban хранит историю банов и текущее состояние в SQLite (`/var/lib/fail2ban/fail2ban.sqlite3`), что позволяет сохранять блокировки после перезагрузки сервиса.

### Ключевые параметры конфигурации

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `bantime` | Длительность блокировки IP | 10m (600с) |
| `findtime` | Временное окно для подсчета попыток | 10m (600с) |
| `maxretry` | Количество попыток до срабатывания бана | 5 |
| `backend` | Метод получения логов (`auto`, `systemd`, `polling`, `pyinotify`) | `auto` |
| `banaction` | Действие для блокировки (интеграция с firewall) | `iptables-multiport` |
| `ignoreip` | Список доверенных IP (белый список) | `127.0.0.1/8 ::1` |

### Бэкенды мониторинга (Backend)

-   **systemd**: Чтение напрямую из journald (рекомендуется для современных дистрибутивов).
-   **pyinotify**: Использование событий ядра для отслеживания изменений в файлах логов (эффективнее polling).
-   **polling**: Периодическая проверка файлов (используется, если другие методы недоступны).

### Бэкенды фаервола (Banaction)

-   **iptables-ipset**: Использование `ipset` для эффективной блокировки большого количества адресов.
-   **nftables-multiport**: Нативная поддержка `nftables` (использует динамические наборы `sets`).
-   **firewalld**: Интеграция через `firewall-cmd`.
-   **cloudflare**: Обновление правил Firewall/WAF на стороне Cloudflare через API.

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
```

### Приоритет конфигурации

Всегда используйте файл `jail.local` или файлы в `jail.d/` для переопределения настроек, чтобы избежать потери данных при обновлении пакета.
1. `/etc/fail2ban/jail.conf` — не трогать.
2. `/etc/fail2ban/jail.local` — основные правки.

### Базовая настройка (`/etc/fail2ban/jail.local`)

```ini
[DEFAULT]
# Игнорировать локальный хост и доверенную сеть
ignoreip = 127.0.0.1/8 ::1 192.168.1.0/24

# Базовые параметры бана (1 час)
bantime  = 1h
findtime = 10m
maxretry = 3

# Использование системного журнала по умолчанию
backend = systemd

# Выбор действия (для nftables)
banaction = nftables-multiport
```

### Активация защитных модулей (Jails)

#### Защита SSH
```ini
[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
maxretry = 3
```

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

#### Интеграция с Nginx и Rate Limiting
Блокировка IP, превышающих лимиты Nginx.
```ini
[nginx-limit-req]
enabled = true
port    = http,https
filter  = nginx-limit-req
logpath = /var/log/nginx/error.log
maxretry = 5
```

### Создание кастомного фильтра

Пример для блокировки попыток доступа к `wp-login.php`.
1. Создайте `/etc/fail2ban/filter.d/wp-auth.conf`:
```ini
[Definition]
failregex = ^<HOST> -.*"POST /wp-login.php.*" 200
```
2. Проверьте фильтр на реальном логе:
```bash
sudo fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/wp-auth.conf
```

### Интеграция с nftables

В современных ОС (Debian 11+, RHEL 8+) рекомендуется использовать `nftables`. Fail2ban создает таблицу `f2b-table`.

Просмотр заблокированных адресов в nftables:
```bash
nft list set inet f2b-table addr-set-sshd
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
```

## Дополнительная информация

### Оптимизация производительности

-   **Использование ipset**: При использовании iptables обязательно включайте `banaction = iptables-ipset-protoall` для работы с тысячами заблокированных IP без деградации производительности.
-   **Мониторинг SQLite**: База `/var/lib/fail2ban/fail2ban.sqlite3` может расти. Просмотр статистики:
    ```bash
    sqlite3 /var/lib/fail2ban/fail2ban.sqlite3 "SELECT count(*) FROM bans;"
    ```

### Типичные ошибки

1.  **Конфликт backend**: Если указан `backend = systemd`, но `logpath` ведет на несуществующий файл, сервис может не запуститься.
2.  **Время (Timezone)**: Несоответствие часовых поясов в логах приложения и системы приводит к тому, что fail2ban игнорирует события как "устаревшие".
3.  **Прокси (X-Forwarded-For)**: Если сервер за Nginx-прокси, fail2ban увидит IP прокси. Требуется настройка `real_ip` в Nginx и соответствующих фильтров.

### Связанные темы

-   [SSH hardening](../../ssh/server/ssh_hardening_best_practices.md) — комплексная защита SSH.
-   [nftables: практические сценарии](../../Networking/Settings/tools/nftables/practical_scenarios.md) — современная фильтрация.
-   [DDoS/WAF обзор](../../../Security/ApplicationSecurity/ddos_overview.md) — высокоуровневая защита.
-   [Linux security механизмы](../Linux_Security_Mechanisms_Overview.md) — контекст безопасности системы.

### Лучшие практики

1.  **Используйте jail.local**: Никогда не редактируйте `jail.conf` напрямую.
2.  **Эффективные действия**: Используйте `ipset` или `nftables` для минимизации нагрузки на ядро.
3.  **Белый список**: Всегда добавляйте свои IP/подсети в `ignoreip`.
4.  **Регулярный аудит**: Периодически проверяйте `tail -f /var/log/fail2ban.log`.
5.  **Официальная документация**: [fail2ban.org](https://www.fail2ban.org).
