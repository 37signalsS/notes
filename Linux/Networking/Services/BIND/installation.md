# Установка DNS-сервера BIND

---

## Определения

**BIND9 (Berkeley Internet Name Domain version 9)** — наиболее распространённая реализация **DNS (Domain Name System — система доменных имён)** сервера, обеспечивающая гибкость, масштабируемость и поддержку современных стандартов безопасности. Разрабатывается и поддерживается организацией **ISC (Internet Systems Consortium)**.

**named (Name Daemon)** — системная служба (демон), реализующая функциональность BIND. В дистрибутивах семейства **Debian/Ubuntu** служба называется `bind9`, в **RHEL/CentOS/Fedora** — `named`.

**dnsutils / bind9-host** — пакеты диагностических утилит (`dig`, `nslookup`, `host`), необходимых для проверки работы DNS-серверов и отладки разрешения имён.

**bind9utils / bind-utils** — пакеты служебных утилит управления (`rndc`, `named-checkconf`, `named-checkzone`, `named-compilezone`), используемых для валидации конфигурации и управления запущенным демоном.

**bind9-doc** — пакет с локальной документацией в формате HTML и PDF, включающей man-страницы и справочные материалы по конфигурации.

**python3-bind** — библиотеки Python для программного взаимодействия с BIND через RNDC или DNS-запросы.

**Актуальность:** инструкции применимы для версий BIND 9.18+ **LTS (Long Term Support)** и 9.20+ **ESV (Extended Support Version)**.

---

## Основные концепции

### Предварительные проверки перед установкой

Перед развёртыванием BIND убедитесь, что среда подготовлена:

1.  **Порт 53 свободен:** BIND требует монопольного доступа к UDP/TCP порту 53. В современных дистрибутивах по умолчанию запущен `systemd-resolved`, который занимает порт `53/udp` на адресе `127.0.0.53`.
    ```bash
    sudo ss -ulnp | grep :53
    # → если видите systemd-resolved или другой процесс — требуется отключение
    ```

2.  **Установлен NTP-клиент:** Для корректной работы DNSSEC, TSIG и репликации Slave-серверов критически важна синхронизация времени. Установите `chrony` или `ntp` до или сразу после BIND.
    ```bash
    # Debian/Ubuntu
    sudo apt install -y chrony

    # RHEL/CentOS/Fedora
    sudo dnf install -y chrony
    ```

3.  **Проверка существующей установки:** Если BIND уже был развёрнут ранее, удалите устаревшие пакеты для чистого контекста:
    ```bash
    # Debian/Ubuntu
    sudo apt purge -y bind9 bind9utils dnsutils

    # RHEL/CentOS/Fedora
    sudo dnf remove -y bind bind-utils
    ```

### Состав пакетов и репозитории

При установке BIND в различных дистрибутивах используются разные именования пакетов. Основной демон всегда — `named`.

| Пакет | Назначение | Содержимое |
| :--- | :--- | :--- |
| **`bind9` / `bind`** | Основной демон DNS-сервера (`named`), утилита управления `rndc`, инструменты валидации (`named-checkconf`, `named-checkzone`, `named-compilezone`), библиотеки. | Демон, RNDC, утилиты проверки. |
| **`bind9utils` / `bind-utils`** | Утилиты для управления и проверки конфигурации. | `rndc`, `named-checkconf`, `named-checkzone`, `named-compilezone`. |
| **`dnsutils` / `bind-utils`** | Клиентские утилиты для диагностики. | `dig`, `nslookup`, `host`. |
| **`bind9-doc`** | Локальная документация в формате HTML и PDF. | Man-страницы, руководства. |
| **`python3-bind`** | Библиотеки Python для программного взаимодействия с BIND. | Python-модули для RNDC и DNS. |

### Конфликты с локальными резолверами

В современных дистрибутивах (Ubuntu 18.04+, Debian 10+, RHEL 8+) по умолчанию запущен `systemd-resolved`, который занимает порт `53/udp` на адресе `127.0.0.53`. Для корректной работы BIND как полноценного сервера необходимо отключить `systemd-resolved` и переконфигурировать `/etc/resolv.conf`.

**Техническая причина конфликта:** `systemd-resolved` создает stub-зона на `127.0.0.53:53` и перехватывает все DNS-запросы через NSS (Name Service Switch). BIND не может привязаться к порту 53, пока stub активен.

### Структура директорий и файлов

#### Debian / Ubuntu

| Путь | Назначение |
| :--- | :--- |
| `/etc/bind/named.conf` | Главный файл конфигурации (корневой include). |
| `/etc/bind/named.conf.options` | Глобальные опции: ACL, форвардеры, параметры безопасности, прослушиваемые порты. |
| `/etc/bind/named.conf.local` | Объявление пользовательских зон (Master/Slave) и Views. |
| `/etc/bind/named.conf.default-zones` | Стандартные зоны (root-серверы, localhost, широковещательные адреса). |
| `/etc/bind/zones/` | Стандартная директория для хранения файлов описания зон (zone files). |
| `/var/cache/bind/` | Директория для кэша, сессий и временных данных. |
| `/var/lib/bind/` | Директория для динамически обновляемых зон и журналов (journal). |
| `/var/log/bind/` | Стандартная директория для логов (при настройке кастомного логирования). |

#### RHEL / CentOS / Fedora

| Путь | Назначение |
| :--- | :--- |
| `/etc/named.conf` | Главный файл конфигурации (часто объединён в один файл). |
| `/etc/named.rfc1912.zones` | Стандартные зоны (localhost, широковещательные адреса). |
| `/etc/named.iscdlv.key` | Ключ для управления через RNDC (автоматически создаётся при установке в новых версиях). |
| `/var/named/` | Директория для файлов зон (Master/Slave). |
| `/var/named/data/` | Директория для сессий, кэша, статистики. |
| `/var/named/dynamic/` | Директория для динамически обновляемых зон и журналов (journal). |
| `/var/log/messages` | Системный журнал (по умолчанию, через journalctl). |

### Пользователь и группа

BIND запускается под непривилегированным пользователем `named` (RHEL-family) или `bind` (Debian/Ubuntu). Это ограничивает ущерб при возможных уязвимостях в демоне. При настройке прав на файлы зон используйте соответствующего пользователя:

```bash
# Debian/Ubuntu
sudo chown -R bind:bind /etc/bind/zones

# RHEL/CentOS/Fedora
sudo chown -R named:named /var/named
```

---

## Практические сценарии

### Установка в Debian / Ubuntu

1.  **Обновление кэша пакетов:**
    ```bash
    sudo apt-get update
    # → Hit:1 http://deb.debian.org/debian bookworm InRelease
    ```

2.  **Установка пакетов:**
    ```bash
    sudo apt-get install -y bind9 bind9utils dnsutils
    # → success
    ```

3.  **Устранение конфликта с systemd-resolved:**
    ```bash
    # Остановка и отключение службы
    sudo systemctl stop systemd-resolved
    sudo systemctl disable systemd-resolved

    # Замена символической ссылки на реальный файл (если требуется)
    sudo rm /etc/resolv.conf
    echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf
    # → success
    ```

4.  **Запуск и активация:**
    ```bash
    sudo systemctl enable --now bind9
    # → active (running)
    ```

### Установка в дистрибутивах семейства RHEL (Red Hat Enterprise Linux)

Инструкция актуальна для **RHEL, Rocky Linux, AlmaLinux и Fedora**.

1.  **Установка через DNF:**
    ```bash
    sudo dnf install -y bind bind-utils
    # → success
    ```

2.  **Генерация ключа rndc (RHEL-specific):**
    В отличие от Debian/Ubuntu, где ключ создаётся автоматически, в RHEL-family требуется ручное создание:
    ```bash
    # Создание ключевого файла
    sudo rndc-confgen -a -k /etc/rndc.key
    # → /etc/rndc.key

    # Проверка подключения
    sudo rndc status
    # → version: 9.18.x ...
    ```

3.  **Настройка SELinux:**
    Для Master-серверов необходимо разрешить запись в директории зон:
    ```bash
    sudo setsebool -P named_write_master_zones 1
    # → success
    ```

    Проверка контекстов файлов:
    ```bash
    ls -Z /var/named
    # → system_u:object_r:named_zone_t:s0 db.example.com
    ```

4.  **Запуск службы:**
    ```bash
    sudo systemctl enable --now named
    # → active (running)
    ```

### Установка в Alpine Linux (Docker/Минимализм)

```bash
apk add bind bind-utils
# Создание конфигурации по умолчанию, если отсутствует
rc-update add named
rc-service named start
# → [ok]
```

### Развёртывание в Docker

Для быстрой изоляции и тестирования можно использовать официальный образ. Монтируйте конфигурацию и файлы зон для сохранности данных:

```bash
docker run -d \
  --name bind9 \
  -p 53:53/udp \
  -p 53:53/tcp \
  -v /path/to/named.conf.options:/etc/bind/named.conf.options:ro \
  -v /path/to/zones:/etc/bind/zones:ro \
  internetsystemsconsortium/bind9:9.18
# → [container_id]
```

---

## Проверка работоспособности

### 1. Проверка версии и сборки
```bash
named -v
# → BIND 9.18.28-1~deb12u1-Debian (Extended Support Version) <id:5e6e76c>
```

### 2. Проверка прослушиваемых портов
Убедитесь, что `named` слушает порт 53 на нужных интерфейсах.
```bash
sudo ss -tulpn | grep :53
# → udp UNCONN 0 0 127.0.0.1:53 0.0.0.0:* users:(("named",pid=1234,fd=20))
# → tcp LISTEN 0 10 127.0.0.1:53 0.0.0.0:* users:(("named",pid=1234,fd=21))
```

### 3. Проверка синтаксиса конфигурации
Утилита проверяет основной файл и все вложенные (`include`).
```bash
sudo named-checkconf /etc/bind/named.conf
# → (no output means success)
```

### 4. Проверка состояния службы
```bash
# Debian/Ubuntu
sudo systemctl status bind9

# RHEL/CentOS/Fedora
sudo systemctl status named
```

### 5. Проверка логирования
```bash
# Просмотр логов в реальном времени
sudo journalctl -u bind9 -f
# → named[1234]: starting BIND 9.18.28 ...
```

### 6. Тестовый запрос
Выполните запрос к самому себе, чтобы убедиться в ответе сервера.
```bash
dig @127.0.0.1 localhost
# → ;; ANSWER SECTION:
# → localhost. 604800 IN A 127.0.0.1
```

---

## Типичные проблемы при установке

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **`bind9` / `named` не стартует** | Порт 53 занят `systemd-resolved` или другим процессом. | `ss -ulnp | grep :53`, отключение конфликтующей службы. |
| **`permission denied` при чтении зон** | Неверные права на файлы или политики AppArmor/SELinux. | `sudo chown -R bind:bind /etc/bind/zones`, проверка AppArmor/SELinux. |
| **`rndc: connection failed`** | Отсутствует или неверный ключ `/etc/rndc.key`. | `sudo rndc-confgen -a`, проверка прав `chmod 640 /etc/rndc.key`. |
| **Служба неактивна после `reload`** | Синтаксическая ошибка в конфиге или файле зоны. | `named-checkconf`, `journalctl -u bind9 -n 50`. |
| **`SERVFAIL` на все запросы** | Ошибка в конфигурации зоны или DNSSEC-политики. | `named-checkzone`, проверка `dnssec-validation`. |
| **`/etc/resolv.conf` перезаписывается** | DHCP-клиент или `systemd-resolved` восстанавливает stub. | Настройка `resolvconf` или отключение DHCP-обновления DNS. |

---

## Дополнительная информация

### Брандмауэр

Для работы сервера необходимо открыть порты `53/udp` (запросы) и `53/tcp` (ответы > 512 байт и трансфер зон).

*   **ufw (Ubuntu):** `sudo ufw allow Bind9`
*   **firewalld (RHEL):** `sudo firewall-cmd --permanent --add-service=dns && sudo firewall-cmd --reload`
*   **nftables:** добавьте правило в фильтр-таблицу для `tcp/udp dport 53 accept`.

### Ограничения AppArmor / SELinux

Если BIND выдает ошибку `permission denied` при чтении файлов зон, проверьте политики:
*   **AppArmor (Debian/Ubuntu):** Настройки в `/etc/apparmor.d/usr.sbin.named`. После правок: `sudo systemctl restart appappor`.
*   **SELinux (RHEL):** Проверьте контексты файлов `ls -Z /var/named`. Корректный тип для зон — `named_zone_t`.

### Связанные темы

*   **[Обзор BIND](./overview.md)** — архитектура, роли сервера, базовые концепции.
*   **[Диагностика BIND](./troubleshooting.md)** — решение типичных проблем, анализ логов.
*   **[Настройка Master-сервера](./master_server_local_zone.md)** — конфигурация первой локальной зоны.
*   **[Безопасность DNS](../../../../Networking/Protocols/DNS/dns_security.md)** — DNSSEC, DoT/DoH/DoQ, TSIG, XoT.
*   **[Протокол DNS](../../../../Networking/Protocols/DNS/dns.md)** — фундаментальные принципы работы системы.
*   **[Диагностика сетевых служб DNS](../../../Diagnostics/Networking/dns/overview.md)** — работа с утилитами `dig`, `host`, `nslookup`.
