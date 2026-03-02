# Docker развертывание 389DS

## Запуск в Docker-контейне распространяется в виде официального Docker-обраре

389DSза. Установка сводится к запуску контейнера с необходимыми параметрами.

### Базовая команда запуска

```bash
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=example,dc=com \
  -e DM_PASSWORD=mysecretpassword \
  -e DS_SCHEMA_INETPERSON=false \
  389ds/ds-container:latest
```

### Переменные окружения

| Переменная | Описание | Обязательно |
| :--- | :--- | :--- |
| `SUFFIX` | Корневой DN дерева LDAP (например, `dc=example,dc=com`) | Да |
| `DM_PASSWORD` | Пароль администратора (Directory Manager) | Да |
| `DS_SCHEMA_INETPERSON` | Включить схему inetPerson (по умолчанию `true`) | Нет |
| `DS_INDEX` | Включить индексацию при старте (`true`/`false`) | Нет |

### Порты

* **3389** — LDAP (стандартный порт)
* **3636** — LDAPS (LDAP over SSL/TLS)

> **Примечание:** Использование портов > 1024 позволяет запускать контейнер от непривилегированного пользователя.

### Структура данных

* **Database** — хранение данных в `/data/db`
* **Backups** — резервные копии в `/data/backups`
* **Config** — конфигурация в `/data/config`
* **Schemas** — схемы (обычно не требуют изменений, добавляются редко)

### Утилиты управления

После запуска контейнера внутри доступны стандартные LDAP-утилиты:
* `ldapsearch` — поиск по дереву
* `ldapmodify` — модификация записей
* `ldapadd` — добавление записей
* `dsconf` — утилита управления 389DS

### Проверка работоспособности

```bash
# Подключение к контейнеру
docker exec -it 389ds /bin/bash

# Проверка конфигурации
dsconf -D "cn=Directory Manager" ldap://localhost:3389 config get

# Поиск базовой записи
ldapsearch -x -H ldap://localhost:3389 -D "cn=Directory Manager" -W -b "dc=example,dc=com"
```

## Создание одноузлового кластера

1. Создать директорию для данных: `mkdir -p /data/ldap`
2. Запустить контейнер с параметрами
3. Проверить логи: `docker logs -f 389ds`
4. Дождаться сообщения `389DS container started`
