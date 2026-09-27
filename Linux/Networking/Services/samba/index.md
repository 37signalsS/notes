# Samba: Обзор

## Определения

**Samba** — программный комплекс с открытым исходным кодом, реализующий протокол **SMB/CIFS**. Позволяет Unix-системам интегрироваться в сети Windows, предоставляя доступ к файлам и принтерам, а также выполняя роли члена домена (Member Server) или контроллера домена (AD DC).

**SMB (Server Message Block)** — сетевой протокол прикладного уровня для совместного использования ресурсов. Актуальный стандарт 2026 года — **SMBv3.1.1**, поддерживающий обязательное шифрование AES-256 и защиту от атак типа MitM.

**SMB Direct (RDMA)** — расширение протокола для передачи данных напрямую между памятью систем, минуя стек TCP/IP и CPU, что критично для 100GbE+ сетей.

**SMB Multichannel** — технология одновременного использования нескольких сетевых соединений для увеличения пропускной способности и обеспечения отказоустойчивости.

**CIFS (Common Internet File System)** — устаревший диалект SMBv1. Использование CIFS в современных сетях запрещено из-за критических уязвимостей (EternalBlue).

**Discovery Services (WSD/mDNS)** — современные механизмы обнаружения ресурсов, заменившие NetBIOS. **WSD (Web Services for Devices)** является стандартом для Windows 10/11.

**smb.conf** — центральный конфигурационный файл Samba (`/etc/samba/smb.conf`). Управляет глобальными настройками демона и параметрами отдельных сетевых ресурсов (шар).

**Шара (share)** — логический ресурс (директория или принтер), экспортируемый сервером для сетевого доступа. Каждая шара настраивается индивидуально в контексте прав доступа и производительности.

**VFS (Virtual File System) modules** — расширяемые модули Samba, подключаемые к сетевым ресурсам (шарам) для добавления функциональности: аудит, корзина, снапшоты, антивирусная проверка. Указываются в директиве `vfs objects`.

**Zero Trust SMB** — архитектурный подход, требующий обязательного шифрования (`smb encrypt = required`), сильной аутентификации (Kerberos) и строгой изоляции сервиса.

## Базовые концепции

### Архитектура Samba

| Демон / Служба | Назначение |
| :--- | :--- |
| **`smbd`** | Основной демон: файловые ресурсы (Shares), аутентификация, блокировки. |
| **`nmbd`** | Разрешение имён NetBIOS (legacy, обычно отключается в AD-средах). |
| **`winbindd`** | Интеграция с Active Directory, маппинг SID ↔ UID/GID, SSO. |
| **`wsdd` / `avahi`** | (Внешние) Обеспечивают видимость сервера в сетевом окружении Windows/macOS. |
| **`samba`** | Мастер-демон для режима Active Directory Domain Controller (AD DC). |

### Режимы работы

| Режим | Параметр `security` | Описание |
| :--- | :--- | :--- |
| **Standalone** | `user` | Локальная аутентификация. Идеально для изолированных файловых серверов. |
| **Domain Member** | `ads` | Linux-сервер как член домена Windows. Требует Kerberos и Winbind/SSSD. |
| **Domain Controller** | `ads` | Samba работает как AD DC, управляя пользователями, группами и GPO. |

### Версии SMB и безопасность (Стандарты 2026)

| Версия | Статус | Безопасность и возможности |
| :--- | :--- | :--- |
| **SMBv1** | **Запрещён** | Небезопасен. Должен быть принудительно отключен. |
| **SMBv3.0** | Допустима | Шифрование AES-128-CCM, поддержка кластеров. |
| **SMBv3.1.1** | **Рекомендуется** | Шифрование AES-256-GCM, защита от downgrade-атак. |

> **Конфигурация безопасности 2026:**
> ```ini
> server min protocol = SMB3_11
> server smb encrypt = required
> ntlm auth = ntlmv2-only
> ```

### Процесс согласования SMB (Negotiation)

При установке соединения клиент и сервер выполняют Negotiate Protocol:
1. **SMB2_NEGOTIATE** — клиент отправляет список поддерживаемых диалектов.
2. **SMB2_NEGOTIATE Response** — сервер выбирает максимальный общий диалект.
3. **SMB2_SESSION_SETUP** — аутентификация (Kerberos или NTLM).
4. **SMB2_TREE_CONNECT** — подключение к конкретной шаре.

В SMBv3.1.1 добавлен параметр `EncryptionCapabilities`, принудительно требующий совпадение алгоритмов шифрования.

### Подпись и целостность пакетов

SMB signing обеспечивает защиту от MitM-атак путем добавления HMAC-SHA256 к каждому пакету. В SMBv3.1.1 подпись является обязательной для всех соединений, что исключает возможность downgrade-атак.

## Практические сценарии

### 1. Корпоративное файловое хранилище

Замена Windows File Server с полной поддержкой ACL и интеграцией в Active Directory. В 2026 году акцент делается на использовании **SMB Multichannel** для агрегации линков без LACP на стороне коммутатора.

**Требования:**
- Сервер с двумя и более NIC 10GbE+
- Конфигурация `server multi channel = yes`
- Отключение `nmbd` (не требуется в AD-средах)

### 2. Отказоустойчивый кластер (Scale-Out File Server)

Использование **CTDB** (Cluster Trivial Database) поверх распределенных ФС (CephFS, GlusterFS) для создания единого пространства имен с высокой доступностью. Поддержка **Witness Protocol** позволяет клиентам мгновенно переключаться на другой узел кластера при сбое.

**Примечание:** CTDB требует общих хранилищ (LUN) или распределенных ФС с синхронизацией метаданных.

### 3. Оптимизация для рабочих станций Apple

Использование VFS-модуля `fruit` для поддержки специфических метаданных macOS и ускорения поиска через интеграцию со Spotlight (через Elasticsearch или Tracker).

### 4. Гибридное облако (On-Premises кэш)

Синхронизация локальных шар с удаленными хранилищами с использованием Samba в качестве локального кэширующего прокси для минимизации задержек при работе с данными.

### 5. Высокопроизводительное хранилище (High-Perf)

Настройка для максимальной пропускной способности в 10GbE+ сетях с использованием SSD/NVMe.

```ini
[global]
   workgroup = WORKGROUP
   security = user
   server min protocol = SMB3_11
   server smb encrypt = required

   # Тюнинг производительности 2026
   aio read size = 1
   aio write size = 1
   server multi channel = yes
   use sendfile = yes
   min receivefile size = 16384

   # Оптимизация сетевого стека
   socket options = TCP_NODELAY IPTOS_LOWDELAY SO_RCVBUF=131072 SO_SNDBUF=131072

[FastData]
   path = /data/production
   comment = NVMe Optimized Storage
   valid users = @sysadmins
   writable = yes
   browsable = yes
   vfs objects = streams_xattr
```

### 6. Изолированная шара с гостевым доступом

Применяется для публичных архивов внутри доверенного периметра.

```ini
[global]
   map to guest = bad user

[PublicArchive]
   path = /srv/samba/public
   guest ok = yes
   read only = yes
   browsable = yes
   public = yes
```

### 7. Резервное копирование Time Machine (Apple)

Использование Samba в качестве цели для бэкапов macOS.

```ini
[TimeMachine]
   path = /backups/timemachine
   valid users = macuser
   writable = yes
   vfs objects = fruit streams_xattr
   fruit:time machine = yes
   fruit:aapl = yes
   fruit:metadata = stream
   fruit:model = MacSamba
```

## Структура конфигурации smb.conf

| Секция | Назначение |
| :--- | :--- |
| `[global]` | Основные настройки: роль сервера, безопасность, сетевые параметры, логирование. |
| `[homes]` | Динамическое создание персональных шар на основе домашних директорий пользователей Linux. |
| `[printers]` | Настройка общего доступа к очередям печати (CUPS). |
| `[имя_шары]` | Пользовательская конфигурация конкретного ресурса. |

### Ключевые параметры глобальной секции

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `server min protocol` | Минимальная версия протокола. | `SMB3_11` (защита от атак) |
| `server smb encrypt` | Обязательное шифрование трафика. | `required` |
| `aio read size` | Порог асинхронного чтения. | `1` (всегда асинхронно для SSD) |
| `aio write size` | Порог асинхронной записи. | `1` (всегда асинхронно для SSD) |
| `server multi channel` | Включение Multichannel. | `yes` |
| `map to guest` | Обработка неизвестных пользователей. | `Never` (безопасность) |

## Установка и базовая настройка

### Инсталляция компонентов

```bash
# Debian / Ubuntu / Mint
sudo apt update && sudo apt install -y samba samba-common-bin smbclient

# RHEL / Rocky / AlmaLinux / Fedora
sudo dnf install -y samba samba-common samba-client
```

### Верификация конфигурации

Перед каждым перезапуском сервиса необходимо проверять синтаксис файла:

```bash
testparm -s
# → Load smb config files from /etc/samba/smb.conf
# → Loaded services file OK.
```

### Управление службами

Samba состоит из двух основных демонов, но в современных сетях (SMBv2/v3) `smbd` является самодостаточным.

```bash
# Основной демон (SMB/CIFS)
sudo systemctl enable --now smbd

# Демон имен (NetBIOS) - отключать, если не нужны старые Windows XP/7
sudo systemctl disable --now nmbd

# Проверка активных подключений
smbstatus
```

### Управление доступом (Linux vs SMB)

Для корректной работы необходимо соблюдение двух уровней разрешений:

1. **Права ФС (Linux):** У пользователя/группы должны быть права на уровне ядра (`chmod`, `chown`).
2. **Права Samba:** Ограничения в `smb.conf` (`valid users`, `read only`).

**Пример создания пользователя:**
```bash
# Создание системного пользователя без оболочки
sudo useradd -M -s /usr/sbin/nologin smbuser
# Добавление пользователя в базу Samba
sudo smbpasswd -a smbuser
```

## Производительность и тюнинг

- **Asynchronous I/O (AIO):** в 2026 году `aio read size = 1` и `aio write size = 1` являются стандартом для SSD/NVMe, позволяя избежать блокировок процесса `smbd`.
- **SMB Direct (RDMA):** требует поддержки со стороны NIC (RoCE или iWARP). Значительно снижает latency.
- **Kernel Oplocks:** должны быть включены для эффективного кэширования на стороне клиента.
- **sendfile:** `use sendfile = yes` позволяет передавать данные напрямую из кэша страниц ядра в сетевой стек, минуя пользовательское пространство.
- **Socket Options:** `TCP_NODELAY` и увеличенные `SO_RCVBUF`/`SO_SNDBUF` снижают латентность на 10GbE+.

## Виртуальная файловая система (VFS)

VFS-модули расширяют функциональность без изменения ядра Samba. Порядок вызова модулей — справа налево в цепочке `vfs objects`.

| Модуль | Назначение |
| :--- | :--- |
| **`fruit`** | Максимальная совместимость с macOS (метаданные, Time Machine). |
| **`shadow_copy2`** | Реализация «Предыдущих версий» на базе снапшотов ФС. |
| **`recycle`** | Сетевая корзина для удаленных файлов. |
| **`full_audit`** | Детальный аудит операций (соответствие требованиям комплаенса). |
| **`glusterfs` / `ceph`** | Прямой доступ к распределенным ФС в обход ядерного монтирования. |
| **`acl_xattr`** | Хранение NTFS ACL в расширенных атрибутах. |
| **`virusfilter`** | Антивирусная проверка через ClamAV/Sophos. |

## Порты и диагностика

| Порт | Назначение |
| :--- | :--- |
| **445/TCP** | Основной порт SMB (рекомендуется ограничить только доверенными сетями). |
| **137-139** | Legacy NetBIOS (рекомендуется закрывать/отключать). |
| **5357/TCP** | WSD (Web Services Discovery) — для видимости в сети. |

### Ключевые утилиты

- `testparm` — проверка синтаксиса `smb.conf`.
- `smbstatus` — мониторинг сессий и блокировок файлов.
- `smbclient` — отладка доступа с клиента.
- `wbinfo` / `getent` — проверка маппинга пользователей AD.

### Диагностика подключения

```bash
# Проверка доступности шар с локальной или удаленной машины
smbclient -L //127.0.0.1 -U smbuser
# → Sharename       Type      Comment
# → ---------       ----      -------
# → FastData        Disk      NVMe Optimized Storage
```

### Диагностика сессий и шифрования

```bash
# Просмотр статуса шифрования текущих сессий
smbstatus -v
# → Encryption: AES-256-GCM (Active)
```

### Анализ трафика

```bash
# Захват SMB трафика без полезной нагрузки (только заголовки)
sudo tcpdump -i eth0 port 445 -s 128 -w smb_debug.pcap
```

### Проверка целостности баз данных

```bash
# Проверка базы secrets
sudo tdbtool /var/lib/samba/private/secrets.tdb check
```

## Мониторинг и observability

### Мониторинг для SRE

- **SMB Multichannel:** `smbstatus -S` — проверка использования нескольких соединений клиентом.
- **Активные сессии:** `smbstatus` — мониторинг в реальном времени.
- **Логи:** `journalctl -t smbd -t nmbd -t winbindd -p err..emerg`
- **Производительность диска:** `iostat -x 1` (Queue Depth, await).

### Интеграция с системами мониторинга

Samba не имеет встроенного экспортера метрик для Prometheus. Используйте:
- **node_exporter** для системных метрик (текстовые файлы с метриками).
- **smbclient** в скриптах для проверки доступности шар.
- **Zabbix Agent** с пользовательскими проверками (`system.run`).

### Уровни логирования

| Уровень | Назначение |
| :--- | :--- |
| `log level = 1` | Стандартный, минимальный объем. |
| `log level = 3` | Средняя детализация, ошибки протокола. |
| `log level = 10` | Максимальная отладка, включает дампы пакетов — **опасно** для производительности. |

## Документация раздела

- [Настройка сервера](./samba_setup.md) — базовые и продвинутые конфигурации.
- [Безопасность и VFS](./samba_security.md) — hardening и модульное расширение.
- [Интеграция с AD](./samba_ad.md) — работа в доменах и маппинг ID.
- [Устранение неполадок](./samba_troubleshooting.md) — решение типовых проблем.
- [Кластеризация (CTDB)](./samba_cluster.md) — высокая доступность и failover.
- [Мониторинг](./samba_monitoring.md) — Prometheus, Grafana, Loki, алертинг.
- [Автоматизация (Ansible)](./samba_automation.md) — IaC и плейбуки.
- [Резервное копирование](./samba_backup.md) — rsync, borgbackup, LVM-снапшоты.
- [SIEM и комплаенс](./samba_siem.md) — аудит, Wazuh, ELK, Sigma-правила.
- [Group Policy (GPO)](./samba_gpo.md) — управление политиками в AD.

## См. также

- [NFS: Сетевая ФС для Unix](../nfs/index.md)
- [Протокол Kerberos](../../../../Security/Concepts/kerberos.md)
- [Монтирование SMB в Linux](../../../FileSystems/mounting/index.md)
- [SELinux: Механизмы безопасности](../../../Security/Mechanisms/SELinux.md)
- [TCP Tuning](../../../Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — оптимизация для SMB-трафика
- [fio: Бенчмаркинг](../../../Diagnostics/Filesystem/fio.md) — тестирование дисковой подсистемы
- [rsync: Основы](../../../SystemAdministration/rsync.md) — синхронизация файлов
- [borgbackup: Обзор](../../../SystemAdministration/backup_and_recovery.md) — дедупликация и шифрование
- [Wazuh: SIEM](../../../../Security/Tools/wazuh.md) — платформа безопасности
- [Ansible: Роли](../../../../Ansible/ansible_roles.md) — структура автоматизации
