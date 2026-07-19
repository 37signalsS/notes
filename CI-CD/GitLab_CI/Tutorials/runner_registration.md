# Регистрация GitLab Runner

## Определения

**GitLab Runner** — это агент с открытым исходным кодом, который работает в GitLab CI/CD для выполнения заданий (jobs) из пайплайна.

**Executor** — компонент Runner'а, который определяет среду выполнения задания (например, Docker, Shell, Kubernetes).

**Токен аутентификации (Authentication Token)** — уникальный токен с префиксом `glrt-`, который выдается GitLab при создании записи Runner'а в интерфейсе. Это современный и безопасный способ регистрации (с версии 16.0).

Базовые понятия подробно описаны в статье: **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**.

## Основные концепции

С версии **GitLab 16.0** процесс регистрации изменился:

1. **Создание в UI:** Сначала вы создаете Runner в интерфейсе GitLab (на уровне проекта, группы или всего инстанса).
2. **Настройка:** Вы заранее указываете теги, описание и настройки защиты в интерфейсе.
3. **Регистрация:** Вы запускаете команду `register` на сервере, используя полученный токен `glrt-`.

> **Важно:** Старый метод с использованием *Registration Token* (ввод токена и последующая настройка тегов в CLI) считается устаревшим и может быть отключен в новых версиях GitLab (17.0+).

## Практические сценарии

### Сценарий 1: Современная регистрация с Docker Executor (Рекомендуемый)

#### Шаг 1: Создание Runner в интерфейсе GitLab

1. Перейдите в **Settings > CI/CD > Runners**.
2. Нажмите **New project runner** (или Group runner).
3. Укажите платформу (например, `linux`).
4. Введите **Tags** (например, `docker, build`). Это критично: Runner будет брать только задачи с этими тегами.
5. Нажмите **Create runner**.
6. Скопируйте появившуюся команду регистрации или только **Runner authentication token** (начинается с `glrt-`).

#### Шаг 2: Запуск регистрации на сервере

Выполните команду через временный Docker-контейнер (замените `YOUR_TOKEN` на токен `glrt-`):

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine-v17.0.0 \
  register \
    --non-interactive \
    --url "https://gitlab.com/" \
    --token "YOUR_TOKEN" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock"
# → Runner registered successfully.
```

#### Шаг 3: Запуск Runner как постоянного сервиса

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v17.0.0
```

### Сценарий 2: Регистрация с Shell Executor (Linux)

1. **Установка:**
    ```bash
    curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
    sudo apt-get install gitlab-runner
    ```

2. **Регистрация:**
    Создайте Runner в UI GitLab, получите токен и выполните:
    ```bash
    sudo gitlab-runner register \
      --url "https://gitlab.com/" \
      --token "glrt-XXXXXXXX" \
      --executor "shell"
    ```

## Дополнительная информация

### Массовое развертывание
Для автоматизации (Ansible, Terraform) используйте заранее созданные токены или механизмы автоматического создания через API GitLab.

### Безопасность
- **Никогда** не сохраняйте `config.toml` в публичных репозиториях, так как он содержит токен аутентификации.
- Используйте **[Secrets Manager](../Concepts/gitlab_ci_variables_secrets.md)** для передачи чувствительных данных в пайплайны.

### Смотрите также

- **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — архитектура и выбор типа исполнителя.
- **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — установка через Helm.
- **[GitLab Runner в Docker Compose](./gitlab_runner_docker_compose.md)** — запуск стека локально.
