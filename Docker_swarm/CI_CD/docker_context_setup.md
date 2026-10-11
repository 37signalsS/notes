# Использование Docker Context в CI/CD для Docker Swarm

> **Статус:** Docker Swarm не развивается. Применяется только для поддержки существующих
> развёртываний; для новых — Kubernetes.

**Актуально для:** Docker Engine 29.x+, Docker CLI 29.x+

Общие сведения о механизме контекстов см. в основном разделе **[Docker Context](../../Docker/docker_context.md)**. В данном документе рассматривается специфика использования контекстов для автоматизации развертывания в кластере Docker Swarm.

## Определения

- **[Docker Context](../../Docker/docker_context.md):** Механизм управления профилями подключения к различным Docker-хостам. Позволяет инкапсулировать параметры (адрес API, сертификаты mTLS, настройки SSH) и быстро переключаться между ними в рамках CLI.
- **Целевое окружение (Target Environment):** Конкретный экземпляр инфраструктуры (development, staging, production), на который выполняется развертывание кода или конфигураций.
- **[mTLS (mutual TLS)](../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls):** Протокол взаимной проверки сертификатов, используемый контекстом для безопасной авторизации на удаленном Swarm-менеджере по порту 2376.
- **[Docker Swarm Mode](../docker_swarm_overview.md):** Встроенный механизм оркестрации Docker. В контексте CI/CD контексты используются для переключения между кластерами без изменения пайплайнов.
- **Ephemeral Runner (эфемерный раннер):** Раннер, который создаётся заново для каждого джоба и уничтожается после завершения. Не требует `after_script` очистки.
- **Self-hosted Runner (постоянный раннер):** Раннер, который живёт между джобами. Требует обязательной очистки контекста и сертификатов после каждого деплоя.

## Базовые концепции

### Преимущества использования в CI/CD

Использование контекстов вместо прямой передачи переменных окружения (`DOCKER_HOST`, `DOCKER_CERT_PATH`) обеспечивает:

- **Декларативность:** Параметры подключения описываются один раз при создании контекста, далее используются только короткие имена профилей.
- **Изоляция окружений:** Каждый контекст имеет собственный изолированный набор сертификатов, что исключает риск отправки команд не в тот кластер при параллельном выполнении задач.
- **Безопасность:** Снижается риск утечки `DOCKER_HOST` через логи пайплайнов, так как в основных командах деплоя фигурирует только имя контекста.
- **Унификация команд:** Пайплайны используют идентичные команды `docker stack deploy` вне зависимости от того, разворачивается ли приложение на локальный узел или удаленный продакшен.

### Сравнение методов подключения к Swarm Manager из CI/CD

| Критерий | mTLS контекст | SSH контекст | Прямой `DOCKER_HOST` |
|:---|:---|:---|:---|
| Транспорт | TCP 2376/TLS | SSH stdio-канал (port 22) | TCP 2377/Raw |
| Аутентификация | Клиентский сертификат | SSH-ключ | Без аутентификации (не для прода) |
| Безопасность | Высокая (взаимная аутентификация) | Высокая (ключ + `ssh-agent`) | Низкая (открытый порт) |
| Firewall | Порт 2376 только с IP раннеров | Порт 22 только с IP раннеров | Порт 2377 — НЕ открывать |
| Ротация секретов | Перевыпуск через CA | Ротация через `ssh-agent` | Не применима |
| Подходит для продакшена | Да | Да | Нет |
| Зависимость от ssh-agent | Нет | Да | Нет |

### Схема взаимодействия компонентов

1. **Runner (CI):** Извлекает сертификаты из защищенных переменных (Secrets).
2. **CLI (Context):** Создает именованный профиль (например, `swarm-prod`), связывая адрес менеджера и пути к файлам сертификатов.
3. **API (Swarm):** Принимает команды от Runner, проверяя клиентский сертификат (mTLS).
4. **Orchestrator:** Выполняет обновление сервисов в кластере.

### Важное замечание о версиях CLI

В Docker CLI v23.0 поддержка Kubernetes в командах `docker context` и `docker stack` была удалена (депрекация в v20.10). Команда `docker context create --kubernetes` больше не существует. Для работы со Swarm используется только тип endpoint `docker` (mTLS или SSH).

## Предварительные требования

### Инфраструктура

- **Настроенный mTLS:** CA, серверные и клиентские сертификаты на стороне менеджера и раннера. Детали генерации см. в **[swarm_setup.md](./swarm_setup.md)**.
- **Сетевой доступ:** Порт 2376/TCP (mTLS) или 22/TCP (SSH) открыт только с IP-адресов CI-раннеров. Firewall-правило:
  ```bash
  ufw allow from <CI_RUNNER_IP>/32 to any port 2376
  ```
- **Docker Engine и CLI:** Версия 29.x+ на раннере и менеджере. Docker CLI v29 содержит исправления для TLS-валидации (CVE-2025-61727, CVE-2025-61729).
- **Синхронизация времени:** NTP активен на всех нодах. Расхождение более 5 секунд приводит к ошибкам валидации сертификатов (`certificate has expired` при корректном сроке).

### Секреты и permissions

- **Права на ключи:** `chmod 600 ~/.docker/*.pem` — обязательное условие. Docker CLI откажется использовать ключ с более широкими правами.
- **CI-секреты:** Переменные `$CA_PEM`, `$CERT_PEM`, `$KEY_PEM` должны иметь тип `File` (GitLab CI) или `file` (GitHub Actions), чтобы избежать перенаправления в логи.
- **Маскирование:** Переменные с содержимым PEM должны быть помечены как `Masked` в настройках CI/CD.

## Практические сценарии

### Сценарий 1: Локальная настройка и управление удаленным кластером

Для управления Swarm с рабочей станции администратора через mTLS:

1. Разместите клиентские сертификаты в директории `~/.docker/`.
2. Создайте контекст:

   ```bash
   docker context create prod-swarm \
     --docker "host=tcp://prod-manager.example.com:2376,ca=~/.docker/ca.pem,cert=~/.docker/cert.pem,key=~/.docker/key.pem"
   ```
   # → Профиль prod-swarm создан и готов к использованию

3. Активируйте контекст и проверьте связь:

   ```bash
   docker context use prod-swarm
   docker node ls
   ```
   # → Отобразится список узлов удаленного кластера

### Сценарий 2: Динамическое создание контекста в пайплайне GitLab CI

В эфемерных раннерах контекст создается "на лету" перед каждой операцией деплоя.

**Пример `.gitlab-ci.yml`:**

```yaml
deploy_prod:
  stage: deploy
  image: docker:29.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    # Удаление контекста, если он остался от предыдущих запусков (для shared runners)
    - docker context rm -f swarm-ctx || true
    - docker context create swarm-ctx \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-ctx
  script:
    - docker stack deploy -c docker-compose.yml myapp --with-registry-auth
```

### Сценарий 3: Использование SSH контекста (Альтернатива mTLS)

Если в организации принята авторизация по SSH-ключам, Docker Context может использовать прямое подключение через SSH:

```bash
# Создание контекста через SSH
docker context create ssh-swarm \
  --docker "host=ssh://deploy-user@swarm-manager.example.com"
```
# → Доступ к Docker API будет осуществляться через SSH (требует наличия ключа в ssh-agent)

**Важно для CI:** На эфемерных раннерах SSH-ключ должен передаваться через переменную `SSH_PRIVATE_KEY` и добавляться в `ssh-agent` в `before_script`:

```bash
eval "$(ssh-agent -s)"
echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
mkdir -p ~/.ssh
chmod 700 ~/.ssh
```

### Сценарий 4: Верификация контекста после создания

Перед выполнением `docker stack deploy` необходимо убедиться, что контекст работает корректно. Добавьте проверку в `before_script`:

```yaml
deploy_prod:
  stage: deploy
  image: docker:29.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem && echo "$CERT_PEM" > ~/.docker/cert.pem && echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f swarm-prod || true
    - docker context create swarm-prod \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use swarm-prod
    # Верификация: проверяем доступность кластера и роль узла
    - docker info --format '{{.Swarm.LocalNodeState}}' | grep -q "active" || (echo "ERROR: Swarm is not active" && exit 1)
    - docker node ls --format '{{.Hostname}} {{.Status}}' | head -1
  script:
    - docker stack deploy -c docker-compose.yml myapp --with-registry-auth --prune
  after_script:
    - docker context rm -f swarm-prod || true
```

**Что проверяется:**
- `docker info --format '{{.Swarm.LocalNodeState}}'` — подтверждает, что подключение к кластеру работает и Swarm активен.
- `docker node ls` — показывает список узлов (доказывает, что mTLS-аутентификация прошла успешно).

### Сценарий 5: Жизненный цикл контекста в пайплайне (after_script cleanup)

На долгоживущих раннерах (Self-hosted) контексты накапливаются между запусками. Секреты должны очищаться в `after_script`:

```yaml
deploy:
  stage: deploy
  image: docker:29.x
  variables:
    CONTEXT_NAME: "swarm-${CI_ENVIRONMENT_SLUG}"
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
      --docker "host=$DOCKER_HOST,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use ${CONTEXT_NAME}
  script:
    - docker stack deploy -c docker-compose.yml app-${CI_ENVIRONMENT_SLUG} --with-registry-auth --prune
  after_script:
    # Обязательная очистка: удаление контекста и сертификатов
    - docker context rm -f ${CONTEXT_NAME} || true
    - rm -rf ~/.docker/
```

**Важно:** На эфемерных раннерах (GitLab SaaS, GitHub Actions) `after_script` не обязателен — контейнер уничтожается после завершения. Но на Self-hosted раннерах это критично для безопасности.

### Сценарий 6: Мультиокружение через Docker Context (dev/staging/prod)

Для деплоя в несколько окружений из одного пайплайна используйте уникальные имена контекстов:

```yaml
.deploy_template: &deploy_template
  stage: deploy
  image: docker:29.x
  before_script:
    - mkdir -p ~/.docker
    - echo "$CA_PEM" > ~/.docker/ca.pem
    - echo "$CERT_PEM" > ~/.docker/cert.pem
    - echo "$KEY_PEM" > ~/.docker/key.pem
    - chmod 600 ~/.docker/*.pem
    - docker context rm -f ${CONTEXT_NAME} || true
    - docker context create ${CONTEXT_NAME} \
      --docker "host=${DOCKER_HOST},ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
    - docker context use ${CONTEXT_NAME}
    - docker info --format '{{.Swarm.LocalNodeState}}' | grep -q "active"
  script:
    - docker stack deploy -c envs/${ENVIRONMENT}/docker-compose.yml infra-${ENVIRONMENT} --with-registry-auth --prune
  after_script:
    - docker context rm -f ${CONTEXT_NAME} || true
    - rm -rf ~/.docker/

deploy_dev:
  <<: *deploy_template
  variables:
    ENVIRONMENT: dev
    CONTEXT_NAME: swarm-dev
    DOCKER_HOST: tcp://dev-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
      when: manual

deploy_staging:
  <<: *deploy_template
  variables:
    ENVIRONMENT: staging
    CONTEXT_NAME: swarm-staging
    DOCKER_HOST: tcp://staging-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual

deploy_prod:
  <<: *deploy_template
  variables:
    ENVIRONMENT: prod
    CONTEXT_NAME: swarm-prod
    DOCKER_HOST: tcp://prod-manager.example.com:2376
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
```

### Сценарий 7: Docker Context + Buildx (кросс-платформенные сборки)

Docker Context позволяет Buildx собирать образы для нескольких архитектур (amd64, arm64) на удаленном кластере или через удаленный Docker API:

```bash
# Создание контекста для удаленного сборщика
docker context create buildkit-ctx \
  --docker "host=ssh://build-user@build-node.example.com"

# Создание buildx-инстанса, привязанного к контексту
docker buildx create --name multiarch \
  --driver docker-container \
  --use buildkit-ctx

# Сборка для двух архитектур
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t myregistry/myapp:latest \
  --push .
```

**Преимущества:**
- Сборка для arm64 на x86_64 хосте (эмуляция через QEMU или нативно на ARM-нодах).
- Использование удаленного BuildKit для ускорения сборки (кэш, параллелизм).

**Важно:** Для работы `docker-container` драйвера Buildx требуется, чтобы целевой Docker-хост поддерживал запуск контейнеров. Не все Swarm-менеджеры подходят по ресурсам — для сборки лучше выделить отдельную ноду (builder node) вне менеджер-пула.

### Дополнительные операции и диагностика

Основные команды для обслуживания контекстов в CI:

```bash
# Список всех доступных контекстов
docker context ls

# Просмотр детальной конфигурации контекста (проверка путей и хоста)
docker context inspect swarm-ctx

# Удаление контекста после завершения задачи (гигиена пайплайна)
docker context rm swarm-ctx
```

### Интеграция с registry authentication

Флаг `--with-registry-auth` в `docker stack deploy` критичен для работы с приватным registry. При его использовании Swarm Manager передает временный токен авторизации на все worker-ноды, что избавляет от необходимости выполнять `docker login` на каждом сервере вручную. Без этого флага воркеры не смогут скачать образы из приватного реестра.

```yaml
script:
  # Авторизация в GitLab Container Registry (или Harbor)
  - echo "$CI_REGISTRY_PASSWORD" | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
  # Деплой с передачей прав воркерам
  - docker stack deploy -c docker-compose.yml myapp --with-registry-auth --prune
```

## Особые случаи и ограничения

### Ротация сертификатов mTLS

Срок действия клиентских и серверных сертификатов — типовое значение 3650 дней (~10 лет). При приближении к сроку истечения:
1. Сгенерируйте новый набор сертификатов на CA-ноде (см. `swarm_setup.md`).
2. Обновите переменные `$CA_PEM`, `$CERT_PEM`, `$KEY_PEM` в CI/CD-секретах.
3. Выполните деплой через новый контекст — старые контексты автоматически перестанут работать после отзыва сертификата на менеджере.

Для автоматизации проверки срока используйте cron-задачу:

```bash
# Проверка срока действия сертификата (критично за 30 дней)
openssl x509 -in cert.pem -noout -dates | grep "notAfter"
# Если осталось < 30 дней — инициировать ротацию
```

### SSH-agent в эфемерных раннерах

При использовании SSH-контекста в GitLab CI/GitHub Actions SSH-агент должен быть запущен заново для каждого джоба:

```yaml
before_script:
  - eval "$(ssh-agent -s)"
  - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
  - mkdir -p ~/.ssh
  - chmod 700 ~/.ssh
  # Проверка доступности менеджера
  - ssh -o StrictHostKeyChecking=no deploy-user@swarm-manager.example.com "docker node ls"
```

### Запуск в air-gapped средах

В изолированных сетях без доступа к Docker Hub используйте:

- **Внутренний registry:** Harbor, GitLab Container Registry, или простой `registry:3` контейнер в Swarm.
- **Предварительно скачанные образы:** `docker pull` на ноде с доступом, `docker save` → `docker load` на целевой ноде.
- **Контекст с внутренним DNS:** Вместо `prod-manager.example.com` используйте внутренний IP или CNAME из корпоративного DNS.

### Credential Store для registry

Docker CLI поддерживает внешние credential stores (`docker-credential-helpers`). В CI-пайплайнах вместо `docker login` с переменными можно использовать:

```bash
# Если credential store настроен на хосте
docker context create swarm-prod \
  --docker "host=tcp://prod-manager:2376,ca=$HOME/.docker/ca.pem,cert=$HOME/.docker/cert.pem,key=$HOME/.docker/key.pem"
```

В эфемерных раннерах credential store обычно не доступен — используйте `--password-stdin`.

### Различия поведения: Linux vs Windows раннеры

На Windows Server раннерах Docker Context работает иначе:
- Пути к сертификатам используют Windows-разделители: `C:\Users\runner\.docker\ca.pem`.
- `chmod 600` не работает — используйте ACL:
  ```powershell
  icacls C:\Users\runner\.docker\*.pem /inheritance:r /grant:r "runner:F"
  ```
- В GitLab CI Windows Runner используйте образ `docker:windows` или `mcr.microsoft.com/windows/servercore:ltsc2022`.

## Сравнение методов подключения (mTLS vs SSH vs direct DOCKER_HOST)

| Метод | Безопасность | Сложность настройки | Ротация секретов | Рекомендация |
|:---|:---|:---|:---|:---|
| mTLS контекст | Высокая | Средняя | CA + перевыпуск | Стандарт для продакшена |
| SSH контекст | Высокая | Низкая | Ротация SSH-ключа | Альтернатива, если mTLS не настроен |
| `DOCKER_HOST` переменная | Низкая | Минимальная | Не применима | Только для dev-окружений |
| Прямой монтинг `/var/run/docker.sock` | Низкая | Минимальная | Не применима | Запрещено в продакшене |

## Дополнительная информация

### Безопасность и защита данных

- **Права доступа:** Файлы `key.pem` и приватные SSH-ключи должны иметь права доступа `600`. Команда `chmod 600 ~/.docker/*.pem` обязательна в пайплайнах.
- **Очистка данных:** При использовании долгоживущих раннеров (Self-hosted) всегда выполняйте `docker context rm` в секции `after_script`, чтобы предотвратить утечку путей к сертификатам.
- **Маскирование:** Убедитесь, что переменные `$CA_PEM`, `$CERT_PEM`, `$KEY_PEM` помечены как "Masked" в настройках CI/CD, чтобы их содержимое не попало в логи.
- **Firewall:** Никогда не открывайте порт 2375 (незащищенный Docker API). Используйте только 2376 с mTLS.
- **Никогда не храните ключи в репозитории:** `ca-key.pem` и `ssh-private-key` должны жить только в секрет-хранилище CI/CD (GitLab Secrets, HashiCorp Vault).

### Устранение типичных ошибок

| Ошибка | Причина | Способ решения |
|:---|:---|:---|
| `context already exists` | Попытка создать контекст с тем же именем на постоянном раннере | Добавить `docker context rm -f` перед созданием |
| `TLS: unknown authority` | Ошибка в сертификате CA | Проверить соответствие `ca.pem` корневому сертификату сервера |
| `permission denied` | Некорректные права на файл ключа | Применить `chmod 600` к ключу и сертификату |
| `Is the docker daemon running?` | Порт 2376 закрыт или адрес хоста неверный | Проверить доступность порта через `nc -zv <host> 2376` |
| `certificate has expired` | Сертификат клиента или сервера истек | Проверить сроки через `openssl x509 -in cert.pem -noout -dates`, при необходимости перевыпустить |
| `x509: certificate signed by unknown authority` | Сертификат подписан внутренним CA, который не добавлен в trust store | Убедиться, что `ca.pem` — корневой сертификат того же CA, которым подписан серверный сертификат |
| `Error response from daemon: context "xxx" is already in use` | Контекст активно используется другим процессом | Переключиться на `default` контекст (`docker context use default`), затем удалить |
| `error during connect: Get http://...` | Некорректный формат `DOCKER_HOST` или отсутствие `tcp://` префикса | Проверить формат: `tcp://<IP>:2376` (обязательно с `tcp://`) |
| `context deadline exceeded` | Закрыт порт 2376 или неверный IP менеджера | Проверить firewall и значение `$DOCKER_HOST` |
| `ssh: handshake failed` | SSH-ключ не добавлен в агент или неверный пароль | Проверить `ssh-add -l` и права на `~/.ssh` |

### Best Practices

- **Используйте переменные типа `File`** для PEM-файлов в GitLab CI / GitHub Actions — это предотвращает перенаправление содержимого в логи.
- **Удаляйте контекст в `after_script`** на Self-hosted раннерах. На эфемерных раннерах это опционально.
- **Верифицируйте контекст** перед деплоем через `docker info --format '{{.Swarm.LocalNodeState}}'`.
- **Ротируйте сертификаты** proactively — настроите мониторинг срока действия через `openssl x509`.
- **Никогда не коммитьте** PEM-файлы или SSH-ключи в репозиторий. Используйте Ansible Vault, HashiCorp Vault или CI/CD-секреты.
- **Ограничьте firewall:** Порт 2376 разрешайте только с IP-адресов CI-раннеров:
  ```bash
  ufw allow from <CI_RUNNER_IP>/32 to any port 2376
  ```
- **Используйте `--with-registry-auth`** всегда при деплое стеков с приватным registry.
- **Предпочитайте mTLS SSH-подключению** в продакшене — mTLS обеспечивает более тонкий контроль доступа через клиентские сертификаты.

### Связанные документы

- **[Подготовка кластера (mTLS)](./swarm_setup.md)** — генерация сертификатов и настройка порта 2376.
- **[Развертывание инфраструктуры](./infra_deployment.md)** — примеры деплоя Traefik через контексты.
- **[Лучшие практики CI/CD](./best_practices.md)** — стандарты безопасности и оптимизации.
- **[Docker Context — общее руководство](../../Docker/docker_context.md)** — базовая механика контекстов, хранение в `~/.docker/`.
- **[Docker Swarm — обзор](../docker_swarm_overview.md)** — архитектура кластера и режим global.
- **[Deploy приложения через GitLab CI](./app_deployment.md)** — пайплайны деплоя в Swarm с Docker Context.
- **[GitLab Runner в Swarm](./gitlab_runner_swarm.md)** — развертывание раннеров с автокеллингом через docker.sock.
