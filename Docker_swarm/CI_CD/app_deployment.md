# Развертывание приложения в Docker Swarm через GitLab CI

## Определения

- **Стек приложения (Application Stack):** Логическая группа сервисов, описанная в Stack-файле (YAML), которая управляется как единое целое. Включает в себя настройки репликации, лимиты ресурсов и сетевые правила.
- **Область окружения (Environment Scope):** Функционал GitLab CI для разграничения переменных и секретов между средами (`staging`, `production`). Позволяет безопасно хранить разные сертификаты mTLS для разных кластеров. Подробнее в **[Переменные и секреты GitLab CI](../../CI-CD/GitLab_CI/Concepts/gitlab_ci_variables_secrets.md)**.
- **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md):** Утилита для сборки образов в userspace. Является стандартом для безопасных CI-пайплайнов, так как не требует привилегий root или доступа к `docker.sock`.
- **[Docker Context](../CI_CD/docker_context_setup.md):** Механизм изоляции параметров подключения. В CI/CD позволяет пайплайну переключаться между кластерами одной командой, инкапсулируя внутри себя адрес менеджера и пути к TLS-ключам.

## Базовые концепции

### Архитектура конвейера доставки (CD)

Процесс доставки приложения в Swarm-кластер строится по принципу разделения сред сборки и исполнения:

1. **Этап сборки (Build):**
   - Используется изолированный образ Kaniko.
   - Сборка образа происходит с использованием кэширования слоев в удаленном реестре (`--cache=true`).
   - Образ тегируется уникальным идентификатором коммита `${CI_COMMIT_SHA}` и, опционально, `${CI_COMMIT_TAG}`.
2. **Промежуточное хранение (Registry):**
   - Образ пушится в GitLab Container Registry или внешний реестр (Harbor).
   - Swarm-менеджеры должны иметь сетевой доступ к реестру для последующего скачивания образа воркерами.
3. **Этап развертывания (Deploy):**
   - Раннер создает временный Docker Context.
   - Выполняется команда `docker stack deploy`, которая отправляет обновленную спецификацию на Swarm Manager через mTLS (порт 2376).
   - Менеджеры кластера инициируют Rolling Update.

### Безопасность и управление секретами

- **Аутентификация через mTLS:** Раннер должен обладать клиентским сертификатом, подписанным тем же CA, что и Docker Daemon на менеджерах.
- **Тип переменных File:** В GitLab CI сертификаты (`ca.pem`, `cert.pem`, `key.pem`) следует хранить как переменные типа `File`, чтобы избежать их прямого вывода в логи и упростить передачу путей в Docker Context.
- **Флаг `--with-registry-auth`:** Критически важный параметр. При его использовании менеджер кластера передает временный токен авторизации реестра на все рабочие узлы (Workers), что избавляет от необходимости выполнять `docker login` на каждом сервере вручную.

## Практические сценарии

### Сценарий 1: Эталонный пайплайн .gitlab-ci.yml

Пример конфигурации, использующей современные практики безопасности и управления контекстами:

```yaml
stages:
  - build
  - deploy

variables:
  # Использование форка kaniko для актуальных исправлений
  KANIKO_IMAGE: "osscontainertools/kaniko:v1.28.0"
  STACK_NAME: "myapp-prod"

build_app:
  stage: build
  image:
    name: $KANIKO_IMAGE
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor 
      --context $CI_PROJECT_DIR 
      --dockerfile $CI_PROJECT_DIR/Dockerfile 
      --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
      --cache=true

deploy_prod:
  stage: deploy
  image: docker:29.x
  environment:
    name: production
    url: https://myapp.example.com
  script:
    # Создание контекста "на лету" из переменных типа File
    - docker context create remote-swarm 
      --docker "host=tcp://$SWARM_MANAGER_IP:2376,ca=$DOCKER_CA,cert=$DOCKER_CERT,key=$DOCKER_KEY"
    - docker context use remote-swarm
    # Авторизация в реестре для передачи прав воркерам
    - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
    # Деплой с обновлением образов
    - docker stack deploy -c docker-compose.yml $STACK_NAME --with-registry-auth --prune
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Сценарий 2: Верификация успешности деплоя

Так как `docker stack deploy` завершается сразу после принятия команды менеджером, необходимо добавить проверку реального состояния сервисов:

```bash
# В секции script после деплоя:
- |
  echo "Ожидание стабилизации сервисов..."
  for i in {1..30}; do
    STATUS=$(docker stack services $STACK_NAME --format "{{.Replicas}}")
    if [[ "$STATUS" == *"3/3"* ]]; then # Замените 3/3 на ожидаемое кол-во реплик
      echo "Деплой успешно завершен"
      exit 0
    fi
    sleep 10
  done
  echo "Ошибка: Время ожидания стабилизации истекло"
  docker stack ps $STACK_NAME --no-trunc
  exit 1
```

## Дополнительная информация

### Управление переменными по окружениям

Используйте **Protected Variables** для продакшена. Это гарантирует, что секреты кластера (сертификаты) будут доступны только в пайплайнах, запущенных в защищенных ветках (`main`, `master`) или по тегам.

### Диагностика проблем

| Симптом | Причина | Решение |
|:---|:---|:---|
| `context deadline exceeded` | Закрыт порт 2376 или неверный IP | Проверить Firewall и значение `$SWARM_MANAGER_IP`. |
| `image not found` на воркерах | Отсутствует `--with-registry-auth` | Добавить флаг в команду `docker stack deploy`. |
| Обновление зависло (Pending) | Недостаточно ресурсов на узлах | Проверить `docker node inspect` и лимиты в YAML. |
| Ошибка сертификата | SAN сертификата не включает IP | См. **[swarm_setup.md](./swarm_setup.md)** (Сценарий 2). |

### Связанные документы

- **[app_lifecycle.md](./app_lifecycle.md)** — глубокий разбор Rolling Update, Health Checks и Rollback.
- **[swarm_setup.md](./swarm_setup.md)** — инструкция по генерации mTLS сертификатов и настройке порта 2376.
- **[best_practices.md](./best_practices.md)** — общие рекомендации по эксплуатации Swarm.
- **[docker_context_setup.md](./docker_context_setup.md)** — нюансы работы с контекстами.
- **[infra_deployment.md](./infra_deployment.md)** — развертывание системных компонентов (Traefik).

