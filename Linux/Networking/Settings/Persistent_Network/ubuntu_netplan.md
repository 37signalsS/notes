# Настройка Netplan в Ubuntu

**Netplan** — это стандартная утилита для конфигурации сети в дистрибутивах Ubuntu (начиная с версии 17.10) и Debian (v12+), использующая декларативный подход на основе файлов в формате YAML (Yet Another Markup Language). Netplan выступает в роли абстрактного слоя: он не настраивает сетевые интерфейсы напрямую, а генерирует конфигурационные файлы для выбранных бэкендов (**renderers**), таких как `systemd-networkd` (основной выбор для серверов) или `NetworkManager` (для рабочих станций).

С выходом **Netplan 1.2.x** проект продолжает активно развиваться и рекомендован для использования во всех окружениях, включая встраиваемые системы.

## Определения

- **Backend (Renderer / Бэкенд)** — системная служба, которая непосредственно управляет сетевыми интерфейсами. Основные варианты: `systemd-networkd` и `NetworkManager`.
- **YAML (Yet Another Markup Language)** — человекочитаемый формат сериализации данных, чувствительный к отступам (использование табуляции запрещено).
- **Match** — секция, позволяющая идентифицировать сетевой интерфейс по различным критериям (MAC-адрес, драйвер, имя), прежде чем применять к нему настройки.
- **Set-name** — параметр, позволяющий переименовать интерфейс при его обнаружении (часто используется совместно с `match`).
- **Пути конфигурации (в порядке приоритета):**
  - `/run/netplan/*.yaml` — временные настройки (например, от `cloud-init`).
  - `/etc/netplan/*.yaml` — основные настройки администратора.
  - `/lib/netplan/*.yaml` — настройки, поставляемые системными пакетами.
- **Интерфейс командной строки (CLI):**
  - `netplan status` — вывод детального состояния всех интерфейсов, включая IP, маршруты и DNS.
  - `netplan get [key]` — получение текущей конфигурации или значения конкретного ключа.
  - `netplan set [key=value]` — динамическое изменение параметров через CLI (сохраняется в `/etc/netplan/`).

## Базовые концепции

### Структура конфигурации

Файлы Netplan всегда начинаются с корневого блока `network`. Критически важно соблюдать иерархию отступов (обычно 2 или 4 пробела).

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: true
      optional: true
```

### Ключевые параметры

1. **`renderer`**: определяет бэкенд управления. На серверах рекомендуется `networkd`, на десктопах — `NetworkManager`.
2. **`match`**: позволяет привязать конфиг к конкретному «железу».
   ```yaml
   match:
     macaddress: 52:54:00:12:34:56
   ```
3. **`set-name`**: переименование интерфейса (например, в `eth0` для совместимости).
4. **`optional: true`**: не блокирует загрузку системы, если линк на интерфейсе отсутствует.
5. **`critical: true`**: интерфейс важен для загрузки (например, при загрузке по iSCSI/NFS).
6. **`activation-mode`**: (v0.101+) может принимать значения `up`, `off`, `manual`. Позволяет поднять интерфейс без назначения IP.

## Практические сценарии

### 1. Статический IP-адрес и маршруты

Параметры `gateway4` и `gateway6` устарели. Используйте секцию `routes`.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      addresses:
        - 10.10.10.10/24
      routes:
        - to: default
          via: 10.10.10.1
          metric: 100
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
```

### 2. Сетевой мост (Bridge) и VLAN

Мост с поддержкой фильтрации VLAN (VLAN-aware).

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: no
  bridges:
    br0:
      interfaces: [enp0s3]
      addresses: [192.168.1.50/24]
      parameters:
        stp: true
        forward-delay: 0
```

### 3. Маршрутизация на основе политик (PBR) и VRF

Использование VRF для полной изоляции сетевого стека.

```yaml
network:
  version: 2
  renderer: networkd
  vrfs:
    vrf-blue:
      table: 10
      interfaces: [enp0s8]
  ethernets:
    enp0s8:
      addresses: [10.0.0.10/24]
      routes:
        - to: default
          via: 10.0.0.1
          table: 10
```

### 4. Агрегация каналов (Bonding) и SR-IOV

Настройка виртуальных функций (VF) для высокопроизводительных систем.

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp1s0:
      virtual-functions:
        - count: 4
          # v0.100+: назначение MAC и VLAN для VF
          vlan: 100
```

### 5. Современный WiFi (WPA3-SAE)

Требует `renderer: NetworkManager` и поддержку со стороны драйвера.

```yaml
network:
  version: 2
  renderer: NetworkManager
  wifis:
    wlan0:
      dhcp4: true
      access-points:
        "MyHomeWiFi":
          password: "my-secure-password"
          auth:
            key-management: sae # WPA3
```

### 6. Нативный Wireguard (v0.100+)

Создание туннеля напрямую через Netplan.

```yaml
network:
  version: 2
  tunnels:
    wg0:
      mode: wireguard
      key: <private_key_content>
      port: 51820
      addresses: [10.100.0.1/24]
      peers:
        - keys:
            public: <peer_public_key>
          endpoint: 1.2.3.4:51820
          allowed-ips: [10.100.0.0/24]
```

### 7. Продвинутая настройка DHCP

Для тонкой настройки DHCPv4 используйте секцию `dhcp4-overrides`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: true
      dhcp4-overrides:
        use-dns: false
        use-ntp: false
        use-hostname: false
        route-metric: 100
        hostname: "server01"
      dhcp-identifier: mac
      nameservers:
        addresses: [10.0.0.1]
```

Для DHCPv6 (stateful) используйте `dhcp6: true`. Для stateless DHCPv6 (только опции, адрес через SLAAC) — `accept-ra: true` вместе с `dhcp6: true`.

### 8. МТУ и аппаратные параметры

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s3:
      dhcp4: true
      mtu: 9000
```

Для Jumbo-фреймов убедитесь, что коммутаторы в пути поддерживают соответствующий MTU. Для управления аппаратной разгрузкой (GRO, LRO, TSO) используйте секцию `ethtool`.

### 9. Режимы активации интерфейсов

| Значение | Поведение |
| :--- | :--- |
| `up` (по умолчанию) | Интерфейс поднимается, применяются IP/маршруты/DNS. |
| `manual` | Интерфейс поднимается без назначения IP (требует внешнего управления). |
| `off` | Интерфейс остаётся выключенным. |

### 10. Безопасное переключение renderer

При смене renderer (например, с `NetworkManager` на `networkd`):

1. Сохраните текущую конфигурацию.
2. Отключите предыдущий renderer.
3. Примените новый конфиг через `netplan apply`.
4. Проверьте состояние интерфейсов.

## Дополнительная информация

### Управление и диагностика

| Команда | Описание |
| :--- | :--- |
| `sudo netplan try` | Безопасное применение с автооткатом через 120 секунд. |
| `sudo netplan apply` | Немедленное применение конфигурации. |
| `sudo netplan --debug generate` | Проверка синтаксиса и генерация конфигов для бэкендов без их применения. |
| `netplan status` | Вывод сводки по интерфейсам, IP и маршрутам (v0.100+). |
| `netplan get all` | Получение всей текущей конфигурации. |
| `journalctl -u systemd-networkd` | Логи бэкенда при использовании `renderer: networkd`. |
| `journalctl -u NetworkManager` | Логи бэкенда при использовании `renderer: NetworkManager`. |

### Валидация и откат изменений

Перед применением конфигурации используйте проверку синтаксиса и механизм безопасного применения.

```bash
# Проверка синтаксиса и генерация без применения
sudo netplan --debug generate

# Безопасное применение с 120-секундным автооткатом
sudo netplan try
# Если за 120 секунд не подтвердить (Enter), конфигурация откатится автоматически.
# Для немедленного подтверждения: Enter в течение 120 секунд.
```

**Стратегия бэкапа:**
```bash
# Бэкап текущей конфигурации Netplan
sudo cp -r /etc/netplan /root/netplan.bak.$(date +%F)
```

**Аварийный доступ при неработающей сети:**
При некорректной конфигурации система может потерять доступ по сети. Рекомендуется держать активным хотя бы один консольный сеанс (tty) при внесении изменений.

Для отката через systemd:
```bash
# Перезапуск с предыдущим конфигом (работает, если предыдущий конфиг валиден)
sudo netplan apply

# Если netplan не работает, можно откатиться к ручному управлению через systemd-networkd
sudo systemctl enable --now systemd-networkd
```

**Валидация в CI/CD:**
```bash
# Линтинг YAML
yamllint /etc/netplan/*.yaml

# Проверка Netplan без применения
netplan generate --dry-run 2>/dev/null || netplan --debug generate
```

### Жизненный цикл конфигурации и systemd-интеграция

Netplan является ранним элементом загрузки. Его работа состоит из двух фаз:
1. **`netplan generate`** — выполняется автоматически через `netplan-apply.service` или `NetworkManager` при старте; генерирует конфигурацию в `/run/netplan/` для выбранного бэкенда.
2. **`netplan apply`** — применяет сгенерированную конфигурацию (перезапускает бэкенд или отправляет ему сигнал перезагрузки).

**Порядок загрузки (Ubuntu Server с `systemd-networkd`):**
```
systemd-udevd → systemd-tmpfiles-setup → netplan-apply.service → systemd-networkd → systemd-networkd-wait-online → network-online.target → multi-user.target
```

**Параметр `optional: true`:**
Если интерфейс не имеет линка при загрузке (например, кабель не подключён), `optional: true` не блокирует запуск `systemd-networkd-wait-online` и всей системы. Без этого параметра загрузка может затянуться до 2 минут (тайм-аут wait-online).

**Взаимодействие с `network-online.target`:**
Для сервисов, критичных к наличию сети, используйте `After=network-online.target` и `Wants=network-online.target`. При использовании Netplan + `systemd-networkd` этот target становится активным только после успешного завершения `systemd-networkd-wait-online`.

### Автоматизация и IaC

В средах с множеством серверов конфигурация должна быть централизованной и идемпотентной.

**Принцип именования файлов:**
- Используйте префиксы, отражающие порядок применения: `00-base.yaml`, `10-vlan.yaml`, `99-custom.yaml`.
- Файлы объединяются лексикографически; последний файл переопределяет параметры интерфейсов предыдущих.

**Ansible:**
Подробные сценарии автоматизации Netplan через Ansible, включая валидацию и troubleshooting, см. в [Ansible: Модули управления сетевой конфигурацией Linux](../../Ansible/Modules/ansible_network_configuration_modules.md).

**Валидация в pipeline:**
```bash
# Предварительная проверка перед деплоем
netplan get --origin=run all | grep -E 'ethernets|bridges|vrfs'
sudo netplan --debug generate
```

**Генерация из шаблонов (Jinja2):**
```jinja2
network:
  version: 2
  renderer: networkd
  ethernets:
    {{ interface_name }}:
      addresses: [{{ ip_address }}/{{ prefix }}]
      routes:
        - to: default
          via: {{ gateway }}
      nameservers:
        addresses: [{{ dns1 }}, {{ dns2 }}]
```

### Типичные ошибки и решение

- **Ошибка отступов (YAML):** Netplan крайне чувствителен к пробелам. Используйте 2 или 4 пробела, табуляция (Tab) строго запрещена.
- **Конфликт бэкендов:** Если в системе запущены и `systemd-networkd`, и `NetworkManager`, они могут конфликтовать за управление интерфейсом. Убедитесь, что `renderer` выбран правильно для вашей роли (сервер/десктоп).
- **Отсутствие пакетов для WiFi/VPN:** Для работы WiFi (WPA3) требуется `wpasupplicant`, для Wireguard — `wireguard-tools`. Netplan лишь генерирует конфиги, но не заменяет сами инструменты.
- **Интерфейс не поднимается:** Проверьте вывод `netplan status` и убедитесь, что параметр `optional: true` не мешает ожиданию готовности сети другими службами.
- **Неверный идентификатор DHCP:** Некоторые DHCP-серверы требуют `dhcp-identifier: mac` вместо стандартного `clientid`. Укажите явно, если сервер не выдает адрес.
- **Ошибка синтаксиса YAML:** Проверьте файлы через `netplan --debug generate`. Частая причина — использование `gateway4`/`gateway6` (устарело) или пропуск `version: 2`.

### Особенности работы

- **Объединение файлов:** Если в `/etc/netplan/` несколько файлов, они объединяются лексикографически. Файл `99-custom.yaml` переопределит настройки из `01-netcfg.yaml`.
- **Взаимодействие с автоматической генерацией:** Часто пакеты автоматической настройки создают файл в `/etc/netplan/50-cloud-init.yaml`. Не редактируйте его напрямую; создайте файл с более высоким приоритетом (например, `90-local.yaml`).

### Углублённое устранение неполадок

**Анализ pipeline Netplan:**
```bash
# 1. Проверить синтаксис YAML
sudo netplan --debug generate
# → покажет файлы, пути конфигурации и применённые настройки

# 2. Проверить, какой бэкенд получил конфигурацию
# Для systemd-networkd:
sudo networkctl list
# Для NetworkManager:
sudo nmcli device status
sudo nmcli -f all connection show

# 3. Проверить логи бэкенда
sudo journalctl -u systemd-networkd -b
sudo journalctl -u NetworkManager -b
```

**Ошибка: "Interface not found"**
- Проверьте `match`/`set-name`: возможно, интерфейс был переименован.
- Проверьте `networkctl list` или `nmcli device status`, чтобы увидеть фактическое имя.

**Ошибка: "Cannot apply" / "Conflicting settings"**
- Несколько файлов в `/etc/netplan/` могут конфликтовать. Проверьте порядок применения: `01-` < `90-`.
- Не добавляйте один и тот же интерфейс в несколько файлов без понимания приоритета.

**Ошибка: "No carrier"**
- Интерфейс поднят, но нет линка. Проверьте кабель, коммутатор, параметры `optional: true`.
- Проверьте `ip link show <iface>`.

**Ошибка: "DNS not resolving"**
- Убедитесь, что `systemd-resolved` активен: `resolvectl status`.
- Проверьте, не перезаписывает ли другой сервис `/etc/resolv.conf`.

**Ошибка: "netplan try" зависает**
- Нажмите `Enter` для подтверждения или дождитесь 120 секунд для автоотката.
- Если откат не работает, переключитесь на tty и отредактируйте файл вручную.

### См. также

- **[systemd-networkd](./systemd_networkd.md)** — глубокая настройка основного бэкенда для серверов.
- **[Агрегация каналов (Bonding)](../../../../Networking/Concepts/link_aggregation.md)** — теория LACP и балансировки.
- **[Маршрутизация по политикам (PBR)](../../Policy_Based_Routing/index.md)** — подробный обзор таблиц и правил.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры ядра, критичные для Netplan и бэкендов.
- **[Диагностика persistent-конфигурации](./persistent_network_troubleshooting.md)** — flowchart и типичные сценарии.
