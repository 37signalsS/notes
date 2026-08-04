# Регистрация GitLab Runner

## Определения

**GitLab Runner** — это агент (приложение на Go), который опрашивает сервер GitLab на наличие заданий (jobs), выполняет их и возвращает результат.

**Executor (Исполнитель)** — компонент Runner'а, определяющий среду выполнения задания (Docker, Shell, Kubernetes, VirtualBox). Подробнее см. **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**.

**Runner Manager** — экземпляр службы `gitlab-runner`, запущенный на конкретном хосте. Один менеджер может управлять несколькими зарегистрированными раннерами.

**Токен аутентификации (Authentication Token)** — уникальный секрет с префиксом `glrt-`. С версии 16.0 это единственный способ регистрации. В отличие от старых токенов, он создается **до** регистрации и привязан к конкретной конфигурации раннера в UI/API.

## Основные концепции (GitLab 16.0+)

С выходом GitLab 17.0 старый метод с использованием *Registration Token* (общий токен для всего проекта) отключен по умолчанию (ошибка `410 Gone`).

**Новый процесс (UI-First):**
1. **Создание записи:** Вы создаете объект Runner в интерфейсе GitLab или через API.
2. **Получение токена:** GitLab выдает токен `glrt-`. **Внимание:** Он показывается только один раз.
3. **Регистрация:** Вы привязываете локальный Runner Manager к этой записи с помощью команды `register --token glrt-...`.

## Практические сценарии

### Сценарий 1: Регистрация с Docker Executor (Рекомендуемый)

#### Шаг 1: Создание в интерфейсе
1. Перейдите в **Settings > CI/CD > Runners**.
2. Нажмите **New project runner**.
3. Укажите платформу (`linux`) и **Tags** (например, `docker, build`). 
    - *Важно:* Параметры (теги, доступ к незащищенным веткам) теперь настраиваются **только** здесь, а не в CLI.
4. Нажмите **Create runner** и скопируйте токен `glrt-...`.

#### Шаг 2: Выполнение регистрации
Используйте временный контейнер для создания конфигурации:

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine-v17.2.0 \
  register \
    --non-interactive \
    --url "https://gitlab.com/" \
    --token "glrt-YOUR_AUTHENTICATION_TOKEN" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock"
```

#### Шаг 3: Запуск постоянного сервиса
```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v17.2.0
```

### Сценарий 2: Автоматическая регистрация через API (DevOps-подход)

Для массового развертывания (Ansible/Terraform) используйте Authenticated API. Требуется Personal Access Token (PAT) с правами `api`.

```bash
# 1. Создание раннера и получение glrt- токена
RUNNER_TOKEN=$(curl --request POST "https://gitlab.example.com/api/v4/user/runners" \
     --header "PRIVATE-TOKEN: <YOUR_PAT>" \
     --data "runner_type=project_type" \
     --data "project_id=<ID>" \
     --data "description=autoscale-runner" \
     --data "tag_list=prod,linux" | jq -r .token)

# 2. Регистрация на хосте
gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "$RUNNER_TOKEN" \
  --executor "shell"
```

### Сценарий 3: Удаление раннера (Unregister)

Если раннер больше не нужен, его необходимо правильно отвязать от системы.

```bash
# Удаление конкретного раннера по токену
gitlab-runner unregister --url "https://gitlab.example.com/" --token "glrt-XXXXX"

# Удаление ВСЕХ раннеров, настроенных в локальном config.toml
gitlab-runner unregister --all-runners
```

## Решение проблем (Troubleshooting)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **410 Gone - runner registration disallowed** | Попытка использовать старый Registration Token в GitLab 17.0+ | Используйте новый метод с `glrt-` токеном. |
| **403 Forbidden** | Недостаточно прав у токена или PAT | Проверьте Scope у PAT (`api`) или права пользователя в проекте. |
| **ERROR: Registering runner... failed** | Проблемы с TLS-сертификатом | Используйте `--template-config` или добавьте CA в доверенные. |
| **Runner is offline (UI)** | Runner Manager не запущен или нет связи | Проверьте `systemctl status gitlab-runner` или логи Docker. |

## Дополнительная информация

### Безопасность
- **Токен в безопасности:** После регистрации `glrt-` токен сохраняется в `/etc/gitlab-runner/config.toml`. Защитите этот файл (права `600`).
- **Защищенные ветки:** В настройках раннера (UI) включьте "Protected", если он имеет доступ к продакшн-секретам.

### Смотрите также

- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — глубокая теория.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — Helm-чарты используют те же `glrt-` токены.
- **[GitLab Runner в Docker Compose](./gitlab_runner_docker_compose.md)** — локальное окружение.
