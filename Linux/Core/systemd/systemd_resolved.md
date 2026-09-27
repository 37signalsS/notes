# systemd-resolved: DNS-резолвер и управление именами

## Определения

* **`systemd-resolved`** — системный DNS-резолвер, интегрированный в `systemd`, обеспечивающий разрешение доменных имен, кэширование, валидацию DNSSEC и поддержку шифрованных протоколов (DNS-over-TLS, DNS-over-HTTPS, DNS-over-QUIC).
* **Stub-резолвер (заглушка)** — локальная служба, работающая на `127.0.0.53` (стандартный порт), принимающая запросы от приложений и пересылающая их внешним (upstream) DNS-серверам. Обеспечивает единую точку входа для всех DNS-запросов системы.
* **Split DNS** — механизм маршрутизации DNS-запросов через разные upstream-серверы в зависимости от домена или сетевого интерфейса. Позволяет направлять внутренние запросы корпоративного DNS через VPN, а внешние — через публичные резолверы.
* **DNSSEC (DNS Security Extensions)** — набор расширений протокола DNS, обеспечивающих аутентичность и целостность DNS-ответов. `systemd-resolved` может валидировать DNSSEC-записи, защищая от атак подмены (spoofing).
* **DNS-over-TLS (DoT)** — протокол шифрования DNS-трафика через TLS (порт 853). Предотвращает перехват и модификацию DNS-запросов промежуточными узлами.
* **DNS-over-HTTPS (DoH)** — протокол шифрования DNS-трафика через HTTPS (порт 443). Более устойчив к блокировке, чем DoT, так как использует стандартный HTTPS-трафик.
* **DNS-over-QUIC (DoQ)** — современный протокол шифрования DNS на базе QUIC (v255+). Обеспечивает меньшие задержки за счет использования UDP вместо TCP.
* **LLMNR (Link-Local Multicast Name Resolution)** — протокол разрешения имен в локальной сети без DNS-сервера. Использует multicast-адрес `224.0.0.252:5355`. Включен по умолчанию, но рекомендуется отключать в production для безопасности.
* **mDNS (Multicast DNS)** — протокол разрешения имен в локальной сети (RFC 6762), используемый для обнаружения устройств (Apple Bonjour, Avahi). Работает на multicast-адресе `224.0.0.251:5353`.

## Основные концепции

### Архитектура и место в системе

`systemd-resolved` занимает центральное место в цепочке разрешения имен Linux:

```
Приложение (curl, ssh, wget)
        │
        ▼
  NSS (getaddrinfo)
        │
        ▼
  /etc/nsswitch.conf (hosts: resolve)
        │
        ▼
  D-Bus API → systemd-resolved (127.0.0.53)
        │
        ├─→ Кэш (внутренний)
        ├─→ DNSSEC валидация
        └─→ Upstream DNS-серверы
              │
              ├─→ 1.1.1.1 (DoT)
              ├─→ 8.8.8.8 (обычный)
              └─→ 10.0.0.2 (корпоративный через VPN)
```

### Интеграция с systemd-networkd

`systemd-resolved` тесно интегрирован с `systemd-networkd`. При настройке DNS в `.network` файлах:

```ini
# /etc/systemd/network/eth0.network
[Network]
DHCP=yes

# DNS-серверы, полученные через DHCP
DNS=10.0.0.2 10.0.0.3

# Домены поиска
Domains=~corp.internal

# Включить DNS-over-TLS
DNSOverTLS=yes
```

`systemd-networkd` передает эти настройки в `systemd-resolved`, который автоматически маршрутизирует запросы к соответствующим upstream-серверам.

### Жизненный цикл службы

`systemd-resolved` состоит из двух юнитов:

1. **`systemd-resolved.service`** — основной демон, обрабатывающий DNS-запросы.
2. **`systemd-resolved.socket`** — socket-активация для запуска демона при первом DNS-запросе.

```bash
# Проверка статуса
systemctl status systemd-resolved

# Проверка socket-активации
systemctl status systemd-resolved.socket
```

### Сравнение с традиционным подходом

| Характеристика | Традиционный (resolv.conf) | systemd-resolved |
| :--- | :--- | :--- |
| **Кэширование** | Нет (или nscd) | Встроенное с TTL |
| **DNSSEC** | Нет | Полная поддержка |
| **DoT/DoH/DoQ** | Нет | Нативная поддержка |
| **Split DNS** | Ограниченно | Полная поддержка |
| **Переконфигурация** | Перезапуск сервисов | Горячая перезагрузка |
| **Интеграция с systemd** | Минимальная | Полная |

## Конфигурация

### Глобальные параметры: /etc/systemd/resolved.conf

```ini
[Resolve]
# Upstream DNS-серверы (можно указать несколько)
# Формат: протокол://адрес#имя_хоста
DNS=1.1.1.1 8.8.8.8 2606:4700:4700::1111

# DNS over TLS (DoT) - шифрование через TLS (порт 853)
DNSOverTLS=yes

# DNS over QUIC (DoQ) - поддержка в v255+
# DNS=quic://dns.adguard-dns.com

# DNSSEC валидация
# yes - включена, bogus ответы отбрасываются
# allow-downgrade - включена с fallback при проблемах
# no - отключена
DNSSEC=yes

# Локальный домен поиска
# ~. - принять все запросы (default route для DNS)
# ~corp.internal - только запросы к этому домену
Domains=~.

# LLMNR (Link-Local Multicast Name Resolution)
# Рекомендуется отключать в production для безопасности
LLMNR=no

# mDNS (multicast DNS)
MulticastDNS=no

# Статус заглушки на 127.0.0.53
# yes - заглушка активна (по умолчанию)
# no - заглушка отключена, resolv.conf должен содержать реальные серверы
DNSStubListener=yes

# Режим управления /etc/resolv.conf
# auto - symlink на заглушку (по умолчанию)
# manual - ручное управление
# static - статический файл
ResolvConfMode=auto

# Кэширование
# yes - включено (по умолчанию)
# no - отключено
Cache=yes
CacheFromLocalhost=yes

# Отрицательное кэширование (для NXDOMAIN)
# Время хранения неудачных запросов
CacheFromLocalhost=no
```

### Применение конфигурации

```bash
# Проверка синтаксиса
sudo systemd-analyze cat-config systemd/resolved.conf

# Просмотр текущей конфигурации с учетом всех источников
resolvectl show-global

# Перезапуск службы
sudo systemctl restart systemd-resolved

# Проверка статуса
resolvectl status
# → Global
# →          Protocols: +LLMNR -mDNS +DNSOverTLS DNSSEC=yes/supported
# → resolv.conf mode: stub
```

### Per-link конфигурация (systemd-networkd)

```ini
# /etc/systemd/network/10-eth0.network
[Match]
Name=eth0

[Network]
DNS=10.0.0.2 10.0.0.3
Domains=~corp.internal ~.
DNSOverTLS=yes
DNSSEC=yes
```

```ini
# /etc/systemd/network/20-tun0.network
[Match]
Name=tun0

[Network]
# VPN-специфичные DNS-серверы
DNS=100.64.0.2
Domains=~vpn.corp.internal
```

### Управление через resolvectl

```bash
# Назначение DNS-серверов интерфейсу
sudo resolvectl dns eth0 10.0.0.2 10.0.0.3

# Назначение доменов поиска
sudo resolvectl domain eth0 "~corp.internal"

# Отключение DNS для интерфейса
sudo resolvectl revert eth0

# Просмотр текущей конфигурации
resolvectl status

# Просмотр DNS-серверов для конкретного домена
resolvectl query corp.internal
```

## Практические сценарии

### 1. Базовая настройка для сервера

```bash
# 1. Включить systemd-resolved
sudo systemctl enable --now systemd-resolved

# 2. Настроить /etc/resolv.conf как symlink
sudo rm -f /etc/resolv.conf
sudo ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

# 3. Настроить upstream-серверы
sudo tee /etc/systemd/resolved.conf <<EOF
[Resolve]
DNS=1.1.1.1 8.8.8.8
DNSOverTLS=yes
DNSSEC=yes
Domains=~.
LLMNR=no
MulticastDNS=no
Cache=yes
EOF

# 4. Перезапустить службу
sudo systemctl restart systemd-resolved

# 5. Проверить
resolvectl status
getent hosts google.com
```

### 2. Split DNS для VPN

Настройка маршрутизации внутренних запросов через VPN-туннель:

```bash
# 1. Настроить DNS для физического интерфейса
sudo resolvectl dns eth0 8.8.8.8 1.1.1.1
sudo resolvectl domain eth0 "~."

# 2. Настроить DNS для VPN-интерфейса
sudo resolvectl dns tun0 10.0.0.2
sudo resolvectl domain tun0 "~corp.internal"

# 3. Проверить маршрутизацию
resolvectl query corp.internal
# → corp.internal: 10.0.0.50 (через tun0)

resolvectl query google.com
# → google.com: 142.250.185.110 (через eth0)

# 4. Сделать персистентным через systemd-networkd
sudo tee /etc/systemd/network/10-eth0.network <<EOF
[Match]
Name=eth0

[Network]
DNS=8.8.8.8 1.1.1.1
Domains=~.
EOF

sudo tee /etc/systemd/network/20-tun0.network <<EOF
[Match]
Name=tun0

[Network]
DNS=10.0.0.2
Domains=~corp.internal
EOF

sudo systemctl restart systemd-networkd
```

### 3. Включение шифрованного DNS (DoT/DoH)

```bash
# 1. Настроить DoT в resolved.conf
sudo tee /etc/systemd/resolved.conf <<EOF
[Resolve]
DNS=1.1.1.1#cloudflare-dns.com 8.8.8.8#dns.google
DNSOverTLS=yes
DNSSEC=yes
EOF

# 2. Перезапустить службу
sudo systemctl restart systemd-resolved

# 3. Проверить статус
resolvectl status | grep -A5 "DNS Servers"
# → DNS Servers: 1.1.1.1 (cloudflare-dns.com), 8.8.8.8 (dns.google)

# 4. Проверить шифрованное соединение
sudo resolvectl log-level debug
# Найти в логах: "Using TCP for DNS server 1.1.1.1:853"
sudo resolvectl log-level info

# 5. Проверка через openssl
openssl s_client -connect 1.1.1.1:853
# → Должен показать успешное TLS-соединение
```

### 4. Диагностика DNS-проблем

```bash
# 1. Проверка, что systemd-resolved слушает
ss -ulnp | grep :53
# → MUST show systemd-resolve на 127.0.0.53

# 2. Проверка кэша
resolvectl statistics
# → Cache Statistics: 1234 hits, 567 misses

# 3. Очистка кэша
resolvectl flush-caches

# 4. Проверка через getent (учитывает NSS)
getent ahosts google.com

# 5. Проверка через dig (прямой запрос)
dig @8.8.8.8 google.com

# 6. Проверка через resolvectl (учитывает кэш)
resolvectl query google.com

# 7. Просмотр логов
journalctl -u systemd-resolved -n 50

# 8. Проверка доступных upstream-серверов
resolvectl dns
```

### 5. Отключение systemd-resolved и переход на традиционный режим

```bash
# 1. Остановить и отключить службу
sudo systemctl stop systemd-resolved
sudo systemctl disable systemd-resolved

# 2. Удалить симлинк и создать обычный файл
sudo rm -f /etc/resolv.conf
sudo tee /etc/resolv.conf <<EOF
nameserver 8.8.8.8
nameserver 1.1.1.1
options timeout:1 attempts:2 rotate
EOF

# 3. Проверить
getent hosts google.com
dig google.com +short

# 4. Проверить, что заглушка не слушает
ss -ulnp | grep 53

# Обратное включение
sudo systemctl enable --now systemd-resolved
sudo rm -f /etc/resolv.conf
sudo ln -s /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
```

### 6. Интеграция с локальным DNS-сервером (Unbound)

```bash
# 1. Установить Unbound
sudo apt install unbound  # Debian/Ubuntu
sudo dnf install unbound  # RHEL/CentOS

# 2. Настроить Unbound как кэширующий резолвер
sudo tee /etc/unbound/unbound.conf <<EOF
server:
    interface: 127.0.0.1
    port: 53
    do-ip4: yes
    do-ip6: no
    access-control: 127.0.0.0/8 allow
    access-control: 0.0.0.0/0 refuse
    cache-max-ttl: 3600
    cache-min-ttl: 60
EOF

# 3. Запустить Unbound
sudo systemctl enable --now unbound

# 4. Настроить systemd-resolved использовать Unbound
sudo resolvectl dns lo 127.0.0.1
sudo resolvectl domain lo "~."

# 5. Проверить
dig @127.0.0.1 google.com +short
```

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| DNS не разрешает имена | `systemd-resolved` не запущен | `systemctl status systemd-resolved` | `sudo systemctl enable --now systemd-resolved` |
| Порт 53 занят | Конфликт с dnsmasq/BIND | `ss -ulnp \| grep :53` | Остановите конфликтующий сервис |
| DoT не работает | Блокировка порта 853 | `openssl s_client -connect 1.1.1.1:853` | Откройте порт 853 в файрволе |
| DNS возвращает stale данные | Кэш не очищен | `resolvectl statistics` | `resolvectl flush-caches` |
| Split DNS не работает | Неправильная настройка доменов | `resolvectl domain` | Проверьте `Domains=~` в конфигурации |
| DNS работает, но медленно | Медленный upstream или проблемы с маршрутизацией | `dig @<upstream> example.com` | Проверьте сетевую связность |
| LLMNR/mDNS включены | Рекомендуется отключать в production | `resolvectl status` | `LLMNR=no` в resolved.conf |
| Запросы к внутренним доменам утекают | Split DNS не настроен | `resolvectl query internal.corp` | Настройте домены для VPN-интерфейса |

## Рекомендации по эксплуатации

1. **Включайте DNS-over-TLS** для защиты DNS-трафика от перехвата. Используйте публичные резолверы с DoT (Cloudflare 1.1.1.1, Google 8.8.8.8).
2. **Отключайте LLMNR и mDNS** в production для предотвращения обнаружения хостов и атак.
3. **Используйте Split DNS** для маршрутизации внутренних запросов через корпоративный DNS.
4. **Включайте DNSSEC** для валидации DNS-ответов и защиты от spoofing-атак.
5. **Настройте кэширование** для снижения нагрузки на upstream-серверы и уменьшения задержек.
6. **Используйте `resolvectl status`** для диагностики текущей конфигурации и проверки доступности upstream-серверов.
7. **Не редактируйте `/etc/resolv.conf` напрямую** — используйте `resolvectl` или конфигурацию systemd-networkd.
8. **Избегайте `nscd`** — он конфликтует с `systemd-resolved` и может возвращать устаревшие данные.
9. **Для контейнеров** пробрасывайте `/etc/resolv.conf` с хоста или настройте DNS через Docker/Kubernetes.
10. **Мониторьте кэш** через `resolvectl statistics` для обнаружения проблем с TTL и производительностью.

## Ограничения и особенности

* **Только клиент:** `systemd-resolved` не является DNS-сервером и не может раздавать имена другим узлам. Для серверного режима используйте BIND, Unbound или dnsmasq.
* **Одновременный запуск с nscd:** Конфликтует и приводит к двойному кэшированию. Отключите один из них.
* **Контейнеры:** В Docker/контейнерах без systemd `systemd-resolved` недоступен. Используйте DNS Docker (`127.0.0.11`) или внешние резолверы.
* **Версии systemd:** Поддержка DoQ и некоторых функций требует systemd v255+. Проверяйте версию: `systemd --version`.
* **IPv6:** При включенном IPv6 `systemd-resolved` отправляет параллельные A/AAAA-запросы. Для медленных IPv6-каналов может потребоваться настройка приоритетов через `/etc/gai.conf`.
* **Конфликт с NetworkManager:** Убедитесь, что в `/etc/NetworkManager/NetworkManager.conf` настроен `dns=systemd-resolved`.

## Дополнительная информация

### См. также

* [DNS-клиент в Linux](../../Networking/Concepts/dns_client.md) — детальный разбор NSS, `/etc/resolv.conf` и цепочки разрешения.
* [DNS-безопасность](../../../Networking/Protocols/DNS/dns_security.md) — DNSSEC, DoT, DoH.
* [systemd-networkd](../../Networking/Settings/Persistent_Network/systemd_networkd.md) — сетевая конфигурация и интеграция с resolved.
* [systemd-timesyncd](./time_synchronization.md) — синхронизация времени (критична для DNSSEC).
* [Диагностика DNS](../../Diagnostics/Networking/dns/overview.md) — методы поиска проблем с разрешением имен.
