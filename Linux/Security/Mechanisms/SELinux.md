# SELinux (Security-Enhanced Linux)

## Определения

*   **SELinux** — механизм принудительного контроля доступа (Mandatory Access Control, MAC) в ядре Linux. Применяет централизованные политики безопасности, которые нельзя обойти пользователям или процессам.
*   **MAC (Mandatory Access Control)** — мандатное управление доступом, где политики определяются централизованно.
*   **DAC (Discretionary Access Control)** — дискреционное управление доступом, где правами управляет владелец файла (стандартная модель Linux).
*   **LSM (Linux Security Modules)** — фреймворк в ядре Linux для реализации моделей MAC. SELinux построен на базе LSM.
*   **Контекст безопасности** — метка в формате `user:role:type:level`, хранящаяся в расширенных атрибутах файлов.

### Компоненты контекста безопасности

| Компонент | Описание | Пример |
|-----------|----------|--------|
| **User** | Пользователь SELinux | `system_u`, `unconfined_u` |
| **Role** | Роль, определяющая доступные домены | `system_r`, `object_r` |
| **Type/Domain** | Тип для объектов, домен для процессов | `httpd_t`, `httpd_sys_content_t` |
| **Level** | Уровень чувствительности (MLS/MCS) | `s0`, `s0:c0.c1023` |

### Типы политик

*   **MLS (Multi-Level Security)** — многоуровневая система (иерархические уровни: «совершенно секретно», «секретно»).
*   **MCS (Multi-Category Security)** — многокатегорийная система (неиерархические категории: «проект А», «проект Б»).
*   **TE (Type Enforcement)** — основной механизм типизации доступа.
*   **RBAC (Role-Based Access Control)** — управление доступом на основе ролей.

## Основные концепции

### Схема работы

1.  **Субъект** (процесс с контекстом) пытается получить доступ к **объекту** (файл, порт с контекстом).
2.  SELinux проверяет политики (база данных правил в ядре).
3.  На основе сопоставления контекстов — **разрешает** или **запрещает** доступ.
4.  Все действия протоколируются.

### Режимы работы

| Режим | Описание | Применение |
|-------|----------|------------|
| **Enforcing** | Политики активно применяются, нарушения блокируются и логируются | Производственная среда |
| **Permissive** | Политики не применяются, но нарушения логируются | Отладка, создание политик |
| **Disabled** | SELinux полностью отключен | Не рекомендуется |

### Булевы значения (Booleans)

Параметризованные политики для включения/отключения функций без изменения всей политики.

**Примеры:**

*   `httpd_can_network_connect` — разрешить HTTPD сетевые соединения.
*   `samba_enable_home_dirs` — разрешить Samba доступ к домашним каталогам.
*   `allow_ftpd_full_access` — полный доступ FTP.

### Особенности применения

*   **Гибкое ограничение прав** — на уровне ядра.
*   **Снижение рисков** — от ошибок разработчиков или компрометации.
*   **Изоляция процессов** — ограничение скомпрометированных процессов.
*   **Протоколирование** — все действия записываются в журнал.

> **Важно:** Пользователь `root` с контекстом `unconfined_t` не ограничен SELinux.

## Практические сценарии

### Управление режимами

```bash
# Проверка текущего статуса
sestatus
getenforce

# Временное переключение (до перезагрузки)
sudo setenforce 0  # Permissive
sudo setenforce 1  # Enforcing

# Постоянное отключение (требуется перезагрузка)
# /etc/selinux/config
SELINUX=disabled
```

> Полное отключение (`Disabled`) требует перезагрузки для перемаркировки ФС. `setenforce 0` переводит только в `Permissive`.

### Просмотр контекстов

```bash
# Файлы и каталоги
ls -Z /var/www/html
# drwxr-xr-x. root root system_u:object_r:httpd_sys_content_t:s0 /var/www/html

# Процессы
ps -Z aux | grep nginx
# system_u:system_r:httpd_t:s0 root 12345 ... nginx
```

> Подробнее о `ps`: [`ps`](../../Diagnostics/Processes/ps.md)

### Управление пользователями, ролями, типами

```bash
# Просмотр пользователей SELinux
semanage user -l

# Просмотр ролей
semanage role -l

# Просмотр типов
seinfo -t
```

### Управление портами

```bash
# Разрешенные порты для типа http_port_t
semanage port -l | grep http_port_t

# Добавление нового порта
sudo semanage port -a -t http_port_t -p tcp 5080

# Удаление порта
sudo semanage port -d -t http_port_t -p tcp 5080
```

### Управление файловыми контекстами

```bash
# Просмотр правил
semanage fcontext -l | grep '/var/www'

# Добавление правила для нового каталога
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/my_app(/.*)?"

# Применение контекста к файлам
sudo restorecon -Rv /srv/my_app
```

### Управление булевыми значениями

```bash
# Просмотр всех значений
getsebool -a

# Временное включение/отключение
sudo setsebool httpd_can_network_connect on

# Постоянное включение
sudo setsebool -P httpd_can_network_connect on
```

### Диагностика и устранение проблем

```bash
# Логи аудита (отказы SELinux)
sudo tail -f /var/log/audit/audit.log | grep AVC
```

**Создание модуля политики:**

```bash
# Генерация модуля из логов
sudo grep "AVC" /var/log/audit/audit.log | audit2allow -M my_custom_policy

# Установка модуля
sudo semodule -i my_custom_policy.pp
```

### Примеры настройки

**Изменение порта SSH:**

```bash
# 1. Изменить порт в /etc/ssh/sshd_config (например, 5022)
# 2. Добавить порт в SELinux
sudo semanage port -a -t ssh_port_t -p tcp 5022
# 3. Перезапустить sshd
```

**Изменение каталога данных MySQL:**

```bash
# Для каталога /srv/mysql
sudo semanage fcontext -a -t mysqld_db_t "/srv/mysql(/.*)?"
sudo restorecon -Rv /srv/mysql
```

### SELinux и Docker

```bash
# Монтирование тома с автоматической сменой контекста
# z — приватный контекст
# Z — общий контекст
docker run -v /host/path:/container/path:z my_image
```

## Дополнительная информация

### История

*   Разработано NSA США.
*   Впервые в ядре Linux — 1998 год.
*   В составе ядра 2.6 (2003) через LSM.

### Чтение меток MLS/MCS

Для удобного чтения меток (например, `SystemLow` вместо `s0`):

```bash
# Установка
sudo dnf install mcstrans  # RHEL/CentOS
sudo apt install mcstrans   # Debian/Ubuntu

# Запуск
sudo systemctl start mcstransd
```

### Инструменты

| Пакет | Утилиты | Назначение |
|-------|---------|------------|
| `setools-console` | `semanage`, `seinfo`, `sesearch`, `audit2allow` | Анализ и управление политиками |
| `policycoreutils` | `restorecon`, `setenforce`, `sestatus` | Базовые операции |
| `audit` | `auditctl`, `ausearch`, `aureport` | Аудит системных событий |

### Связанные темы

*   **[Docker и SELinux](../../../Docker/Docker_security/security_overview.md)** — безопасность контейнеров
*   **[AppArmor](../AppArmor.md)** — альтернативный MAC-механизм
*   **[Аудит](../../Diagnostics/Logging/audit.md)** — аудит системных событий
