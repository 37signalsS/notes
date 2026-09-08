# Развертывание 389DS в Docker

## Определения

**389 Directory Server (389DS)** — корпоративный LDAP-сервер с открытым исходным кодом. Контейнеризация 389DS позволяет быстро развертывать масштабируемые службы каталогов с предсказуемой конфигурацией и упрощенным обновлением.

**Официальный образ:** `quay.io/389ds/dirsrv` (ранее `quay.io/389ds/ds-container`). Образ базируется на AlmaLinux/CentOS Stream и оптимизирован для работы в стандартном Docker, Podman и OpenShift. Начиная с версии 3.x, образ использует LMDB в качестве хранилища по умолчанию.

**Instance (Экземпляр):** Изолированный процесс LDAP-сервера со своей базой данных и конфигурацией. В контейнере по умолчанию создается один экземпляр с именем `localhost`.

**dirsrv (UID 389):** Системный пользователь внутри контейнера, от имени которого работает процесс `ns-slapd`. Это важно учитывать при настройке прав доступа на смонтированные тома.

**Том `/data`:** Единый корневой каталог персистентных данных. Сервер создает внутри него иерархию `config`, `db`, `logs`, `tls`, `schema`. Отделение данных от бинарных файлов (read-only rootfs) делает обновление образа бесшовным.

**LMDB (Lightning Memory-Mapped Database):** Встраиваемая библиотека хранения ключ-значение с memory-mapped файлами. В 389DS 3.x заменила BDB как backend по умолчанию. Критически зависит от скорости диска и объема разделяемой памяти (`/dev/shm`).

## Базовые концепции

### Архитектура образа

Официальный образ `quay.io/389ds/dirsrv` строится по принципу многослойности:
1. **Base layer:** AlmaLinux/CentOS Stream с системными библиотеками и зависимостями (OpenLDAP, OpenSSL, Python, systemd-lite).
2. **Runtime layer:** Установленный пакет `389-ds-base` со сборочными скриптами и утилитами (`dsconf`, `dsctl`, `ldapsearch`, `ldapmodify`).
3. **Entrypoint layer:** Скрипты инициализации, которые обрабатывают переменные окружения и создают инстанс при первом запуске.

Процесс `ns-slapd` является PID 1 внутри контейнера. Это означает, что сигналы остановки (`SIGTERM`) доставляются напрямую серверу, что позволяет Docker корректно завершать контейнер без дополнительного `tini` или `dumb-init`.

### Выбор образа

Рекомендуется использовать образы из **Quay.io**, так как они являются первичными и обновляются чаще, чем зеркала на Docker Hub.

*   `quay.io/389ds/dirsrv:latest` — актуальная стабильная версия (обычно ветка 3.x).
*   `quay.io/389ds/dirsrv:3.1` — конкретная мажорная версия для обеспечения стабильности в production.

Правило pinning: в production всегда указывайте digest образа (`@sha256:...`) или точный тег мажорной версии, чтобы избежать непреднамеренных изменений.

### Переменные окружения для инициализации

Эти переменные используются только при первом запуске контейнера для создания инстанса. При повторном запуске (когда `/data` уже содержит конфигурацию) они игнорируются.

| Переменная | Описание | Обязательно | Значение по умолчанию |
| :--- | :--- | :--- | :--- |
| `DS_DM_PASSWORD` | Пароль администратора (`cn=Directory Manager`) | Да | Генерируется случайно (см. лог) |
| `DS_SUFFIX_NAME` | Корневой DN (например, `dc=example,dc=com`) | Да | Извлекается из имени хоста |
| `DS_INSTANCE_NAME` | Имя экземпляра сервера | Нет | `localhost` |
| `DS_BACKEND_NAME` | Имя бэкенда базы данных | Нет | `userRoot` |
| `DS_STARTUP_TIMEOUT` | Время ожидания запуска (сек) | Нет | `60` |
| `DS_MEMORY_PERCENTAGE` | % RAM для автонастройки кэша БД | Нет | `25` |
| `DS_REPLICA_ID` | Уникальный ID реплики (для Multi-Master) | Нет | `65535` (standalone) |

### Логирование в контейнере

В отличие от классической установки, 389DS в Docker настроен на **зеркалирование логов в stdout/stderr**:
- **Access log:** `stdout` (информация о запросах).
- **Errors log:** `stderr` (ошибки и предупреждения).
- **Audit log:** По умолчанию только в файл `/data/logs/audit`.

Это позволяет использовать стандартные драйверы логирования Docker (json-file, journald, gelf, loki) без дополнительной настройки.

### Безопасность и Rootless

Процесс `ns-slapd` работает от пользователя `dirsrv` (UID 389). Контейнер поддерживает запуск в **Rootless Docker** или **Podman**, так как стандартные порты (3389/3636) находятся выше привилегированного диапазона (1024).

### Порты и сеть

| Порт (Контейнер) | Протокол | Назначение |
| :--- | :--- | :--- |
| **3389** | LDAP | Стандартный доступ (рекомендуется STARTTLS) |
| **3636** | LDAPS | Защищенный доступ через SSL/TLS |
| **60389** | LDAP | Альтернативный порт в некоторых конфигурациях |

## Практические сценарии

### Предварительные требования

- Docker Engine 20.10+ или Podman 4.0+
- Доступ к `quay.io` для скачивания образа
- На хосте создана директория для персистентного хранилища с правами UID 389 (например, `mkdir -p /opt/389ds/data && chown -R 389:389 /opt/389ds/data`)
- Открыты порты 3389 и 3636 (если используется `-p` вместо пользовательских сетей)

### Быстрый запуск (Docker CLI)

```bash
docker run -d \
  --name 389ds-server \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /opt/389ds/data:/data:Z \
  -e DS_DM_PASSWORD=MySecurePassword123 \
  -e DS_SUFFIX_NAME="dc=example,dc=com" \
  quay.io/389ds/dirsrv:latest
```

**Валидация:**
```bash
# Проверка статуса
docker exec 389ds-server dsctl localhost status

# Поиск записи по умолчанию
docker exec 389ds-server ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -w MySecurePassword123 \
  -b "dc=example,dc=com" "(objectClass=*)"
```

### Развертывание через Docker Compose

Рекомендуемый способ для production, позволяющий управлять лимитами ресурсов, сетями и Healthcheck.

```yaml
services:
  ldap:
    image: quay.io/389ds/dirsrv:latest
    container_name: 389ds
    ports:
      - "389:3389"
      - "636:3636"
    volumes:
      - ./ldap_data:/data:Z
      # Опционально: подкладывание LDIF для авто-импорта при создании
      # - ./init:/data/config/init:ro
    environment:
      - DS_DM_PASSWORD=admin_password
      - DS_SUFFIX_NAME=dc=example,dc=com
      - DS_REPLICA_ID=1
    shm_size: '2gb' # Важно для производительности LMDB
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    deploy:
      resources:
        limits:
          memory: 4G
    healthcheck:
      test: ["CMD", "dsconf", "-D", "cn=Directory Manager", "ldap://localhost:3389", "status"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Валидация:**
```bash
docker compose up -d
docker compose ps
docker compose logs -f 389ds
```

### Многоконтейнерная среда (Docker сеть)

Для кластера из нескольких узлов используйте пользовательскую сеть Docker, чтобы контейнеры могли обращаться друг к другу по именам.

```yaml
services:
  ldap-01:
    image: quay.io/389ds/dirsrv:latest
    container_name: ldap-01
    environment:
      - DS_DM_PASSWORD=StrongPassword
      - DS_SUFFIX_NAME=dc=example,dc=com
      - DS_REPLICA_ID=1
    volumes:
      - ./ldap_01:/data:Z
    shm_size: '2gb'
    networks:
      - ldap-net

  ldap-02:
    image: quay.io/389ds/dirsrv:latest
    container_name: ldap-02
    environment:
      - DS_DM_PASSWORD=StrongPassword
      - DS_SUFFIX_NAME=dc=example,dc=com
      - DS_REPLICA_ID=2
    volumes:
      - ./ldap_02:/data:Z
    shm_size: '2gb'
    networks:
      - ldap-net

networks:
  ldap-net:
    driver: bridge
```

**Валидация:**
```bash
docker compose up -d
docker exec ldap-01 ping -c 2 ldap-02
docker exec ldap-02 ping -c 2 ldap-01
```

### Продвинутая инициализация (Auto-setup)

Контейнер 389DS поддерживает несколько механизмов автоматизации:

1.  **LDIF Import:** Любые `.ldif` файлы, помещенные в `/data/config/init/`, будут автоматически импортированы при **первом** запуске (создании инстанса).
2.  **Setup INF:** Если вам нужна сложная конфигурация, создайте файл `setup.inf` и укажите путь к нему в переменной `DS_SETUP_INF`. Это позволяет настроить плагины, репликацию и тюнинг БД на этапе развертывания.

### Резервное копирование и восстановление

В контейнере рекомендуется использовать **Online Backup** через утилиты `dsconf`.

**Резервное копирование (LDIF export):**
```bash
# Экспорт всей базы в LDIF внутри контейнера
docker exec 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 \
  backend export userRoot --ldif /data/backups/backup_$(date +%F).ldif

# Резервная копия на хосте (через том)
cp ./ldap_data/backups/backup_*.ldif /path/to/secure/storage/
```

**Офлайн-бэкап через том (tar.gz):**
```bash
# Остановка контейнера для консистентного бэкапа LMDB
docker compose down
tar -czf /backups/389ds-offline-$(date +%F).tar.gz -C ./ldap_data .
docker compose up -d
```

**Восстановление:**
1.  Остановите контейнер.
2.  Удалите содержимое `./ldap_data/db/`.
3.  Запустите контейнер с флагом импорта или используйте `dsconf backend import`:
```bash
docker exec 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 \
  backend import userRoot /data/backups/backup_file.ldif
```

### Обновление контейнера

Обновление 389DS в Docker обычно проходит бесшовно, так как данные отделены от бинарных файлов.

1.  Сделайте бэкап (см. выше).
2.  Остановите старый контейнер: `docker compose down`.
3.  Обновите версию в `compose.yaml`.
4.  Запустите новый контейнер: `docker compose up -d`.
5.  Проверьте логи: сервер автоматически выполнит `upgrade` конфигурации `dse.ldif` при необходимости.

### Структура данных в томе /data

При монтировании тома в `/data` сервер создает следующую структуру:
- `/data/config`: Конфигурационные файлы (`dse.ldif`).
- `/data/db`: Файлы базы данных (LMDB/BDB).
- `/data/logs`: Журналы доступа, ошибок и аудита.
- `/data/tls`: Сертификаты и ключи.
- `/data/schema`: Пользовательские схемы LDAP.

### Управление через exec

Внутри контейнера доступны все современные утилиты управления:

```bash
# Проверка статуса сервера
docker exec 389ds dsctl localhost status

# Управление конфигурацией через dsconf
docker exec 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 config get

# Поиск записей
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -w admin_password \
  -b "dc=example,dc=com" "(objectClass=*)"
```

### Запуск нескольких инстансов на одном хосте

При необходимости запустить несколько независимых экземпляров 389DS на одном хосте используйте:
- Разные имена контейнеров
- Разные тома для `/data`
- Разные маппинги портов (например, `3890:3389`, `6360:3636`)

```bash
docker run -d \
  --name 389ds-secondary \
  -p 3890:3389 \
  -p 6360:3636 \
  -v /opt/389ds/data2:/data:Z \
  -e DS_DM_PASSWORD=AnotherPassword \
  -e DS_SUFFIX_NAME="dc=secondary,dc=example,dc=com" \
  quay.io/389ds/dirsrv:latest
```

### Автоматизация бэкапа через Cron на хосте

```bash
#!/bin/bash
# /etc/cron.daily/389ds-backup
set -euo pipefail

BACKUP_DIR="/opt/389ds/backups"
mkdir -p "$BACKUP_DIR"

docker exec 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 \
  backend export userRoot --ldif "/data/backups/backup-$(date +%F).ldif"

# Ротация: удалить бэкапы старше 30 дней
find "$BACKUP_DIR" -name "backup-*.ldif" -mtime +30 -delete
```

### Управление через Docker Secrets

Для production рекомендуется передавать пароль `DS_DM_PASSWORD` через Docker Secrets или переменные окружения, проброшенные из защищенного хранилища.

```yaml
services:
  ldap:
    image: quay.io/389ds/dirsrv:latest
    environment:
      - DS_SUFFIX_NAME=dc=example,dc=com
    secrets:
      - ds_dm_password
    volumes:
      - ./ldap_data:/data:Z

secrets:
  ds_dm_password:
    file: ./secrets/ds_dm_password.txt
```

## Дополнительная информация

### Настройка TLS/SSL

Контейнер автоматически создает самоподписанный сертификат при первом запуске. Для использования корпоративных сертификатов:

1. Поместите сертификат в `/data/tls/server.crt`.
2. Поместите приватный ключ в `/data/tls/server.key`.
3. Поместите цепочку CA в `/data/tls/ca.crt`.
4. Перезапустите контейнер.

**Важно:** Убедитесь, что файлы сертификатов имеют права чтения для UID 389 (`dirsrv`).

### Оптимизация производительности

1. **SHM (Shared Memory):** Для 389DS критически важен размер разделяемой памяти. Всегда устанавливайте `shm_size` в Docker Compose (минимум 1 ГБ, рекомендуется 2 ГБ и выше). LMDB использует memory-mapped файлы, и недостаток `/dev/shm` приводит к падению производительности или ошибкам `MMAP`.
2. **Лимиты файлов (nofile):** Убедитесь, что `ulimit -n` внутри контейнера достаточно велик (минимум 65535). Это задается через секцию `ulimits` в Compose.
3. **Хранилище:** Используйте SSD для директории `/data/db`. Избегайте использования сетевых файловых систем (NFS/SMB) для файлов базы данных из-за возможных проблем с блокировками LMDB.
4. **CPU Pinning:** Для продакшен сред с высокой нагрузкой установите `cpuset` или `cpu_shares`, чтобы снизить контекстные переключения.
5. **Мониторинг кэша:** Регулярно проверяйте `ds_backend_entry_cache_hit_ratio`. Значение ниже 85% указывает на нехватку RAM или неправильный `DS_MEMORY_PERCENTAGE`.

### Безопасность

1. **Docker Secrets:** Для production рекомендуется передавать пароль `DS_DM_PASSWORD` через Docker Secrets или переменные окружения, проброшенные из защищенного хранилища (Vault).
2. **Rootless:** Используйте Podman или Rootless Docker для минимизации рисков компрометации хоста.
3. **ReadOnly FS:** Можно запускать контейнер с частично доступной только для чтения файловой системой, оставив `/data` и `/run` доступными для записи.
4. **SELinux:** При монтировании томов используйте флаг `:Z` (SELinux relabeling) или `:z` (shared label), чтобы избежать denials.
5. **Сетевые политики:** Ограничьте доступ к портам 3389/3636 на уровне хостового файрвола или Docker Network Policies.

### Логирование и аудит

- **Драйверы логирования:** Настройте `log-driver` и `log-opt` в `daemon.json` или на уровне сервиса для ротации и отправки логов в централизованную систему (ELK, Loki).
- **Уровень детализации:** Для временной диагностики повысьте уровень логов:
```bash
docker exec 389ds dsconf -D "cn=Directory Manager" ldap://localhost:3389 \
  config replace nsslapd-accesslog-level=256
```
- **Аудит:** Файл `/data/logs/audit` содержит детальную историю изменений. Для продакшена настройте ротацию через `logrotate` или отправку в SIEM.

### Устранение неполадок (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Контейнер падает (Exit 1)** | Ошибка прав на `/data` | Выполните `chown -R 389:389 /opt/389ds/data` на хосте. |
| **SELinux Denials** | Отсутствует флаг `:Z` | При монтировании тома добавьте `:Z` (например, `-v /data:/data:Z`). |
| **Insufficient access** | Ошибка в `DS_DM_PASSWORD` | Проверьте пароль. Если он генерировался автоматически, найдите его в логах первого запуска. |
| **Низкая скорость записи** | Недостаточно SHM или медленный диск | Проверьте `shm_size` и используйте локальный SSD. |
| **Ошибка TLS (Self-signed)** | Клиент не доверяет сертификату | Импортируйте `/data/tls/ca.crt` в доверенное хранилище клиента. |
| **OOMKill** | Недостаточно памяти для LMDB | Увеличьте `limits.memory` и `DS_MEMORY_PERCENTAGE` до 50. |
| **LMDB: Map failed** | Недостаточно `shm_size` или виртуальной памяти | Увеличьте `shm_size` до 4gb и проверьте `vm.max_map_count`. |
| **Контейнер стартует медленно** | Большая база, индексация | Увеличьте `DS_STARTUP_TIMEOUT`. При использовании `docker run` без healthcheck добавьте `--health-cmd`. |
| **Ротация логов не работает** | Неправильный драйвер логирования | Проверьте настройки `log-opt max-size` и `max-file` в Compose. |
| **Проблемы с репликацией** | DNS не разрешает имена контейнеров | Используйте пользовательскую сеть Docker или явные IP в соглашениях. |

**Логи:** Основной источник информации — `docker logs 389ds` и файлы в `/data/logs/errors`. Для повышения детализации используйте `dsconf ... config replace nsslapd-errorlog-level=...`.

### Best Practices

1. **Pinning образов:** Используйте digest или мажорные теги вместо `latest`.
2. **Один процесс на контейнер:** Не запускайте `dsconf` или другие утилиты в долгоживущих контейнерах; используйте `docker exec` или одноразовые контейнеры.
3. **Валидация после запуска:** Всегда проверяйте `dsctl status` и делайте пробный `ldapsearch` перед добавлением контейнера в балансировщик.
4. **Резервное копирование:** Тестируйте восстановление из бэкапа минимум раз в квартал.
5. **Мониторинг:** Добавьте `healthcheck` в Compose и интегрируйте метрики с Prometheus (порт 9100 в 3.x).
6. **Логирование:** Используйте структурированные логи (JSON) и отправляйте их в централизованную систему.

### Ограничения и edge cases

1. **Операционные атрибуты:** `targetattr="*"` не включает операционные атрибуты (например, `entrycsn`, `entryusn`). Это поведение LDAPv3 и не зависит от контейнеризации.
2. **Производительность Effective Rights:** Вызов `getEffectiveRights` для большого числа записей создает нагрузку. В контейнере это особенно заметно из-за ограниченного `shm_size`.
3. **Макросы при `add`:** Макросы ACI (`$dn` и `$attr`) не расшифровываются при операции `add` в некоторых конфигурациях. Тестируйте перед использованием.
4. **Взаимодействие с MemberOf:** Если используется плагин `MemberOf`, убедитесь, что ACI на группы не конфликтует с автоматическим обновлением атрибута `member`.
5. **Root vs Container root:** Даже если процесс внутри контейнера работает от UID 389, хостный root может получить доступ к файлам тома. Используйте `userns-remap` для дополнительной изоляции.
6. **Бэкап LMDB:** Прямое копирование файлов `db/` во время работы сервера приведет к повреждению. Используйте только `dsconf backend export` или остановите контейнер.

### Связанные материалы

- [Обзор 389DS](./overview.md) — общие сведения и архитектура
- [Настройка ACI](./aci.md) — управление доступом
- [Репликация](./replication.md) — создание кластеров в Docker
- [Плагины](./plugins.md) — особенности работы авторизации и MemberOf
- [Интеграция с SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/index.md) — настройка клиентов для работы с 389DS
