# Регистрация GitLab Runner

## Определения

**GitLab Runner** — это агент (приложение на языке Go), который опрашивает сервер GitLab на наличие заданий (jobs), выполняет их и возвращает результат (логи, артефакты). Runner работает по принципу исходящих соединений (Pull-модель) и не требует входящего доступа извне.

**Executor (Исполнитель)** — компонент Runner, определяющий изолированную среду выполнения задания (Docker, Shell, Kubernetes, VirtualBox). Подробнее см. **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**.

**Runner Manager** — экземпляр службы `gitlab-runner`, запущенный на конкретном хосте. Один менеджер может управлять несколькими зарегистрированными раннерами через один файл конфигурации.

**Токен аутентификации (Authentication Token)** — уникальный секрет с префиксом `glrt-` (например, `glrt-t1_xxxx`). Начиная с версии GitLab 16.0, это основной способ регистрации. Токен привязан к конкретной конфигурации раннера, созданной в интерфейсе GitLab.

## Основные концепции (GitLab 17.0+)

С выходом GitLab 17.0 старый метод регистрации через *Registration Token* (общий токен для группы или проекта) полностью отключен по умолчанию (ошибка `410 Gone`).

**Архитектура регистрации (UI-First):**
1.  **Декларация:** Вы создаете запись о раннере в интерфейсе GitLab (Admin, Group или Project). Здесь вы заранее определяете теги, тип исполнения (защищенные ветки) и описание.
2.  **Токенизация:** GitLab генерирует `glrt-` токен. Он отображается один раз и является единственным ключом для связки локального менеджера с серверной записью.
3.  **Связывание:** Вы запускаете `register` на целевой машине, передавая только URL сервера и `glrt-` токен. Локальные настройки (executor) дополняют серверную конфигурацию.

---

## Практические сценарии

### Сценарий 1: Регистрация с Docker Executor (Рекомендуемый)

Этот сценарий предполагает запуск раннера в Docker-контейнере для изоляции процессов сборки.

#### 1. Создание в интерфейсе GitLab
1.  Перейдите в **Settings > CI/CD > Runners** (или **Admin Area > Runners** для общего раннера).
2.  Нажмите **New project runner**.
3.  Выберите платформу (`Linux`) и укажите **Tags** (например, `docker, nodejs`).
4.  Нажмите **Create runner** и скопируйте токен `glrt-...`.

#### 2. Выполнение регистрации (One-off container)
Используйте временный контейнер для генерации `config.toml`:

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine-v17.5.0 \
  register \
    --non-interactive \
    --url "https://gitlab.example.com/" \
    --token "glrt-YOUR_TOKEN_HERE" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock" \
    --docker-network-mode "bridge"
```

#### 3. Запуск постоянного сервиса
```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v17.5.0
```

---

### Сценарий 2: Регистрация на Linux (Shell Executor)

Подходит для задач, требующих прямого доступа к ресурсам хоста (например, для сборки системных пакетов).

```bash
# Регистрация
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_TOKEN_HERE" \
  --executor "shell"

# Проверка статуса
sudo gitlab-runner status
# → gitlab-runner: Service is running
```

---

### Сценарий 3: Массовая регистрация через API (IaC)

Для автоматизации через Ansible или Terraform используйте GitLab API. Требуется Personal Access Token (PAT) с правами `api`.

```bash
# 1. Создание записи раннера через API
RESPONSE=$(curl --request POST "https://gitlab.example.com/api/v4/user/runners" \
     --header "PRIVATE-TOKEN: ${GITLAB_PAT}" \
     --data "runner_type=project_type" \
     --data "project_id=42" \
     --data "tag_list=autoscale,high-cpu" \
     --data "description=API-Registered-Runner")

# 2. Извлечение токена
AUTH_TOKEN=$(echo $RESPONSE | jq -r .token)

# 3. Регистрация на узле
gitlab-runner register --non-interactive --url "https://gitlab.example.com/" --token "$AUTH_TOKEN" --executor "docker" --docker-image "ruby:3.2"
```

---

### Сценарий 4: Использование шаблонов конфигурации (--template-config)

Если вам нужно применить сложные настройки (например, лимиты памяти в Docker или настройки кэширования S3) при регистрации множества раннеров, используйте файл-шаблон.

**Файл `template.toml`:**
```toml
[[runners]]
  [runners.docker]
    memory = "4g"
    cpus = "2"
    privileged = false
  [runners.cache]
    Type = "s3"
    Path = "shared-cache"
    [runners.cache.s3]
      ServerAddress = "s3.amazonaws.com"
      BucketName = "my-gitlab-cache"
```

**Команда регистрации:**
```bash
gitlab-runner register \
  --token "glrt-..." \
  --url "https://gitlab.com/" \
  --template-config /path/to/template.toml \
  --executor "docker"
```

---

## После регистрации: Структура config.toml

После успешной регистрации в файле `/etc/gitlab-runner/config.toml` появляется блок `[[runners]]`.

*   **`concurrent`**: Глобальный лимит одновременно выполняемых задач на этом менеджере.
*   **`check_interval`**: Частота опроса сервера GitLab (в секундах).
*   **`token`**: Здесь хранится ваш `glrt-` токен. Никогда не передавайте его третьим лицам.
*   **`executor`**: Выбранный тип среды выполнения.

---

## Решение проблем (Troubleshooting)

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **410 Gone** | Попытка регистрации через устаревший Registration Token | Используйте `glrt-` токен, созданный в UI GitLab 16.0+. |
| **403 Forbidden** | PAT не имеет прав `api` или пользователь не владелец проекта | Проверьте Scope у токена и права доступа в GitLab. |
| **Runner is Offline в UI** | Служба `gitlab-runner` не запущена на хосте | Выполните `gitlab-runner run` или проверьте `systemctl status`. |
| **Certificate verify failed** | Самоподписанный сертификат GitLab | Добавьте `--tls-ca-file` или импортируйте CA в доверенные системные. |
| **glrt- token not found** | Токен был удален в UI GitLab | Создайте новый раннер в UI и выполните перерегистрацию. |

---

## Дополнительная информация

### Уровни раннеров
1.  **Shared (Общие):** Доступны всем проектам (настраиваются в Admin Area).
2.  **Group (Групповые):** Доступны всем проектам внутри конкретной группы.
3.  **Project (Проектные):** Привязаны к одному конкретному репозиторию.

### Безопасность
*   **Protected Runners:** Включайте эту опцию в UI для раннеров, имеющих доступ к продакшн-секретам. Такие раннеры будут запускать задачи только из защищенных веток/тегов.
*   **Runtime Isolation:** Для недоверенного кода всегда используйте Docker или Kubernetes Executor вместо Shell.

### Смотрите также
*   **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — архитектура и выбор исполнителя.
*   **[GitLab Runner в Docker Compose](./gitlab_runner_docker_compose.md)** — развертывание полного стека локально.
*   **[Интеграция с Kubernetes](../Advanced/gitlab_kubernetes_integration_guide.md)** — регистрация в кластере через Helm.
