# Обзор 389 Directory Server (389DS)

## Определения

**389 Directory Server (389DS)** — современный, масштабируемый LDAP-сервер корпоративного уровня с открытым исходным кодом. Разрабатывается сообществом под эгидой Red Hat и является основой для Red Hat Directory Server и FreeIPA. Исторически проект развивался как Netscape Directory Server, затем Fedora Directory Server.

**LDAPv3 (Lightweight Directory Access Protocol)** — основной протокол доступа к данным. 389DS полностью поддерживает стандарты LDAPv3, включая расширенные операции (Extended Operations), контроли (Controls) и SASL-аутентификацию.

**LMDB (Lightning Memory-Mapped Database)** — высокопроизводительный движок хранения данных, ставший стандартом в версиях 3.x. Он обеспечивает консистентность по ACID и высокую скорость чтения за счет использования `mmap`.

**Slapi (Service Layer API)** — программный слой и набор библиотек, позволяющий расширять функциональность сервера через C-плагины. Это ядро модульности 389DS.

**Cockpit 389-ds** — современный веб-интерфейс (плагин к Cockpit) для визуального управления инстансами, конфигурацией, ACI и репликацией.

**DIT (Directory Information Tree)** — иерархическая структура данных LDAP, организованная в виде дерева записей. Корневой узел называется Root DSE (DSA-Specific Entry). В 389DS каждый суффикс (например, `dc=example,dc=com`) представляет собой отдельную ветвь DIT с собственным бэкендом.

**Suffix (Суффикс)** — корневой DN дерева данных в 389DS. Например, `dc=example,dc=com`. Каждый суффикс привязан к конкретному бэкенду (Database Backend). В кластере Multi-Master все суффиксы реплицируются между мастерами.

**Database Backend (Бэкенд базы данных)** — компонент, отвечающий за хранение данных и индексов для конкретного суффикса. В 389DS 3.x используется LMDB. На одном инстансе может быть несколько бэкендов (например, `userRoot` для пользователей и отдельный для конфигурации).

**Index (Индекс)** — структура данных LMDB, ускоряющая поиск по определенному атрибуту. Типы индексов: `eq` (equality — точное совпадение), `sub` (substring — поиск по подстроке), `pres` (presence — проверка наличия атрибута). Отсутствие индекса приводит к полному сканированию базы (Full Table Scan).

**Root DSE** — корневая запись DIT, доступная по пустому основанию (`""`). Содержит информацию о поддерживаемых возможностях сервера: суффиксах, версии, контрольных точках репликации. По умолчанию доступна анонимно, но в production ее содержимое часто ограничивают.

**nsslapd** — основной процесс сервера 389DS. В контейнере работает как PID 1. Отвечает за прием соединений, парсинг LDAP-запросов и координацию плагинов.

**cn=config** — динамическая конфигурация сервера, хранимая в LDIF-файле `dse.ldif`. Изменения применяются онлайн без перезапуска `nsslapd`. В 389DS 3.x это предпочтительный способ управления конфигурацией (в отличие от статических текстовых файлов).

**ACI (Access Control Instructions)** — основной механизм управления доступом в 389DS. В отличие от OpenLDAP, где права хранятся в `cn=config`, ACI в 389DS являются значениями атрибута `aci` самих записей в дереве LDAP. Это делает политику распределенной и переносимой вместе с данными.

## Базовые концепции

### Ключевые особенности версии 3.x

1.  **Полный переход на LMDB:** Начиная с версии 3.1.3, поддержка BerkeleyDB полностью удалена. LMDB обеспечивает более высокую производительность на чтение и упрощенное управление памятью.
2.  **Инструментарий нового поколения:**
    *   `dsctl`: Управление жизненным циклом инстансов (создание, удаление, бэкап, восстановление).
    *   `dsconf`: Гранулярная настройка конфигурации `cn=config` через CLI.
    *   `dsidm`: Управление данными (пользователи, группы, пароли).
3.  **JSON-логирование:** Поддержка вывода логов аудита и ошибок в формате JSON для интеграции с современными системами мониторинга (ELK, Grafana Loki).
4.  **Безопасность:** Поддержка современных алгоритмов хеширования паролей (`YESCRYPT`, `PBKDF2`) и строгая проверка TLS (SSF).

### Архитектура системы

Архитектура 389DS построена по модульному принципу:

1.  **Front-end (LDAP Layer):** Принимает входящие соединения, выполняет парсинг протокола и проверку синтаксиса.
2.  **Slapi Layer:** Управляет вызовом плагинов (Pre-operation, Post-operation, Database). Здесь же работает логика ACI и репликации.
3.  **Back-end (DB Layer):** Отвечает за хранение данных и индексов в LMDB. Каждый суффикс может иметь свой бэкенд.

### DIT: структура и проектирование

DIT в 389DS организуется по отделам (OU — Organizational Unit) или доменам (DC — Domain Component). Типичная структура enterprise-окружения:

```
dc=example,dc=com
├── ou=people         # Пользователи
├── ou=groups         # Группы
├── ou=services       # Служебные аккаунты приложений
├── ou=contractors    # Внешние сотрудники
└── ou=hosts          # Учетные записи хостов (sudo, ssh)
```

**Best practices проектирования DIT:**
- Используйте плоскую структуру, если не требуется иерархия OU.
- Разделяйте пользователей и группы на отдельные OU.
- Для хостовых учетных записей используйте отдельный суффикс или OU с особыми ACI.
- Избегайте глубокой вложенности (более 3-4 уровней) — это усложняет ACI и замедляет поиск.

### Индексация и производительность LMDB

Индексы критичны для производительности. Без индекса на `uid` поиск пользователя по логину будет сканировать всю базу.

**Типы индексов:**

| Тип | Использование | Пример атрибута |
| :--- | :--- | :--- |
| **eq** | Точное совпадение | `uid`, `mail`, `cn` |
| **sub** | Поиск по подстроке | `cn`, `sn`, `telephoneNumber` |
| **pres** | Проверка наличия | `objectClass` |
| **approx** | Фонетический поиск | редко используется |

**Создание индекса:**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr uid --type eq,sub

# Проверка индексов
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix list
```

**Важно:** Изменение индексов требует переиндексации существующих данных. На больших базах (>100 000 записей) это создает нагрузку на I/O. Выполняйте в часы низкой активности.

### Управление памятью и кэширование

LMDB использует memory-mapped файлы, что делает производительность критически зависимой от оперативной памяти и скорости диска.

- **DB Cache:** 389DS автоматически выделяет кэш для LMDB. Размер управляется через `dsconf config replace nsslapd-cache-autosize=...` (процент RAM) или `nsslapd-cachememsize` (фиксированный размер в байтах).
- **Entry Cache:** Кэш записей для часто запрашиваемых объектов. Мониторинг: `dsctl localhost memusage`.
- **Hit Ratio:** Целевое значение — выше 85%. Если ниже — увеличьте `nsslapd-cachememsize` или проверьте паттерны доступа.

### Журналирование и аудит

389DS ведет три типа логов:

| Лог | Путь (по умолчанию) | Назначение |
| :--- | :--- | :--- |
| **Access** | `/var/log/dirsrv/slapd-<instance>/access` | Запросы клиентов (bind, search, modify) |
| **Errors** | `/var/log/dirsrv/slapd-<instance>/errors` | Ошибки, предупреждения, критические события |
| **Audit** | `/var/log/dirsrv/slapd-<instance>/audit` | Изменения конфигурации и данных (если включен) |

**Уровни логирования (`nsslapd-accesslog-level`):**
- `0` — минимальный (только Bind и startup/shutdown)
- `4` — стандартный (все операции)
- `256` — детальный ACL (для отладки ACI, сильно замедляет сервер)

**JSON-формат (389DS 3.x):**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-accesslog-level=4 \
  nsslapd-log-format=json
```

### Сравнение с OpenLDAP

| Характеристика | OpenLDAP | 389 Directory Server |
| :--- | :--- | :--- |
| **Конфигурация** | `cn=config` (текстовые LDIF) | Динамическая через `dsconf` и API |
| **Расширяемость** | Overlays (статические/динамические) | Slapi Plugins (полноценные C-модули) |
| **Репликация** | Syncrepl (pull-модель) | Multi-master (push-модель), до 20+ мастеров |
| **Управление** | CLI (ldapmodify), требует знания LDIF | CLI (`dsconf`), Cockpit Web UI |
| **Масштабируемость** | Экстремальная, но сложная настройка | Высокая "из коробки" для больших DIT |
| **Логирование** | Системный syslog | Прямое логирование в файлы, JSON-формат |
| **Хранение** | MDB (LMDB) в 2.6+ | LMDB с 3.1.3 (полный отказ от BDB) |
| **Индексы** | Статические в `cn=config` | Динамические через `dsconf backend index` |

## Практические сценарии

### Выбор метода развертывания

1.  **Docker/Podman:** Идеально для CI/CD, тестирования и микросервисной архитектуры. См. [Развертывание в Docker](./docker.md).
2.  **Bare-metal/VM:** Рекомендуется для крупных инсталляций, требующих максимальной производительности дисковой подсистемы и LMDB.
3.  **Kubernetes:** Развертывание через StatefulSets для оркестрированных окружений. См. [Kubernetes Deploy](./k8s_deploy/k8s-administration.md).

### Предварительные требования (Bare-metal / VM)

- **ОС:** RHEL 8+/9+, AlmaLinux, Rocky Linux, Ubuntu 22.04+ (через репозиторий)
- **Пакеты:** `389-ds-base`, `389-ds-base-legacy-tools` (для `dsconf` и `dsctl`)
- **Пользователь:** `dirsrv` (UID 389) — процесс работает от этого пользователя
- **Порты:** 3389 (LDAP), 3636 (LDAPS) — открыты в файрволе
- **Диск:** Локальный SSD или NVMe. NFS/SMB для `/var/lib/dirsrv` недопустимы из-за блокировок LMDB.
- **Память:** Минимум 2 ГБ, рекомендуется 8 ГБ+ (эффект "cache warming" для LMDB)
- **Лимиты файлов:** `nofile` не ниже 65535 (`/etc/security/limits.conf`)

### Жизненный цикл эксплуатации

Типовой рабочий процесс администратора 389DS:

1.  **Развертывание (`dsctl`):** Создание нового инстанса, настройка системных лимитов и первоначальных суффиксов.
2.  **Конфигурация (`dsconf`):** Включение плагинов (MemberOf, Referential Integrity), настройка индексов, логирования и ACI.
3.  **Управление данными (`dsidm` / `ldapmodify`):** Создание структур OU, групп и пользователей.
4.  **Мониторинг:** Регулярная проверка `errors` логов и метрик производительности LMDB.
5.  **Обслуживание:** Онлайн-бэкапы через `dsconf` и обновление схем.

### Развертывание: создание инстанса

```bash
# Установка (RHEL/AlmaLinux/Rocky)
dnf install -y 389-ds-base

# Создание инстанса с суффиксом
dscreate from-file /tmp/setup.inf

# Или интерактивно
dscreate interactive
```

**Пример `setup.inf`:**
```ini
[general]
config_password = StrongPassword
full_machine_name = ldap.example.com
# ...

[slapd]
instance_name = localhost
suffix = dc=example,dc=com
root_password = StrongPassword
# ...
```

**Валидация:**
```bash
dsctl localhost status
dsconf -D "cn=Directory Manager" ldap://localhost status
```

### Создание суффикса и бэкенда

```bash
# Создание корневого суффикса (если не создан при dscreate)
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix create \
  --suffix "dc=example,dc=com" \
  --be-name userRoot

# Проверка
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix list
```

### Создание индексов

```bash
# Индексы для стандартных атрибутов
dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr uid --type eq,sub

dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr mail --type eq,sub

dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr objectClass --type eq

# Переиндексация (неблокирующая, но создает нагрузку)
dsconf -D "cn=Directory Manager" ldap://localhost backend index reindex \
  --suffix "dc=example,dc=com" userRoot
```

### Расширение схемы

```bash
# Добавление кастомного атрибута
dsconf -D "cn=Directory Manager" ldap://localhost schema attribute-type add \
  --name "employeeID" \
  --syntax "1.3.6.1.4.1.1466.115.121.1.15" \
  --description "Employee identifier"

# Добавление objectClass
dsconf -D "cn=Directory Manager" ldap://localhost schema objectclass add \
  --name "myPerson" \
  --sup person \
  --must uid,cn,sn,employeeID \
  --may mail,telephoneNumber,departmentNumber

# Проверка
dsconf -D "cn=Directory Manager" ldap://localhost schema attribute-type list | grep employeeID
```

### Резервное копирование и восстановление

**Онлайн-бэкап (LDIF export):**
```bash
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend export userRoot --ldif /backups/backup_$(date +%F).ldif
```

**Офлайн-бэкап (том /var/lib/dirsrv):**
```bash
systemctl stop dirsrv.target
tar -czf /backups/389ds-offline-$(date +%F).tar.gz -C /var/lib/dirsrv .
systemctl start dirsrv.target
```

**Восстановление:**
```bash
# Остановка сервера
systemctl stop dirsrv.target

# Очистка базы (если требуется)
rm -rf /var/lib/dirsrv/slapd-localhost/db/userRoot/*

# Запуск сервера
systemctl start dirsrv.target

# Импорт из LDIF
dsconf -D "cn=Directory Manager" ldap://localhost \
  backend import userRoot /backups/backup_file.ldif
```

### Мониторинг и метрики

**Базовый статус:**
```bash
dsctl localhost status
dsconf -D "cn=Directory Manager" ldap://localhost status
```

**Использование памяти:**
```bash
dsctl localhost memusage
# Вывод: DB cache, entry cache, hit ratio
```

**Активные операции:**
```bash
dsctl localhost monitor
```

**Чтение логов:**
```bash
# Последние ошибки
tail -n 50 /var/log/dirsrv/slapd-localhost/errors

# Поиск медленных операций (>100ms)
grep "etime=1" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'etime=' '{print $2}' | cut -d' ' -f1 | sort -rn | head -20
```

### Типовые задачи администрирования

-   **Управление доступом:** Настройка гранулярных прав через [ACI](./aci.md).
-   **Расширение функционала:** Включение и настройка [Плагинов](./plugins.md).
-   **Обеспечение отказоустойчивости:** Настройка [Репликации](./replication.md).
-   **Управление данными:** Создание пользователей и групп через `dsidm` или `ldapmodify`.

## Дополнительная информация

### Мониторинг и наблюдаемость

389DS предоставляет богатые возможности для отслеживания состояния:
- **JSON Access Logs:** Позволяют анализировать `etime` (время выполнения операции), `notes=U` (неиндексированные поиски) и распределение запросов по клиентам.
- **SNMP:** Поддержка стандартных MIB для мониторинга через Zabbix или Nagios.
- **Prometheus:** Интеграция возможна через сторонние экспортеры или сбор логов в Grafana Loki с последующим извлечением метрик.

### Рекомендации по безопасности (Hardening)

-   **Security Strength Factor (SSF):** Настройка минимального порога SSF (например, `ssf=128`) для запрета аутентификации и модификации данных через незащищенные каналы.
-   **TLS/SSL:** Обязательное использование TLS 1.3. Отключение слабых шифров и поддержка только Forward Secrecy.
-   **Политики паролей:** Использование плагина Account Policy для принудительной сложности и ротации паролей.
-   **Минимизация привилегий:** Запуск сервера от непривилегированного пользователя (обычно `dirsrv`).
-   **Ограничение Root DSE:** Скрытие информации о версии сервера и конфигурации от анонимных пользователей.

### Производительность и оптимизация

1.  **Кэширование:** Убедитесь, что `nsslapd-cachememsize` составляет не менее 50% от объема индексных данных. Для базы на 1 млн записей рекомендуется 4-8 ГБ.
2.  **Индексы:** Все атрибуты, используемые в фильтрах поиска (`uid`, `mail`, `cn`), должны иметь индекс `eq`. Избегайте индексов `sub` на атрибутах с высокой кардинальностью.
3.  **Диск:** Используйте локальный NVMe. Отключайте `atime` на разделе с базой. Проверяйте `iostat -x 1` — `%util` должен быть ниже 70%.
4.  **Сеть:** Для репликации используйте выделенный интерфейс или VLAN. Задержка (>5ms) между мастерами влияет на латентность операций записи.
5.  **Ограничение размера результата:** Настройте `nsslapd-sizelimit` и `nsslapd-pagedsizelimit`, чтобы предотвратить исчерпание памяти при широких поисках.

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `nsslapd` не стартует | Недостаточно `shm` или порт занят | Проверьте `ipcs -m`, `ss -tlnp \| grep 3389` |
| `MMAP: Map failed` | Недостаточно виртуальной памяти | Увеличьте `vm.max_map_count` (sysctl) или уменьшите `nsslapd-cachememsize` |
| `Insufficient access` | ACI или Bind DN неверен | Проверьте `effectiveRights` через `getEffectiveRights` |
| Медленный поиск | Отсутствует индекс или кэш переполнен | Проверьте `notes=U` в access log, создайте индекс |
| `Can't contact LDAP server` | Файрвол или `nsslapd` упал | `systemctl status dirsrv.target`, `ss -tlnp \| grep 3389` |
| Высокий `iowait` | Недостаточно IOPS на диске | Проверьте `iostat -x 1`, перейдите на NVMe |
| Ошибки репликации | Разница времени (Clock Skew) | Настройте NTP, проверьте `repl-agmt status` |
| `entryCSN` конфликты | Дубликаты Replica ID | Уникальный ID для каждого мастера (1..65534) |
| OOM при фиксе | Слишком большой `update-delay` | Уменьшите батчи, увеличьте RAM |
| `nsslapd-accesslog-level=256` замедляет сервер | Детальное логирование ACL | Верните уровень к `4` после диагностики |
| Анонимный bind работает | `nsslapd-allow-anonymous-access` не отключен | `dsconf config replace nsslapd-allow-anonymous-access=off` |

### Миграция с OpenLDAP

Ключевые отличия при переходе с OpenLDAP 2.4/2.6 на 389DS:
1.  **Хранение:** OpenLDAP `mdb` → 389DS `LMDB` (формат несовместим, требуется импорт).
2.  **ACL:** Текстовые `access to...` → атрибуты `aci` в записях. Требуется ручная миграция правил.
3.  **Репликация:** `olcSyncrepl` (pull) → `dsconf replication` (push, MMR).
4.  **Индексы:** `olcIndex` → `dsconf backend index`.
5.  **Схема:** `cn=schema,cn=config` → `dsconf schema attribute-type/objectclass`.

### Системные требования для версии 3.x

| Ресурс | Минимально | Рекомендуется (Production) |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра (высокая параллельность операций) |
| **RAM** | 2 ГБ | 8 ГБ+ (эффект "cache warming" для LMDB) |
| **Диск** | 10 ГБ | SSD/NVMe (LMDB критично к задержкам записи) |
| **IOPS** | 1000 | 10000+ (для >100 000 записей с индексами) |
| **nofile** | 65535 | 65535 (на уровне ОС и systemd) |

### Связанные материалы

-   [Развертывание в Docker](./docker.md) — быстрый старт в контейнерах.
-   [Управление доступом (ACI)](./aci.md) — детальное руководство по правам.
-   [Плагины](./plugins.md) — обзор модульной архитектуры.
-   [389DS в Kubernetes](./k8s_deploy/k8s-administration.md) — эксплуатация в оркестрированных окружениях.
-   [LDAP: основы протокола](../ldap_fundamentals.md) — терминология и структура DIT.
-   [LDAP Troubleshooting](../ldap_troubleshooting.md) — диагностика проблем.
-   [LDAP Security Hardening](../ldap_security.md) — настройка безопасности.
-   [LDAP мониторинг](../ldap_monitoring.md) — метрики и алерты.
-   [LDAP backup/restore](../ldap_backup_restore.md) — стратегии бэкапов.
