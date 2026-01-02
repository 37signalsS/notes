# Практическое руководство: Регистрация GitLab Runner с Docker Executor

## Шаг 1: Подготовка и получение токена

1.  **Создайте проект в GitLab**, если у вас его еще нет.
2.  Перейдите в ваш проект.
3.  В левом меню выберите **Settings > CI/CD**.
4.  Найдите раздел **Runners** и нажмите **Expand**.
5.  В секции "Register a new project runner" вы увидите URL вашего инстанса GitLab и **регистрационный токен**. Скопируйте этот токен, он понадобится на следующем шаге.
6.  (Рекомендация) На этой же странице можно отключить опцию **Enable shared runners for this project**, чтобы убедиться, что ваши пайплайны будут использовать только ваш собственный Runner.

## Шаг 2: Регистрация Runner

Этот шаг выполняется на сервере, где будет работать ваш Runner. На сервере должен быть установлен Docker.

1.  Подключитесь к вашему серверу по SSH.
2.  Выполните следующую команду `docker run` для запуска процесса регистрации. Эта команда запустит временный контейнер, который задаст вам несколько вопросов и создаст конфигурационный файл.

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v14.10.0 \
  register
```

**Разбор команды:**
*   `--rm -it`: Запускает контейнер в интерактивном режиме и автоматически удаляет его после завершения.
*   `-v /srv/gitlab-runner/config:/etc/gitlab-runner`: **Очень важный шаг.** Мы монтируем директорию `/srv/gitlab-runner/config` с хост-машины внутрь контейнера. Именно в этой директории сохранится итоговый файл конфигурации `config.toml`, который позволит запускать Runner постоянно. Вы можете выбрать любой другой путь вместо `/srv/gitlab-runner/config`.
*   `-v /var/run/docker.sock:/var/run/docker.sock`: Это позволяет GitLab Runner'у взаимодействовать с Docker-демоном на хост-машине, чтобы запускать дочерние контейнеры для выполнения CI/CD задач.
*   `gitlab/gitlab-runner:alpine-v14.10.0`: Указываем конкретную, зафиксированную версию образа Runner'а. Рекомендуется использовать теги с версиями, а не `latest`.
*   `register`: Команда, которая запускает процесс интерактивной регистрации.

## Шаг 3: Интерактивная настройка

После запуска команды выше, Runner задаст вам несколько вопросов:

1.  **"Please enter the gitlab-ci coordinator URL..."**: Введите URL вашего GitLab, который вы видели на странице Runners (например, `https://gitlab.com/` или `https://gitlab.example.com/`).
2.  **"Please enter the registration token..."**: Вставьте токен, который вы скопировали на Шаге 1.
3.  **"Please enter a description for the runner..."**: Введите понятное имя для Runner'а (например, `my-docker-runner`).
4.  **"Please enter tags for the runner..."**: Введите теги через запятую (например, `docker, linux`). Теги позволяют направлять задачи на конкретные Runner'ы. Этот шаг можно пропустить, нажав Enter.
5.  **"Please enter the executor..."**: Введите `docker`.
6.  **"Please enter the default Docker image..."**: Введите имя образа, который будет использоваться по умолчанию для задач, если в `.gitlab-ci.yml` не указан другой (например, `alpine:latest`).

После этого вы увидите сообщение "Runner registered successfully". В директории `/srv/gitlab-runner/config` на вашем хосте появится файл `config.toml`.

## Шаг 4: Запуск Runner как сервиса

Теперь, когда у нас есть файл конфигурации, можно запустить Runner как постоянный фоновый процесс.

Выполните ту же команду, что и для регистрации, но с небольшими изменениями:
*   Замените `-it` на `-d` (detach), чтобы запустить в фоне.
*   Уберите команду `register`.
*   Добавьте `--name gitlab-runner`, чтобы дать контейнеру постоянное имя.

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v14.10.0
```
*   `--restart always`: Гарантирует, что Runner будет автоматически перезапускаться вместе с сервером.

Проверить, что Runner запущен, можно командой `docker ps`.

## Шаг 5: Проверка в GitLab

Вернитесь в GitLab в раздел **Settings > CI/CD > Runners**. Вы должны увидеть свой новый Runner в списке "Project runners" с зеленым кружком, означающим, что он на связи.
