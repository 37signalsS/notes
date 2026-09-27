# IPsec (Internet Protocol Security)

## Определения

**IPsec (Internet Protocol Security)** — набор протоколов и стандартов для обеспечения безопасности данных на сетевом уровне (L3) модели OSI. Он обеспечивает аутентификацию, целостность и конфиденциальность IP-пакетов.

**Ключевое отличие от других VPN-технологий:**
- **Policy-based IPsec (Классический):** Не создаёт явных туннельных интерфейсов. Трафик перехватывается ядром на основе политик (SPD).
- **Route-based IPsec (Современный):** Использует виртуальные интерфейсы (**VTI** или **XFRM**). Это позволяет использовать стандартную таблицу маршрутизации и динамические протоколы (OSPF, BGP) поверх зашифрованного канала.

---

## Основные концепции

### Архитектура и протоколы

Стек IPsec состоит из двух основных протоколов передачи данных и протоколов управления ключами.

| Протокол | Назначение | Порт/ID | Особенности |
|----------|------------|---------|-------------|
| **ESP** (Encapsulating Security Payload) | Шифрование + Аутентификация | IP 50 | Основной протокол для передачи данных. |
| **AH** (Authentication Header) | Только аутентификация | IP 51 | Защищает весь пакет, включая внешний IP-заголовок. Несовместим с NAT. |
| **IKE (v1/v2)** | Обмен ключами и аутентификация | UDP 500, 4500 | Протокол управления сессиями. |

### Протоколы обмена ключами (IKE)

#### IKEv1 (Устаревший)
Использует двухфазную модель:
1. **Phase 1 (ISAKMP SA):** Установление защищённого канала управления.
   - **Main Mode:** 6 сообщений, скрывает ID сторон.
   - **Aggressive Mode:** 3 сообщения, быстрее, но идентификаторы передаются в открытом виде (небезопасно).
2. **Phase 2 (IPsec SA / Quick Mode):** Согласование параметров шифрования для передачи пользовательских данных.

#### IKEv2 (Современный)
**Рекомендуется к использованию.** Основные улучшения:
- **Типы SA:** Вместо "фаз" используются **IKE_SA** (управление) и **CHILD_SA** (данные). Первый CHILD_SA создается автоматически при аутентификации.
- **Эффективность:** Соединение устанавливается за 4 сообщения (IKE_SA_INIT и IKE_AUTH).
- **Нативная поддержка NAT-T:** Встроена в протокол, не требует сложной настройки.
- **MOBIKE:** Позволяет менять IP-адрес клиента (например, при переходе с Wi-Fi на 4G) без разрыва туннеля.
- **Reliability:** Все сообщения подтверждаются (ACK), что делает протокол более устойчивым.

### Ассоциации безопасности (SA) и политики безопасности (SP)

**SA (Security Association)** — логический однонаправленный туннель. Для двусторонней связи требуется пара SA (входящая и исходящая).

**Компоненты управления в ядре:**
- **SAD (Security Associations Database):** Хранит параметры активных туннелей (ключи, алгоритмы, SPI).
- **SPD (Security Policy Database):** Хранит политики, определяющие судьбу пакета: `protect` (зашифровать), `bypass` (пропустить так), `discard` (отбросить).
- **SPI (Security Parameter Index):** 32-битное число в заголовке пакета, по которому приемник находит нужную запись в SAD.
- **Traffic Selectors (TS):** Диапазоны IP-адресов и портов, для которых разрешена передача данных внутри конкретной SA.

### Режимы инкапсуляции

| Режим | Описание | Схема пакета | Применение |
|-------|----------|--------------|------------|
| **Транспортный** | Шифруется только полезная нагрузка (L4+) | `[IP][ESP][Data]` | Хост-хост; GRE поверх IPsec |
| **Туннельный** | Шифруется весь исходный IP-пакет | `[New IP][ESP][Old IP][Data]` | Site-to-Site VPN; Клиент-Шлюз |

### Механизмы защиты

- **Защита от повторов (Anti-Replay):** Использование порядковых номеров (Sequence Numbers) для предотвращения повторной передачи перехваченных пакетов.
- **ESN (Extended Sequence Number):** 64-битные счетчики для высокоскоростных каналов (10Gbps+), чтобы избежать частого пересогласования ключей.
- **Perfect Forward Secrecy (PFS):** Гарантирует, что компрометация одного ключа не приведет к расшифровке прошлых сессий (через регулярный переобмен Diffie-Hellman).
- **NAT Traversal (NAT-T):** Инкапсуляция ESP в UDP (порт 4500) для прохождения через NAT-устройства.

---

## Предварительные требования

### Версии ПО

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| **strongSwan** | 5.7.0 | 6.0+ | swanctl.conf как основной формат конфигурации |
| **Ядро Linux** | 4.19+ | 5.15+ | XFRM-интерфейсы, полная поддержка AEAD |
| **charon-systemd** | 5.7.0 | 6.0+ | Демон для обработки IKEv2 |
| **libstrongswan** | 5.7.0 | 6.0+ | Криптографические плагины |

### Установка strongSwan

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install strongswan libcharon-extra-plugins strongswan-swanctl

# RHEL/CentOS/Rocky/Alma
sudo dnf install strongswan

# Arch Linux
sudo pacman -S strongswan
```

После установки демон `charon-systemd` запускается автоматически. Основные пути:

| Путь | Назначение |
|------|------------|
| `/etc/swanctl/conf.d/` | Конфигурационные файлы (HCL-подобный синтаксис) |
| `/etc/swanctl/private/` | Приватные ключи |
| `/etc/swanctl/certs/` | Сертификаты |
| `/etc/swanctl/cacerts/` | CA-сертификаты |
| `/etc/swanctl/secrets.conf` | Секреты (PSK) |
| `/var/log/charon.log` | Логи демона (если включено файловое логирование) |

### Включение IP Forwarding

Без включения маршрутизации ядро не будет пересылать расшифрованные пакеты во внутреннюю сеть:

```bash
# Временно
sudo sysctl -w net.ipv4.ip_forward=1

# Постоянно
echo "net.ipv4.ip_forward = 1" | sudo tee -a /etc/sysctl.d/99-ipsec.conf
sudo sysctl -p /etc/sysctl.d/99-ipsec.conf
```

### Модули ядра

```bash
# Проверка загруженности модулей XFRM
lsmod | grep xfrm
# → xfrm_user  alt_task  ... (ожидаемый вывод)

# Загрузка при необходимости
sudo modprobe af_key
sudo modprobe esp4
```

---

## Практические сценарии

### Реализации IPsec на Linux

1. **strongSwan:** Эталонная реализация, полная поддержка IKEv2, плагинов и современных методов аутентификации.
2. **LibreSwan:** Форк с фокусом на безопасность и простоту, популярен в RHEL-based дистрибутивах.
3. **XFRM (Kernel):** Подсистема ядра Linux, отвечающая за обработку пакетов. strongSwan управляет XFRM через интерфейс Netlink.

### Настройка strongSwan (swanctl.conf)

Современный метод настройки использует формат HCL-like и демон `charon-systemd`.

#### Site-to-Site с PSK (простая настройка)

```hcl
# /etc/swanctl/conf.d/site-to-site.conf
connections {
    gw-to-gw {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        version = 2
        proposals = aes256gcm128-sha256-modp2048

        # Dead Peer Detection — обнаружение отказа пира
        dpd_delay = 30s
        dpd_timeout = 120s

        # Переобмен ключами IKE SA (24 часа)
        rekey_time = 86400s

        local {
            auth = psk
            id = 198.51.100.1
        }
        remote {
            auth = psk
            id = 203.0.113.2
        }

        children {
            net-net {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                # Современный набор алгоритмов (AEAD)
                esp_proposals = aes256gcm128-sha256
                start_action = trap
                close_action = restart
                dpd_action = restart

                # Защита от повторов
                replay_window = 32

                # Переобмен ключами CHILD SA
                life_time = 3600s
                rekey_time = 3000s
                rand_time = 300s
            }
        }
    }
}

secrets {
    ike-gw {
        secret = "V3ryStr0ngP4ssw0rd"
    }
}
```

> **Важно:** `start_action = trap` указывает ядру автоматически запускать туннель при появлении трафика, соответствующего `local_ts`/`remote_ts`. Это предпочтительнее ручного `start_action = start` для Site-to-Site сценариев.

#### Site-to-Site с сертификатами (Production)

Для промышленных сред рекомендуется сертификатная аутентификация — каждый шлюз идентифицируется уникальным сертификатом, что исключает риски компрометации общего PSK.

```bash
# Генерация CA (на одной из сторон или на отдельном хосте)
ipsec pki --gen --type rsa --size 4096 --outform pem > ca.key
ipsec pki --self --ca --lifetime 3650 --in ca.key \
    --type rsa --dn "CN=VPN CA" --outform pem > ca.crt

# Генерация сертификата для шлюза A
ipsec pki --gen --type rsa --size 4096 --outform pem > gwA.key
ipsec pki --pub --in gwA.key --type rsa | \
    ipsec pki --issue --lifetime 3650 --cacert ca.crt --cakey ca.key \
    --dn "CN=gw1.example.com" --san=gw1.example.com --flag serverAuth --flag ikeIntermediate \
    --outform pem > gwA.crt

# Генерация сертификата для шлюза B (зеркально)
ipsec pki --gen --type rsa --size 4096 --outform pem > gwB.key
ipsec pki --pub --in gwB.key --type rsa | \
    ipsec pki --issue --lifetime 3650 --cacert ca.crt --cakey ca.key \
    --dn "CN=gw2.example.com" --san=gw2.example.com --flag serverAuth --flag ikeIntermediate \
    --outform pem > gwB.crt

# Установка сертификатов (на каждом шлюзе)
sudo cp ca.crt /etc/swanctl/cacerts/
sudo cp gwA.crt /etc/swanctl/certs/        # на шлюзе A
sudo cp gwA.key /etc/swanctl/private/       # на шлюзе A
sudo chmod 600 /etc/swanctl/private/gwA.key
```

```hcl
# /etc/swanctl/conf.d/site-to-site-cert.conf
connections {
    gw-to-gw-cert {
        remote_addrs = 203.0.113.2
        local_addrs = 198.51.100.1
        version = 2
        proposals = aes256gcm128-sha384-ecp384

        dpd_delay = 30s
        dpd_timeout = 120s
        rekey_time = 86400s

        fragmentation = yes

        local {
            auth = pubkey
            certs = gwA.crt
            id = gw1.example.com
        }
        remote {
            auth = pubkey
            cacerts = ca.crt
            id = gw2.example.com
        }

        children {
            net-net {
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-sha384-ecp384
                start_action = trap
                close_action = restart
                dpd_action = restart
                replay_window = 32
                life_time = 3600s
                rekey_time = 3000s
                rand_time = 300s
            }
        }
    }
}
```

#### Remote Access (Road Warrior) с EAP-TLS

Сценарий для удалённых пользователей: сервер выдаёт виртуальные IP-адреса, клиенты аутентифицируются сертификатами через EAP-TLS.

```bash
# Генерация серверного сертификата (аналогично Site-to-Site)
ipsec pki --gen --type rsa --size 4096 --outform pem > vpn.key
ipsec pki --pub --in vpn.key --type rsa | \
    ipsec pki --issue --lifetime 3650 --cacert ca.crt --cakey ca.key \
    --dn "CN=vpn.example.com" --san=vpn.example.com --flag serverAuth \
    --outform pem > vpn.crt

# Генерация клиентского сертификата
ipsec pki --gen --type rsa --size 2048 --outform pem > client.key
ipsec pki --pub --in client.key --type rsa | \
    ipsec pki --issue --lifetime 3650 --cacert ca.crt --cakey ca.key \
    --dn "CN=user@example.com" --outform pem > client.crt

# Экспорт клиентского сертификата в формате PKCS#12 (.p12) для импорта в ОС клиента
openssl pkcs12 -export -inkey client.key -in client.crt -certfile ca.crt \
    -out client.p12 -name "VPN Client"
```

```hcl
# /etc/swanctl/conf.d/remote-access.conf
connections {
    remote-access {
        version = 2
        local_addrs = 0.0.0.0
        proposals = aes256gcm128-sha384-ecp384

        dpd_delay = 30s

        pools = remote-pool

        local {
            auth = pubkey
            certs = vpn.crt
            id = vpn.example.com
        }
        remote {
            auth = eap-tls
            cacerts = ca.crt
            id = %any
        }

        children {
            remote-tunnel {
                local_ts = 10.0.0.0/8,172.16.0.0/12
                esp_proposals = aes256gcm128-sha384-ecp384
                rekey_time = 3600s
                dpd_action = restart
            }
        }
    }
}

pools {
    remote-pool {
        addrs = 10.100.0.0/24
        dns = 10.0.0.53, 8.8.8.8
    }
}
```

### Настройка Routed IPsec (XFRM интерфейс)

Использование XFRM-интерфейсов позволяет привязать шифрование к конкретному сетевому устройству, что упрощает маршрутизацию и настройку Firewall.

```bash
# 1. Создание интерфейса с ID (должен совпадать с if_id в swanctl.conf)
ip link add xfrm0 type xfrm dev eth0 if_id 1
ip link set xfrm0 up

# 2. Назначение адреса и маршрута
ip addr add 169.254.1.1/30 dev xfrm0
ip route add 192.168.2.0/24 dev xfrm0

# 3. Проверка привязки
ip xfrm policy | grep if_id
```

### Настройка файрвола для IPsec

IPsec требует разрешения нескольких протоколов на внешнем интерфейсе:

```bash
# nftables (рекомендуется)
sudo nft add rule inet filter input ip saddr 203.0.113.2 ip protocol esp accept
sudo nft add rule inet filter input ip saddr 203.0.113.2 udp dport 500 accept
sudo nft add rule inet filter input ip saddr 203.0.113.2 udp dport 4500 accept

# iptables (legacy)
sudo iptables -A INPUT -s 203.0.113.2 -p esp -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.2 -p udp --dport 500 -j ACCEPT
sudo iptables -A INPUT -s 203.0.113.2 -p udp --dport 4500 -j ACCEPT

# Разрешение трафика между внутренними подсетями (POSTrouting для NAT, если требуется)
sudo iptables -A FORWARD -s 192.168.1.0/24 -d 192.168.2.0/24 -j ACCEPT
sudo iptables -A FORWARD -s 192.168.2.0/24 -d 192.168.1.0/24 -j ACCEPT
```

### MTU и MSS в IPsec

Инкапсуляция ESP добавляет оверхед (от 50 до 73 байт). Для стабильной работы TCP необходимо:
1. Уменьшать MTU на туннельном интерфейсе (до ~1400-1420).
2. Использовать **MSS Clamping** для автоматической подстройки размера сегмента:
```bash
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
```

### Полный production-ready пример

Ниже приведена полная конфигурация Site-to-Site VPN между двумя Linux-шлюзами с сертификатной аутентификацией, DPD, anti-replay и AEAD-шифрованием.

**Шлюз A (198.51.100.1, сеть 192.168.1.0/24):**

```hcl
# /etc/swanctl/conf.d/production-site-a.conf
connections {
    site-b {
        version = 2
        local_addrs = 198.51.100.1
        remote_addrs = 203.0.113.2

        # IKE SA: управление каналом
        proposals = aes256gcm128-sha384-ecp384
        rekey_time = 86400s
        dpd_delay = 30s
        dpd_timeout = 120s
        fragmentation = yes

        local {
            auth = pubkey
            certs = gwA.crt
            id = gw1.example.com
        }
        remote {
            auth = pubkey
            cacerts = ca.crt
            id = gw2.example.com
        }

        children {
            lan-to-lan {
                # CHILD SA: шифрование данных
                local_ts = 192.168.1.0/24
                remote_ts = 192.168.2.0/24
                esp_proposals = aes256gcm128-sha384-ecp384

                # Автозапуск при появлении трафика
                start_action = trap
                close_action = restart
                dpd_action = restart

                # Anti-replay
                replay_window = 32

                # Переоблючение ключей CHILD SA
                life_time = 3600s
                rekey_time = 3000s
                rand_time = 300s
            }
        }
    }
}
```

```bash
# /etc/sysctl.d/99-ipsec.conf
net.ipv4.ip_forward = 1

# Применение
sudo sysctl -p /etc/sysctl.d/99-ipsec.conf

# Загрузка конфигурации
sudo swanctl --load-all

# Ручной запуск (или автоматически при трафике через start_action=trap)
sudo swanctl --initiate --child lan-to-lan

# Проверка
sudo swanctl --list-sas
# → ESTABLISHED, IKEv2, AES_GCM_16_256, ECP_384
```

### Практический урок: настройка IPsec на современном стеке (charon-systemd)

Данный урок демонстрирует пошаговое развёртывание IPsec на современном стеке (`charon-systemd` + `strongSwan` + `swanctl`/`vici`) и служит примером миграции с legacy-стека (`ipsec.conf`/`pluto`).

#### Топология стенда

- **Шлюз A (левый):** `192.168.52.138` (внутренняя сеть `172.16.150.0/24`, тестовый хост `172.16.150.90`)
- **Шлюз B (правый):** `192.168.52.141` (внутренняя сеть `172.16.100.0/24`, тестовый хост `172.16.100.101`)

#### Шаг 1. Проверка связности

Перед началом убедитесь, что между подсетями нет связи:

```bash
# На шлюзе A
ping -c 3 172.16.100.101
# → Destination Host Unreachable

# На шлюзе B
ping -c 3 172.16.150.90
# → Destination Host Unreachable
```

#### Шаг 2. Установка пакетов

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install strongswan libcharon-extra-plugins strongswan-swanctl

# RHEL/CentOS/Rocky/Alma
sudo dnf install strongswan
```

#### Шаг 3. Верификация демона

Убедитесь, что запущен `charon-systemd`, а не legacy-демон `pluto`:

```bash
sudo systemctl status strongswan
# → Active: active (running)
# → Главный процесс: charon-systemd
# → strongswan-starter отсутствует
```

#### Шаг 4. Конфигурация

Создайте файл `/etc/swanctl/conf.d/linux-to-linux.conf`:

```hcl
# /etc/swanctl/conf.d/linux-to-linux.conf
connections {
    linux-to-linux {
        remote_addrs = 192.168.52.141
        local_addrs = 192.168.52.138
        version = 2
        proposals = aes256-sha256-modp2048

        local {
            auth = psk
            id = linux-1
        }
        remote {
            auth = psk
            id = linux-2
        }

        children {
            net-net {
                local_ts = 172.16.150.0/24
                remote_ts = 172.16.100.0/24
                esp_proposals = aes256-sha256
                start_action = trap
                close_action = restart
                dpd_action = restart
            }
        }
    }
}

secrets {
    linux-to-linux {
        secret = "qwerty!"
    }
}
```

На шлюзе B создайте зеркальный конфиг, поменяв `local_addrs` ↔ `remote_addrs`, `linux-1` ↔ `linux-2` и подсети `172.16.150.0/24` ↔ `172.16.100.0/24`.

> **Важно:** `qwerty!` — учебный PSK. В production используйте ключ длиной не менее 64 символов: `openssl rand -base64 48`.

#### Шаг 5. Применение конфигурации

```bash
# Загрузка конфигурации и секретов
sudo swanctl --load-all

# Проверка загруженных соединений
sudo swanctl --list-conns
```

#### Шаг 6. Запуск туннеля

Туннель запускается автоматически при появлении трафика (`start_action = trap`), либо вручную по имени `children`-блока:

```bash
# Ручной запуск (по имени children, НЕ connections)
sudo swanctl --initiate --child net-net
```

> **Важно:** Для запуска туннеля используется имя `children`-блока (`net-net`), а не имя `connections` (`linux-to-linux`). Попытка запуска по имени connection приведёт к ошибке.

#### Шаг 7. Валидация

```bash
# Проверка статуса SA
sudo swanctl --list-sas
# → ESTABLISHED, IKEv2, ...

# Пинг через туннель
ping -c 3 172.16.100.101
# → Ответы с правой стороны
```

#### Шаг 8. Диагностика

```bash
# Состояние туннеля
sudo swanctl --list-sas

# Статистика демона
sudo swanctl --stats

# Пакеты и байты в ядре
ip -s xfrm state

# Политики в ядре
ip xfrm policy
```

---

### Настройка strongSwan (legacy ipsec.conf/ipsec.secrets)

Помимо современного формата [`swanctl.conf`](#настройка-strongswan-swanctlconf), strongSwan поддерживает устаревший формат конфигурации `ipsec.conf`/`ipsec.secrets` (наследие проекта FreeS/WAN). Данный формат используется демоном `pluto` и встречается в существующих инсталляциях, а также в примерах для вендорского оборудования.

> **Важно:** Legacy-формат не поддерживает `charon-systemd`. Для его использования требуется демон `pluto` (пакет `strongswan-pluto` или `libstrongswan-pluto`). В новых инсталляциях предпочитайте [swanctl.conf](#настройка-strongswan-swanctlconf).

#### Структура конфигурационных файлов

| Файл | Назначение | Формат |
|------|------------|--------|
| `/etc/ipsec.conf` | Определения туннелей (`conn`), алгоритмы IKE/ESP, идентификаторы | INI-подобный |
| `/etc/ipsec.secrets` | PSK и приватные ключи | Текстовый (chmod 600) |
| `/etc/ipsec.d/` | Директория для сертификатов и CA (если используется X.509) | PEM |

#### Практический пример: Site-to-Site с PSK

**Топология стенда:**
- **Шлюз A (Public IP):** `192.168.52.138` (внутренняя сеть `172.16.150.0/24`)
- **Шлюз B (Public IP):** `192.168.52.141` (внутренняя сеть `172.16.100.0/24`)

**Шаг 1. Установка strongSwan с поддержкой legacy-формата**

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install strongswan strongswan-pluto

# RHEL/CentOS/Rocky/Alma
sudo dnf install strongswan strongswan-pluto
```

**Шаг 2. Настройка `/etc/ipsec.conf` на Шлюзе A**

```bash
config setup
    uniqueids=no

conn linux-to-linux
    keyexchange=ike
    ike=aes256-sha256-modp2048!
    esp=aes256-sha256!
    left=192.168.52.138
    right=192.168.52.141
    leftid=192.168.52.138
    rightid=192.168.52.141
    leftsubnet=172.16.150.0/24
    rightsubnet=172.16.100.0/24
    auto=add
```

**Шаг 3. Настройка `/etc/ipsec.secrets` на Шлюзе A**

```text
192.168.52.138 : PSK "qwerty"
192.168.52.141 : PSK "qwerty"
```

```bash
# Установка строгих прав доступа
sudo chmod 600 /etc/ipsec.secrets
sudo chown root:root /etc/ipsec.secrets
```

**Шаг 4. Настройка Шлюза B (зеркальная конфигурация)**

На Шлюзе B (`192.168.52.141`) параметры `left` и `right` меняются местами:

```bash
config setup
    uniqueids=no

conn linux-to-linux
    keyexchange=ike
    ike=aes256-sha256-modp2048!
    esp=aes256-sha256!
    left=192.168.52.141
    right=192.168.52.138
    leftid=192.168.52.141
    rightid=192.168.52.138
    leftsubnet=172.16.100.0/24
    rightsubnet=172.16.150.0/24
    auto=add
```

```text
192.168.52.141 : PSK "qwerty"
192.168.52.138 : PSK "qwerty"
```

**Шаг 5. Включение IP Forwarding и применение конфигурации**

```bash
# Включение маршрутизации (на обоих шлюзах)
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-ipsec.conf
sudo sysctl -p /etc/sysctl.d/99-ipsec.conf

# Проверка конфигурации
sudo ipsec verify

# Запуск strongSwan
sudo systemctl restart strongswan

# Инициализация туннеля
sudo ipsec up linux-to-linux
```

**Шаг 6. Валидация**

```bash
# Проверка статуса
sudo ipsec status
# → "linux-to-linux" #1: ESTABLISHED, IKEv2, ...

# Просмотр SA в ядре
ip xfrm state
ip xfrm policy

# Пинг через туннель
ping -c 4 172.16.100.90
```

Детальная диагностика: [Управление и диагностика](#управление-и-диагностика).

#### Разбор параметров конфигурации

| Параметр | Описание |
|----------|----------|
| `config setup` | Глобальные параметры strongSwan |
| `uniqueids=no` | Разрешить многопользовательские ID (нужно при использовании IP в качестве ID) |
| `conn <name>` | Имя туннельного соединения |
| `keyexchange=ike` | Протокол обмена ключами (IKEv1/IKEv2) |
| `ike=aes256-sha256-modp2048!` | Алгоритмы IKE SA (восклицательный знак — обязательное соответствие) |
| `esp=aes256-sha256!` | Алгоритмы ESP (данные) |
| `left` | IP-адрес локального интерфейса |
| `right` | IP-адрес удалённого шлюза |
| `leftid` | Идентификатор локальной стороны |
| `rightid` | Идентификатор удалённой стороны |
| `leftsubnet` | Внутренняя сеть локальной стороны |
| `rightsubnet` | Внутренняя сеть удалённой стороны |
| `auto=add` | Автоматически загружать соединение при старте (не запускать туннель) |

#### Задание на самостоятельную работу: текстовые идентификаторы

В примере выше в качестве `leftid`/`rightid` используются IP-адреса. Для использования текстовых идентификаторов (например, `linux-one`, `linux-two`):

1. Удалите строку `uniqueids=no` из `config setup`
2. Замените IP-адреса в `leftid`/`rightid` на текстовые значения
3. Убедитесь, что идентификаторы совпадают в `ipsec.secrets` на обеих сторонах

```bash
# Пример с текстовыми ID
conn linux-to-linux
    leftid=linux-one
    rightid=linux-two
```

---

## Управление и диагностика

### Команды strongSwan (swanctl)

```bash
# Управление конфигурацией
swanctl --load-all            # Перезагрузка конфигурации и секретов
swanctl --load-conns          # Только конфигурации
swanctl --load-creds          # Только сертификаты и ключи

# Мониторинг
swanctl --list-sas            # Просмотр активных ассоциаций (туннелей)
swanctl --list-sas --ike      # Только IKE SA (управление)
swanctl --list-sas --child    # Только CHILD SA (данные)
swanctl --list-conns          # Просмотр загруженных конфигураций
swanctl --list-certs          # Просмотр установленных сертификатов

# Управление туннелями
swanctl --initiate --child net-net  # Ручной запуск туннеля
swanctl --terminate --child net-net # Принудительное завершение CHILD SA
swanctl --reinit <connection>       # Перезапуск IKE SA

# Диагностика
swanctl --log                # Просмотр логов демона charon
swanctl --stats              # Статистика работы демона
```

### Диагностика в ядре (XFRM)

```bash
# Просмотр баз данных
ip xfrm state            # Просмотр SAD (ключи, алгоритмы, SPI)
ip xfrm policy           # Просмотр SPD (правила перехвата трафика)

# Статистика
ip -s xfrm state         # Статистика пакетов (ошибки аутентификации, счетчики)
ip -s xfrm policy        # Статистика по политикам

# Фильтрация
ip xfrm state proto esp               # Только ESP-ассоциации
ip xfrm state spi 0x12345678          # Конкретная SA по SPI
ip xfrm policy dir out                # Только исходящие политики
ip xfrm policy tmpl src 198.51.100.1  # Политики для конкретного шлюза

# Очистка (при отладке)
ip xfrm state flush                   # Очистка всех SA
ip xfrm policy flush                  # Очистка всех политик
```

### Валидация после настройки

После применения конфигурации обязательна проверка корректности работы:

```bash
# 1. Проверка статуса ассоциаций (ожидаем ESTABLISHED)
sudo swanctl --list-sas
# → 示例 вывода:
#   gw-to-gw: #1, ESTABLISHED, IKEv2, ...
#     local  '198.51.100.1' ... 198.51.100.1
#     remote '203.0.113.2' ... 203.0.113.2
#     AES_CBC-256/HMAC_SHA2_256_128/PRF_HMAC_SHA2_256/MODP_2048
#     net-net: #1, ESTABLISHED, TUNNEL, ESP, ...
#       local  192.168.1.0/24
#       remote 192.168.2.0/24

# 2. Проверка согласованных алгоритмов
sudo swanctl --list-sas --raw

# 3. Пинг через туннель (с внутреннего хоста)
ping -c 4 192.168.2.1

# 4. Проверка прохождения зашифрованного трафика
sudo tcpdump -i any proto esp -c 10

# 5. Проверка MTU (должен уменьшиться на оверхед)
ping -M do -s 1372 -c 1 192.168.2.1

# 6. Проверка маршрута
ip route get 192.168.2.1
# → 192.168.2.1 via ... dev xfrm0 src 192.168.1.1

# 7. Статистика ошибок (не должно быть роста)
ip -s xfrm state | grep -A2 "replay-shift\|integrity-error\|overflow"
```

### Типовые проблемы

| Ошибка / Симптом | Вероятная причина | Решение |
|------------------|-------------------|---------|
| `NO_PROPOSAL_CHOSEN` | Несовпадение алгоритмов шифрования | Синхронизировать `proposals` на обеих сторонах. Убедиться, что версии strongSwan поддерживают AEAD-алгоритмы. |
| `AUTHENTICATION_FAILED` | Неверный PSK или ID сертификата | Проверить `secrets` и соответствие `local_id` / `remote_id`. Для сертификатов — проверить цепочку доверия (`ipsec pki --verify`). |
| `TS_UNACCEPTABLE` | Ошибка в Traffic Selectors (подсетях) | Убедиться, что `local_ts` одной стороны совпадает с `remote_ts` другой. |
| `INVALID_KE_PAYLOAD` | Несовместимые DH-группы (KE) | Указать совместимую группу в `proposals` (например, `modp2048` или `ecp384`). |
| `INVALID_SYNTAX` | Синтаксическая ошибка в конфигурации | Проверить `swanctl --log` — charon указывает строку с ошибкой. |
| `SINGLE_PAIR_REQUIRED` | Несовпадение количества SA в proposal | Использовать `proposals = default` или указать одну пару алгоритмов. |
| `FAILED_CP_REQUIRED` | Клиент запросил конфигурацию internal IP, но пул не настроен | Добавить секцию `pools` в конфигурацию. |
| `TEMPORARY_FAILURE` | Временная ошибка negotiation (часто при mismatch DPD) | Проверить настройки `dpd_delay`/`dpd_timeout` на обеих сторонах. |
| Туннель UP, трафик не идет | Firewall блокирует ESP или проблемы MTU | Разрешить IP 50 (ESP), UDP 500/4500, настроить MSS Clamping. |
| Туннель UP, TCP зависает | MSS превышает MTU туннеля | Настроить MSS Clamping: `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`. |
| Туннель UP, UDP не работает | Конфликт NAT-T с существующим NAT | Проверить `swanctl --list-sas` — если порт источника не 4500, NAT-T может не работать. |
| `REVOCATION_CHECK_FAILED` | Сертификат отозван или OCSP-сервер недоступен | Проверить OCSP URI в сертификате, проверить доступность OCSP-резпондера. При необходимости временно: `revocation = ifuri`. |
| Туннель repeatedly flaps | DPD срабатывает из-за нестабильного канала | Увеличить `dpd_delay`/`dpd_timeout` или уменьшить `life_time` CHILD SA. |

---

## Безопасность и рекомендации по шифрованию

### Одобренные алгоритмы (Production)

| Компонент | Рекомендуемые | Минимально допустимые | Запрещённые |
|-----------|---------------|----------------------|-------------|
| **IKE SA (proposals)** | `aes256gcm128-sha384-ecp384`, `aes256gcm128-sha384-x25519` | `aes256-sha256-modp2048` | 3DES, MD5, SHA1, modp768, modp1024 |
| **ESP (esp_proposals)** | `aes256gcm128-ecp384`, `aes256gcm128-sha384`, `chacha20poly1305-sha256` | `aes256gcm128-sha256` | 3DES, DES, NULL, MD5 |
| **DH-группы (KE)** | ECP-384 (group 20), X25519, modp4096 | modp2048 | modp768, modp1024 |
| **PRF** | SHA-384, SHA-256 | SHA-256 | MD5, SHA1 |

### Шифрование: что использовать и почему

**AEAD (Authenticated Encryption with Associated Data)** — рекомендуемый класс алгоритмов, объединяющий шифрование и аутентификацию в одной операции. Примеры: AES-GCM, ChaCha20-Poly1305.

Преимущества AEAD перед комбинацией `cipher + HMAC`:
- **Производительность:** Одна операция вместо двух, аппаратное ускорение (AES-NI, ARMv8 CE).
- **Безопасность:** Исключены атаки на взаимодействие cipher/HMAC (谨慎 композиция).
- **Простота:** Меньше параметров для согласования.

**PFS (Perfect Forward Secrecy):** Обеспечивается использованием ECDHE (ECP-384, X25519) в IKE SA. Каждая сессия генерирует уникальный обмен Diffie-Hellman, что делает компрометацию长期 ключа бесполезной для расшифровки прошлых сессий.

### Рекомендации по аутентификации

| Метод | Безопасность | Масштабируемость | Применение |
|-------|-------------|-----------------|------------|
| **PSK** | Средняя (один ключ на все пиринги) | Низкая | Lab, small-scale (<5 peers) |
| **Certificate (X.509)** | Высокая (индивидуальные ключи) | Высокая | Production, >5 peers |
| **EAP-TLS** | Высокая (сертификат клиента) | Высокая | Remote Access |
| **EAP-MSCHAPv2** | Средняя (пароль) | Средняя | Remote Access (legacy) |

### Параметры DPD (Dead Peer Detection)

DPD обнаруживает отказ удалённого пира и инициирует переподключение:

```
dpd_delay = 30s     # Интервал отправки DPD-запросов
dpd_timeout = 120s  # Таймаут до объявления пира мёртвым
dpd_action = restart # Действие при обнаружении мёртвого пира:
                     #   restart — перезапуститьCHILD SA
                     #   clear   — удалить SA без перезапуска
                     #   hold    — заморозить SA (для ручного анализа)
```

### Параметры Anti-Replay

```
replay_window = 32  # Размер окна anti-replay (по умолчанию 32 пакета)
                     # Для высокоскоростных каналов (10Gbps+) рекомендуется 64–128
                     #   ESN (Extended Sequence Number) включается автоматически
                     #   при replay_window > 32 или при необходимости
```

### Защита ключей PSK

- Минимальная длина: 64 символа (смешанные буквы, цифры, спецсимволы).
- Генерация: `openssl rand -base64 48` ( producing 64-символьную строку).
- Хранение: отдельный файл с правами `600`, не в основном конфиге.
- Ротация: регулярная смена ключей с синхронизацией на всех пирах.

---

## IKEv2 Advanced

### Ротация сертификатов (Certificate Renewal)

Сертификаты имеют ограниченный срок жизни. Рекомендуется автоматическая ротация:

```bash
# 1. Генерация нового ключа
ipsec pki --gen --type rsa --size 4096 \
    --outform pem > /etc/swanctl/private/gwA-new.key

# 2. Получение нового сертификата от CA
ipsec pki --issue --lifetime 730 \
    --cacert /etc/swanctl/cacerts/ca.crt \
    --cakey /etc/swanctl/private/ca.key \
    --in /etc/swanctl/private/gwA-new.key \
    --outform pem > /etc/swanctl/certs/gwA-new.crt \
    --dn "CN=gw1.example.com" \
    --san="gw1.example.com" \
    --san="198.51.100.1"

# 3. Замена ключа и сертификата
mv /etc/swanctl/private/gwA.key /etc/swanctl/private/gwA.key.old
mv /etc/swanctl/private/gwA-new.key /etc/swanctl/private/gwA.key
mv /etc/swanctl/certs/gwA.crt /etc/swanctl/certs/gwA.crt.old
mv /etc/swanctl/certs/gwA-new.crt /etc/swanctl/certs/gwA.crt

# 4. Перезагрузка конфигурации
swanctl --load-creds
swanctl --load-all
swanctl --reinit site-to-site
```

**Автоматизация ротации (cron):**

```bash
# /etc/cron.monthly/ipsec-renew
#!/bin/bash
# Проверка срока действия сертификата
EXPIRY=$(openssl x509 -in /etc/swanctl/certs/gwA.crt -noout -enddate | cut -d= -f2)
EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( ($EXPIRY_EPOCH - $NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 30 ]; then
    # Запуск ротации
    /usr/local/bin/ipsec-renew.sh
fi
```

### OCSP (Online Certificate Status Protocol)

Проверка отозванности сертификатов в реальном времени:

```bash
# Конфигурация OCSP в strongSwan
# /etc/swanctl/conf.d/ocsp.conf
connections {
    site-b {
        # ... (базовые параметры)
        local {
            auth = pubkey
            certs = gwA.crt
            ocsp_uri = http://ocsp.example.com
        }
        remote {
            auth = pubkey
            cacerts = ca.crt
            ocsp_uri = http://ocsp.example.com
        }
    }
}
```

```bash
# Проверка OCSP вручную
openssl ocsp -issuer /etc/swanctl/cacerts/ca.crt \
    -cert /etc/swanctl/certs/gwA.crt \
    -url http://ocsp.example.com \
    -resp_text
```

### CRL (Certificate Revocation List)

Список отозванных сертификатов:

```bash
# 1. Генерация CRL на CA
ipsec pki --signcrl --cacert ca.crt --cakey ca.key \
    --lastcrl /etc/swanctl/crls/ca.crl \
    --outform pem > /etc/swanctl/crls/ca.crl \
    --delete /etc/swanctl/certs/revoked.crt

# 2. Распространение CRL
cp /etc/swanctl/crls/ca.crl /etc/swanctl/cacerts/

# 3. Перезагрузка
swanctl --load-creds
```

```bash
# Просмотр CRL
openssl crl -in /etc/swanctl/crls/ca.crl -noout -text

# Проверка, отозван ли сертификат
openssl verify -crl /etc/swanctl/crls/ca.crl \
    -CAfile /etc/swanctl/cacerts/ca.crt \
    /etc/swanctl/certs/gwA.crt
```

### Multiple CA Support

Поддержка нескольких CA для мульти-пиринга:

```bash
# /etc/swanctl/conf.d/multi-ca.conf
connections {
    partner-a {
        remote {
            auth = pubkey
            cacerts = ca-partner-a.crt  # CA партнёра A
        }
    }
    partner-b {
        remote {
            auth = pubkey
            cacerts = ca-partner-b.crt  # CA партнёра B
        }
    }
}
```

---

## Security Hardening

### Защита от DoS-атак

```bash
# strongSwan: включение cookie exchange (Aggressive Mode protection)
# /etc/strongswan.conf.d/99-hardening.conf
charon {
    # Включить cookie exchange для защиты от DoS
    send_cookie = yes

    # Ограничение.rate limit для IKE
    retransmit_timeout = 4.0
    retransmit_tries = 5
    retransmit_base = 1.8

    # Блокировка при большом количестве неудачных попыток
    # (реализуется через iptables/nftables)
}
```

```bash
# nftables: rate limiting для IKE
sudo nft add rule inet filter input udp dport 500 \
    meter ike-limit { ip saddr limit rate 10/second burst 20 packets } accept
sudo nft add rule inet filter input udp dport 500 drop

# nftables: защита от SYN flood на IKE
sudo nft add rule inet filter input udp dport 500 \
    ct state new limit rate 5/second accept
sudo nft add rule inet filter input udp dport 500 ct state new drop
```

### Защита от replay-атак

```bash
# Увеличение окна anti-replay для высокоскоростных каналов
# /etc/swanctl/conf.d/hardening.conf
connections {
    high-security {
        children {
            secure-tunnel {
                # Увеличенное окно anti-replay
                replay_window = 128  # По умолчанию 32
            }
        }
    }
}
```

### Ограничение доступа к IPsec

```bash
# Разрешить IKE/ESP только от конкретных IP
# nftables
sudo nft add rule inet filter input ip saddr { 203.0.113.2, 203.0.113.3 } \
    udp dport 500 accept
sudo nft add rule inet filter input ip saddr { 203.0.113.2, 203.0.113.3 } \
    udp dport 4500 accept
sudo nft add rule inet filter input ip saddr { 203.0.113.2, 203.0.113.3 } \
    ip protocol esp accept
sudo nft add rule inet filter input udp dport 500 drop
sudo nft add rule inet filter input udp dport 4500 drop
sudo nft add rule inet filter input ip protocol esp drop
```

---

## Сетевая оптимизация

### Sysctl-параметры для IPsec

```bash
# /etc/sysctl.d/99-ipsec-performance.conf

# === XFRM ===
net.core.xfrm_acq_expires = 30
net.ipv4.xfrm4_gc_thresh = 262144

# === Маршрутизация ===
net.ipv4.ip_forward = 1
net.ipv4.route.max_size = 524288

# === Сетевые буферы ===
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216

# === Conntrack ===
net.netfilter.nf_conntrack_max = 262144
net.netfilter.nf_conntrack_udp_timeout = 60
net.netfilter.nf_conntrack_udp_timeout_stream = 180
```

```bash
sudo sysctl -p /etc/sysctl.d/99-ipsec-performance.conf
```

### RSS (Receive Side Scaling) для ESP

```bash
# Проверка поддержки RSS
ethtool -k eth0 | grep -i "receive-side-scaling"

# Включение RSS
sudo ethtool -K eth0 rx-hash on

# Настройка распределения ESP по ядрам
# определяем RSS хеш для ESP
sudo ethtool -X eth0 hfunc toeplitz

# Проверка распределения прерываний
cat /proc/interrupts | grep eth0
```

### GRO/GSO Offload

```bash
# Включение GRO (Generic Receive Offload)
sudo ethtool -K eth0 gro on

# Включение GSO (Generic Segmentation Offload)
sudo ethtool -K eth0 gso on

# Включение TSO (TCP Segmentation Offload)
sudo ethtool -K eth0 tso on

# Проверка
ethtool -k eth0 | grep -E "gro|gso|tso"
```

---

## Расширенное сравнение VPN

| Критерий | IPsec | WireGuard | OpenVPN | GRE over IPsec |
|----------|-------|-----------|---------|----------------|
| **Уровень** | L3 | L3 | L2/L3 | L3 (unicast/multicast) |
| **Протокол** | IKEv2 + ESP | WireGuard | OpenSSL + TCP/UDP | GRE + ESP |
| **Производительность** | Высокая (HW offload) | Очень высокая | Низкая (userspace) | Высокая |
| **Простота настройки** | Средняя | Очень простая | Средняя | Средняя |
| **Мультикаст** | Только Route-based | ❌ | ❌ | ✅ |
| **Динамические маршруты** | OSPF/BGP (Route-based) | ❌ | ❌ | OSPF/BGP |
| **Аутентификация** | PSK, X.509, EAP | Ключи | PSK, сертификаты, LDAP | PSK |
| **Резидентность** | Есть (стеки) | Модуль ядра | Userspace | Модуль ядра |
| **NAT-Traversal** | NAT-T (ESP in UDP) | Встроен | TCP (обход) | NAT-T |
| **Enterprise HW** | Полная поддержка | Ограниченная | Нет | Полная поддержка |
| **RFC/стандарты** | RFC 4301-4309 | Draft | Open source | RFC 2784/2890 |

### Когда что выбирать

| Сценарий | Рекомендация | Причина |
|----------|-------------|---------|
| Site-to-Site (Linux ↔ Linux) | **IPsec (strongSwan)** | Полная поддержка IKEv2 |
| Site-to-Site (Linux ↔ Cisco/MikroTik) | **IPsec** | Стандарт индустрии |
| Remote Access VPN | **WireGuard** или **OpenVPN** | Простота для клиентов |
| Мультикаст/динамическая маршрутизация | **GRE over IPsec** | GRE для multicast + IPsec для безопасности |
| Высокоскоростной канал (10Gbps+) | **IPsec с HW offload** | Аппаратное ускорение |
| Быстрое развёртывание | **WireGuard** | 5 минут на настройку |

---

## Постоянная конфигурация (Persistence)

### systemd-networkd для XFRM-интерфейсов

Создание XFRM-интерфейса, который автоматически поднимается при загрузке:

```ini
# /etc/systemd/network/30-xfrm.netdev
[NetDev]
Name=xfrm0
Kind=xfrm

[Xfrm]
InterfaceId=1
Parent=eth0
```

```ini
# /etc/systemd/network/30-xfrm.network
[Match]
Name=xfrm0

[Network]
Address=169.254.1.1/30

[Route]
Destination=192.168.2.0/24
Gateway=169.254.1.2
```

### Netplan (Ubuntu)

```yaml
# /etc/netplan/50-xfrm.yaml
network:
  version: 2
  tunnels:
    xfrm0:
      mode: xfrm
      id: 1
      link: eth0
      addresses:
        - 169.254.1.1/30
      routes:
        - to: 192.168.2.0/24
          via: 169.254.1.2
```

### Автозапуск strongSwan

Демон `charon-systemd` уже настроен на автозапуск. Для ручного управления:

```bash
sudo systemctl enable strongswan   # Автозапуск при загрузке
sudo systemctl start strongswan    # Немедленный запуск
sudo systemctl status strongswan   # Проверка статуса
sudo journalctl -u strongswan -f   # Мониторинг логов в реальном времени
```

---

## Дополнительная информация

### Сравнение с другими технологиями

| Технология | Уровень | Плюсы | Минусы |
|------------|---------|-------|--------|
| **IPsec** | L3 | Стандарт индустрии, Hardware Offload | Сложность, высокий оверхед |
| **WireGuard** | L3 | Скорость, простота, современная крипто | Пока меньше поддержки в Enterprise HW |
| **OpenVPN** | L2/L3 | Проходит через любые Firewall (TCP) | Низкая производительность (Userspace) |
| **GRE over IPsec** | L3 | Мультикаст, динамические маршруты | Двойной оверхед |

> Детальное сравнение: [Расширенное сравнение VPN](#расширенное-сравнение-vpn)

### Связанные документы

**Основные:**
- **[Настройка LibreSwan](./ipsec_libreswan.md)** — дефолтный IPsec в RHEL/CentOS/Rocky/Alma.
- **[Диагностика IPsec (legacy)](./ipsec_troubleshooting.md)** — отладка legacy-систем (racoon/KAME).
- **[Настройка KAME/racoon](./ipsec_linux_setup.md)** — руководство по конфигурации устаревшего стека.

**Продвинутые:**
- **[Динамическая маршрутизация](./ipsec_routing.md)** — OSPF/BGP поверх IPsec (FRRouting).
- **[Мониторинг IPsec](./ipsec_monitoring.md)** — Prometheus, Grafana, логирование, health check.
- **[Высокая доступность IPsec](./ipsec_ha.md)** — Active/Passive, VRRP, Keepalived.
- **[Производительность IPsec](./ipsec_performance.md)** — HW offload, sysctl, нагрузочные тесты.
- **[Совместимость с оборудованием](./ipsec_interoperability.md)** — Cisco, MikroTik, pfSense, Juniper.

**Смежные:**
- **[Интеграция GRE с IPsec](../gre/gre_ipsec_integration.md)** — построение Route-based VPN с поддержкой мультикаста.
- **[MTU и VPN](../../OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — детальный разбор накладных расходов.
- **[Сетевые интерфейсы Linux](../../../Linux/Networking/Concepts/linux_network_interfaces.md)** — типы VTI и XFRM.

---
