# Harbor: Работа с реестром

## Определения

* **Проект (Project)**: Логическое пространство имен в Harbor для группировки образов. Аналог репозитория в Docker Hub. Проекты могут быть публичными (public) или приватными (private).
* **Робот-аккаунт (Robot Account)**: Специальная учётная запись для автоматизации доступа к Harbor из CI/CD-систем. Имеет ограниченные права и срок действия.
* **Аутентификация**: Процесс проверки подлинности пользователя или системы перед предоставлением доступа к реестру.

## Основные концепции

Работа с Harbor включает три основных операции: аутентификацию, отправку (push) и получение (pull) образов. Все образы в Harbor организованы по проектам.

### Типы аутентификации

| Метод | Назначение | Формат логина |
| :--- | :--- | :--- |
| **Пользователь** | Интерактивный доступ через UI или CLI | `username` / `password` |
| **Робот-аккаунт** | Автоматизация в CI/CD | `robot$<имя>` / `<токен>` |
| **Deploy Token** | Одноразовый доступ для развёртывания | `<токен>` |

### Структура имен образов

Полное имя образа в Harbor включает:

```
<hostname>/<project>/<image>:<tag>
```

Пример: `harbor.example.com/library/nginx:1.25`

* **hostname**: Доменное имя Harbor (указывается в `harbor.yml` при установке)
* **project**: Имя проекта (`library` для публичных образов)
* **image**: Имя образа
* **tag**: Версия (рекомендуется использовать SemVer, см. [версионирование образов](../image_versioning_and_tagging.md))

### Права доступа к проектам

| Проект | Pull | Push |
| :--- | :--- | :--- |
| **Публичный** | Без аутентификации | Требуется аутентификация |
| **Приватный** | Требуется аутентификация | Требуется аутентификация |

## Практические сценарии

### Сценарий 1: Аутентификация пользователя

Войдите в Harbor с учётной записью пользователя:

```bash
docker login harbor.example.com
# Username: admin
# Password: <YourAdminPassword>

# Результат: Login Succeeded
```

После успешного входа токен сохраняется в `~/.docker/config.json`.

Для выхода:

```bash
docker logout harbor.example.com
```

### Сценарий 2: Аутентификация робот-аккаунта для CI/CD

Робот-аккаунты предпочтительнее для автоматизации:

1. Создайте робот-аккаунт в UI Harbor: **Project → Robot Accounts → New Robot Account**
2. Выберите права (push, pull, scan) и срок действия
3. Скопируйте сгенерированный токен

Используйте в CI/CD:

```bash
docker login harbor.example.com -u 'robot$ci-bot' -p '<токен>'
```

Преимущества робот-аккаунтов:

* Ограниченные права (принцип наименьших привилегий)
* Ограниченный срок действия
* Легко отозвать без влияния на других пользователей

### Сценарий 3: Тегирование и отправка образа

Подготовьте образ к отправке в Harbor:

```bash
# Создайте образ локально
docker build -t my-app:latest .

# Присвойте тег Harbor
docker tag my-app:latest harbor.example.com/library/my-app:v1.0.0

# Отправьте в Harbor
docker push harbor.example.com/library/my-app:v1.0.0
```

Для публикации нескольких тегов одновременно:

```bash
docker tag my-app:latest harbor.example.com/library/my-app:v1
docker tag my-app:latest harbor.example.com/library/my-app:latest

docker push harbor.example.com/library/my-app --all-tags
```

Рекомендации по тегированию см. в [версионировании образов](../image_versioning_and_tagging.md).

### Сценарий 4: Получение образа

Скачайте образ из Harbor:

```bash
# Публичный проект (без аутентификации)
docker pull harbor.example.com/library/nginx:1.25

# Приватный проект (требуется аутентификация)
docker login harbor.example.com
docker pull harbor.example.com/my-project/my-app:v1.0.0
```

### Сценарий 5: Работа с Helm-чартами

Harbor поддерживает хранение Helm-чартов через OCI:

```bash
# Вход в реестр
helm registry login harbor.example.com -u admin -p <password>

# Публикация чарта
helm push my-chart-1.0.0.tgz oci://harbor.example.com/my-project

# Установка чарта
helm install my-release oci://harbor.example.com/my-project/my-chart --version 1.0.0
```

## Дополнительная информация

### Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unauthorized: authentication required` | Не выполнена аутентификация | Выполните `docker login` |
| `denied: requested access to the resource is denied` | Недостаточно прав | Проверьте права пользователя/робот-аккаунта |
| `tls: failed to verify certificate` | Недоверенный сертификат | Установите корневой CA (см. [сертификаты](./certificates.md)) |
| `manifest unknown` | Образ с таким тегом не найден | Проверьте имя тега в UI Harbor |

### Лучшие практики

* **Используйте робот-аккаунты для CI/CD**: Не применяйте учётные данные пользователей в автоматизации
* **Фиксируйте версии по дайджесту**: Для production используйте `image@sha256:...` вместо тегов
* **Очищайте старые образы**: Настройте политики хранения для удаления устаревших версий
* **Сканируйте образы**: Включите автоматическое сканирование на уязвимости при push

### Связанные документы

[Обзор Harbor](./overview.md) описывает возможности реестра. [Установка Harbor](./installation.md) — развёртывание через Docker Compose и Helm. [Создание сертификатов](./certificates.md) — настройка TLS для доверия клиентов. [Версионирование образов](../image_versioning_and_tagging.md) — стратегии тегирования. [Docker Registry](../docker_registries.md) — общие принципы работы с реестрами.
