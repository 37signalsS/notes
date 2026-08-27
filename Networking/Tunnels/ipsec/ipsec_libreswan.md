# IPsec: настройка LibreSwan на Linux

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл содержит руководство по настройке LibreSwan — дефолтной реализации IPsec в RHEL/CentOS/Rocky/Alma Linux.

> **strongSwan vs LibreSwan:** strongSwan используется в Debian/Ubuntu и является основным в [основном документе](./ipsec.md). LibreSwan — дефолт в RHEL-подобных дистрибутивах и включён в ядро через модуль `xfrm_libreswan`.

---

## Определения

**LibreSwan** — бесплатная реализация IPsec для Linux, форк исходного кода IPsec-линукса (FreeS/WAN). Демон ключей — `pluto`. Управление через утилиту `ipsec` (обёртка над `pluto` и `whack`).

**pluto** — основной демон LibreSwan, отвечающий за согласование IKE (IKEv1 и IKEv2) и управление ключами. Взаимодействует с ядром через Netlink (XFRM).

**whack** — интерфейс управления для передачи команд демону `pluto` (запуск/остановка туннелей, перезагрузка конфигурации).

**ipsec.conf** — основной конфигурационный файл LibreSwan (аналог `swanctl.conf` в strongSwan). Содержит определения туннелей (`conn`), политики и параметры.

**ipsec.secrets** — файл хранения PSK и приватных ключей (аналог `/etc/swanctl/secrets.conf`).

---

## Основные концепции

### Отличия от strongSwan

| Параметр | strongSwan | LibreSwan |
|----------|------------|-----------|
| Демон | `charon-systemd` | `pluto` |
| Конфигурация | `swanctl.conf` (HCL-like) | `ipsec.conf` (INI-like) |
| Секреты | `swanctl.secrets` / `secrets.conf` | `ipsec.secrets` |
| Управление | `swanctl` | `ipsec` (whack) |
| IKEv2 | По умолчанию | По умолчанию (с 3.x) |
| XFRM | Netlink | Netlink |
| Пакеты (RHEL) | `strongswan` | Входит в ядро, `libreswan` |

### Конфигурационные файлы

| Путь | Назначение |
|------|------------|
| `/etc/ipsec.conf` | Определения туннелей и общие параметры |
| `/etc/ipsec.secrets` | PSK и приватные ключи (chmod 600) |
| `/etc/ipsec.d/` | Каталог для сертификатов и CRL |
| `/etc/ipsec.d/certs/` | Сертификаты (`.crt`) |
| `/etc/ipsec.d/private/` | Приватные ключи (`.key`) |
| `/etc/ipsec.d/cacerts/` | CA-сертификаты |
| `/etc/ipsec.d/crls/` | Списки отозванных сертификатов |
| `/var/log/pluto.log` | Логи демона pluto |

---

## Предварительные требования

### Установка

```bash
# RHEL/CentOS/Rocky/Alma 8+
sudo dnf install libreswan

# RHEL/CentOS 7
sudo yum install libreswan

# После установки демон pluto запускается автоматically
sudo systemctl status ipsec
```

### Модули ядра

```bash
# LibreSwan использует встроенные модули XFRM
sudo modprobe af_key
sudo modprobe esp4

# Проверка
lsmod | grep -E "af_key|esp4|xfrm"
```

### IP Forwarding

```bash
# Временно
sudo sysctl -w net.ipv4.ip_forward=1

# Постоянно
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-ipsec.conf
sudo sysctl -p /etc/sysctl.d/99-ipsec.conf
```

### Порты и протоколы

| Протокол | Порт | Назначение |
|----------|------|------------|
| UDP | 500 | IKE согласование |
| UDP | 4500 | NAT-Traversal |
| ESP | IP 50 | Шифрование данных |

---

## Практические сценарии

### Site-to-Site с PSK

#### Конфигурация Шлюза A (`/etc/ipsec.conf`)

```bash
# /etc/ipsec.conf
config setup
    # Опционально: включить отладку (уровень 0-5)
    # plutodebug="control controlmore"
    # Раскомментировать для включения логирования
    # uniqueids=yes

conn site-to-site
    # Тип соединения
    type=tunnel
    # Автоматический запуск при появлении трафика
    auto=add

    # Локальный и удалённый адреса
    left=198.51.100.1
    leftsubnet=192.168.1.0/24
    right=203.0.113.2
    rightsubnet=192.168.2.0/24

    # Аутентификация
    authby=secret

    # IKEv2 (рекомендуется)
    ikev2=yes

    # Алгоритмы шифрования
    # IKE SA
    ike=aes256gcm-sha384-modp2048!
    # ESP (CHILD SA)
    esp=aes256gcm-sha384-modp2048!

    # PFS (Perfect Forward Secrecy)
    pfsgroup=modp2048

    # Интервалы переоблючения ключей
    ikelifetime=86400s
    lifetime=3600s

    # DPD (Dead Peer Detection)
    dpddelay=30s
    dpdtimeout=120s
    dpdaction=restart

    # Окно anti-replay
    replay_window=32

    # Максимальное количество сообщений IKE
    ikefrag=yes
```

#### Конфигурация Шлюза B (`/etc/ipsec.conf`)

```bash
# /etc/ipsec.conf (зеркальная конфигурация)
config setup

conn site-to-site
    type=tunnel
    auto=add

    # Зеркальные адреса
    left=203.0.113.2
    leftsubnet=192.168.2.0/24
    right=198.51.100.1
    rightsubnet=192.168.1.0/24

    authby=secret
    ikev2=yes

    ike=aes256gcm-sha384-modp2048!
    esp=aes256gcm-sha384-modp2048!
    pfsgroup=modp2048

    ikelifetime=86400s
    lifetime=3600s

    dpddelay=30s
    dpdtimeout=120s
    dpdaction=restart

    replay_window=32
    ikefrag=yes
```

#### Файл секретов (`/etc/ipsec.secrets`)

```bash
# /etc/ipsec.secrets
# Формат: <local_ip> <remote_ip> : PSK "секрет"
198.51.100.1 203.0.113.2 : PSK "your-very-secret-key-here-change-me"
```

```bash
# Права доступа (ОБЯЗАТЕЛЬНО)
sudo chmod 600 /etc/ipsec.secrets
sudo chown root:root /etc/ipsec.secrets
```

#### Запуск и проверка

```bash
# Перезагрузка конфигурации
sudo ipsec restart

# Или перезагрузка pluto без остановки
sudo ipsec reload

# Проверка статуса
sudo ipsec status
# → "site-to-site" #1: ESTABLISHED IKEv2 ...

# Проверка активных SA
sudo ipsec statusall

# Ручной запуск туннеля
sudo ipsec up site-to-site

# Остановка туннеля
sudo ipsec down site-to-site

# Проверка в ядре
ip xfrm state
ip xfrm policy
```

### Site-to-Site с сертификатами

#### Генерация CA и сертификатов

```bash
# 1. Создание CA
sudo ipsec pki --self --ca --lifetime 3650 \
    --in /etc/ipsec.d/private/ca.key \
    --out /etc/ipsec.d/cacerts/ca.crt \
    --dn "CN=VPN CA"

# 2. Генерация ключа Шлюза A
sudo ipsec pki --gen --type rsa --size 4096 \
    --outform pem > /etc/ipsec.d/private/gwA.key

# 3. Получение сертификата Шлюза A
sudo ipsec pki --issue --lifetime 3650 \
    --cacert /etc/ipsec.d/cacerts/ca.crt \
    --cakey /etc/ipsec.d/private/ca.key \
    --in /etc/ipsec.d/private/gwA.key \
    --outform pem > /etc/ipsec.d/certs/gwA.crt \
    --dn "CN=gw1.example.com" \
    --san="gw1.example.com" \
    --san="198.51.100.1"

# 4. Повторить для Шлюза B (заменить gwA на gwB)
```

#### Конфигурация с сертификатами

```bash
# /etc/ipsec.conf
conn site-to-site-cert
    type=tunnel
    auto=add

    left=198.51.100.1
    leftsubnet=192.168.1.0/24
    leftcert=gwA.crt
    leftid="gw1.example.com"

    right=203.0.113.2
    rightsubnet=192.168.2.0/24
    rightid="gw2.example.com"
    rightca=/etc/ipsec.d/cacerts/ca.crt

    ikev2=yes
    ike=aes256gcm-sha384-ecp384!
    esp=aes256gcm-sha384-ecp384!
    pfsgroup=ecp384

    ikelifetime=86400s
    lifetime=3600s

    dpddelay=30s
    dpdtimeout=120s
    dpdaction=restart
    ikefrag=yes
```

### Remote Access (Road Warrior)

#### Конфигурация шлюза

```bash
# /etc/ipsec.conf
config setup
    uniqueids=no

conn remote-access
    type=xauth
    auto=add

    left=198.51.100.1
    leftsubnet=0.0.0.0/0

    right=%any
    rightaddresspool=10.10.10.0/24
    rightcert=client.crt

    ikev2=yes
    xauthby=file
    xauth_identity=%any

    ike=aes256gcm-sha384-ecp384!
    esp=aes256gcm-ecp384!

    dpddelay=30s
    dpdtimeout=120s
    dpdaction=clear
```

#### Файл пользователей XAuth

```bash
# /etc/ipsec.d/passwd (формат: пароль хеш)
# Генерация хеша:
# mkpasswd -m sha-512
# Или:
# openssl passwd -6

# /etc/ipsec.d/passwd
user1:$6$rounds=5000$salt$hash...
user2:$6$rounds=5000$salt$hash...
```

```bash
# Права доступа
sudo chmod 600 /etc/ipsec.d/passwd
```

---

## Управление и диагностика

### Основные команды

| Команда | Описание |
|---------|----------|
| `ipsec status` | Краткий статус всех туннелей |
| `ipsec statusall` | Детальный статус (включая SA, политики) |
| `ipsec up <conn>` | Ручной запуск туннеля |
| `ipsec down <conn>` | Остановка туннеля |
| `ipsec add <conn>` | Добавление соединения в sans |
| `ipsec delete <conn>` | Удаление соединения |
| `ipsec restart` | Перезапуск демона pluto |
| `ipsec reload` | Перезагрузка конфигурации без перезапуска |
| `ipsec brief` | Статус в компактном формате |
| `ipsec verify` | Проверка системы на соответствие требованиям |

### Диагностика

```bash
# Логи pluto
sudo tail -f /var/log/pluto.log

# Отладка (уровень 0-5)
# Раскомментировать в ipsec.conf: plutodebug="control controlmore"
sudo ipsec restart
sudo tail -f /var/log/pluto.log

# Проверка в ядре
ip xfrm state
ip xfrm policy
ip -s xfrm state    # Статистика пакетов

# Проверка маршрута
ip route get <remote_internal_ip>

# Анализ трафика
sudo tcpdump -n -i any port 500 or port 4500 or proto 50
```

### Автоматическая проверка системы

```bash
# Проверка соответствия требованиям
sudo ipsec verify
# → Checking your system to see what IPsec daemons and kernel are possible...
# → Processing defaults...
# → of pluto...
# → ...
```

---

## Типовые проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `ipsec` не запускается | Ошибка в `ipsec.conf` | Проверить `sudo ipsec verify`, исправить синтаксис |
| `no matching connection` | Имя `conn` не совпадает | Проверить `leftid`/`rightid` и `conn` в `ipsec.conf` |
| `authentication failed` | Неверный PSK или сертификат | Проверить `ipsec.secrets`, права доступа |
| `NO_PROPOSAL_CHOSEN` | Несовпадение алгоритмов | Синхронизировать `ike`/`esp` на обеих сторонах |
| `TS_UNACCEPTABLE` | Несовпадение подсетей | Проверить `leftsubnet`/`rightsubnet` |
| SA установлен, трафик нет | Firewall или MTU | Разрешить ESP, настроить MSS Clamping |
| `pluto` падает | Ошибка в конфигурации | Проверить `journalctl -u ipsec`, исправить `ipsec.conf` |

---

## Дополнительная информация

### Сравнение с strongSwan

| Критерий | strongSwan | LibreSwan |
|----------|------------|-----------|
| De facto standard | Debian/Ubuntu | RHEL/CentOS |
| Формат конфига | HCL-like (современный) | INI-like (классический) |
| IKEv2 | Полная поддержка | Полная поддержка |
| EAP | Плагины | Встроенный |
| Хост-based VPN | strongSwan charon-cmd | `ipsec` с `right=%any` |
| Производительность | Сопоставима | Сопоставима |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, настройка strongSwan.
- **[Диагностика IPsec (legacy)](./ipsec_troubleshooting.md)** — отладка KAME/racoon (частично применимо к LibreSwan).
- **[Мониторинг IPsec](./ipsec_monitoring.md)** — Prometheus, Grafana, логирование.
- **[Высокая доступность IPsec](./ipsec_ha.md)** — failover и кластеризация.
