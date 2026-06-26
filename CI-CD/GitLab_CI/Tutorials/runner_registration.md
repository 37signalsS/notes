# Регистрация GitLab Runner

## Определения

**GitLab Runner** — это агент с открытым исходным кодом, который работает в GitLab CI/CD для выполнения заданий (jobs) из пайплайна.

**Executor** — компонент Runner'а, который определяет среду выполнения задания (например, Docker, Shell, VirtualBox).

**Регистрационный токен (Registration Token)** — уникальный токен, связывающий Runner с конкретным проектом или группой в GitLab.

Базовые понятия подробно описаны в статье: **[Обзор GitLab Runners и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)**.

## Основные концепции

Для успешной регистрации и работы Runner'а необходимо соблюдение следующих условий:

1. **Доступ к инстансу GitLab:** Runner должен иметь сетевой доступ к URL GitLab по протоколу HTTP/HTTPS.
2. **Типы Runner'ов:**
    - **Project runners:** Привязаны к конкретному проекту.
    - **Group runners:** Доступны для всех проектов в группе.
    - **Shared runners:** Доступны для всех проектов инстанса (предоставляются администратором).
3. **Безопасность:** Регистрационный токен является конфиденциальной информацией. После регистрации Runner получает собственный `authentication token` для дальнейшей работы.

## Практические сценарии

### Сценарий 1: Регистрация Runner с Docker Executor (Рекомендуемый)

Docker Executor обеспечивает изоляцию сред выполнения и повторяемость результатов.

#### Шаг 1: Получение регистрационного токена

1. В проекте GitLab перейдите в **Settings > CI/CD**.
2. Найдите раздел **Runners** и нажмите **Expand**.
3. В секции "Register a new project runner" скопируйте **URL** и **registration token**.
4. Рекомендуется отключить опцию **Enable shared runners for this project**, если вы планируете использовать только собственные ресурсы.

#### Шаг 2: Запуск интерактивной регистрации

Подключитесь к серверу и выполните команду для запуска процесса регистрации через временный контейнер:

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v17.0.0 \
  register
# → Runtime platform arch=amd64 os=linux pid=7 revision=... version=...
# → Running in system-mode.
```

**Параметры команды:**
- `-v /srv/gitlab-runner/config:/etc/gitlab-runner` — монтирование директории для сохранения `config.toml`.
- `-v /var/run/docker.sock:/var/run/docker.sock` — доступ к Docker-демону хоста для запуска контейнеров заданий.
- `register` — запуск встроенного мастера регистрации.

#### Шаг 3: Ввод параметров конфигурации

Следуйте подсказкам мастера:
1. **URL:** Введите адрес GitLab (например, `https://gitlab.com/`).
2. **Token:** Вставьте скопированный регистрационный токен.
3. **Description:** Имя Runner'а (например, `docker-runner-prod`).
4. **Tags:** Список тегов через запятую (`docker, linux`).
5. **Executor:** Выберите `docker`.
6. **Default Image:** Образ по умолчанию (`alpine:latest`).

После завершения вы увидите:
`# → Runner registered successfully. Feel free to start it, but if it's running already the config should be reloaded automatically!`

#### Шаг 4: Запуск Runner'а как постоянного сервиса

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v17.0.0
# → a1b2c3d4e5f6... (ID контейнера)
```

Проверьте статус:
```bash
docker ps
# → CONTAINER ID   IMAGE                         STATUS         NAMES
# → a1b2c3d4e5f6   gitlab/gitlab-runner:alpine   Up 5 seconds   gitlab-runner
```

### Сценарий 2: Регистрация с Shell Executor

Shell Executor выполняет задачи напрямую в ОС хоста. Используется для простых задач или когда деплой требует прямого доступа к инструментам сервера.

1. **Установка:**
    ```bash
    curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
    # → Repository successfully installed
    sudo apt-get install gitlab-runner
    # → gitlab-runner is already the newest version
    ```

2. **Регистрация:**
    ```bash
    sudo gitlab-runner register
    # → Enter the GitLab instance URL: https://gitlab.com/
    # → Enter the registration token: [TOKEN]
    # → Enter the executor: shell
    # → Runner registered successfully.
    ```

## Дополнительная информация

### Специфические Runner'ы для инфраструктуры

Для задач управления инфраструктурой (Ansible, Terraform) рекомендуется выделять отдельные Runner'ы:

- **Изоляция:** Ограничение доступа через `tags` (например, `infra`) гарантирует, что только проверенные пайплайны получат доступ к критическим ключам.
- **Protected Runners:** В настройках GitLab можно пометить Runner как "Protected", тогда он будет выполнять задания только из защищенных веток и тегов.

### Смотрите также

- **[Обзор GitLab Runners и Executor'ов](../Advanced/gitlab_ci_runners_executors.md)** — сравнение типов исполнителей.
- **[Интеграция GitLab CI с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — использование Kubernetes Executor.
- **[Интеграция Ansible с GitLab CI/CD](./ansible_integration.md)** — пример использования тегов для деплоя.
