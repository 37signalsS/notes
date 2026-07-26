# fail2ban

## Определения

**fail2ban** — специализированный сервис (демон) для защиты сервера от brute-force атак и других автоматизированных угроз. Он анализирует системные логи и логи приложений в реальном времени, выявляет подозрительную активность (многократные ошибки аутентификации, поиск эксплойтов, сканирование портов) и автоматически блокирует IP-адреса нарушителей на уровне сетевого экрана (firewall).

Связано: [brute-force атаки](../../../Security/Concepts/brute_force_attacks.md)

## Базовые концепции

### Архитектура и принцип работы

1.  **Мониторинг (Jail)**: Концепция «тюрьмы» (jail) объединяет фильтр (регулярные выражения для поиска в логах) и действие (команды для блокировки).
2.  **Обнаружение (Filter)**: Использует регулярные выражения (failregex) для поиска паттернов в файлах логов или системном журнале.
3.  **Действие (Action)**: Выполняет команды при достижении порога нарушений (блокировка через iptables, nftables, firewalld, отправка уведомлений).
4.  **Жизненный цикл блокировки**: IP попадает в бан на время `bantime`, если совершил `maxretry` нарушений в течение окна `findtime`.

### Ключевые параметры конфигурации

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `bantime` | Длительность блокировки IP | 10m (600с) |
| `findtime` | Временное окно для подсчета попыток | 10m (600с) |
| `maxretry` | Количество попыток до срабатывания бана | 5 |
| `backend` | Метод получения логов (`auto`, `systemd`, `polling`) | `auto` |
| `banaction` | Действие для блокировки (интеграция с firewall) | `iptables-multiport` |
| `ignoreip` | Список доверенных IP (белый список) | `127.0.0.1/8 ::1` |

### Бэкенды логов и фаервола

-   **Бэкенды логов**:
    -   `systemd`: Чтение напрямую из journald (рекомендуется для современных дистрибутивов).
    -   `polling` / `pyinotify`: Мониторинг текстовых файлов логов.
-   **Бэкенды фаервола**:
    -   `iptables-ipset`: Использование `ipset` для эффективной блокировки большого количества адресов.
    -   `nftables-multiport`: Нативная поддержка `nftables` (использует динамические наборы `sets`).
    -   `firewalld`: Интеграция через `firewall-cmd`.

### Инкрементальная блокировка (Incremental Banning)

Современные версии fail2ban поддерживают «рецидивную» схему (recidive jail). Если IP-адрес блокируется повторно в течение короткого времени, срок бана увеличивается экспоненциально. Это эффективно против ботов, которые возвращаются сразу после разблокировки.

## Практические сценарии

### Установка

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install fail2ban ipset

# RHEL / AlmaLinux / Rocky
sudo dnf install fail2ban fail2ban-firewalld
```

### Базовая настройка

Всегда используйте файл `jail.local` для переопределения настроек, чтобы избежать потери данных при обновлении пакета.

```bash
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
```

#### Глобальные настройки (`/etc/fail2ban/jail.local`)

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

Обычно включена по умолчанию, но требует проверки `enabled = true`.

```ini
[sshd]
enabled = true
port    = ssh
logpath = %(sshd_log)s
maxretry = 3
```

#### Защита от рецидивистов (Recidive)

Блокирует на длительный срок (например, на неделю) те IP, которые часто попадают в бан в других модулях.

```ini
[recidive]
enabled  = true
logpath  = /var/log/fail2ban.log
banaction = %(banaction_allports)s
bantime  = 1w
findtime = 1d
maxretry = 5
```

### Интеграция с nftables

В современных ОС (Debian 11+, RHEL 8+) рекомендуется использовать `nftables`. Fail2ban создает таблицу `f2b-table` и динамически управляет наборами адресов.

```ini
# jail.local
[DEFAULT]
banaction = nftables-multiport
banaction_allports = nftables-allports
```

Просмотр заблокированных адресов в nftables:
```bash
nft list set inet f2b-table addr-set-sshd
```

### Интеграция с Nginx и Rate Limiting

Fail2ban может блокировать IP, которые вызывают ошибки 404 (поиск админок) или превышают лимиты запросов Nginx.

1.  **В Nginx** (подробнее в [DDoS-защита](../../../Security/ApplicationSecurity/ddos_overview.md)):
    ```nginx
    limit_req_zone $binary_remote_addr zone=one:10m rate=1r/s;
    ```
2.  **В fail2ban** (`jail.local`):
    ```ini
    [nginx-limit-req]
    enabled = true
    port    = http,https
    filter  = nginx-limit-req
    logpath = /var/log/nginx/error.log
    maxretry = 5
    ```

### Управление через CLI

```bash
# Проверка общего статуса
sudo fail2ban-client status

# Статус конкретной "тюрьмы" и список заблокированных IP
sudo fail2ban-client status sshd

# Ручная блокировка IP
sudo fail2ban-client set sshd banip 1.2.3.4

# Ручная разблокировка IP
sudo fail2ban-client set sshd unbanip 1.2.3.4

# Разблокировать IP во всех тюрьмах сразу
sudo fail2ban-client unban 1.2.3.4
```

## Дополнительная информация

### Оптимизация производительности

-   **Использование ipset**: При использовании iptables обязательно включайте `banaction = iptables-ipset-protoall` для работы с тысячами заблокированных IP без деградации производительности.
-   **База данных**: Fail2ban хранит историю банов в `/var/lib/fail2ban/fail2ban.sqlite3`. Это позволяет сохранять состояние после перезагрузки сервиса.

### Типичные ошибки

1.  **Конфликт backend**: Если указан `backend = systemd`, но `logpath` ведет на несуществующий файл, сервис может не запуститься.
2.  **Блокировка самого себя**: Всегда добавляйте свои IP в `ignoreip`.
3.  **DROP vs REJECT**: По умолчанию используется REJECT. Для скрытия факта наличия фаервола можно сменить на DROP в файлах `action.d`.

### Связанные темы

-   [SSH hardening](../../ssh/server/ssh_hardening_best_practices.md) — комплексная защита SSH.
-   [nftables: практические сценарии](../../Networking/Settings/tools/nftables/practical_scenarios.md) — современная фильтрация.
-   [DDoS/WAF обзор](../../../Security/ApplicationSecurity/ddos_overview.md) — высокоуровневая защита.
-   [Linux security механизмы](../Linux_Security_Mechanisms_Overview.md) — контекст безопасности системы.

### Лучшие практики

1.  Никогда не редактируйте `jail.conf` напрямую.
2.  Используйте `recidive` jail для долгосрочной блокировки настойчивых атакующих.
3.  Настройте почтовые уведомления для критических сервисов.
4.  Периодически проверяйте логи: `tail -f /var/log/fail2ban.log`.
5.  Официальная документация: [fail2ban.org](https://www.fail2ban.org).
