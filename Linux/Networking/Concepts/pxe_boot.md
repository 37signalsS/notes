# PXE: Загрузка по сети

## Определения

**PXE (Preboot Execution Environment — среда исполнения перед загрузкой)** — это стандартная среда, позволяющая компьютеру загружаться по сети, используя только свою сетевую карту (NIC), без необходимости в локальном загрузочном устройстве (жестком диске, USB-накопителе).

**NBP (Network Boot Program — программа сетевой загрузки)** — небольшой исполняемый файл (например, `pxelinux.0` или `ipxe.efi`), который скачивается клиентом по сети и управляет дальнейшим процессом загрузки ОС.

**HTTP Boot** — современное расширение спецификации UEFI, позволяющее загружать NBP или ядро ОС напрямую по протоколам HTTP/HTTPS вместо медленного и ненадежного TFTP.

## Базовые концепции

PXE является стандартом де-факто для автоматизированного развертывания серверов (Bare Metal Provisioning), работы бездисковых станций (VDI) и систем аварийного восстановления.

### Компоненты PXE-инфраструктуры

1.  **Клиент:** Устройство с сетевой картой, поддерживающей стек PXE (в ПЗУ карты или в прошивке UEFI).
2.  **DHCP-сервер:** Выдает клиенту временный IP-адрес и передает параметры загрузки:
    *   `next-server` (Option 66): IP-адрес сервера загрузки.
    *   `filename` (Option 67): Имя загрузочного файла.
3.  **TFTP-сервер:** Предоставляет загрузчик (NBP) по упрощенному протоколу UDP. В современных сетях TFTP используется только для доставки первичного загрузчика (iPXE/GRUB), который затем переходит на HTTP.
4.  **Файловый сервер (HTTP/NFS):** Хранит тяжелые компоненты: ядро Linux (`vmlinuz`), `initramfs`, файлы инсталлятора или корневую файлорую систему (`rootfs`).

### Процесс загрузки (Legacy vs UEFI)

| Этап | Legacy (BIOS) | UEFI |
| :--- | :--- | :--- |
| **Инициализация** | 16-битный стек PXE | 32/64-битный EFI Network Stack |
| **DHCP Запрос** | Обычный DHCP Discover | DHCP Discover с указанием Architecture Type (Option 93) |
| **Получение NBP** | Скачивает `pxelinux.0` через TFTP | Скачивает `.efi` файл (через TFTP или HTTP Boot) |
| **Режим CPU** | Реальный режим (1 МБ памяти) | Защищенный режим (доступ ко всей памяти) |
| **Безопасность** | Отсутствует | Поддержка Secure Boot (подпись загрузчика) |

#### Детальный механизм DORA-загрузки:
1.  **Discover:** Клиент рассылает широковещательный запрос.
2.  **Offer:** DHCP-сервер предлагает IP и указывает `next-server`.
3.  **Request:** Клиент запрашивает предложенные параметры.
4.  **Acknowledge:** Сервер подтверждает аренду и передает `filename` (путь к NBP).
5.  **Transfer:** Клиент обращается к TFTP-серверу за файлом NBP.

Подробнее о [процессе загрузки Linux](../../Core/kernel/boot_process.md).

## Практические сценарии

### 1. Настройка сетевой загрузки в прошивке

*   **BIOS:** Включить `LAN Option ROM` или `Network Stack`. Установить `Network/PXE` первым в `Boot Priority`.
*   **UEFI:** Включить `Network Stack`, выбрать режим `IPv4 PXE Support` или `IPv6 PXE Support`. Для использования **HTTP Boot** необходимо выбрать соответствующий тип загрузки в меню BIOS (доступно в UEFI 2.5+).

### 2. Настройка DHCP для PXE (Dnsmasq)

`dnsmasq` — наиболее удобный инструмент для малых и средних сред, совмещающий DHCP, TFTP и DNS.

```bash
# /etc/dnsmasq.conf
interface=eth0
dhcp-range=192.168.1.50,192.168.1.150,255.255.255.0,12h

# Параметры для PXE
enable-tftp
tftp-root=/srv/tftp

# Определение типа клиента (Option 93)
dhcp-match=set:efi64,option:client-arch,7
dhcp-match=set:efi64,option:client-arch,9
dhcp-match=set:bios,option:client-arch,0

# Выдача разных загрузчиков в зависимости от архитектуры
dhcp-boot=tag:bios,pxelinux.0
dhcp-boot=tag:efi64,ipxe.efi
```

### 3. Развертывание iPXE: Продвинутая загрузка

**iPXE** — это open-source реализация PXE, которая позволяет обходить ограничения классического PXE (медленный TFTP, отсутствие скриптов).

**Преимущества iPXE:**
*   Загрузка через **HTTP/HTTPS** (в 10-50 раз быстрее TFTP).
*   Загрузка через **iSCSI**, **NFS**, **Fibre Channel**.
*   Поддержка скриптов для меню выбора ОС.

**Пример скрипта iPXE (`boot.ipxe`):**
```ipxe
#!ipxe
dhcp
set server_ip 192.168.1.10
set base-url http://${server_ip}/os

menu Choose Operating System
item ubuntu_24_04 Install Ubuntu 24.04 LTS
item rescue       System Rescue
choose --default ubuntu_24_04 --timeout 5000 target || goto cancel

:ubuntu_24_04
kernel ${base-url}/ubuntu/vmlinuz initrd=initrd.gz cloud-config-url=${base-url}/configs/user-data ip=dhcp
initrd ${base-url}/ubuntu/initrd.gz
boot

:rescue
kernel ${base-url}/rescue/vmlinuz
initrd ${base-url}/rescue/initrd.img
boot
```

## Дополнительная информация

### Диагностика и решение проблем

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **PXE-E32: TFTP Timeout** | TFTP сервер недоступен или заблокирован файрволом | Проверить UDP порт 69. Проверить `tftp-root`. |
| **PXE-E51: No DHCP offers** | Клиент не видит DHCP-сервер или пул адресов пуст | Проверить L2-связность. Включить [DHCP Snooping](../../../Networking/Protocols/DHCP/dhcp_security.md#dhcp-snooping---отслеживание-dhcp) на коммутаторе. |
| **PXE-E53: No boot filename** | DHCP-сервер выдал IP, но не передал Option 67 | Проверить конфиг DHCP на наличие параметра `filename`. |
| **UEFI: Secure Boot Violation** | Загрузчик (`ipxe.efi`) не подписан | Отключить Secure Boot или использовать подписанный загрузчик `shim.efi`. |

### Современные решения для Provisioning (2026)

| Решение | Описание | Основной метод |
| :--- | :--- | :--- |
| **Netbox + Netbox-Provisioning** | Автоматизация на основе данных из IPAM/DCIM | iPXE API |
| **Tinkerbell (Equinix)** | Cloud-native Provisioning через Kubernetes | PXE + Hook (Docker images) |
| **Canonical MAAS** | Управление физическими серверами как облаком | PXE + DHCP + IPMI |
| **Red Hat Ironic** | Компонент OpenStack для Bare Metal | iPXE / Virtual Media |

### См. также
* [Настройка DHCP-сервера](../Services/DHCP/isc_dhcp_server_overview.md)
* [Процесс загрузки Linux](../../Core/kernel/boot_process.md)
* [BIOS и UEFI](../../Core/firmware_bios_uefi.md)
* [Безопасность DHCP](../../../Networking/Protocols/DHCP/dhcp_security.md)
