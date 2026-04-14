# Docker развёртывание 389DS

## Определения

**Официальный образ:** `quay.io/389ds/ds-container` (поддерживается проектом 389DS).

> **Примечание:** Образ `389ds/ds-container:latest` на Docker Hub может быть устаревшим. Рекомендуется использовать `quay.io/389ds/ds-container:<version>`.

## Базовые концепции

### Запуск контейнера

Базовая команда запуска:

```bash
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=example,dc=com \
  -e DM_PASSWORD=mysecretpassword \
  quay.io/389ds/ds-container:latest
```

### Переменные окружения

| Переменная | Описание | Обязательно | Значение по умолчанию |
| :--- | :--- | :--- | :--- |
| `SUFFIX` | Корневой DN дерева LDAP | Да | — |
| `DM_PASSWORD` | Пароль Directory Manager | Да | — |
| `DS_SCHEMA_INETPERSON` | Включить схему inetPerson | Нет | `true` |
| `DS_INDEX` | Включить индексацию при старте | Нет | `true` |
| `DS_REINDEX` | Пересоздать индексы при старте | Нет | `false` |
| `DS_CONTAINER_PORT` | Порт LDAP внутри контейнера | Нет | `3389` |
| `DS_SECURE_PORT` | Порт LDAPS внутри контейнера | Нет | `3636` |

### Порты

| Порт | Протокол | Описание |
| :--- | :--- | :--- |
| **3389** | LDAP | Стандартный порт (нешифрованный или StartTLS) |
| **3636** | LDAPS | LDAP over SSL/TLS |

> **Примечание:** Порты > 1024 позволяют запускать контейнер от непривилегированного пользователя.

## Практические сценарии

### Структура данных

| Путь | Описание |
| :--- | :--- |
| `/data/db` | База данных (LMDB) |
| `/data/backups` | Резервные копии |
| `/data/config` | Конфигурация (`cn=config`) |
| `/data/schema` | Схемы (редко требуют изменений) |
| `/data/tls` | TLS-сертификаты (опционально) |

### Утилиты управления

Внутри контейнера доступны стандартные LDAP-утилиты:

* `ldapsearch` — поиск по дереву
* `ldapmodify` — модификация записей
* `ldapadd` — добавление записей
* `dsconf` — управление конфигурацией 389DS
* `dsctl` — управление экземпляром (старт/стоп/бэкап)

### Проверка работоспособности

```bash
# Подключение к контейнеру
docker exec -it 389ds /bin/bash

# Проверка конфигурации
dsconf -D "cn=Directory Manager" ldap://localhost:3389 config get

# Поиск базовой записи
ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "dc=example,dc=com" "(objectClass=*)"
```

### Развёртывание одноузлового кластера

1. Создать директорию для данных: `mkdir -p /data/ldap`
2. Запустить контейнер с параметрами (см. выше)
3. Проверить логи: `docker logs -f 389ds`
4. Дождаться сообщения: `389DS container started`

## Дополнительная информация

### TLS/SSL конфигурация

Для использования LDAPS требуется смонтировать сертификаты:

```bash
docker run -d \
  --name 389ds \
  -v /data/ldap:/data \
  -v /path/to/certs:/data/tls:ro \
  -e SUFFIX=dc=example,dc=com \
  -e DM_PASSWORD=password \
  quay.io/389ds/ds-container:latest
```

Требования к сертификатам:

* Серверный сертификат: `/data/tls/server.crt`
* Ключ: `/data/tls/server.key`
* CA-сертификат: `/data/tls/ca.crt`

### Ресурсы

* **CPU:** 2 ядра минимум, 4+ для production
* **RAM:** 2 ГБ минимум, 4–8 ГБ для production
* **Диск:** 10 ГБ+, SSD рекомендуется

### Связанные документы

* [Обзор 389DS](./overview.md) — общая информация
* [Настройка репликации](./replication.md) — multi-master конфигурация
* [Развёртывание в Kubernetes](./k8s_deploy/basic_concepts.md) — StatefulSet deployment
* [ACI](./aci.md) — управление доступом
