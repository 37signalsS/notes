# PXE: Загрузка по сети

## Определения

**PXE (Preboot Execution Environment — среда исполнения перед загрузкой)** — стандартная среда, позволяющая компьютеру загружаться по сети, используя только сетевую карту (NIC), без необходимости в локальном загрузочном устройстве (HDD/SSD/USB).

**NBP (Network Boot Program)** — исполняемый файл (например, `pxelinux.0`, `ipxe.efi`, `grubx64.efi`), который скачивается клиентом по сети и управляет дальнейшим процессом загрузки ОС или инсталлятора.

**ProxyDHCP** — расширение PXE, позволяющее развернуть PXE-инфраструктуру без модификации основного DHCP-сервера (например, если он управляется другим отделом). ProxyDHCP отвечает только на PXE-запросы, предоставляя параметры загрузки, в то время как основной DHCP выдает IP-адреса.

**Virtual Media (Redfish/IPMI)** — современная альтернатива PXE, позволяющая монтировать ISO-образы напрямую через контроллер управления (BMC) по протоколам HTTP/NFS/Samba.

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
| **Инициализация** | 16-битный PXE Stack | 32/64-битный EFI Network Stack |
| **DHCP Запрос** | Обычный DHCP Discover | DHCP Discover + Architecture Type (Option 93) |
| **Протоколы** | Только TFTP | TFTP, HTTP, HTTPS (HTTP Boot) |
| **Режим CPU** | Реальный режим (1 МБ) | Защищенный режим (Long Mode) |
| **Безопасность** | Отсутствует | Secure Boot (цепочка доверия) |

#### UEFI Secure Boot Chain
Для загрузки в режиме Secure Boot используется **Shim** — легковесный загрузчик, подписанный ключом Microsoft.
1. `UEFI Firmware` (проверяет подпись `shim.efi`).
2. `Shim` (проверяет подпись `grubx64.efi` или `ipxe.efi` ключом дистрибутива или владельца).
3. `GRUB/iPXE` (загружает ядро).
4. `Kernel` (должен быть подписан).

### PXE в сетях IPv6 (DHCPv6)
В IPv6 процесс отличается отсутствием широковещательных рассылок (используется Multicast):
*   Клиент отправляет `Solicit` с запросом опции 59 (`OPT_BOOTFILE_URL`).
*   Сервер отвечает `Advertise`, предоставляя URL (например, `tftp://[2001:db8::1]/ipxe.efi` или `http://[2001:db8::1]/boot.efi`).

Подробнее о [процессе загрузки Linux](../../Core/kernel/boot_process.md).

## Практические сценарии

### 1. Настройка DHCP для PXE (Dnsmasq)

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

### 2. Сценарий ProxyDHCP
Позволяет добавить PXE в существующую сеть без доступа к основному DHCP-серверу (например, Windows DHCP или роутер провайдера).

```bash
# Настройка dnsmasq в режиме Proxy
dhcp-range=192.168.1.0,proxy
pxe-service=x86PC, "Boot from Network (Legacy)", bios/pxelinux
pxe-service=x86-64_EFI, "Boot from Network (UEFI)", efi64/ipxe.efi
```

### 3. Продвинутая загрузка через iPXE (HTTP)
iPXE позволяет загружать образы по HTTP/HTTPS, что критично для облачных сред и медленных каналов.

**Пример скрипта `boot.ipxe` с использованием облачного конфига:**
```ipxe
#!ipxe
dhcp
set base-url http://repo.local/os/ubuntu/24.04

# Загрузка ядра с параметрами автоустановки (Cloud-Init)
kernel ${base-url}/vmlinuz initrd=initrd.gz autoinstall ds=nocloud-net;s=http://cfg.local/nodes/${mac:hex}/ ip=dhcp
initrd ${base-url}/initrd.gz
boot
```

## Дополнительная информация

### Диагностика и решение проблем

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **PXE-E32: TFTP Timeout** | Файрвол или проблемы с MTU | Проверить UDP/69. Уменьшить `blksize` до 512, если сеть нестабильна. |
| **TFTP Error: Access Violation** | Права доступа на файлы | `chmod -R 644 /srv/tftp`. Проверить владельца (обычно `nobody` или `tftp`). |
| **PXE-E51: No DHCP offers** | Проблемы L2 или DHCP Snooping | Проверить `Helper Address` на L3-коммутаторе. Проверить лимиты DHCP-пула. |
| **MTU/Fragmentation Issues** | Пакеты TFTP отбрасываются | Отключить `blksize` или настроить `MSS Clamping` на роутере. |
| **Secure Boot Violation** | Неподписанный NBP | Использовать `shim.efi` или добавить хеш загрузчика в базу UEFI (MOK). |

### Современные решения для Provisioning (2026)

| Решение | Описание | Метод доставки |
| :--- | :--- | :--- |
| **Canonical MAAS** | Превращает дата-центр в "облако" | PXE + iPXE + IPMI/Redfish |
| **Tinkerbell** | Стек от Equinix для K8s-native Bare Metal | PXE + Hook (Docker images) |
| **Red Hat Ironic** | Управление физическими узлами в OpenStack/OpenShift | iPXE / Virtual Media |
| **Netbox + Custom Hooks** | Автоматизация на основе Inventory | API-driven PXE configs |

### См. также
* [Настройка DHCP-сервера](../Services/DHCP/isc_dhcp_server_overview.md)
* [Процесс загрузки Linux](../../Core/kernel/boot_process.md)
* [BIOS и UEFI](../../Core/firmware_bios_uefi.md)
* [Безопасность DHCP](../../../Networking/Protocols/DHCP/dhcp_security.md)
