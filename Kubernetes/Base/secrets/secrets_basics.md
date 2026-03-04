# Kubernetes Secrets: Основы

## Определения

**Secret** — это объект Kubernetes для хранения небольших объёмов чувствительных данных (пароли, токены, ключи API).

> **Важно:** По умолчанию данные в Secret хранятся в etcd в кодировке **Base64**, а не в зашифрованном виде. Base64 — не шифрование, данные легко раскодировать. Подробнее см. [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Отличие Secret от ConfigMap

| Признак | Secret | ConfigMap |
| :--- | :--- | :--- |
| **Назначение** | Конфиденциальные данные | Некритичные конфигурационные данные |
| **Доступ** | Строгие политики RBAC | Более открытый доступ |
| **Хранение** | Требуется шифрование в etcd | Хранится в открытом виде |
| **Представление** | `data` (Base64), `stringData` | `data`, `binaryData` |
| **Типы** | Типизированные форматы (`tls`, `dockerconfigjson`) | Нет специальных типов |

### Типы Secret

- **Opaque**: тип по умолчанию, произвольные пары ключ-значение
- **kubernetes.io/service-account-token**: аутентификация с API-сервером
- **kubernetes.io/dockerconfigjson**: учётные данные Docker Registry
- **kubernetes.io/basic-auth**: логины и пароли для базовой аутентификации
- **kubernetes.io/ssh-auth**: приватные SSH-ключи
- **kubernetes.io/tls**: TLS-сертификаты и приватные ключи
- **bootstrap.kubernetes.io/token**: подключение новых нод к кластеру

## Практические сценарии

### Создание Secret

Декларативно через манифест или императивно через kubectl. Подробнее см. [Создание Secret](creating_secrets.md).

### Использование в подах

Secret можно использовать как переменные окружения или монтировать как тома. Подробнее см. [Использование Secret](using_secrets.md).

### Безопасность

Подробнее см. [Безопасность Secret](security.md):

- Шифрование в etcd (Encryption at Rest)
- Неизменяемые Secrets (`immutable: true`)
- RBAC

## Дополнительная информация

### Ограничения

- Размер одного Secret: **до 1 MiB** (ограничение etcd)
- Максимальный размер annotations: **256 KB**
- Для больших данных используйте внешние хранилища или [ConfigMap](../configmap.md) с `binaryData`

> **Нюанс:** Ограничение 1 MiB применяется к сериализованным данным (включая metadata, annotations). При превышении 256 KB в annotations Secret не будет создан.

### Связанные темы

- [Создание Secret](creating_secrets.md)
- [Использование Secret](using_secrets.md)
- [Хранение в etcd](etcd_storage.md)
- [Безопасность Secret](security.md)
- [Внешние менеджеры](external_managers.md)
- [ConfigMap](../configmap.md) — для неконфиденциальных данных
- [Sealed Secrets (Security)](../../Security/sealed_secrets_overview.md)
- [RBAC](../../Security/rbac/rbac_overview.md) — управление доступом
