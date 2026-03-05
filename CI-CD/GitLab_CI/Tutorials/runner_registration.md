# Регистрация GitLab Runner

### Определения

- **[GitLab Runner](https://docs.gitlab.com/runner/)**: Отдельное приложение, которое выполняет задания (jobs) из пайплайнов GitLab CI/CD. Runner опрашивает сервер GitLab, забирает задачи и выполняет их в указанной среде.
- **[Executor](https://docs.gitlab.com/runner/executors/)**: Модуль внутри Runner'а, определяющий, как и где будут выполняться скрипты (в Docker-контейнере, на хосте через shell или в Kubernetes Pod).
- **Регистрационный токен**: Уникальный токен, связывающий Runner с конкретным проектом или группой в GitLab.

### Основные концепции

#### Типы Runner'ов по области видимости

| Тип | Область видимости | Контроль | Использование |
| :--- | :--- | :--- | :--- |
| **Shared** | Вся инстанция GitLab | Администраторы | Общие задачи |
| **Group** | Все проекты в группе | Владельцы группы | Командные задачи |
| **Specific** | Конкретный проект | Владельцы проекта | Специфичные задачи |

Подробнее о типах Runner'ов см. в статье: **[Обзор Runner'ов и Исполнителей в GitLab CI](../Advanced/gitlab_ci_runners_executors.md)**.

#### Docker Executor

Docker Executor — один из наиболее популярных типов исполнителей. Он запускает каждую задачу в изолированном Docker-контейнере, что обеспечивает воспроизводимость и безопасность.

### Предварительные требования

1. **Проект в GitLab.**
2. **Сервер** (Linux), на котором будет работать Runner.
3. **Установленный Docker** на этом сервере.

## Практический сценарий: Регистрация Runner с Docker Executor

### Шаг 1: Получение регистрационного токена

1. В вашем проекте GitLab перейдите в **Settings > CI/CD**.
2. Найдите раздел **Runners** и нажмите **Expand**.
3. В секции "Register a new project runner" вы увидите URL вашего инстанса GitLab и **регистрационный токен**. Скопируйте токен.
4. **Рекомендация:** На этой же странице отключите опцию **Enable shared runners for this project**, чтобы гарантировать, что пайплайны будут использовать только ваш собственный Runner.

### Шаг 2: Запуск интерактивной регистрации

1. Подключитесь к серверу по SSH.
2. Выполните команду `docker run` для запуска процесса регистрации. Эта команда запустит временный контейнер, который задаст вам несколько вопросов и создаст конфигурационный файл.

```bash
# Эта команда запустит интерактивный процесс регистрации
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v16.2.0 \
  register
```

**Разбор команды:**

- `--rm -it`: Запускает контейнер в интерактивном режиме и автоматически удаляет его после завершения.
- `-v /srv/gitlab-runner/config:/etc/gitlab-runner`: **Критически важный шаг.** Мы монтируем директорию с хоста (`/srv/gitlab-runner/config`) внутрь контейнера. В этой директории Runner создаст файл `config.toml`, который будет сохранен на хосте и использован для постоянной работы.
- `-v /var/run/docker.sock:/var/run/docker.sock`: Позволяет Runner'у внутри контейнера управлять Docker-демоном на хост-машине для запуска CI/CD-задач.
- `gitlab/gitlab-runner:alpine-v16.2.0`: Используем образ Runner'а с **зафиксированной версией**, а не `latest`, для предсказуемости.
- `register`: Команда, инициирующая процесс регистрации.

### Шаг 3: Ответы на вопросы

В интерактивном режиме Runner задаст вам несколько вопросов:

1. **"Enter the GitLab instance URL..."**: Введите URL вашего GitLab (например, `https://gitlab.com/`).
2. **"Enter the registration token..."**: Вставьте токен, скопированный на Шаге 1.
3. **"Enter a description for the runner..."**: Введите понятное имя (например, `docker-runner-prod`).
4. **"Enter tags for the runner..."**: Введите теги через запятую (например, `docker, linux`). Теги позволяют направлять задачи на конкретные Runner'ы).
5. **"Enter the executor..."**: Введите `docker`.
6. **"Enter the default Docker image..."**: Введите образ, который будет использоваться по умолчанию, если в `.gitlab-ci.yml` не указан другой (например, `alpine:latest`).

После этого вы увидите сообщение "Runner registered successfully". Файл `config.toml` появится в директории `/srv/gitlab-runner/config` на вашем хосте.

### Шаг 4: Запуск Runner'а как сервиса

Теперь, когда конфигурация создана, запустим Runner как постоянный фоновый сервис.

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v16.2.0
```

- `-d`: Запуск в фоновом режиме (detached).
- `--name gitlab-runner`: Присваиваем контейнеру постоянное имя для удобства управления.
- `--restart always`: Гарантирует, что Runner будет автоматически перезапускаться вместе с сервером.

Проверить статус можно командой `docker ps`.

### Шаг 5: Проверка в GitLab

Вернитесь в GitLab в раздел **Settings > CI/CD > Runners**. Ваш новый Runner должен появиться в списке "Project runners" с зеленым индикатором, означающим, что он на связи и готов к работе.

## Дополнительная информация

### Альтернативный сценарий: Регистрация с Shell Executor

`shell` executor — самый простой способ начать работу, но он **не рекомендуется для production** из-за отсутствия изоляции и рисков для безопасности. Он выполняет CI/CD-задачи непосредственно на хост-машине.

1. **Установка:** Установите GitLab Runner как бинарный файл, а не через Docker, следуя [официальной инструкции](https://docs.gitlab.com/runner/install/linux-repository.html).

    ```bash
    # Для Debian/Ubuntu:
    curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
    sudo apt-get install gitlab-runner
    ```

2. **Регистрация:** Запустите `sudo gitlab-runner register` и в качестве Executor'а выберите `shell`.
3. **Статус:** Runner будет запущен как системный сервис. Проверить его можно командой `sudo gitlab-runner status`.

### Связанные документы

- **[Обзор Runner'ов и Исполнителей в GitLab CI](../Advanced/gitlab_ci_runners_executors.md)** — подробное сравнение типов executor'ов.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Kubernetes Executor.
- **[Официальная документация GitLab Runner](https://docs.gitlab.com/runner/)**
