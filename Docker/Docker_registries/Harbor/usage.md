# Harbor: Работа с реестром

## Определения

Базовые понятия (Проект, Робот-аккаунт и др.) описаны в [обзоре Harbor](./overview.md).

* **Аутентификация**: Процесс проверки подлинности пользователя или системы перед предоставлением доступа к реестру.

## Основные концепции

Работа с Harbor включает три основных операции: аутентификацию, отправку (push) и получение (pull) образов. Все образы в Harbor организованы по проектам.

### Типы аутентификации

| Метод | Назначение | Формат логина |
| :--- | :--- | :--- |
| **Пользователь** | Интерактивный доступ | `username` / `password` (или CLI Secret) |
| **Робот-аккаунт** | Автоматизация в CI/CD | `robot$<имя>` / `<токен>` |

> **Примечание:** Для пользователей с OIDC/LDAP рекомендуется использовать **CLI Secret** (находится в профиле пользователя в UI Harbor) вместо основного пароля.

### Структура имен образов

Для взаимодействия с Harbor имя образа должно соответствовать формату:

```
<hostname>/<project>/<image>:<tag>
```

Пример: `harbor.example.com/library/nginx:1.25`

* **hostname**: Доменное имя Harbor (указывается в `harbor.yml` при установке).
* **project**: Логическое пространство имен (проект `library` — по умолчанию для публичных образов).
* **image**: Имя репозитория образов.
* **tag**: Версия образа (рекомендуется использовать SemVer, см. [версионирование образов](../image_versioning_and_tagging.md)).

### Права доступа к проектам

| Тип проекта | Pull (Скачивание) | Push (Загрузка) |
| :--- | :--- | :--- |
| **Публичный** | Анонимно (без логина) | Требуется аутентификация |
| **Приватный** | Требуется аутентификация | Требуется аутентификация |

## Практические сценарии

### Сценарий 1: Интерактивная аутентификация пользователя

Войдите в Harbor с учётной записью пользователя для работы через CLI:

```bash
docker login harbor.example.com
# Username: admin
# Password: <YourAdminPassword>

# → Login Succeeded
```

После успешного входа токен сохраняется в `~/.docker/config.json`.

Для завершения сессии:

```bash
docker logout harbor.example.com
# → Removing login credentials for harbor.example.com
```

### Сценарий 2: Аутентификация робот-аккаунта для CI/CD

Робот-аккаунты обеспечивают безопасность автоматизированных систем:

1. Создайте робот-аккаунт в UI Harbor: **Project → Robot Accounts → New Robot Account**.
2. Выберите необходимые права (push, pull, scan) и срок действия.
3. Сохраните сгенерированный токен (показывается один раз).

Использование в пайплайне:

```bash
docker login harbor.example.com -u 'robot$ci-bot' -p 'SECRET_TOKEN'
# → Login Succeeded
```

**Преимущества:**
* Принцип наименьших привилегий (права только на конкретные проекты).
* Возможность отзыва без смены пароля пользователя.
* Аудит действий автоматики.

### Сценарий 3: Тегирование и публикация образа

Подготовьте локальный образ и отправьте его в реестр Harbor:

```bash
# 1. Сборка образа
docker build -t my-app:latest .

# 2. Присвоение тега в формате Harbor
docker tag my-app:latest harbor.example.com/library/my-app:v1.0.0

# 3. Отправка в реестр
docker push harbor.example.com/library/my-app:v1.0.0
# → The push refers to repository [harbor.example.com/library/my-app]
# → v1.0.0: digest: sha256:... size: ...
```

Для публикации нескольких тегов (например, версии и `latest`):

```bash
docker tag my-app:latest harbor.example.com/library/my-app:v1
docker tag my-app:latest harbor.example.com/library/my-app:latest

docker push harbor.example.com/library/my-app --all-tags
```

### Сценарий 4: Получение (скачивание) образа

Загрузка образов из различных типов проектов:

```bash
# Из публичного проекта (без предварительного login)
docker pull harbor.example.com/library/nginx:1.25
# → 1.25: Pulling from library/nginx
# → Digest: sha256:...
# → Status: Downloaded newer image for harbor.example.com/library/nginx:1.25

# Из приватного проекта
docker login harbor.example.com
docker pull harbor.example.com/my-project/my-app:v1.0.0
```

### Сценарий 5: Работа с Helm-чартами через OCI

Harbor позволяет хранить Helm-чарты в том же реестре, что и Docker-образы:

```bash
# 1. Аутентификация в Helm
helm registry login harbor.example.com -u admin -p <password>
# → Login Succeeded

# 2. Публикация чарта (в формате OCI)
helm push my-chart-1.0.0.tgz oci://harbor.example.com/my-project
# → Pushed: harbor.example.com/my-project/my-chart:1.0.0
# → Digest: sha256:...

# 3. Установка чарта напрямую из Harbor
helm install my-release oci://harbor.example.com/my-project/my-chart --version 1.0.0
```

## Дополнительная информация

### Устранение неполадок

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `unauthorized: authentication required` | Отсутствует или просрочена сессия | Выполните `docker login` |
| `denied: requested access to the resource is denied` | Недостаточно прав в проекте | Проверьте роль пользователя или Robot Account |
| `tls: failed to verify certificate` | Самоподписанный сертификат Harbor | Установите Root CA (см. [сертификаты](./certificates.md)) |
| `manifest unknown` | Тег или образ не существует | Проверьте наличие образа в UI Harbor |

### Лучшие практики

* **Приоритет Robot Accounts**: Всегда используйте робот-аккаунты для CI/CD вместо личных учетных записей.
* **Использование CLI Secret**: Для интеграции с LDAP/AD используйте CLI Secret для повышения безопасности.
* **Версионирование по дайджестам**: В критических средах (Production) ссылайтесь на образ по `sha256` дайджесту для гарантии неизменности.
* **Автоматическая очистка**: Настраивайте Retention Policies в настройках проекта для удаления старых или неиспользуемых тегов.

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и возможности.
* **[Установка Harbor](./installation.md)** — развертывание через Docker Compose и Helm.
* **[Создание сертификатов](./certificates.md)** — настройка TLS.
* **[Версионирование образов](../image_versioning_and_tagging.md)** — стратегии тегирования.
* **[Docker Registry](../docker_registries.md)** — общие принципы работы с реестрами.
