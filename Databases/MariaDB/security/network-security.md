# Сетевая безопасность MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

Контроль сетевого доступа — первый рубеж защиты. Даже самый сильный пароль бесполезен, если порт открыт на всю сеть без ограничений.

## Определения

- **bind-address** — IP-адрес интерфейса, к которому привязывается `mysqld` (параметр `bind-address` в `my.cnf`). Привязка к `127.0.0.1` отключает удалённые TCP-подключения полностью.
- **skip-networking** — параметр, полностью отключающий TCP/IP-сокет. MariaDB слушает только Unix-сокет и shared memory. Полезен на резервных хостах или в контейнерах без внешнего доступа.
- **skip-name-resolve** — отключает DNS-резолв при проверке хоста в `mysql.user`. Ускоряет подключение и исключает DNS-spoofing, но требует, чтобы в GRANT были указаны IP-адреса, а не домены.
- **max_connections** — глобальный лимит одновременных соединений к инстансу.
- **max_user_connections** — пер-пользовательский лимит одновременных соединений.
- **wait_timeout / interactive_timeout** — время неактивности (в секундах), после которого неинтерактивное / интерактивное соединение закрывается сервером.
- **max_allowed_packet** — максимальный размер одного сетевого пакета. Защищает от попыток передать сверхбольшой запрос через один пакет.
- **max_connect_errors** — количество ошибок соединения с хоста, после которого MariaDB блокирует дальнейшие попытки с этого хоста.
- **Unix-сокет** — файловый дескриптор (обычно `/var/lib/mysql/mysql.sock`), через который локальные клиенты подключаются без TCP. Быстрее TCP и не зависит от файрвола.
- **MariaDB X Protocol** — протокол для SQL/NoSQL-доступа, работающий поверх TCP отдельно от классического MySQL-протокола. По умолчанию порт `33060`.

## Архитектура сетевого доступа

Сетевой слой MariaDB состоит из трёх независимых плоскостей:

1. **Unix-сокет и shared memory** — локальный транспорт между клиентом на том же хосте и `mysqld`. Не требует `bind-address`, не проходит через файрвол, не шифруется. Параметры: `socket`, `shared-memory-base-name`.
2. **Классический MySQL-протокол (TCP)** — порт `3306/TCP` по умолчанию. Ограничивается `bind-address`, файрволом хоста, `skip-networking`, `skip-name-resolve`.
3. **X Protocol** — порт `33060/TCP` по умолчанию. Включён через `mysqlx=1`. Требует отдельного контроля доступа и, как и классический протокол, шифруется через TLS.

```ini
[mariadb]
# Локальный транспорт
socket = /var/lib/mysql/mysql.sock
skip-networking = 0

# TCP-транспорт (классический)
bind-address = 10.0.5.20
port = 3306

# X Protocol
mysqlx = 1
mysqlx-bind-address = 10.0.5.20
mysqlx-port = 33060
```

## Привязка к интерфейсу и ограничение доступа

### Основные сценарии

```ini
[mariadb]
# Сценарий A: только локальный доступ (без удалённых подключений)
bind-address = 127.0.0.1
# skip-networking = 1  # альтернатива: полное отключение TCP

# Сценарий B: доступ только с конкретного интерфейса
bind-address = 10.0.5.20

# Сценарий C: доступ с нескольких интерфейсов (MariaDB 10.4+)
# skip-networking = 0
# bind-address = 0.0.0.0  # слушать на всех, но ограничить файрволом
```

> **Важно:** `bind-address = 0.0.0.0` слушает на всех IPv4-интерфейсах. Рекомендуется привязка к конкретному адресу или `127.0.0.1`. Если требуется доступ через IPv6 — используйте `::1` или конкретный IPv6-адрес; MariaDB привязается к нему отдельно.

## Ограничение соединений (защита от DoS)

```ini
[mariadb]
# Максимальное количество одновременных соединений (весь сервер)
max_connections = 500

# Лимит соединений на одного пользователя (вместе с глобальным)
max_user_connections = 50

# Таймаут неактивных соединений (в секундах)
wait_timeout = 600
interactive_timeout = 600

# Максимальный размер пакета (защита от атак через большие запросы)
max_allowed_packet = 64M

# Количество ошибок соединения с хоста, после которого блокируются дальнейшие попытки
max_connect_errors = 100
```

```sql
-- Проверка текущих лимитов
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'max_user_connections';
SHOW VARIABLES LIKE 'wait_timeout';
SHOW VARIABLES LIKE 'max_connect_errors';
SHOW GLOBAL STATUS LIKE 'Max_used_connections';
SHOW GLOBAL STATUS LIKE 'Connection_errors_max_connections';

-- Мониторинг активных соединений
SELECT USER, HOST, COUNT(*) as connections
FROM information_schema.PROCESSLIST
GROUP BY USER, HOST
ORDER BY connections DESC;
```

## TCP-параметры хоста (sysctl)

Поведение TCP-стек влияет на устойчивость соединений и защиту от SYN-flood / TIME-WAIT exhaustion:

```bash
# /etc/sysctl.d/99-mariadb-tcp.conf

# Увеличить backlog для синхронизации очереди
net.core.somaxconn = 4096

# Защита от SYN-флуда
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_synack_retries = 2

# Повторить отправку TCP keepalive
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 60
net.ipv4.tcp_keepalive_probes = 5

# Ограничить TIME-WAIT очередь
net.ipv4.tcp_max_tw_buckets = 1440000
net.ipv4.tcp_tw_reuse = 1

# Применение
sudo sysctl --system
```

## Настройка файрвола

### UFW (Debian/Ubuntu)

```bash
# Разрешить доступ к MariaDB только с конкретных подсетей
sudo ufw allow from 10.0.5.0/24 to any port 3306 proto tcp

# Или с конкретного IP (напр., приложение на том же хосте)
sudo ufw allow from 10.0.5.10 to any port 3306 proto tcp

# X Protocol (если используется)
sudo ufw allow from 10.0.5.0/24 to any port 33060 proto tcp

# Запретить всё остальное на 3306
sudo ufw deny 3306/tcp

# Проверка правил
sudo ufw status verbose
```

### firewalld (RHEL/CentOS/Fedora)

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="3306" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="33060" protocol="tcp" accept'
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

### nftables (Debian 12+, RHEL 9+, современные дистрибутивы)

```bash
sudo nft add rule inet filter input ip saddr 10.0.5.0/24 tcp dport 3306 accept
sudo nft add rule inet filter input ip saddr 10.0.5.0/24 tcp dport 33060 accept
sudo nft list ruleset
```

## TCP wrappers

MariaDB 10.6+ поддерживает TCP wrappers через `/etc/hosts.allow` и `/etc/hosts.deny` (требует компиляции с `--with-libwrap`):

```bash
# /etc/hosts.deny
mysqld: ALL

# /etc/hosts.allow
mysqld: 10.0.5. 127.0.0.1
```

> **Важно:** TCP wrappers проверяются до аутентификации MariaDB. Убедитесь, что файлы имеют корректные права (`root:root`, `0644`), иначе MariaDB отклонит все подключения.

## systemd socket activation

Для полного описания systemd управления см. **[MariaDB под systemd](systemd.md#socket-activation)**.

На современных системах MariaDB может запускаться через `systemd`-сокет, что позволяет сервису запускаться по первому подключению и упрощает управление:

```ini
# /etc/systemd/system/mariadb.socket
[Unit]
Description=MariaDB Socket

[Socket]
ListenStream=/var/lib/mysql/mysql.sock
ListenStream=3306
# Accept=yes включает per-connection сервис
Accept=no

[Install]
WantedBy=sockets.target
```

```bash
sudo systemctl enable --now mariadb.socket
```

> **Важно:** При socket activation параметр `bind-address` игнорируется; привязка выполняется через `systemd`. Проверяйте `ss -tlnp | grep 3306` — в выводе должен быть `systemd`, а не `mysqld`.

## Валидация

```bash
# Проверка, что MariaDB слушает только на нужных адресах
ss -tlnp | grep 3306
# → 10.0.5.20:3306, не 0.0.0.0:3306

# Проверка, что порт 3306 не открыт на 0.0.0.0
sudo ss -tnlp | grep 3306

# Проверка файрвола
sudo ufw status verbose
sudo firewall-cmd --list-all
sudo iptables -L -n | grep 3306
sudo nft list ruleset

# Проверка Unix-сокета
ls -la /var/lib/mysql/mysql.sock
mysql -u root -e "SHOW VARIABLES LIKE 'socket';"

# Проверка X Protocol
mysql -u root -e "SHOW VARIABLES LIKE 'mysqlx%';"
ss -tlnp | grep 33060
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[SSL/TLS](ssl-tls.md)** — шифрование трафика через TLS.
- **[Аутентификация](authentication.md)** — защита от brute-force, `max_password_errors`, `caching_sha2_password`.
- **[Дополнительные параметры](additional-parameters.md)** — `local-infile`, `skip-show-database` и другие параметры безопасности.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation`.
- **[Диагностика репликации](../replication/troubleshooting.md)** — `Error 2003` при репликации.
- **[Диагностика безопасности](../security/troubleshooting.md)** — `ERROR 2003`, отказ файрвола, DoS.

## Дополнительная информация

- [MariaDB Server System Variables](https://mariadb.com/docs/server/server-system-variables/)
- [MariaDB Firewall Rules (UFW)](https://help.ubuntu.com/community/UFW)
- [firewalld Rich Rules](https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html)
- [nftables Wiki](https://wiki.nftables.org/)
- [CIS MariaDB Benchmark](https://www.cisecurity.org/benchmark/mariadb)
