# Настройка IPv6-адресов в Linux

## Определения

**Персистентная настройка сети** — конфигурация параметров сетевых интерфейсов, которая сохраняется после перезагрузки системы.

**Методы назначения адресов:**

- **SLAAC (Stateless Address Autoconfiguration)** — автоматическая генерация адреса на основе префикса сети, полученного от маршрутизатора в сообщениях **Router Advertisement (RA)**.
- **DHCPv6** — получение адреса и параметров сети от сервера. Бывает **Stateful** (выдача адреса) и **Stateless** (только доп. параметры, адрес через SLAAC).
- **Static (Manual)** — ручное назначение фиксированного адреса администратором.

**Дополнительные методы:**

- **Prefix Delegation (DHCPv6 PD)** — механизм, при котором DHCPv6-сервер выдает не单个ный адрес, а префикс (обычно /56 или /64) для всей подсети клиента (роутера, CPE). Клиент затем раздает адреса внутри этого префикса через SLAAC или DHCPv6.
- **IPv4-mapped IPv6 (`::ffff:0:0/96`)** — механизм представления IPv4-адресов внутри IPv6-стека для совместимости dual-stack приложений.

## Основные концепции

### Жизненный цикл адреса

В отличие от IPv4, адрес IPv6 имеет два временных параметра жизни (Lifetime), получаемых через RA или DHCPv6:

- **Preferred Lifetime**: время, в течение которого адрес считается предпочтительным. По истечении этого времени адрес переходит в состояние `deprecated` (используется для старых соединений, но не выбирается для новых).
- **Valid Lifetime**: общее время жизни адреса. По истечении этого времени адрес удаляется с интерфейса.

### Выбор исходного адреса (Source Address Selection)

При наличии нескольких IPv6-адресов на интерфейсе (например, GUA, ULA и временный адрес), ядро Linux выбирает адрес источника для исходящих пакетов согласно **RFC 6724**. Основные правила:
1. Предпочтение одинаковых областей видимости (Scope).
2. Предпочтение адресов в состоянии `preferred` над `deprecated`.
3. Предпочтение временных адресов (Privacy Extensions) для клиентского трафика.
4. Выбор адреса с наиболее длинным общим префиксом с адресом назначения.

Политика может быть дополнительно настроена через `/etc/gai.conf`. По умолчанию ULA имеет приоритет над GUA для локальных назначений.

### Типы идентификаторов интерфейса

- **EUI-64**: формируется на основе MAC-адреса. Позволяет отслеживать устройство.
- **Privacy Extensions (RFC 4941)**: генерация случайных временных адресов.
- **Stable Privacy (RFC 7217)**: генерация стабильного, но случайного адреса для каждой сети, что предотвращает отслеживание при перемещении между сетями.

### Формирование EUI-64

EUI-64 (Extended Unique Identifier) формируется из 48-битного MAC-адреса:
1. MAC делится пополам: `00:11:22` и `33:44:55`.
2. В середину вставляется константа `FF:FE`: `00:11:22:FF:FE:33:44:55`.
3. **Инвертируется U/L бит (7-й бит слева):** если адрес был глобальным (бит = 0), он становится локальным (бит = 1), и наоборот.

### Scope ID (Zone Index)

Link-Local адреса (`fe80::/10`) существуют на каждом интерфейсе. Для указания конкретного интерфейса используется Scope ID:
```bash
ping6 -c 2 ff02::1%eth0
```
Без `%eth0` ядро не определит выходной интерфейс, так как один и тот же префикс `fe80::/10` присутствует на всех интерфейсах.

### Флаги Router Advertisement (RA)

RA-сообщения (ICMPv6 Type 134) содержат флаги, управляющие поведением хостов:

| Флаг | Назначение |
| :--- | :--- |
| **M (Managed Address Configuration)** | Если `1`, хост должен использовать Stateful DHCPv6 для получения адреса. |
| **O (Other Configuration)** | Если `1`, хост должен получить доп. параметры (DNS, домен поиска) через DHCPv6, даже если адрес получен через SLAAC. |
| **H (Home Agent)** | Используется для мобильности IPv6 (Mobile IPv6). |

### Матрица выбора метода назначения адресов

| Сценарий | Рекомендуемый метод | Обоснование |
| :--- | :--- | :--- |
| **Клиентские устройства (ноутбуки, телефоны)** | SLAAC + Stateless DHCPv6 | Автоматическая конфигурация, Privacy Extensions, низкая нагрузка на сеть. |
| **Серверы с фиксированной ролью** | Static + Stable Privacy | Предсказуемость адресации, отсутствие зависимостей от DHCP. |
| **Централизованное управление адресами** | DHCPv6 Stateful | Единый пул адресов, аудит, интеграция с DNS (DDNS). |
| **CPE / домашние роутеры** | DHCPv6 Prefix Delegation + SLAAC | Автоматическое раздачи префиксов клиентам внутренней сети. |
| **Временная настройка / отладка** | iproute2 (`ip -6 addr add`) | Быстрое применение, сброс при перезагрузке. |

### Параметры sysctl для автоконфигурации

Параметры настраиваются в пространстве `net.ipv6.conf.*`. Приоритет: `<ifname>` > `default` > `all`.

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **`autoconf`** | `0` / `1` | Разрешает/запрещает генерацию адресов через SLAAC. |
| **`accept_ra`** | `0` / `1` / `2` | Прием RA от маршрутизаторов. `0` — выкл, `1` — вкл, `2` — принудительно при `forwarding=1`. |
| **`accept_ra_defrtr`** | `0` / `1` | Прием информации о Default Router из RA. |
| **`accept_ra_pinfo`** | `0` / `1` | Прием параметров сети (DNS, домен) из RA (RFC 6106). |
| **`use_tempaddr`** | `0` / `1` / `2` | Включение Privacy Extensions. `2` — временные адреса предпочтительны. |
| **`temp_valid_lft`** | секунды | Время жизни временного адреса Privacy Extensions. |
| **`addr_gen_mode`** | `0` / `1` / `2` / `3` | `0` — EUI-64, `1` — None (только статические), `2` — Stable Privacy (RFC 7217), `3` — Random. |

**Постоянная запись sysctl:**
```bash
# /etc/sysctl.d/60-ipv6-address.conf
net.ipv6.conf.all.autoconf = 1
net.ipv6.conf.default.autoconf = 1
net.ipv6.conf.all.accept_ra = 1
net.ipv6.conf.default.accept_ra = 1
net.ipv6.conf.all.use_tempaddr = 2
net.ipv6.conf.default.use_tempaddr = 2

# Применение
sudo sysctl --system
```

## Практические сценарии

### 1. SLAAC (Stateless Address Autoconfiguration)

SLAAC работает «из коробки» в большинстве дистрибутивов. Хост получает префикс через RA и генерирует адрес самостоятельно.

**NetworkManager (SLAAC):**
```bash
# Автоконфигурация через RA
sudo nmcli connection modify "eth0" ipv6.method auto

# Включение Stable Privacy вместо EUI-64
sudo nmcli connection modify "eth0" ipv6.addr-gen-mode stable-privacy

# Применение
sudo nmcli connection up "eth0"
```

**Netplan (Ubuntu — SLAAC + Stateless DHCPv6):**
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      accept-ra: true
      dhcp6: true
      nameservers:
        addresses: ["2001:db8::ffff"]
```

**systemd-networkd (SLAAC):**
```ini
# /etc/systemd/network/25-ipv6.network
[Match]
Name=enp0s3

[Network]
IPv6AcceptRA=yes
IPv6PrivacyExtensions=kernel
```

**Проверка:**
```bash
# Проверка, что SLAAC включен
sysctl net.ipv6.conf.all.autoconf
# → 1

# Проверка получения RA
rdisc6 eth0
# → Должен показать Router Advertisement с префиксом

# Проверка назначенных адресов
ip -6 addr show dev eth0
# → inet6 2001:db8::.../64 scope global dynamic

# Проверка временных адресов
ip -6 addr show dev eth0 | grep temporary
```

### 2. DHCPv6 Stateful

Адрес и параметры сети (DNS, домен) выдаются DHCPv6-сервером.

**NetworkManager (DHCPv6 Stateful):**
```bash
# Получение адреса от DHCPv6-сервера
sudo nmcli connection modify "eth0" ipv6.method dhcp

# Применение
sudo nmcli connection up "eth0"
```

**Netplan (DHCPv6 Stateful):**
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp6: true
```

**systemd-networkd (DHCPv6 Stateful):**
```ini
# /etc/systemd/network/25-ipv6.network
[Match]
Name=enp0s3

[Network]
DHCP=ipv6

[DHCPv6]
WithoutRA=no
UseDelegatedPrefix=yes
```

**dhclient (ISC DHCP Client):**
```bash
# Запрос адреса через DHCPv6 Stateful
sudo dhclient -6 -P -N eth0

# Освобождение адреса
sudo dhclient -6 -r eth0
```

**dhcpcd (lightweight, Alpine, Raspberry Pi OS):**
```bash
# В /etc/dhcpcd.conf:
# interface eth0
#   ipv6_only
#   ipv6_ra=1

sudo systemctl restart dhcpcd
```

**Проверка:**
```bash
# Проверка полученного адреса
ip -6 addr show dev eth0
# → inet6 2001:db8::.../64 scope global dynamic

# Проверка параметров DHCPv6
sudo dhcpcd -U eth0
# Или
sudo systemd-resolve --status eth0
```

### 3. DHCPv6 Stateless

Адрес получается через SLAAC, а опции (DNS, домен поиска) — через DHCPv6.

**NetworkManager (Stateless DHCPv6):**
```bash
# SLAAC для адреса + DHCPv6 для опций
sudo nmcli connection modify "eth0" ipv6.method auto ipv6.ignore-auto-dns no
```

**Netplan (Stateless DHCPv6):**
```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      accept-ra: true
      dhcp6: true
```

**systemd-networkd (Stateless DHCPv6):**
```ini
# /etc/systemd/network/25-ipv6.network
[Match]
Name=enp0s3

[Network]
IPv6AcceptRA=yes
DHCP=ipv6

[DHCPv6]
WithoutRA=no
```

**Проверка:**
```bash
# Проверка, что адрес получен через SLAAC (флаг dynamic)
ip -6 addr show dev eth0
# → inet6 2001:db8::.../64 scope global dynamic

# Проверка DNS из DHCPv6
resolvectl status eth0
```

### 4. Статическая настройка

#### NetworkManager (nmcli)

```bash
# Установка метода и адреса
sudo nmcli connection modify "eth0" ipv6.method manual ipv6.addresses "2001:db8::10/64"

# Настройка шлюза и DNS
sudo nmcli connection modify "eth0" ipv6.gateway "2001:db8::1" ipv6.dns "2001:db8::ffff"

# Применение
sudo nmcli connection up "eth0"
```

#### Настройка Stable Privacy (RFC 7217)

```bash
# Использование стабильных случайных адресов вместо EUI-64
sudo nmcli connection modify "eth0" ipv6.addr-gen-mode stable-privacy
```

### 5. Netplan (Ubuntu)

Конфигурация в `/etc/netplan/*.yaml`. Параметр `gateway6` устарел, используйте `routes`.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      addresses:
        - "2001:db8::10/64"
      routes:
        - to: default
          via: "2001:db8::1"
      nameservers:
        addresses: ["2001:db8::ffff"]
```

### 6. systemd-networkd

Конфигурация в `/etc/systemd/network/10-eth0.network`.

```ini
[Match]
Name=eth0

[Network]
# Для статики
Address=2001:db8::10/64
Gateway=2001:db8::1

# Для автоконфигурации
IPv6AcceptRA=yes
IPv6PrivacyExtensions=kernel
```

### 7. Временная настройка (iproute2)

Используется для отладки, настройка пропадают после перезагрузки.

```bash
# Добавление адреса
sudo ip -6 addr add 2001:db8::50/64 dev eth0

# Установка токена интерфейса (фиксированная часть для SLAAC)
sudo ip token set ::dead:beef dev eth0

# Проверка маршрута по умолчанию
ip -6 route show default

# Проверка связности
ping6 -c 3 2001:db8::1
```

### 8. Отключение IPv6

**1. Через sysctl (рекомендуемый способ):**

```bash
# В файле /etc/sysctl.d/99-disable-ipv6.conf
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1

# Применение
sudo sysctl --system

# Проверка
cat /proc/net/if_inet6  # должен быть пуст
```

**2. Через GRUB (полное отключение на уровне ядра):**

Добавить `ipv6.disable=1` в параметры `GRUB_CMDLINE_LINUX` в `/etc/default/grub`, затем:
- `sudo update-grub` (Debian/Ubuntu)
- `sudo grub2-mkconfig -o /boot/grub2/grub.cfg` (RHEL/CentOS)

### 9. Настройка Router Advertisement Daemon (radvd)

Для работы SLAAC в сети необходимо настроить маршрутизатор на отправку RA.

```conf
# /etc/radvd.conf
interface eth0 {
    AdvSendAdvert on;
    AdvManagedFlag on;    # M flag: Stateful DHCPv6
    AdvOtherConfigFlag on; # O flag: Stateless DHCPv6
    prefix 2001:db8:1::/64 {
        AdvOnLink on;
        AdvAutonomous on;  # SLAAC включен
    };
    RDNSS 2001:db8::1 {
        AdvRDNSSLifetime 1800;
    };
};
```

```bash
# Применение
sudo sysctl --system
sudo systemctl enable --now radvd

# Проверка работы
rdisc6 eth0
# Должен показать собственный RA
```

## Дополнительная информация

### Проверка состояний адреса (DAD)

При назначении адреса он проходит проверку **Duplicate Address Detection**:
- **tentative**: идет проверка уникальности, адрес еще не активен.
- **dadfailed**: адрес занят в сети, произошел конфликт.
- **deprecated**: время `preferred lifetime` истекло, адрес не рекомендуется для новых соединений.

### Валидация конфигурации

```bash
# Проверка всех адресов на интерфейсе
ip -6 addr show dev eth0

# Проверка маршрутов
ip -6 route show

# Проверка маршрута по умолчанию для конкретного адреса назначения
ip -6 route get 2001:db8::1

# Проверка правил source address selection
ip -6 addrlabel show

# Проверка принятых RA
rdisc6 eth0

# Проверка членства в multicast-группах (NDP)
ip -6 maddr show dev eth0
```

### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Нет шлюза | RA заблокированы файрволом | Разрешить ICMPv6 Type 134. См. **[Firewall для IPv6](./firewall.md)** |
| Дублирование адресов | Неверно настроен DAD или статическая копия | Проверить логи `dmesg`, сменить IP. |
| Пинг есть, связи нет | Проблема выбора Source IP | Проверить приоритеты через `ip addr show`. |
| Адрес в `tentative` долго | DAD не завершается, петля L2 | `tcpdump -i eth0 icmp6`, исключить петли. |
| SLAAC не работает | `accept_ra=0`, `autoconf=0`, неверный префикс, multicast-блокировка | `rdisc6 eth0`, `sysctl net.ipv6.conf.all.accept_ra`. |
| DHCPv6 не дает адрес | Сервер недоступен, M-flag не установлен, файрвол блокирует UDP 546/547 | `dhcpcd -U eth0`, проверить `nftables`. |
| `dadfailed` | Конфликт адреса в сети | Сменить статический IP, проверить DHCPv6/SLAAC. |
| Префикс `/128` для SLAAC | Неверная длина префикса | SLAAC требует `/64`. Исправить префикс на маршрутизаторе. |

### Best Practices

1. **Stable Privacy (RFC 7217):** Использовать `addr_gen_mode=2` вместо EUI-64 на всех интерфейсах для баланса стабильности и приватности.
2. **Privacy Extensions:** Включать `use_tempaddr=2` на клиентских устройствах. На серверах использовать `use_tempaddr=0`.
3. **accept_ra на серверах:** Для статики использовать `accept_ra=0`. Для клиентов — `accept_ra=1`. `accept_ra=2` — только для маршрутизаторов.
4. **/64 для SLAAC:** Обязательно использовать префикс `/64` для автоконфигурации. Другие длины ломают SLAAC.
5. **Постоянная запись sysctl:** Все параметры IPv6 записывать в `/etc/sysctl.d/*.conf`, а не только применять временно.
6. **Валидация после изменений:** Всегда проверять `ip -6 addr show`, `ip -6 route show`, `ping6` после изменения конфигурации.
7. **Scope ID для Link-Local:** Всегда указывать `%interface` при работе с Link-Local адресами в командах.
8. **MSS Clamping при туннелях:** При использовании туннелей (VXLAN, GRE, SIT) настраивать MSS Clamping для избежания фрагментации.

### См. также

- **[Концепции IPv6 в Linux](./concepts.md)** — типы адресов, механизмы автоконфигурации, DHCPv6, radvd.
- **[Диагностика IPv6](./diagnostics.md)** — глубокая отладка сетевых проблем и NDP.
- **[Настройка Netplan](../Persistent_Network/ubuntu_netplan.md)** — подробное руководство по Netplan.
- **[Kubernetes Dual-Stack](./kubernetes_dual_stack.md)** — IPv6 в Kubernetes-кластерах.
