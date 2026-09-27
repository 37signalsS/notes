# PXE: Загрузка по сети

## Определения

**PXE (Preboot Execution Environment — среда исполнения перед загрузкой)** — стандарт Intel, позволяющий компьютеру загружаться по сети, используя только сетевую карту (NIC), без необходимости в локальном загрузочном устройстве (HDD/SSD/USB). Клиент получает IP-адрес через DHCP и скачивает загрузочный образ (NBP) по протоколу TFTP или HTTP.

**NBP (Network Boot Program)** — исполняемый файл, скачиваемый клиентом по сети и запускающий процесс загрузки ОС или инсталлятора. Типичные примеры: `pxelinux.0` (SYSLINUX), `grubx64.efi` (GRUB2), `ipxe.efi` (iPXE).

**DHCP Options для PXE** — набор опций DHCP, определяющих поведение PXE-клиента:

| Опция | Имя | Описание |
| :--- | :--- | :--- |
| 60 | `vendor-class-identifier` | Клиент передаёт `"PXEClient"`; сервер определяет PXE-запрос и возвращает параметры загрузки |
| 66 | `next-server` | IP-адрес TFTP-сервера (или HTTP-сервера для HTTP Boot) |
| 67 | `filename` | Путь к NBP на сервере (`pxelinux.0` для BIOS, `grubx64.efi` для UEFI) |
| 93 | `client-arch` | Архитектура клиента (0=x86 BIOS, 7=x86-64 UEFI, 11=ARM64 UEFI) |

**ProxyDHCP** — расширение PXE, позволяющее развернуть PXE-инфраструктуру без модификации основного DHCP-сервера. ProxyDHCP отвечает только на PXE-запросы (определяя их по Option 60 = `"PXEClient"`), предоставляя параметры загрузки (Options 66/67), в то время как основной DHCP выдает IP-адреса. Подробнее — в файле [dnsmasq](../../Networking/Protocols/DNS/dnsmasq.md).

**Virtual Media (Redfish/IPMI)** — альтернатива PXE, позволяющая монтировать ISO-образы напрямую через контроллер управления (BMC) по протоколам HTTP/NFS/Samba. Используется в серверах с BMC (IPMI, iDRAC, iLO, XCC). Преимущество: нет зависимости от TFTP и DHCP Options. Недостаток: медленнее PXE для массового развёртывания, требует доступа к BMC.

**Chainloading** — механизм последовательной загрузки, при котором один загрузчик передаёт управление другому. Например: PXE Stack → `pxelinux.0` → `grubx64.efi` → ядро Linux. Используется для гибких сценариев (например, загрузка разного софта в зависимости от MAC-адреса).

## Базовые концепции

PXE является фундаментом для Bare Metal Provisioning (MAAS, Tinkerbell, Ironic), работы бездисковых станций и систем быстрого восстановления.

### Компоненты PXE-инфраструктуры

1.  **Клиент:** NIC с поддержкой PXE Stack (Legacy BIOS) или EFI Network Stack (UEFI). В UEFI также поддерживается HTTP Boot (RFC 8010), который позволяет загружать NBP по HTTP/HTTPS вместо TFTP.
2.  **DHCP-сервер:** Выдает IP и указывает путь к загрузчику через Options 66/67. Для ProxyDHCP используется Option 60 для идентификации PXE-клиентов. Подробнее о настройке DHCP для PXE — в файлах [ISC DHCP](../../Linux/Networking/Services/DHCP/isc_dhcp_server_overview.md) и [dnsmasq](../../Networking/Protocols/DNS/dnsmasq.md).
3.  **TFTP-сервер:** Протокол (UDP/69) для доставки NBP. Главный недостаток — отсутствие встроенной проверки целостности и низкая скорость из-за подтверждения каждого блока (ACK).
    *   **Оптимизация:** Современные серверы (tftpd-hpa, dnsmasq) поддерживают `blksize` (увеличение блока с 512 до 1468+ байт) и `windowsize` (отправка нескольких блоков без ожидания ACK).
    *   **Ограничения TFTP:** Максимальный размер файла — 32 МБ (ограничение протокола). Для файлов >100 МБ (kernel + initrd) рекомендуется использовать HTTP/NFS.
4.  **Файловый сервер (HTTP/S, NFS, iSCSI):** Используется для доставки "тяжелых" компонентов (Kernel, Initrd, RootFS). HTTP Boot в UEFI загружает kernel/initrd по HTTP напрямую, минуя TFTP.

## Базовые концепции

PXE является фундаментом для Bare Metal Provisioning (MAAS, Tinkerbell, Ironic), работы бездисковых станций и систем быстрого восстановления.

### Компоненты PXE-инфраструктуры

1.  **Клиент:** NIC с поддержкой PXE Stack (Legacy BIOS) или EFI Network Stack (UEFI).
2.  **DHCP-сервер:** Выдает IP и указывает путь к загрузчику:
    *   `next-server` (Option 66): IP TFTP-сервера.
    *   `filename` (Option 67): Путь к NBP.
    *   `vendor-class-identifier` (Option 60): В режиме ProxyDHCP клиент ищет этот тег для идентификации PXE-сервера.
3.  **TFTP-сервер:** Протокол (UDP/69) для доставки NBP. Главный недостаток — отсутствие встроенной проверки целостности и низкая скорость из-за подтверждения каждого блока (ACK).
    *   **Оптимизация:** Современные серверы (tftpd-hpa, dnsmasq) поддерживают `blksize` (увеличение блока с 512 до 1468+ байт) и `windowsize` (отправка нескольких блоков без ожидания ACK).
4.  **Файловый сервер (HTTP/S, NFS, iSCSI):** Используется для доставки "тяжелых" компонентов (Kernel, Initrd, RootFS), так как TFTP неэффективен для файлов >100 МБ.

### Процесс загрузки (Legacy vs UEFI)

| Этап | Legacy (BIOS) | UEFI |
| :--- | :--- | :--- |
| **Инициализация** | 16-битный PXE Stack (UNDI) | 32/64-битный EFI Network Stack |
| **DHCP Запрос** | DHCP Discover (Option 60=PXEClient) | DHCP Discover + Architecture Type (Option 93) |
| **Протоколы** | Только TFTP | TFTP, HTTP, HTTPS (HTTP Boot, RFC 8010) |
| **Режим CPU** | Реальный режим (1 МБ адресуемого пространства) | Защищенный режим (Long Mode, 64-бит) |
| **Безопасность** | Отсутствует | Secure Boot (цепочка доверия) |
| **NBP** | `pxelinux.0` (SYSLINUX) | `grubx64.efi`, `shim.efi`, `ipxe.efi` |

**Последовательность PXE-загрузки:**

```
1. Клиент: NIC инициирует PXE Stack
   ↓
2. Клиент → DHCP: DHCPDISCOVER (Option 60=PXEClient)
   ↓
3. DHCP → Клиент: DHCPOFFER (Option 66=TFTP-IP, Option 67=NBP-path)
   ↓
4. Клиент: DHCPREQUEST → DHCPACK (получение IP)
   ↓
5. Клиент → TFTP: Запрос NBP (pxelinux.0 / grubx64.efi)
   ↓
6. TFTP → Клиент: NBP загружен и запущен
   ↓
7. NBP: Загрузка конфигурации (pxelinux.cfg/ или grub.cfg)
   ↓
8. NBP: Загрузка kernel + initrd (TFTP или HTTP)
   ↓
9. Kernel: Запуск ядра, монтирование rootfs
```

#### UEFI Secure Boot Chain
Для загрузки в режиме Secure Boot используется **Shim** — легковесный загрузчик, подписанный ключом Microsoft. Подробнее — в файле [BIOS и UEFI](../../Core/firmware_bios_uefi.md).
1. `UEFI Firmware` (проверяет подпись `shim.efi`).
2. `Shim` (проверяет подпись `grubx64.efi` или `ipxe.efi` ключом дистрибутива или владельца).
3. `GRUB/iPXE` (загружает ядро).
4. `Kernel` (должен быть подписан ключом, доверенным Shim'у или UEFI).

### PXE в сетях IPv6 (DHCPv6)
В IPv6 процесс отличается отсутствием широковещательных рассылок (используется Multicast для Solicit):
*   Клиент отправляет `Solicit` с запросом опции 59 (`OPT_BOOTFILE_URL`).
*   Сервер отвечает `Advertise`, предоставляя URL (например, `tftp://[2001:db8::1]/ipxe.efi` или `http://[2001:db8::1]/boot.efi`).

### Сравнение PXE-загрузчиков

| Загрузчик | Тип | Протоколы загрузки | Secure Boot | Скрипты | Сценарий использования |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PXELINUX (SYSLINUX)** | Legacy BIOS | TFTP | Нет | Ограничено (`DEFAULT`, `LABEL`) | Простые сценарии, Legacy-серверы |
| **GRUB2** | BIOS + UEFI | TFTP, HTTP, NFS | Да (через Shim) | Мощные скрипты, переменные | Универсальный выбор, multi-boot |
| **iPXE** | BIOS + UEFI | TFTP, HTTP, HTTPS, iSCSI, AoE | Да | `#!ipxe` скрипты, циклы, условия | Гибкие сценарии, облачные среды |
| **Windows Boot Manager** | UEFI | TFTP, HTTP | Да | Ограничено | Windows PXE-загрузка |

**Рекомендации:**
- **Новые deployments (2026+):** iPXE или GRUB2 — оба поддерживают HTTP Boot и Secure Boot.
- **Legacy-системы:** PXELINUX — проверенный, но ограниченный по функциональности.
- **Массовое развёртывание ОС:** iPXE — позволяет загружать образы по HTTP, что значительно быстрее TFTP для больших файлов.

Подробнее о [процессе загрузки Linux](../../Core/kernel/boot_process.md).

## Практические сценарии

### 1. Установка и настройка TFTP-сервера (tftpd-hpa)

tftpd-hpa — стандартный TFTP-сервер для Debian/Ubuntu/RHEL с расширенными возможностями.

```bash
# Debian/Ubuntu
sudo apt install tftpd-hpa

# RHEL/Rocky/Alma
sudo dnf install tftp-server
```

```bash
# /etc/default/tftpd-hpa (Debian/Ubuntu)
TFTP_USERNAME="tftp"
TFTP_DIRECTORY="/srv/tftp"
TFTP_ADDRESS=":69"
TFTP_OPTIONS="--secure --blocksize 1468"
# --secure: ограничивает доступ только директорией TFTP_DIRECTORY
# --blocksize 1468: увеличивает размер блока (по умолчанию 512)
```

```bash
# Создание структуры каталогов
sudo mkdir -p /srv/tftp/{bios,efi64,arm64,pxelinux.cfg}
sudo chown -R tftp:tftp /srv/tftp
sudo chmod -R 755 /srv/tftp

# Копирование загрузчиков
sudo cp /usr/lib/PXELINUX/pxelinux.0 /srv/tftp/bios/
sudo cp /usr/lib/SYSLINUX/linux.c32 /srv/tftp/bios/     # Модуль для вывода лога
sudo cp /usr/lib/SYSLINUX/menu.c32 /srv/tftp/bios/      # Модуль меню
sudo cp /usr/lib/SYSLINUX/ldlinux.c32 /srv/tftp/bios/   # Ядро SYSLINUX

# UEFI загрузчик (_GRUB2_)
sudo apt install grub-efi-amd64-signed  # Debian/Ubuntu
sudo cp /usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed /srv/tftp/efi64/

# Запуск
sudo systemctl enable --now tftpd-hpa
sudo ss -ulnp | grep :69  # Проверка: должен слушать UDP/69
```

### 2. Конфигурация PXELINUX (BIOS Legacy)

Структура каталогов PXELINUX:

```
/srv/tftp/
├── pxelinux.0              # NBP (загрузчик)
├── bios/
│   ├── pxelinux.0
│   ├── ldlinux.c32
│   ├── menu.c32
│   └── linux.c32
├── efi64/
│   └── syslinux.efi        # UEFI-версия SYSLINUX
├── pxelinux.cfg/           # Конфигурация (автопоиск)
│   ├── default             # Конфигурация по умолчанию
│   ├── 01-AA-BB-CC-DD-EE-FF  # По MAC-адресу (с префиксом 01)
│   └── 192.168.10.50       # По IP-адресу
└── images/
    ├── vmlinuz
    ├── initrd.gz
    └── debian-12-mini.iso
```

**Пример `pxelinux.cfg/default`:**

```
DEFAULT menu.c32
PROMPT 0
TIMEOUT 50  # 5 секунд

MENU TITLE PXE Boot Menu

LABEL install-ubuntu
    MENU LABEL Ubuntu 24.04 Server [Autoinstall]
    KERNEL images/ubuntu/24.04/vmlinuz
    APPEND initrd=images/ubuntu/24.04/initrd.gz autoinstall ds=nocloud-net;s=http://repo.local/autoinstall/ubuntu/24.04/ ip=dhcp

LABEL install-debian
    MENU LABEL Debian 12 [Preseed]
    KERNEL images/debian/12/vmlinuz
    APPEND initrd=images/debian/12/initrd.gz auto=true priority=critical preseed/url=http://repo.local/preseed/debian-12.cfg

LABEL rescue
    MENU LABEL SystemRescue (Live)
    KERNEL images/systemrescue/vmlinuz
    APPEND initrd=images/systemrescue/initrd.img archisobasedocs=sysroot /sysroot.img

LABEL local
    MENU LABEL Boot from local disk
    LOCALBOOT 0
```

**Именование конфигов по приоритету (автопоиск PXELINUX):**
1. `pxelinux.cfg/<MAC>` — по MAC-адресу клиента (с префиксом `01-`)
2. `pxelinux.cfg/<IP>` — по IP-адресу (точка заменяется дефисом)
3. `pxelinux.cfg/default` — общий конфиг

### 3. Настройка DHCP для PXE (Dnsmasq)

Пример конфигурации с оптимизацией TFTP и поддержкой разных архитектур:

```bash
# /etc/dnsmasq.conf
interface=eth1
dhcp-range=192.168.10.50,192.168.10.150,255.255.255.0,12h

# Оптимизация TFTP
enable-tftp
tftp-root=/srv/tftp
tftp-max-blocksize=1468 # Избегаем фрагментации (MTU 1500 - заголовки)

# Определение типа клиента (Option 93)
# 0: BIOS, 7: EFI x86-64, 11: EFI ARM64
dhcp-match=set:bios,option:client-arch,0
dhcp-match=set:efi64,option:client-arch,7
dhcp-match=set:efi64,option:client-arch,9
dhcp-match=set:arm64,option:client-arch,11

# Выдача загрузчиков
dhcp-boot=tag:bios,bios/pxelinux.0
dhcp-boot=tag:efi64,efi64/syslinux.efi
dhcp-boot=tag:arm64,arm64/ipxe.efi
```

### 4. Сценарий ProxyDHCP
Позволяет добавить PXE в существующую сеть без доступа к основному DHCP-серверу (например, Windows DHCP или роутер провайдера).

```bash
# Настройка dnsmasq в режиме Proxy
dhcp-range=192.168.1.0,proxy
pxe-service=x86PC, "Boot from Network (Legacy)", bios/pxelinux
pxe-service=x86-64_EFI, "Boot from Network (UEFI)", efi64/ipxe.efi
```

### 5. Продвинутая загрузка через iPXE (HTTP)
iPXE позволяет загружать образы по HTTP/HTTPS, что критично для медленных каналов и массового развёртывания.

**Пример скрипта `boot.ipxe`:**
```ipxe
#!ipxe
dhcp
set base-url http://repo.local/os/ubuntu/24.04

# Загрузка ядра с параметрами автоустановки
kernel ${base-url}/vmlinuz initrd=initrd.gz autoinstall ds=nocloud-net;s=http://cfg.local/nodes/${mac:hex}/ ip=dhcp
initrd ${base-url}/initrd.gz
boot
```

**Пример с выбором ОС (меню):**
```ipxe
#!ipxe
dhcp || dhcp || shell
set menu-timeout 5000

:main_menu
menu PXE Boot Menu
item ubuntu Install Ubuntu 24.04
item debian Install Debian 12
item rescue SystemRescue
item local Boot from local disk
choose --timeout ${menu-timeout} target || goto local

:ubuntu
set base-url http://repo.local/os/ubuntu/24.04
kernel ${base-url}/vmlinuz autoinstall ds=nocloud-net;s=http://repo.local/autoinstall/ubuntu/
initrd ${base-url}/initrd.gz
boot

:debian
set base-url http://repo.local/os/debian/12
kernel ${base-url}/vmlinuz auto=true priority=critical preseed/url=http://repo.local/preseed/debian-12.cfg
initrd ${base-url}/initrd.gz
boot

:rescue
kernel http://repo.local/os/systemrescue/vmlinuz
initrd http://repo.local/os/systemrescue/initrd.img
boot

:local
sanboot --no-describe --drive 0 || exit
```

### 6. GRUB2 network boot (UEFI)

GRUB2 — универсальный загрузчик с поддержкой UEFI Secure Boot, HTTP Boot и мощных скриптов.

```bash
# Установка GRUB2 для PXE (Debian/Ubuntu)
sudo apt install grub-efi-amd64-signed grub-efi-amd64-bin

# Структура для GRUB2 network boot
/srv/tftp/
└── grub/
    ├── grubx64.efi           # Загрузчик
    └── grub/
        └── grub.cfg          # Конфигурация
```

```bash
# /srv/tftp/grub/grub.cfg (GRUB2)

set timeout=5
set default=0

menuentry "Ubuntu 24.04 Autoinstall" {
    set gfxpayload=keep
    linux /images/ubuntu/24.04/vmlinuz autoinstall ds=nocloud-net;s=http://repo.local/autoinstall/ubuntu/ ip=dhcp
    initrd /images/ubuntu/24.04/initrd.gz
}

menuentry "Debian 12 Preseed" {
    linux /images/debian/12/vmlinuz auto=true priority=critical preseed/url=http://repo.local/preseed/debian-12.cfg
    initrd /images/debian/12/initrd.gz
}

menuentry "SystemRescue (Live)" {
    linux /images/systemrescue/vmlinuz archisobasedocs=sysroot
    initrd /images/systemrescue/initrd.img
}

menuentry "Boot from local disk" {
    exit
}
```

**Важные отличия GRUB2 от PXELINUX:**
- GRUB2 загружает `grub.cfg` из TFTP-пути, указанного в DHCP Option 67
- Поддерживает переменные, условные конструкции и циклы
- Поддерживает Secure Boot через Shim
- Для HTTP Boot: создайте отдельный конфиг с HTTP-путями

## Дополнительная информация

### Диагностика PXE-загрузки

**Команды для проверки TFTP-сервера:**

```bash
# Проверка доступности TFTP-сервера
tftp 192.168.10.5 -c get bios/pxelinux.0  # Клиентский тест
ls -la /srv/tftp/bios/pxelinux.0           # Проверка файла на сервере

# Проверка доступа через netcat
nc -u -z -v 192.168.10.5 69               # Проверка порта UDP/69

# Мониторинг TFTP-соединений в реальном времени
sudo tcpdump -i eth0 port 69 -n -v        # Смотреть DHCP-запросы
sudo tcpdump -i eth0 port 69 -w /tmp/tftp.pcap  # Запись в pcap

# Проверка логов tftpd-hpa
sudo journalctl -u tftpd-hpa -f
sudo tail -f /var/log/syslog | grep tftp
```

**Команды для проверки DHCP:**

```bash
# Тест DHCP-ответа (клиент)
sudo dhclient -v -nw eth0                 # Интерактивный тест
sudo nmap --script broadcast-dhcp-discover -e eth0  # Сканирование DHCP

# Проверка DHCP-клиентов на сервере
sudo dhcpd -t -cf /etc/dhcp/dhcpd.conf   # Валидация конфигурации
sudo dhcp-lease-list                      # Просмотр текущих аренд
sudo journalctl -u dhcpd -f              # Логи ISC DHCP
sudo grep -i pxe /var/lib/dhcp/dhcpd.leases  # PXE-аренды
```

**Команды для проверки сетевой доступности:**

```bash
# Проверка доступности TFTP из подсети клиента
ping 192.168.10.5
traceroute 192.168.10.5

# Проверка firewall на TFTP-сервере
sudo iptables -L -n | grep -E "69|tftp"
sudo nft list ruleset | grep -E "69|tftp"

# Проверка UDP-соединений
sudo ss -ulnp | grep :69
sudo netstat -ulnp | grep :69
```

### Диагностика и решение проблем

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **PXE-E32: TFTP Timeout** | Файрвол или проблемы с MTU | Проверить UDP/69. Уменьшить `blksize` до 512, если сеть нестабильна. |
| **TFTP Error: Access Violation** | Права доступа на файлы | `chmod -R 644 /srv/tftp`. Проверить владельца (обычно `nobody` или `tftp`). |
| **PXE-E51: No DHCP offers** | Проблемы L2 или DHCP Snooping | Проверить `Helper Address` на L3-коммутаторе. Проверить лимиты DHCP-пула. |
| **PXE-E53: No boot filename received** | DHCP не отправляет Option 67 | Проверить `filename` в dhcpd.conf или `dhcp-boot` в dnsmasq. |
| **PXE-E54: Error or outdated boot server configuration** | TFTP-сервер недоступен | Проверить `next-server` (Option 66). Убедиться, что TFTP запущен и слушает UDP/69. |
| **MTU/Fragmentation Issues** | Пакеты TFTP отбрасываются | Отключить `blksize` или настроить `MSS Clamping` на роутере. |
| **Secure Boot Violation** | Неподписанный NBP | Использовать `shim.efi` или добавить хеш загрузчика в базу UEFI (MOK). |
| **UEFI HTTP Boot fails** | Сертификат недоверен или файл не найден | Проверить TLS-сертификат HTTP-сервера. Использовать `curl` для проверки доступности URL. |
| **Загрузка застревает на TFTP** | Проблемы с blksize или фрагментацией | Установить `blksize=512` или проверить MTU на маршрутизаторах. |

### Безопасность PXE

PXE-инфраструктура уязвима к нескольким типам атак:

**1. Rogue DHCP-сервер (MALICIOUS PXE)**
Злоумышленник запускает DHCP-сервер в сети, перенаправляя PXE-клиентов на вредоносный загрузчик.
- **Mitigation:** DHCP Snooping на коммутаторе (ограничение портов, на которых разрешен DHCP-сервер)
- **Mitigation:** Статические DHCP-записи для серверов по MAC-адресу

**2. MITM-атака на TFTP**
Перехват и модификация NBP в процессе загрузки по TFTP (протокол не шифруется).
- **Mitigation:** Использовать iPXE с HTTPS вместо TFTP
- **Mitigation:** Загрузка через UEFI HTTP Boot с проверкой TLS-сертификата
- **Mitigation:** Secure Boot (проверка подписи NBP)

**3. Подмена образов**
Злоумышленник заменяет kernel/initrd на TFTP-сервере.
- **Mitigation:** Регулярная проверка целостности файлов ( checksums)
- **Mitigation:** Загрузка через HTTPS с проверкой подписи
- **Mitigation:** Secure Boot (цепочка доверия до ядра)

**4. DHCP starvation**
Злоумышленник исчерпывает пул IP-адресов DHCP-сервера.
- **Mitigation:** DHCP Snooping + Port Security на коммутаторе
- **Mitigation:** Статические привязки для PXE-серверов

**Best Practices:**
- Используйте изолированную VLAN для PXE-трафика (менеджмент VLAN)
- Включите DHCP Snooping на всех портах, кроме Trunk к DHCP-серверу
- Регулярно обновляйте загрузчики (GRUB2, iPXE) для修补ения уязвимостей
- Используйте Secure Boot в UEFI для проверки подписей NBP и ядра
- Ограничьте доступ к TFTP-серверу через файрвол (только из PXE-подсети)

### Современные решения для Provisioning (2026)

| Решение | Описание | Метод доставки |
| :--- | :--- | :--- |
| **Canonical MAAS** | Превращает дата-центр в "облако" | PXE + iPXE + IPMI/Redfish |
| **Tinkerbell** | Стек от Equinix для K8s-native Bare Metal | PXE + Hook (Docker images) |
| **Red Hat Ironic** | Управление физическими узлами в OpenStack/OpenShift | iPXE / Virtual Media |
| **Netbox + Custom Hooks** | Автоматизация на основе Inventory | API-driven PXE configs |

### PXE в VLAN-среде

В Enterprise-сетях PXE-клиенты часто находятся в отдельных VLAN (Management VLAN, Provisioning VLAN). Ключевые особенности:

**1. DHCP Relay (IP Helper)**
Для работы PXE через VLAN необходимо настроить IP Helper на L3-коммутаторе:
```
interface Vlan100
  ip helper-address 192.168.10.5    # DHCP/PXE сервер
  ip helper-address 192.168.10.6    # Вторичный DHCP (опционально)
```

**2. PXE через Multiple Subnets**
При работе PXE в нескольких подсетях:
- Используйте DHCP Relay на каждом VLAN
- TFTP-сервер должен быть доступен из всех PXE-подсетей
- Рассмотрите размещение TFTP-сервера в Management VLAN с маршрутизацией

**3. Группировка PXE и Provisioning VLAN**
Для изоляции PXE-трафика:
- **VLAN 100:** Management (SSH, DNS, DHCP)
- **VLAN 200:** PXE-загрузка (TFTP, HTTP с образами)
- **VLAN 300:** Provisioning (Ansible, Cloud-init)

### Автоматизация PXE-инфраструктуры

**Пример Ansible-роли для настройки PXE-сервера:**

```yaml
# roles/pxe_server/tasks/main.yml
- name: Установка пакетов для PXE-сервера
  apt:
    name:
      - tftpd-hpa
      - dnsmasq
      - pxelinux
      - syslinux-common
      - grub-efi-amd64-signed
    state: present

- name: Создание структуры каталогов
  file:
    path: "{{ item }}"
    state: directory
    owner: tftp
    group: tftp
    mode: '0755'
  loop:
    - /srv/tftp
    - /srv/tftp/bios
    - /srv/tftp/efi64
    - /srv/tftp/images
    - /srv/tftp/pxelinux.cfg

- name: Копирование PXELINUX загрузчиков
  copy:
    src: "{{ item.src }}"
    dest: "{{ item.dest }}"
    owner: tftp
    group: tftp
  loop:
    - { src: '/usr/lib/PXELINUX/pxelinux.0', dest: '/srv/tftp/bios/' }
    - { src: '/usr/lib/SYSLINUX/menu.c32', dest: '/srv/tftp/bios/' }
    - { src: '/usr/lib/SYSLINUX/ldlinux.c32', dest: '/srv/tftp/bios/' }

- name: Деплой конфигурации PXELINUX
  template:
    src: pxelinux.cfg/default.j2
    dest: /srv/tftp/pxelinux.cfg/default
  notify: restart tftpd-hpa
```

**Пример скрипта для добавления нового хоста в PXE:**

```bash
#!/bin/bash
# add-pxe-host.sh — Добавление PXE-конфигурации для нового хоста

HOSTNAME=$1
MAC=$2
IP=$3
OS=$4  # ubuntu/debian/rhel

if [ -z "$HOSTNAME" ] || [ -z "$MAC" ] || [ -z "$IP" ]; then
    echo "Usage: $0 <hostname> <mac-address> <ip> <os>"
    exit 1
fi

# Нормализация MAC (uppercase, дефисы)
MAC_NORMALIZED=$(echo $MAC | tr '[:lower:]' '[:upper:]' | sed 's/:/-/g')

# Создание конфига по MAC
cat > /srv/tftp/pxelinux.cfg/01-${MAC_NORMALIZED} << EOF
DEFAULT menu.c32
PROMPT 0
TIMEOUT 10

MENU TITLE PXE Boot: ${HOSTNAME}

LABEL install-${OS}
    MENU LABEL Install ${OS^}
    KERNEL images/${OS}/vmlinuz
    APPEND initrd=images/${OS}/initrd.gz preseed/url=http://repo.local/preseed/${HOSTNAME}.cfg ip=${IP}:::255.255.255.0::eth0:off

LABEL local
    MENU LABEL Boot from local disk
    LOCALBOOT 0
EOF

echo "PXE config created: /srv/tftp/pxelinux.cfg/01-${MAC_NORMALIZED}"
```

### См. также
* [Настройка ISC DHCP](../../Linux/Networking/Services/DHCP/isc_dhcp_server_overview.md)
* [Настройка dnsmasq](../../../Networking/Protocols/DNS/dnsmasq.md)
* [DHCP Relay](../../../Networking/Protocols/DHCP/dhcp_relay.md)
* [Процесс загрузки Linux](../../Core/kernel/boot_process.md)
* [BIOS и UEFI](../../Core/firmware_bios_uefi.md)
* [Безопасность DHCP](../../../Networking/Protocols/DHCP/dhcp_security.md)
