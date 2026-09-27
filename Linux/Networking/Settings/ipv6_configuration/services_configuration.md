# Настройка сервисов для работы с IPv6

## Определения

**IPv6-поддержка в сервисах** — способность приложения прослушивать сокеты IPv6 и корректно обрабатывать трафик с адресов длиной 128 бит.

**Режимы прослушивания:**
- **Dual Stack (слушание на `::`)**: сервис прослушивает адрес `::`, что позволяет принимать соединения как по IPv6, так и по IPv4 (при условии, что механизм IPv4-mapped addresses не отключен в ядре). Подробнее о Dual Stack: **[Сосуществование IPv4 и IPv6](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)**.
- **Separate Sockets (Раздельные сокеты)**: явное создание независимых сокетов для IPv4 (`0.0.0.0`) и IPv6 (`::` или конкретные адреса). Требует `net.ipv6.bindv6only=1` или использования опции сокета `IPV6_V6ONLY`.
- **IPv6-only (чистый IPv6)**: сервис слушает только IPv6, явно отказываясь от IPv4-трафика. Используется в IPv6-only инфраструктурах.

**IPv6 Socket Option (`IPV6_V6ONLY`)** — опция уровня сокета (SOL_IPV6), которая управляет поведением отдельного сокета независимо от глобального параметра `net.ipv6.bindv6only`. Если установлена в `1`, сокет `[::]` принимает только IPv6, даже если `bindv6only=0`. Это позволяет приложению гибко управлять поведением без изменения глобальных sysctl.

**systemd Socket Activation** — механизм systemd, при котором сокет создается и прослушивается менеджером systemd, а сервис запускается по требованию при поступлении соединения. Позволяет централизованно управлять прослушиваемыми адресами и портами, включая IPv6.

## Основные концепции

### Механизм IPv4-mapped IPv6

В Linux IPv6-сокет, слушающий на `::`, по умолчанию может принимать IPv4-соединения. IPv4-адрес клиента при этом представляется в виде IPv6-адреса с префиксом `::ffff:0:0/96` (например, `::ffff:192.168.1.1`).
Подробнее: **[Сосуществование IPv4 и IPv6](../../../../Networking/OSI_TCP_IP_Model/Network_layer/Concepts/ipv4_ipv6_dual_stack.md)**.

### Параметр bindv6only

Поведение стека регулируется параметром ядра `net.ipv6.bindv6only`:
- **`0` (Значение по умолчанию)**: сокет `[::]` принимает трафик обоих протоколов.
- **`1`**: сокет `[::]` принимает **только** IPv6. Для поддержки IPv4 сервис должен явно слушать на `0.0.0.0`. Это считается более безопасным и прозрачным для логирования и контроля доступа.

### Socket Option IPV6_V6ONLY vs sysctl bindv6only

Глобальный параметр `net.ipv6.bindv6only` задает поведение по умолчанию для всех новых IPv6-сокетов. Однако отдельное приложение может переопределить это поведение на уровне сокета через опцию `IPV6_V6ONLY`:
- Если `bindv6only=0`, но приложение установило `IPV6_V6ONLY=1`, сокет будет принимать только IPv6.
- Если `bindv6only=1`, приложение может установить `IPV6_V6ONLY=0`, чтобы принимать оба протокола (требует поддержки в коде приложения).

**Практическое значение:**
- `bindv6only=0` — удобно для legacy-приложений, не поддерживающих отдельные сокеты.
- `bindv6only=1` — рекомендуется для новых приложений, так как явно разделяет потоки IPv4 и IPv6, упрощая логирование и аудит.
- `IPV6_V6ONLY` — используется приложениями, которые хотят управлять поведением самостоятельно (например, Nginx с `ipv6only=on`).

### Синтаксис IPv6 в конфигурациях

Из-за использования двоеточия в качестве разделителя в адресах, большинство сервисов требуют заключения IPv6-адреса в квадратные скобки при указании вместе с портом: `[2001:db8::1]:80`.

### systemd Socket Activation для IPv6

Параметр `ListenStream` в юнитах systemd socket поддерживает IPv6-адреса:
```ini
# /etc/systemd/system/nginx.socket
[Socket]
ListenStream=[::]:80
ListenStream=0.0.0.0:80

[Install]
WantedBy=sockets.target
```

```ini
# /etc/systemd/system/nginx@.service
[Service]
ExecStart=/usr/sbin/nginx -g "daemon off;"
```

```bash
# Активация
sudo systemctl enable --now nginx.socket
```

При таком подходе systemd создает оба сокета (IPv4 и IPv6) и запускает сервис при первом соединении.

## Практические сценарии

### 1. Веб-серверы и прокси

#### Nginx

**Dual Stack (рекомендуемый режим):**
```nginx
server {
    listen 80;
    listen [::]:80;
    listen 443 ssl http2;
    listen [::]:443 ssl http2;

    server_name example.com;
    root /var/www/html;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
}
```

**IPv6-only сервер:**
```nginx
server {
    listen [::]:80;
    listen [::]:443 ssl http2;
    # ipv6only=on можно добавить явно, если bindv6only=0
}
```

**Параметр `ipv6only`:**
- `ipv6only=on` — сокет принимает только IPv6, переопределяя `bindv6only`.
- `ipv6only=off` — сокет принимает оба протокола.
- `ipv6only=default` — использует значение по умолчанию из `bindv6only`.

**Проверка:**
```bash
# Проверка, что Nginx слушает IPv6
ss -6 -lntp | grep nginx
# → LISTEN 0 511 [::]:80 [::]:* users:(("nginx",pid=1234,fd=6))

# Проверка IPv4-mapped (если bindv6only=0)
ss -6 -lntp | grep '::ffff'
# → LISTEN 0 511 [::]:80 [::]:* (dual-stack)
```

#### Apache

**Dual Stack:**
```apache
# /etc/apache2/ports.conf
Listen 80
Listen [::]:80
Listen 443
Listen [::]:443
```

```apache
# /etc/apache2/sites-available/example.conf
<VirtualHost *:80>
    ServerName example.com
    DocumentRoot /var/www/html
</VirtualHost>

<VirtualHost [::1]:80>
    ServerName example.com
    DocumentRoot /var/www/html
</VirtualHost>
```

**Важно:** При использовании `NameVirtualHost` в Apache 2.4+ необходимо указать отдельно для IPv4 и IPv6 или использовать `*` для обоих:
```apache
NameVirtualHost *:80
NameVirtualHost [::]:80
```

#### HAProxy

**Dual Stack frontend:**
```haproxy
frontend web_front
    bind :::80 v4v6
    bind :::443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
    default_backend web_back

backend web_back
    server web1 192.168.1.10:8080 check
    server web2 2001:db8::10:8080 check
```

**Ключевые особенности:**
- Тройное двоеточие `:::` — сокращение для `::` с портом.
- Параметр `v4v6` в `bind` явно указывает, что сокет должен принимать оба протокола (аналог `bindv6only=0`).

### 2. Системные и инфраструктурные сервисы

#### SSH (sshd)

**Dual Stack (все интерфейсы):**
```bash
# /etc/ssh/sshd_config
ListenAddress ::
ListenAddress 0.0.0.0
```

**Только IPv6:**
```bash
# /etc/ssh/sshd_config
ListenAddress ::
```

**Только IPv4:**
```bash
# /etc/ssh/sshd_config
ListenAddress 0.0.0.0
```

**Проверка:**
```bash
sudo ss -6 -lntp | grep sshd
# → LISTEN 0 128 [::]:22 [::]:* users:(("sshd",pid=876,fd=3))
```

#### Chrony (NTP)

**Привязка ко всем интерфейсам (IPv4 + IPv6):**
```ini
# /etc/chrony/chrony.conf
bindaddress ::
allow 2001:db8:cafe::/64
```

**Привязка только к IPv6:**
```ini
# /etc/chrony/chrony.conf
bindaddress 2001:db8::1
```

#### systemd-resolved

**Проверка DNS-резолвинга через IPv6:**
```bash
# Статус DNS
resolvectl status

# Прямой запрос через IPv6 DNS
resolvectl query example.com --dns=2001:4860:4860::8888
```

#### systemd Socket Activation

**Пример для кастомного сервиса (TCP echo server):**

```ini
# /etc/systemd/system/echo.service
[Unit]
Description=Echo Service
After=network.target

[Service]
ExecStart=/usr/bin/socat TCP-LISTEN:0,ipv6,fork,reuseaddr -
Restart=always
```

```ini
# /etc/systemd/system/echo.socket
[Unit]
Description=Echo Socket

[Socket]
ListenStream=[::]:8080
ListenStream=0.0.0.0:8080

[Install]
WantedBy=sockets.target
```

```bash
# Активация
sudo systemctl enable --now echo.socket
sudo systemctl status echo.socket
# → Active: active (listening)
```

#### Docker

**Включение IPv6 в демоне:**
```json
{
  "ipv6": true,
  "fixed-cidr-v6": "fd00::/64"
}
```

**Создание IPv6-сети:**
```bash
# Создание bridge-сети с IPv6
docker network create --ipv6 --subnet fd00::/64 my-ipv6-net

# Запуск контейнера в сети
docker run -d --name web --network my-ipv6-net nginx
```

**Проверка:**
```bash
docker inspect web | grep IPv6Address
# → "IPv6Address": "fd00::2/64"
```

#### rsyslog (remote logging)

**Прием логов по IPv6:**
```conf
# /etc/rsyslog.d/10-ipv6-listen.conf
# Прослушивание IPv6 на порт 514
module(load="imtcp" ipv6="on")
input(type="imtcp" port="514" ipv6="on")
```

#### syslog-ng

**Прием логов по IPv6:**
```conf
# /etc/syslog-ng/syslog-ng.conf
source s_net {
    tcp(ip(::) port(514));
    udp(ip(::) port(514));
};
```

### 3. Базы данных

#### PostgreSQL

**Включение прослушивания на IPv6:**
```conf
# /etc/postgresql/*/main/postgresql.conf
listen_addresses = '::'
# Или для Dual Stack:
# listen_addresses = '::,0.0.0.0'
```

**Настройка доступа в pg_hba.conf:**
```conf
# TYPE  DATABASE        USER            ADDRESS                 METHOD
host    all             all             2001:db8:beef::/64      scram-sha-256
host    all             all             ::ffff:192.168.1.0/24   scram-sha-256
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
```

**Важно:** PostgreSQL по умолчанию использует `scram-sha-256` или `md5`. При подключении через IPv6 убедитесь, что pg_hba.conf содержит соответствующую строку для IPv6-подсети.

**Проверка:**
```bash
# Проверка прослушиваемых адресов
sudo ss -6 -lntp | grep postgres
# → LISTEN 0 128 [::]:5432 [::]:* users:(("postgres",pid=1234,fd=5))

# Проверка подключения по IPv6
psql -h 2001:db8::1 -U postgres -d mydb
```

#### Redis

**Настройка прослушивания на IPv6:**
```ini
# /etc/redis/redis.conf
bind 127.0.0.1 ::1
# Или для всех интерфейсов (небезопасно без firewall):
# bind :: -::*
protected-mode yes
```

**Проверка:**
```bash
sudo ss -6 -lntp | grep redis
# → LISTEN 0 128 [::]:6379 [::]:* users:(("redis-server",pid=1234,fd=6))
```

#### MySQL / MariaDB

**Включение прослушивания на IPv6:**
```ini
# /etc/mysql/mysql.conf.d/mysqld.cnf
[mysqld]
bind-address = ::
# Или явно:
# bind-address = 2001:db8::10

# Рекомендуется отключить DNS-резолвинг для ускорения подключений
skip-name-resolve
```

**Предупреждение:** При `skip-name-resolve` все хосты в `mysql.user` должны указываться по IP-адресу. Убедитесь, что записи для `::1` и `127.0.0.1` существуют:
```sql
CREATE USER 'root'@'::1' IDENTIFIED BY 'password';
GRANT ALL PRIVILEGES ON *.* TO 'root'@'::1';
```

**Проверка:**
```bash
sudo ss -6 -lntp | grep mysqld
# → LISTEN 0 80 [::]:3306 [::]:* users:(("mysqld",pid=1234,fd=14))
```

### 4. IPv6-only сервисы

В средах с отключенным IPv4 или при необходимости явной изоляции протоколов настраивается IPv6-only режим:

```bash
# Глобально (влияет на все новые сокеты)
sudo sysctl -w net.ipv6.conf.all.bindv6only=1

# Для конкретного сервиса через systemd override
sudo systemctl edit nginx
# [Service]
# ExecStartPre=/sbin/sysctl -w net.ipv6.conf.all.bindv6only=1
```

**Валидация:**
```bash
# Сокет должен виден только в ss -6, но не в ss -4
ss -6 -lntp | grep nginx
# → есть запись
ss -4 -lntp | grep nginx
# → нет записи (пусто)
```

## Диагностика и проверка

### Анализ прослушиваемых сокетов

```bash
# Просмотр всех TCP-портов IPv6 в режиме прослушивания
ss -6 -lnt

# Просмотр процессов и портов (требуются права root)
sudo ss -6 -lntp

# Все TCP/UDP сокеты (включая неслушающие)
ss -6 -t -a
ss -6 -u -a

# Внутренняя информация о соединениях (PMTUD, MSS)
ss -6 -i

# Проверка конкретного порта
ss -6 -ant | grep :443
```

**Интерпретация вывода:**
- `*:80` или `[::]:80` в столбце Local Address означает готовность принимать IPv6.
- Если `net.ipv6.bindv6only=0`, то `[::]:80` обычно означает прием и IPv4, и IPv6.
- Для проверки, что сокет принимает IPv4, посмотрите на наличие `::ffff:` в выводе `ss -6` или выполните `ss -4 -lntp | grep :80`.

### Проверка через /proc/net/tcp6

```bash
# Чтение таблицы TCP6 сокетов
cat /proc/net/tcp6

# Формат: sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
# local_address в формате [::port]:addr (big-endian hex)

# Пример: порт 80 (0x0050)
# 00000000000000000000000000000000 00000000000000000000000000000000 0A 00000000 00000000 00000000 00000000 00000000 00000000 00000000

# Декодирование адреса (hex → human-readable):
# 00000000000000000000000000000000 = ::
# 00000000000000000000000000000000 = ::
```

### Проверка через getent ahosts

```bash
# Получение всех адресов (A + AAAA) для домена
getent ahosts example.com
# → 192.0.2.1 SYSSTRM  # IPv4
# → 2001:db8::1 SYSSTRM # IPv6

# Принудительно IPv6
getent ahosts6 example.com
```

### Тестирование доступности

```bash
# Проверка TCP-порта через netcat
nc -6 -zv ::1 22

# Проверка HTTP-заголовков через curl
curl -6 -I http://[::1]/

# Проверка dual-stack (оба протокола должны работать)
curl -4 -I http://127.0.0.1/
curl -6 -I http://[::1]/
```

### Проверка IPv4-mapped трафика

```bash
# Перехват пакетов с IPv4-mapped адресами
sudo tcpdump -i eth0 -n 'ip6 and ((ip6[0] & 0xf0) == 0x60) and (ip6 dst ::ffff:0.0.0.0/96 or ip6 src ::ffff:0.0.0.0/96)'
```

## Дополнительная информация

### Типичные ошибки

- **Пропуск квадратных скобок**: в URL и многих конфигах `http://2001:db8::1/` вызовет ошибку парсинга. Правильно: `http://[2001:db8::1]/`.
- **Локальные адреса (Link-Local)**: сервисы редко должны слушать на `fe80::/10`. Если это необходимо, в адресе нужно указывать Scope ID: `[fe80::1%eth0]:8080`.
- **Забытый IPv6 Firewall**: часто порт открывают в `iptables`, но забывают про `ip6tables` или `nftables`, из-за чего сервис недоступен извне по IPv6.
- **Dual Stack без bindv6only**: если `bindv6only=0` (по умолчанию), сокет `[::]:80` принимает и IPv4. Это может скрыть ошибки конфигурации, когда сервис слушает только на `[::]`, но администратор считает, что это IPv6-only.
- **Redis bind**: `bind * -::*` включает прослушивание на всех интерфейсах IPv4 и IPv6. Убедитесь, что `protected-mode yes` включен.
- **PostgreSQL pg_hba.conf**: привязка к `::` без соответствующей строки в `pg_hba.conf` блокирует все IPv6-подключения. Всегда добавляйте строку для IPv6-подсети.
- **MySQL skip-name-resolve**: при включении этой опции все хосты в `mysql.user` должны быть IP-адресами, включая `::1` и `127.0.0.1`.

### Таблица устранения неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Нет подключения по IPv6 | Файрвол блокирует порт в `ip6tables`/`nftables` | Разрешить порт в семействе `inet`. См. **[Firewall для IPv6](./firewall.md)** |
| Служба слушает только IPv4 | В конфиге указан `0.0.0.0`, а не `[::]` или `::` | Добавить `listen [::]:80` (Nginx/Apache) или `bind :::80` (HAProxy) |
| Служба слушает IPv6, но IPv4 не работает | `bindv6only=1` или `ipv6only=on` без отдельного IPv4-сокета | Либо добавить IPv4-слушатель, либо отключить `bindv6only` |
| `ss -6` показывает сокет, но `curl -6` не подключается | Файрвол блокирует, или служба привязана к неправильному адресу | `ss -6 -lntp`, `tcpdump -i eth0 tcp port 80` |
| PostgreSQL: `pg_hba.conf` не пускает по IPv6 | Отсутствует строка для IPv6-подсети в `pg_hba.conf` | Добавить `host all all 2001:db8::/64 scram-sha-256` |
| MySQL: `skip-name-resolve` блокирует root | `root`@`::1` не существует в `mysql.user` | Создать пользователя с IPv6-адресом: `CREATE USER 'root'@'::1'` |
| Redis: `bind` настроен, но клиент не подключается | `protected-mode yes` блокирует внешние подключения | Либо добавить клиента в `bind`, либо отключить `protected-mode` |
| Nginx: `ipv6only=on` не работает | Служебный параметр указан в неправильном блоке | Указать `ipv6only=on` в той же директиве `listen`, что и `[::]:port` |
| Apache: 403 Forbidden только для IPv6 | Не настроен `NameVirtualHost` для `[::]:80` | Добавить `NameVirtualHost [::]:80` |
| Docker: контейнер не получает IPv6 | В демоне не включен `ipv6` или не указан `fixed-cidr-v6` | Проверить `docker info | grep IPv6`, перезапустить демон |
| systemd socket не слушает IPv6 | В `ListenStream` не указаны квадратные скобки | Использовать `ListenStream=[::]:80` (с квадратными скобками) |
| `getent ahosts` возвращает только IPv4 | Нет AAAA-записи в DNS или `gai.conf` отдает IPv4 приоритет | Проверить `dig AAAA example.com`, проверить `/etc/gai.conf` |

### Best Practices

1. **Dual Stack по умолчанию:** Для большинства сервисов используйте Dual Stack (`listen [::]:80` + `listen 80`), а не IPv6-only, чтобы обеспечить совместимость.
2. **bindv6only=1 для новых приложений:** В средах, где IPv4 не требуется, устанавливайте `bindv6only=1` для явного разделения протоколов.
3. **sysctl persistence:** Все параметры ядра записывайте в `/etc/sysctl.d/*.conf`, а не применяйте временно.
4. **SSH Dual Stack:** Явно указывайте оба слушателя (`ListenAddress ::` и `ListenAddress 0.0.0.0`), чтобы не зависеть от значения `bindv6only`.
5. **Базы данных:** Всегда добавляйте IPv6-записи в `pg_hba.conf` и `mysql.user` при переходе на Dual Stack.
6. **Firewall Dual Stack:** Используйте `nftables` с семейством `inet` для единых правил, чтобы не пропустить IPv6.
7. **Валидация после изменений:** Всегда проверяйте `ss -6 -lntp`, `ss -4 -lntp` и `curl -4`/`curl -6` после изменения конфигурации.
8. **Scope ID для Link-Local:** Всегда указывайте `%interface` при работе с Link-Local адресами в конфигах и командах.

### См. также

- **[Настройка адресов IPv6](./address_configuration.md)** — подготовка интерфейсов.
- **[Firewall для IPv6](./firewall.md)** — открытие портов и безопасность ICMPv6.
- **[Диагностика IPv6](./diagnostics.md)** — отладка сетевой связности.
- **[Kubernetes Dual-Stack](./kubernetes_dual_stack.md)** — IPv6 в Kubernetes-кластерах.
- **[Мониторинг IPv6](./monitoring.md)** — Prometheus, Blackbox Exporter, alerting для IPv6.
