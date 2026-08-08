# Установка DNS-сервера BIND

---

## Определения

**BIND9 (Berkeley Internet Name Domain version 9)** — наиболее распространённая реализация **DNS (Domain Name System — система доменных имён)** сервера, обеспечивающая гибкость, масштабируемость и поддержку современных стандартов безопасности.

**dnsutils / bind9-host** — пакеты диагностических утилит (таких как `dig`, `nslookup`, `host`), необходимых для проверки работы DNS-серверов и отладки разрешения имён.

**Актуальность:** инструкции применимы для версий BIND 9.18+ **LTS (Long Term Support)** и 9.20+ **ESV (Extended Support Version)**.

---

## Основные концепции

### Состав пакетов и репозитории

При установке BIND в различных дистрибутивах используются разные именования пакетов. Основной демон всегда — `named`.

| Пакет | Назначение |
| :--- | :--- |
| **`bind9` / `bind`** | Основной демон DNS-сервера (`named`). |
| **`bind9utils` / `bind-utils`** | Утилиты для управления и проверки конфигурации (`rndc`, `named-checkconf`). |
| **`dnsutils` / `bind-utils`** | Клиентские утилиты для диагностики (`dig`, `nslookup`). |
| **`bind9-doc`** | Локальная документация в формате HTML и PDF. |
| **`python3-bind`** | Библиотеки Python для программного взаимодействия с BIND. |

### Конфликты с локальными резолверами

В современных дистрибутивах (Ubuntu 18.04+, Debian 10+, RHEL 8+) по умолчанию запущен `systemd-resolved`, который занимает порт `53/udp` на адресе `127.0.0.53`.

Для корректной работы BIND как полноценного сервера необходимо:
1.  **Отключить `systemd-resolved`:** Это освободит порт 53 для BIND.
2.  **Настроить `/etc/resolv.conf`:** После отключения службы файл резолвера должен указывать на `127.0.0.1` (сам BIND) или внешние DNS, иначе сервер не сможет разрешать внешние имена.

---

## Практические сценарии

### Установка в Debian / Ubuntu

1.  **Установка пакетов:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y bind9 bind9utils dnsutils
    # → success
    ```

2.  **Устранение конфликта с systemd-resolved:**
    ```bash
    # Остановка и отключение службы
    sudo systemctl stop systemd-resolved
    sudo systemctl disable systemd-resolved

    # Замена символической ссылки на реальный файл (если требуется)
    sudo rm /etc/resolv.conf
    echo "nameserver 127.0.0.1" | sudo tee /etc/resolv.conf
    # → success
    ```

3.  **Запуск и активация:**
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

2.  **Настройка SELinux:**
    Для Master-серверов необходимо разрешить запись в директории зон:
    ```bash
    sudo setsebool -P named_write_master_zones 1
    # → success
    ```

3.  **Запуск службы:**
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

Для быстрой изоляции и тестирования можно использовать официальный образ:
```bash
docker run -d --name bind9 -p 53:53/udp -p 53:53/tcp internetsystemsconsortium/bind9:9.18
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

### 4. Тестовый запрос
Выполните запрос к самому себе, чтобы убедиться в ответе сервера.
```bash
dig @127.0.0.1 localhost
# → ;; ANSWER SECTION:
# → localhost. 604800 IN A 127.0.0.1
```

---

## Дополнительная информация

### Безопасность и брандмауэр

Для работы сервера необходимо открыть порты `53/udp` (запросы) и `53/tcp` (ответы > 512 байт и трансфер зон).

*   **ufw (Ubuntu):** `sudo ufw allow Bind9`
*   **firewalld (RHEL):** `sudo firewall-cmd --permanent --add-service=dns && sudo firewall-cmd --reload`

### Ограничения AppArmor / SELinux

Если BIND выдает ошибку `permission denied` при чтении файлов зон, проверьте политики:
*   **AppArmor (Debian/Ubuntu):** Настройки в `/etc/apparmor.d/usr.sbin.named`. После правок: `sudo systemctl restart apparmor`.
*   **SELinux (RHEL):** Проверьте контексты файлов `ls -Z /var/named`. Корректный тип для зон — `named_zone_t`.

### Связанные темы

*   **[Обзор BIND](./overview.md)** — архитектура и роли сервера.
*   **[Диагностика BIND](./troubleshooting.md)** — решение типичных проблем.
*   **[Настройка Master-сервера](./master_server_local_zone.md)** — конфигурация первой локальной зоны.
*   **[Диагностика DNS](../../../Diagnostics/Networking/dns/overview.md)** — использование утилит `dig` и `nslookup`.
