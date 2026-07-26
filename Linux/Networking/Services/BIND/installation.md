# Установка DNS-сервера BIND

## Определения

**BIND9 (Berkeley Internet Name Domain version 9)** — наиболее распространённая реализация **DNS (Domain Name System — система доменных имён)** сервера, обеспечивающая гибкость, масштабируемость и поддержку современных стандартов безопасности.

**dnsutils / bind9-host** — пакеты диагностических утилит (таких как `dig`, `nslookup`, `host`), необходимых для проверки работы DNS-серверов и отладки разрешения имён.

**Актуальность:** инструкции применимы для версий BIND 9.18+ **LTS (Long Term Support — долгосрочная поддержка)** и 9.20+ **ESV (Extended Support Version — версия с расширенным циклом обновлений)**.

## Базовые концепции

### Состав пакетов и репозитории

При установке BIND в различных дистрибутивах используются разные именования пакетов. Основной демон всегда — `named`.

| Пакет | Назначение |
|-------|------------|
| `bind9` / `bind` | Основной демон DNS-сервера (`named`). |
| `bind9utils` / `bind-utils` | Утилиты для управления и проверки конфигурации (`rndc`, `named-checkconf`, `named-checkzone`). |
| `dnsutils` / `bind-utils` | Клиентские утилиты для диагностики (`dig`, `nslookup`, `host`). |
| `bind9-doc` | Локальная документация в формате HTML и PDF. |
| `python3-bind` | Библиотеки Python для взаимодействия с конфигурацией и зонами BIND. |

### Конфликты с локальными резолверами

В современных дистрибутивах (Ubuntu 18.04+, Debian 10+) по умолчанию запущен `systemd-resolved`, который занимает порт `53/udp` на интерфейсе петли (**loopback**). Для корректной работы BIND как полноценного сервера необходимо либо настроить `systemd-resolved` на прослушивание другого порта, либо отключить его.

## Практические сценарии

### Установка в Debian / Ubuntu

1.  **Установка пакетов:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y bind9 bind9utils dnsutils
    ```

2.  **Устранение конфликта с systemd-resolved (если требуется):**
    Если порт 53 занят, отключите встроенный резолвер:
    ```bash
    sudo systemctl stop systemd-resolved
    sudo systemctl disable systemd-resolved
    ```

3.  **Запуск и активация:**
    ```bash
    sudo systemctl enable --now bind9
    ```

### Установка в дистрибутивах семейства RHEL (Red Hat Enterprise Linux)

Инструкция актуальна для **RHEL, Rocky Linux, AlmaLinux и Fedora**.

1.  **Установка через DNF:**
    ```bash
    sudo dnf install -y bind bind-utils
    ```

2.  **Настройка SELinux (Security-Enhanced Linux):**
    Убедитесь, что контексты безопасности позволяют `named` писать в рабочие директории (особенно для Slave-серверов):
    ```bash
    sudo setsebool -P named_write_master_zones 1
    ```

3.  **Запуск службы:**
    ```bash
    sudo systemctl enable --now named
    ```

### Установка в Alpine Linux

Легковесный вариант для контейнеров или минималистичных серверов.

```bash
apk add bind bind-utils
rc-update add named
rc-service named start
```

## Проверка работоспособности

После установки выполните диагностику для подтверждения корректности запуска.

1.  **Проверка версии и сборки:**
    ```bash
    named -v
    # → BIND 9.18.28-1~deb12u1-Debian (Extended Support Version) <id:5e6e76c>
    ```

2.  **Проверка прослушиваемых портов (UDP/TCP 53):**
    ```bash
    sudo ss -tulpn | grep :53
    # → udp UNCONN 0 0 127.0.0.1:53 0.0.0.0:* users:(("named",pid=1234,fd=20))
    # → tcp LISTEN 0 10 127.0.0.1:53 0.0.0.0:* users:(("named",pid=1234,fd=21))
    ```

3.  **Проверка синтаксиса конфигурации:**
    Утилита не возвращает вывода, если ошибок нет.
    ```bash
    sudo named-checkconf /etc/bind/named.conf
    ```

4.  **Тестовый локальный запрос:**
    ```bash
    dig @127.0.0.1 localhost
    # → ;; ANSWER SECTION:
    # → localhost. 604800 IN A 127.0.0.1
    ```

## Дополнительная информация

### Безопасность и брандмауэр

Для работы сервера необходимо открыть порты `53/udp` и `53/tcp` во внешнем интерфейсе.

*   **ufw (Ubuntu):** `sudo ufw allow Bind9`
*   **firewalld (RHEL):** `sudo firewall-cmd --permanent --add-service=dns && sudo firewall-cmd --reload`

### Ограничения AppArmor / SELinux

Если BIND не может прочитать файлы зон в нестандартных директориях, проверьте профили безопасности:
*   В Ubuntu настройки AppArmor находятся в `/etc/apparmor.d/usr.sbin.named`.
*   В RHEL используйте `audit2allow` для анализа отказов SELinux.

**См. также:**

*   [Обзор BIND](./overview.md) — архитектура и роли сервера.
*   [Диагностика и решение проблем](./troubleshooting.md) — глубокий анализ ошибок.
*   [Настройка Master-сервера](./master_server_local_zone.md) — создание первой зоны.
*   [Средства диагностики DNS](../../../Diagnostics/Networking/dns/overview.md) — описание работы `dig` и `nslookup`.
