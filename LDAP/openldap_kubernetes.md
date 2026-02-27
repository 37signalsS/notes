# OpenLDAP в Kubernetes

## Определения

**OpenLDAP** — свободная реализация протокола LDAP (Lightweight Directory Access Protocol), используемая для организации централизованного хранилища информации о пользователях, группах и других сетевых ресурсах.

**LDIF** (LDAP Data Interchange Format) — текстовый формат представления данных LDAP, используемый для экспорта, импорта и резервного копирования данных.

**Operational Attributes** — служебные атрибуты, автоматически генерируемые LDAP-сервером. Не могут быть изменены напрямую пользователями.

**entryUUID** — уникальный идентификатор записи, присваиваемый OpenLDAP-сервером. Специфичен для OpenLDAP (в 389DS используется другое название).

**entryCSN** (Change Sequence Number) — временная метка создания/модификации записи на LDAP-сервере. Используется в механизмах репликации (master-slave, multi-master) для определения актуальности данных.

**memberOf** — operational attribute, автоматически генерируемый сервером, указывающий группы, в которые входит пользователь.

---

## Базовые концепции

### SSL/TLS в OpenLDAP

#### LDAPS (LDAP over SSL/TLS)

- **Порт 636** — LDAPS (зашифрованное соединение сразу)
- **Порт 389** с **startTLS** — шифрование на обычном порту

#### Конфигурация в OpenLDAP

Для включения SSL требуется три параметра в конфигурации:

1. **TLSCertificateFile** — сертификат LDAP-сервера
2. **TLSCertificateKeyFile** — ключ сертификата
3. **TLSCACertificateFile** — Certificate Authority (CA), подписавший сертификат

#### Пример Helm Chart (values.yaml)

```yaml
ldap:
  ssl:
    enabled: true
  certManager:
    enabled: true  # Использовать cert-manager для генерации сертификатов
  # Имя issuer (не создаётся автоматически, требуется создать вручную)
  tls:
    issuer: "selfsign-ldap"
  # Параметры сертификата
  cert:
    dnsNames:
      - "ldap.example.com"
    ipAddresses:
      - "192.168.1.100"
```

**Важно:**
- При использовании cert-manager необходимо предварительно создать Issuer (self-signed или Let's Encrypt)
- В сертификате должны быть указаны DNS-имена и/или IP-адреса, по которым будут подключаться клиенты
- CA-сертификат необходимо добавить в доверенные на Linux-клиентах

#### Добавление CA в доверенные (Linux)

```bash
# Копирование CA-сертификата
cp ca.crt /usr/local/share/ca-certificates/

# Обновление хранилища сертификатов
update-ca-certificates
```

---

### Резервное копирование

#### Экспорт через Apache Directory Studio

1. Подключение к LDAP-серверу
2. Правый клик на root DN → Export → Export to LDIF
3. Указание Search Base (корень дерева)
4. Выбор типа объектов (все или конкретный класс)
5. Опция **Operational Attributes** (для полного бэкапа)
6. Указание пути сохранения .ldif файла

#### Особенности LDIF с русскими символами

Данные на кириллице кодируются в BASE64. Рекомендуется использовать UID в качестве RDN (Relative Distinguished Name) для читаемости резервных копий.

### Восстановление из резервной копии

#### Через Apache Directory Studio

1. Подключение к LDAP-серверу
2. Правый клик на root DN → Import → LDIF Import
3. Выбор файла резервной копии
4. **Рекомендуемые настройки:**
   - **Update Existing Entries** — отключено (чтобы не перезаписать существующие записи)
   - **Continue on Error** — включено (для продолжения при ошибках дублирования)
5. Просмотр логов для анализа ошибок

#### Проблемы с Operational Attributes

При наличии в LDIF Operational Attributes (entryUUID, entryCSN) восстановление через стандартные инструменты невозможно при работающем LDAP-сервере:

```
Entry UUID: no user modification allowed
```

**Решение:** восстановление выполняется при **остановленном LDAP-сервере** с использованием `slapadd`.

---

## Практические сценарии

### Helm Chart для OpenLDAP в Kubernetes

#### Архитектура

- **MultiMaster** — обязательно для работы в Kubernetes (репликация между подами)
- StatefulSet для управления подами
- init-контейнеры для инициализации и восстановления

#### Конфигурация резервного копирования (values.yaml)

```yaml
backup:
  enabled: false          # Включение автоматического backup
  schedule: "0 2 * * *"   # Cron-расписание
  s3:
    endpoint: ""          # S3-совместимое хранилище (MinIO и т.д.)
    bucket: ""            # Имя bucket
    accessKey: ""         # Access Key
    secretKey: ""         # Secret Key

restore:
  enabled: false          # Включение восстановления
  file: ""                # Имя файла backup (.ldif.gz)
```

#### Процесс восстановления из backup

1. Остановка LDAP-сервера (удаление StatefulSet или Pods)
2. Удаление Persistent Volumes
3. В values.yaml: `restore.enabled: true`
4. Указание пути к файлу backup в S3
5. Helm upgrade
6. После восстановления: `restore.enabled: false`

**Важно:** При работающих нескольких подах multi-master восстановление может привести к удалению данных из-за сравнения CSN. Рекомендуется останавливать все поды перед восстановлением.

#### CronJob для автоматического backup

- Использует тот же образ (art-openldap)
- Запускает `ldapsearch` с правами REPL-user
- Экспорт в LDIF с включением Operational Attributes (`+`)
- Сжатие gzip и загрузка в S3

### Известные проблемы Helm Chart

1. **Rollout (изменение количества реплик):**
   - При изменении количества подов в values.yaml новые поды не добавляются в конфигурацию syncrepl автоматически
   - Требуется ручная правка конфигурации

2. **OLC (on-line configuration) size limit:**
   - Обязательная настройка для корректной работы multi-master
   - Без неё возможны проблемы с синхронизацией

---

## Дополнительная информация

### Инструменты

- **Apache Directory Studio** — GUI-клиент для LDAP
- **slapadd** — утилита для импорта данных при остановленном сервере
- **ldapsearch** — утилита для экспорта данных

### Ссылки

- [389DS — альтернатива OpenLDAP](../LDAP/389ds_overview.md)
- [LDAP в Linux](../../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol)
- [Настройка SSSD для LDAP-аутентификации](../../Linux/SystemAdministration/users_management.md#Настройка-SSSD-для-LDAP)
- [Keycloak LDAP Federation](../Security/Tools/keycloak_ldap_federation.md)
