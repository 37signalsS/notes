# Диагностика persistent-конфигурации сети

**Диагностика persistent-конфигурации** — это систематический процесс проверки корректности персистентных сетевых настроек, включая применение конфигурационных файлов, зависимостей systemd, конфликтов менеджеров и состояния интерфейсов при загрузке. Отличается от временной диагностики тем, что фокусируется на **причинах**, по которым настройки не применяются при перезагрузке или перезапуске службы.

## Определения

- **Persistent-конфигурация** — сетевые настройки, сохранённые на диске и автоматически применяемые при загрузке ОС или перезапуске сетевой службы.
- **systemd-зависимости** — граф зависимостей между systemd-юнитами, определяющий порядок запуска сетевых служб и сервисов, зависящих от сети.
- **network-online.target** — systemd-юнит, который активируется только когда сеть готова к работе (есть IP, шлюз и достигнута маршрутизируемость).
- **dry-run** — режим проверки конфигурации без её фактического применения (например, `netplan --debug generate`, `ifreload -dn`).
- **NetworkManager-wait-online** — служба, блокирующая `network-online.target` до момента, пока NetworkManager не завершит настройку всех managed-интерфейсов.

## Базовые концепции

### Flowchart диагностики (Bottom-Up)

```
Проблема: интерфейс не получает настройки после reboot
│
├─ 1. Физический уровень (L1)
│   ├─ Кабель подключен? → ip link show <iface> (флаг LOWER_UP)
│   ├─ NIC определена ядром? → ls /sys/class/net/
│   └─ udev переименовал? → udevadm monitor --kernel --subsystem-match=net
│
├─ 2. Именование интерфейса
│   ├─ Ожидаемое имя существует? → ip -brief link
│   ├─ .link-файл применяется? → networkctl status <iface> | grep "Link File"
│   └─ Predictable names мешают? → net.ifnames=0 (grub) или .link-файл
│
├─ 3. Конфигурационный файл найден?
│   ├─ systemd-networkd → networkctl status <iface> | grep "Network File"
│   ├─ NetworkManager → nmcli device status
│   ├─ Netplan → netplan status
│   └─ ifupdown → cat /run/network/ifstate
│
├─ 4. Конфигурация валидна?
│   ├─ systemd-networkd → networkctl status (без ошибок в логах)
│   ├─ NetworkManager → nmcli connection show (без "unmanaged")
│   ├─ Netplan → netplan --debug generate
│   └─ ifupdown → ifquery --syntax-check
│
├─ 5. Менеджер конфликтует?
│   ├─ Два менеджера на одном интерфейсе? → systemctl status NM networkd
│   ├─ NM managed=false для этого интерфейса? → nmcli device status
│   └─ networkd не видит интерфейс? → networkctl list
│
├─ 6. systemd-зависимости
│   ├─ Сervois ждёт network-online.target? → systemctl list-dependencies <service>
│   ├─ wait-online таймаут? → journalctl -u systemd-networkd-wait-online
│   └─ Порядок загрузки нарушен? → systemd-analyze plot > boot.svg
│
└─ 7. DNS и маршрутизация
    ├─ DNS работает? → resolvectl status
    ├─ Маршрут по умолчанию есть? → ip route show default
    └─ Шлюз достижим? → ping <gateway>
```

## Практические сценарии

### 1. Интерфейс не поднимается при загрузке

**Симптом:** После reboot интерфейс `enp0s3` не имеет IP-адреса.

```bash
# Шаг 1: Проверка физического состояния
ip link show enp0s3
# →如果是 NO-CARRIER или отсутствует LOWER_UP — проблема на L1

# Шаг 2: Проверка, что systemd-networkd видит интерфейс
networkctl list
# → Если интерфейса нет в списке — проблема с .link файлом или match-секцией

# Шаг 3: Проверка применённого .network файла
networkctl status enp0s3 | grep "Network File"
# → Если "unmatched" — .network файл не матчит интерфейс

# Шаг 4: Логи
journalctl -u systemd-networkd -b --no-pager | grep -i "enp0s3"
```

**Типичные причины:**
- Нет `.network` файла с `[Match] Name=enp0s3`
- Имя интерфейса изменилось после обновления ядра (predictable names)
- `.link` файл переопределил имя

### 2. NetworkManager не управляет интерфейсом

**Симптом:** `nmcli device status` показывает `unmanaged` для интерфейса.

```bash
# Шаг 1: Проверка конфигурации managed
cat /etc/NetworkManager/NetworkManager.conf | grep -A5 "\[ifupdown\]"
# → managed=false? → NM игнорирует interfaces из /etc/network/interfaces

# Шаг 2: Проверка keyfile для этого интерфейса
ls /etc/NetworkManager/system-connections/ | grep enp0s3
# → Нет файла? → NM не знает об этом интерфейсе

# Шаг 3: Принудительное управление
sudo nmcli device set enp0s3 managed yes
sudo nmcli connection reload

# Шаг 4: Проверка unmanaged-devices
grep -r "unmanaged-devices" /etc/NetworkManager/
# → Если интерфейс в списке — NM будет его игнорировать
```

### 3. systemd-networkd-wait-online таймаут (2 минуты)

**Симптом:** Загрузка системы задерживается на 2 минуты.

```bash
# Шаг 1: Проверка wait-online
systemctl status systemd-networkd-wait-online
# → Если failed с timeout — интерфейс не достиг состояния routable

# Шаг 2: Определение проблемного интерфейса
journalctl -u systemd-networkd-wait-online -b --no-pager
# → "Giving up waiting for <interface>"

# Шаг 3: Решение — optional интерфейс
# В .network файле:
[Link]
RequiredForOnline=no

# Шаг 4: Решение — уменьшение таймаута
# /etc/systemd/system/systemd-networkd-wait-online.service.d/override.conf
[Service]
ExecStart=
ExecStart=/usr/lib/systemd/systemd-networkd-wait-online --timeout=30
```

### 4. Конфликт NetworkManager и systemd-networkd

**Симптом:** Интерфейс получает IP от одного менеджера, второй его сбрасывает.

```bash
# Шаг 1: Определение активных менеджеров
systemctl is-active NetworkManager systemd-networkd
# → Если оба active — конфликт

# Шаг 2: Проверка, кто управляет интерфейсом
nmcli device status
networkctl list
# → Интерфейс в обоих списках? → конфликт

# Шаг 3: Решение — отключить ненужный менеджер
# Если используется systemd-networkd:
sudo systemctl disable --now NetworkManager
sudo systemctl enable --now systemd-networkd

# Если используется NetworkManager:
sudo systemctl disable --now systemd-networkd
sudo systemctl enable --now NetworkManager

# Шаг 4: Частичное решение — unmanaged-devices
# /etc/NetworkManager/conf.d/99-unmanaged.conf
[ifupdown]
managed=false
```

### 5. Netplan: конфигурация не применяется

**Симптом:** `netplan apply` не вызывает ошибок, но интерфейс не настраивается.

```bash
# Шаг 1: Проверка синтаксиса
sudo netplan --debug generate
# → Покажет все ошибки YAML

# Шаг 2: Проверка, какой бэкенд сгенерирован
ls /run/systemd/network/
# → Для networkd: .network файлы
# → Для NM: ключи в /run/NetworkManager/

# Шаг 3: Проверка приоритетов файлов
ls -la /etc/netplan/
# → Файлы обрабатываются лексикографически
# → 99-custom.yaml переопределяет 01-netcfg.yaml

# Шаг 4: Безопасное применение с автооткатом
sudo netplan try
# → Подтвердить через Enter в течение 120 секунд
```

### 6. DNS не работает после изменения конфигурации

**Симптом:** `ping 8.8.8.8` работает, `ping google.com` — нет.

```bash
# Шаг 1: Проверка текущего резолвера
resolvectl status
# → Если нет DNS-серверов для интерфейса — проблема в конфигурации

# Шаг 2: Проверка /etc/resolv.conf
ls -la /etc/resolv.conf
# → Симлинк на systemd-resolved? → systemctl status systemd-resolved
# → Обычный файл? → cat /etc/resolv.conf

# Шаг 3: Проверка NM + resolved интеграции
# /etc/NetworkManager/conf.d/10-dns-resolved.conf
[main]
dns=systemd-resolved

# Шаг 4: Проверка networkd + resolved
# В .network файле:
[Network]
DNS=8.8.8.8
DNSSEC=allow-downgrade
```

### 7. Откат изменений при потере доступа

**Симптом:** После `netplan apply` или `nmcli connection up` SSH-доступ потерян.

```bash
# Вариант 1: Через консоль/vKVM
# Восстановление из бэкапа:
sudo cp /root/netplan.bak.2026-01-01/*.yaml /etc/netplan/
sudo netplan apply

# Вариант 2: netplan try (автооткат через 120 сек)
# Если применяли через `netplan try` и не подтвердили — откат автоматический

# Вариант 3: Аварийный shell
# При загрузке добавить в kernel cmdline:
# systemd.unit=rescue.target
# Или через grub: e → добавить в строку Linux

# Вариант 4: Восстановление через Live USB
sudo mount /dev/sda1 /mnt
sudo cp /mnt/root/interfaces.bak.* /mnt/etc/network/interfaces
sudo umount /mnt
sudo reboot
```

### 8. Порядок загрузки: что запускается до чего

```bash
# Визуализация зависимостей
systemd-analyze plot > /tmp/boot-order.svg
xdg-open /tmp/boot-order.svg

# Типичный порядок для Ubuntu Server + systemd-networkd:
# systemd-udevd → systemd-tmpfiles-setup → netplan-apply.service
# → systemd-networkd → systemd-networkd-wait-online
# → network-online.target → multi-user.target

# Проверка времени загрузки
systemd-analyze blame | head -10
```

## Дополнительная информация

### Чек-лист диагностики перед применением в production

| Проверка | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Синтаксис конфигурации | `netplan --debug generate` / `ifquery --syntax-check` | Exit code 0, без ошибок |
| Dry-run применения | `ifreload -dn` / `netplan try` | Показывает что изменится, без фактического применения |
| Бэкап текущей конфигурации | `cp -r /etc/netplan /root/bak.$(date +%F)` | Файл скопирован |
| Резервный доступ | Открыть tty-консоль или vKVM | Доступен альтернативный канал |
| Проверка systemd-зависимостей | `systemctl list-dependencies <service>` | Сервис не зависит от интерфейса, который меняется |

### См. также

- **[Постоянная настройка сети](./index.md)** — обзор менеджеров и выбор инструмента.
- **[Порядок диагностики сетевых проблем](../../network_troubleshooting_order.md)** — общая методология Bottom-Up.
- **[sysctl: сетевые параметры ядра](../sysctl_network.md)** — параметры, критичные для persistent-конфигурации.
- **[systemd-networkd](./systemd_networkd.md)** — настройка через `.network` и `.netdev` файлы.
- **[NetworkManager в RHEL](./centos_rhel_networkmanager.md)** — nmcli и keyfile.
