**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 12.3 LTS

# Начальная закалка MariaDB (mariadb-secure-installation)

## Определения

**Закалка (Hardening)** — процесс ужесточения конфигурации MariaDB и окружения до уровня, соответствующего требованиям production-среды и стандартам (CIS Benchmark, NIST, PCI DSS, ФСТЭК).

**mariadb-secure-installation** — интерактивный скрипт, поставляемый с MariaDB, который устраняет стандартные уязвимости конфигурации "из коробки": анонимных пользователей, тестовую базу, удалённый root-доступ, слабую аутентификацию.

**Базовая закалка** — разовые действия после установки (скрипт + первичная конфигурация).  
**Непрерывная закалка** — регулярные проверки: актуальность сертификатов, лишние привилегии, версии пакетов, обновления безопасности.

## Основные концепции

### Что покрывает скрипт

Скрипт `mariadb-secure-installation` изменяет только данные в системных таблицах `mysql.user` и удаляет тестовую базу. Он **не** изменяет:
- Параметры `my.cnf`
- Сетевые правила файрвола
- Права на файлы данных и директории
- Настройки ОС (sysctl, systemd, SELinux/AppArmor)
- Плагины аудита и шифрования
- Ролевую модель и политику паролей

### Защита в глубину (Defense in Depth)

Эффективная закалка строится из нескольких независимых слоёв:
1. Скрипт `mariadb-secure-installation` — базовый уровень
2. `my.cnf` — конфигурационные параметры сервера
3. Файрвол хоста — сетевой контроль
4. TLS — шифрование канала
5. Аудит — фиксация событий
6. ОС — права, SELinux/AppArmor, sysctl

Провал одного слоя компенсируется наличием других. Полное руководство по многоуровневой модели hardening см. в **[Обзор безопасности](index.md)**.

## Предварительные требования

- MariaDB 10.6+ установлен и запущен
- Доступ root через `unix_socket` или пароль
- Права `sudo` для изменения `my.cnf` и перезапуска сервиса
- Бэкап системной базы `mysql` перед изменениями
- Понимание модели аутентификации MariaDB (см. **[Аутентификация](authentication.md)**)

## Практические сценарии

### Сценарий 1: Базовая закалка через скрипт

```bash
sudo mariadb-secure-installation
```

Скрипт задаёт шесть вопросов. Рекомендуемые ответы для production:

| Вопрос | Ответ | Обоснование |
| :--- | :--- | :--- |
| Switch to unix_socket authentication? | `Y` | Root-доступ через системные права ОС, без передачи пароля по сети |
| Change the root password? | `Y` | Даже при `unix_socket` установите сложный пароль как резервный вариант |
| Remove anonymous users? | `Y` | Анонимные пользователи имеют пустое имя и минимальные привилегии |
| Disallow root login remotely? | `Y` | Root доступен только через localhost или unix_socket |
| Remove test database and access to it? | `Y` | Тестовая БД доступна любому пользователю по умолчанию |
| Reload privilege tables now? | `Y` | Изменения применяются без перезапуска сервера |

#### Что делает скрипт внутренне

1. **Анонимные пользователи:** `DELETE FROM mysql.user WHERE User='';`
2. **Тестовая БД:** `DROP DATABASE IF EXISTS test; DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';`
3. **Удалённый root:** `DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');`
4. **Плагин аутентификации:** меняет `mysql_native_password` на `unix_socket` для root (опционально).
5. **Пароль root:** `ALTER USER 'root'@'localhost' IDENTIFIED BY '...';`

### Сценарий 2: Ручная проверка после скрипта

```sql
-- Проверка аутентификации root
SELECT User, Host, Plugin FROM mysql.user WHERE User = 'root';
-- → root | localhost | unix_socket

-- Проверка отсутствия анонимных пользователей
SELECT User, Host, Plugin FROM mysql.user WHERE User = '';
-- → (пустой результат)

-- Проверка отсутствия удалённого root
SELECT User, Host FROM mysql.user WHERE User = 'root' AND Host != 'localhost';
-- → (пустой результат)

-- Проверка отсутствия тестовой БД
SHOW DATABASES;
-- → test отсутствует
```

### Сценарий 3: Дополнительные параметры `my.cnf` после скрипта

Скрипт не изменяет конфигурационный файл. Добавьте параметры в секцию `[mariadb]`:

```ini
[mariadb]
# Запрет загрузки файлов через SQL (LOAD DATA INFILE)
local-infile = 0

# Скрытие списка БД от непривилегированных пользователей
skip-show-database = 1

# Отключение символических ссылок (защита от Path Traversal)
symbolic-links = 0

# Принудительное TLS (обязательно для production)
require_secure_transport = ON
```

Подробнее о каждом параметре, допустимых значениях и последствиях включения: **[Дополнительные параметры](additional-parameters.md)**.

### Сценарий 4: OS-level hardening

Скрипт `mariadb-secure-installation` не затрагивает операционную систему. Выполните эти шаги отдельно.

#### Права на файлы данных

```bash
# Директория datadir
sudo chown mysql:mysql /var/lib/mysql
sudo chmod 700 /var/lib/mysql

# Директория для TLS-ключей
sudo mkdir -p /etc/mysql/ssl
sudo chmod 700 /etc/mysql/ssl
sudo chown mysql:mysql /etc/mysql/ssl
```

Для TLS-ключей используйте `chmod 600` и владельца `mysql:mysql` (см. **[SSL/TLS](ssl-tls.md)**).

#### Systemd hardening

Для общего управления systemd см. **[MariaDB под systemd](systemd.md)**.

Создайте drop-in для сервиса MariaDB (security-focused):

```ini
# /etc/systemd/system/mariadb.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=yes
NoNewPrivileges=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart mariadb
```

#### Sysctl параметры

```bash
sudo tee /etc/sysctl.d/99-mariadb-hardening.conf > /dev/null <<EOF
# Запрет пересылки пакетов
net.ipv4.ip_forward = 0

# Защита от SYN flood
net.ipv4.tcp_syncookies = 1

# Игнорировать ICMP broadcast
net.ipv4.icmp_echo_ignore_broadcasts = 1

# Запрет source-routed пакетов
net.ipv4.conf.all.accept_source_route = 0
EOF
sudo sysctl --system
```

#### Запрет core dumps

```bash
# Текущее значение
sudo sysctl fs.suid_dumpable
# → 0 (рекомендуется)

# Постоянное применение
echo "fs.suid_dumpable = 0" | sudo tee -a /etc/sysctl.d/99-mariadb-hardening.conf
sudo sysctl --system
```

#### SELinux / AppArmor

В production-средах используйте SELinux (RHEL/CentOS) или AppArmor (Debian/Ubuntu) в режиме enforcing. Настройки политик должны разрешать MariaDB доступ только к необходимым директориям и портам.

### Сценарий 5: Проверка закалки

```bash
# Статус сервиса
sudo systemctl status mariadb
# → active (running)

# Открытые порты
ss -tlnp | grep 3306
# → LISTEN 0 80 127.0.0.1:3306 ...

# Отсутствие тестовой БД
mariadb -e "SHOW DATABASES;" | grep -w test
# → (пустой результат)
```

### Сценарий 6: Что НЕ покрывает скрипт (gap analysis)

| Область | Состояние после скрипта | Что нужно сделать отдельно |
| :--- | :--- | :--- |
| Аутентификация | Только для root | Настроить `validate_password`, политику паролей, роли (см. **[Аутентификация](authentication.md)**) |
| TLS | Не настроен | Выпустить сертификаты, включить `require_secure_transport` (см. **[SSL/TLS](ssl-tls.md)**) |
| Аудит | Не настроен | Установить `server_audit`, настроить ротацию, вывод в SIEM (см. **[Аудит](audit.md)**) |
| Шифрование на диске | Не настроено | Включить TDE, настроить ключевое управление (см. **[Шифрование данных (TDE)](tde.md)**) |
| Сетевой доступ | Без изменений | Настроить `bind-address`, файрвол (см. **[Сетевая безопасность](network-security.md)**) |
| Ролевая модель | Без изменений | Создать роли, ограничить привилегии (см. **[Ролевая модель (RBAC)](rbac.md)**) |
| Бинарное логирование | Без изменений | Включить для forensic и репликации (см. **[Бинарное логирование](binary-logging.md)**) |
| Права ОС | Без изменений | Выполнить OS-level hardening (см. Сценарий 4) |

## Типичные ошибки и устранение неполадок

### Ошибка: `mariadb-secure-installation` не запускается

**Симптом:** `Can't connect to local MySQL server through socket`

**Причина:** Сервер не запущен или socket находится в нестандартном пути.

**Решение:**
1. Проверьте статус: `sudo systemctl status mariadb`
2. Проверьте путь socket: `mysqladmin variables | grep socket`
3. Если socket нестандартный, укажите его: `sudo mariadb-secure-installation --socket=/path/to/socket`

### Ошибка: root не может войти после смены плагина

**Симптом:** `Access denied for user 'root'@'localhost'`

**Причина:** Попытка входа по паролю при активном `unix_socket` или наоборот.

**Решение:**
- Для `unix_socket`: всегда используйте `sudo mariadb`
- Для пароля: `mariadb -u root -p`

### Ошибка: `skip-show-database` блокирует приложение

**Симптом:** Приложение не видит список баз

**Причина:** Пользователь не имеет привилегии `SHOW DATABASES`.

**Решение:** Убедитесь, что у прикладного пользователя есть `SHOW DATABASES` на уровне конкретных баз, или настройте доступ через `information_schema`.

### Ошибка: перезапуск сервиса падает после hardening

**Симптом:** `journalctl -u mariadb` показывает `Permission denied`

**Причина:** Неправильные права на `datadir`, ключи TLS или SELinux блокирует доступ.

**Решение:**
```bash
# Проверка владельца datadir
ls -la /var/lib/mysql
# → mysql:mysql

# Проверка SELinux
sudo ausearch -m avc -ts recent | grep mariadb

# Проверка AppArmor
sudo aa-status | grep mariadb
```

## Лучшие практики

1. **Базовая закалка — обязательный минимум.** Скрипт + OS-level hardening + `my.cnf` параметры. Без этого production-запуск недопустим.
2. **Не отключайте `unix_socket` без причины.** Он безопаснее парольной аутентификации для локального root.
3. **Права на ключи — 600.** Никогда не оставляйте приватные ключи с правами группового чтения.
4. **Версионируйте конфигурацию.** `my.cnf` и скрипты hardening должны храниться в Git.
5. **Тестируйте на staging.** Любые изменения hardening сначала на тестовом инстансе с идентичной ОС.
6. **Регулярный аудит.** Раз в квартал проверяйте `mysql.user`, права на файлы, сертификаты, обновления безопасности.
7. **Изолируйте datadir.** На отдельном разделе или LUN с ограничением прав ОС.
8. **Сервисный аккаунт.** Используйте отдельного пользователя `mysql` без логина в shell (`/usr/sbin/nologin`).

## Дополнительная информация

### Ссылки на подразделы

- **[Обзор безопасности](index.md)** — полная многоуровневая модель hardening.
- **[Дополнительные параметры](additional-parameters.md)** — `local-infile`, `skip-show-database`, `symbolic-links`.
- **[Сетевая безопасность](network-security.md)** — файрвол, `bind-address`, защита от DoS.
- **[SSL/TLS](ssl-tls.md)** — сертификаты, mTLS, диагностика.
- **[Аудит](audit.md)** — `server_audit` плагин, комплаенс, SIEM.
- **[Шифрование данных (TDE)](tde.md)** — TDE, Vault, управление ключами.
- **[Ролевая модель (RBAC)](rbac.md)** — создание ролей, привилегии.
- **[Установка MariaDB](../installation_and_setup.md)** — установка и послеустановочная закалка.
- **[Конфигурация MariaDB](../configuration.md)** — полный список параметров `my.cnf`.

### Смежные темы

- **[Обзор MariaDB](../overview.md)** — архитектура и стратегия развития.
- **[Установка СУБД](../../installation_security.md)** — общие принципы закалки баз данных.
