# Проблема дублирования кода в GitLab CI (Boilerplate)

## Определения

**Boilerplate-код (Шаблонный код)** — избыточные фрагменты конфигурации, которые копируются в каждый новый проект без существенных изменений. В GitLab CI это проявляется в виде идентичных определений стадий (`stages`), базовых образов (`image`), скриптов сборки (`script`) и блоков подготовки окружения (`before_script`), жестко зашитых в локальные файлы `.gitlab-ci.yml`.

**Configuration Drift (Дрейф конфигураций)** — прогрессирующее расхождение между изначально одинаковыми пайплайнами. Возникает из-за локальных исправлений багов или обновлений версий в одном проекте, которые не переносятся в другие, что приводит к хаосу в управлении инфраструктурой.

**O(N) Complexity of Maintenance** — концепция, описывающая рост затрат на поддержку инфраструктуры. При использовании boilerplate-кода любая глобальная правка (например, обновление версии Docker, закрытие уязвимости или изменение SSH-политики) требует `N` изменений в `N` репозиториях.

**Copy-Paste Anti-Pattern (Антипаттерн копирования)** — системная проблема, при которой разработчики тиражируют конфигурации через `Ctrl+C` → `Ctrl+V` вместо использования механизмов переиспользования (`extends`, `include`, `!reference`, `inputs`). Является основным источником технического долга на этапе зрелости «Stage 1».

**Контекст этапа:** Первый уровень зрелости CI/CD («Stage 1»). Это естественная точка старта для небольших команд (1–3 сервиса), которая быстро превращается в основной источник технического долга при росте количества микросервисов. Согласно [Эволюции переиспользуемых пайплайнов](../evolution_example.md), этот этап характеризуется максимальной гибкостью при нулевой сопровождаемости.

> [!WARNING]
> **Признаки нахождения на этапе Boilerplate:**
> - Файл `.gitlab-ci.yml` содержит более 50 строк кода, не считая бизнес-логики (тесты, деплой).
> - Для создания пайплайна в новом сервисе разработчик открывает старый сервис и делает `Ctrl+C` → `Ctrl+V`.
> - Обновление версии базового образа (например, `alpine:3.20`) требует создания Merge Request'ов в нескольких репозиториях.
> - Один и тот же `before_script` (SSH-агент, Docker-login, Ansible) дублируется в 10+ проектах.
> - Уязвимость в скрипте сборки, обнаруженная в одном проекте, с вероятностью 100% присутствует во всех остальных.
> - Использование YAML Anchors (`&`/`*`) вместо `!reference` — они не работают между файлами.

### Архитектура типичного Boilerplate-пайплайна

```
┌──────────────────────────────────────────────────────────────────┐
│  Проект A: .gitlab-ci.yml (120 строк)                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ stages: [build, test, deploy]                              │  │
│  │ variables: { DOCKER_DRIVER: overlay2, IMAGE: ... }         │  │
│  │ .setup_docker: { script: [docker login, docker build...] } │  │
│  │ build: { extends: .setup_docker, stage: build }            │  │
│  │ test:  { stage: test, script: [pytest] }                   │  │
│  │ deploy:{ stage: deploy, script: [scp deploy.sh] }          │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Скопировано 1:1 в ↓                                             │
│                                                                  │
│  Проект B: .gitlab-ci.yml (120 строк)                           │
│  Проект C: .gitlab-ci.yml (120 строк)                           │
│  ...                                                             │
│  Проект N: .gitlab-ci.yml (120 строк)                           │
│                                                                  │
│  Итого: N × 120 строк = N × потенциальных багов                  │
└──────────────────────────────────────────────────────────────────┘
```

## Базовые концепции

### Системные причины возникновения

Дублирование кода часто является не ошибкой конкретного разработчика, а следствием незрелости процессов:
1.  **Отсутствие платформенного мышления:** Инфраструктура воспринимается как набор разрозненных скриптов, а не как продукт или сервис.
2.  **Страх «Breaking Changes»:** Из-за отсутствия механизмов версионирования шаблонов проще скопировать рабочий код, чем пытаться создать общую библиотеку, которая может сломать чужие сборки.
3.  **Низкая прозрачность:** Разработчики не знают о существовании лучших практик в соседних командах и «изобретают велосипед» при создании каждого нового сервиса.
4.  **Отсутствие центрального каталога:** Нет выделенного репозитория для шаблонов, поэтому каждый проект хранит свои копии.
5.  **Незнание механизмов переиспользования:** Разработчики не знают о `extends`, `!reference`, `include`, YAML Anchors или считают их излишне сложными.

### Анатомия типичного Boilerplate

Ниже представлен пример конфигурации, которая «кочует» из проекта в проект. Основная проблема — жесткое связывание (tight coupling) логики сборки с версией инструментария и параметрами реестра.

```yaml
# Пример кода, требующего удаления на следующих этапах
stages:
  - build
  - test

variables:
  # Проблема: Эти переменные дублируются в 50+ проектах
  DOCKER_DRIVER: overlay2
  CONTAINER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_REF_SLUG

docker-build:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    # Проблема: Логика авторизации и сборки не инкапсулирована
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build --pull -t $CONTAINER_IMAGE .
    - docker push $CONTAINER_IMAGE
```

### Типичные паттерны дублирования

#### 1. Блоки подготовки окружения (before_script)

Наиболее частый источник дублирования. Один и тот же `before_script` копируется в десятки проектов:

```yaml
# Этот блок повторяется в 30+ проектах
before_script:
  - apk add --no-cache openssh-client curl
  - eval $(ssh-agent -s)
  - chmod 600 "$SSH_PRIVATE_KEY"
  - ssh-add "$SSH_PRIVATE_KEY"
  - mkdir -p ~/.ssh && chmod 700 ~/.ssh
  - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
```

**Решение (Stage 2+):** Вынести в `include:project` шаблон или использовать `extends`:
```yaml
# templates/ssh-setup.yml
.ssh_base:
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - ssh-add "$SSH_PRIVATE_KEY"
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
```

#### 2. Генерация конфигурационных файлов через heredoc

Классический паттерн boilerplate — генерация файлов через `cat > file << 'EOF'`:

```yaml
# Паттерн, который кочует из проекта в проект
generate_config:
  script:
    - |
      cat > /etc/nginx/conf.d/default.conf << 'EOF'
      server {
          listen 80;
          server_name $CI_PROJECT_NAME;
          location / {
              proxy_pass http://localhost:8080;
          }
      }
      EOF
```

**Решение (Stage 2+):** Вынести heredoc-шаблон в отдельный YAML-файл и подключать через `include:local` или `!reference`.

#### 3. SSH-деплой без изоляции

Самый опасный boilerplate — прямо в `.gitlab-ci.yml` зашиты SSH-команды для деплоя:

```yaml
# Опасный паттерн: SSH-ключи в variables, деплой через ssh
deploy_production:
  stage: deploy
  script:
    - ssh $DEPLOY_USER@$DEPLOY_HOST "docker pull $IMAGE && docker restart app"
  variables:
    DEPLOY_HOST: "192.168.1.100"  # IP-адрес зашит прямо в YAML
```

**Решение (Stage 4+):** Инкапсулировать деплой в скрытое задание с `extends` или использовать компоненты (Stage 5).

#### 4. Гард-вары вместо инкапсуляции

Разработчики пытаются сделать код «более безопасным», добавляя проверки, но не меняя архитектуру:

```yaml
# Гард-вары не решают проблему дублирования
build:
  script:
    - |
      if [ -z "$CI_REGISTRY_USER" ]; then
        echo "ERROR: CI_REGISTRY_USER is not set"
        exit 1
      fi
      docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
      docker build -t $IMAGE .
```

**Решение:** Гард-вары полезны, но не заменяют централизацию. Правильный подход — вынести логику в шаблон с `spec:inputs` (Stage 5), где валидация происходит на этапе CI Lint.

### Механизмы переиспользования (для сравнения)

| Механизм | Этап зрелости | Назначение | Ограничение |
| :--- | :--- | :--- | :--- |
| **YAML Anchors (`&`/`*`)** | 1 (костыль) | Копирование блоков в рамках одного файла | Не работают между файлами |
| **`extends`** | 3 | Наследование от скрытых заданий | Массивы `script` не сливаются, а заменяются |
| **`!reference`** (v13.9+) | 3+ | Точечная вставка фрагментов кода | Лимит вложенности 10 уровней |
| **`include`** | 2 | Подключение внешних файлов | Нет типизации входов |
| **`include` + `inputs`** (v16.0+) | 5 | Параметризация подключаемых файлов | Требует SemVer для каталога |

### Почему `script`, `before_script`, `after_script` не сливаются

Критическое техническое ограничение, которое необходимо понимать на этапе Boilerplate:

> **Важно (GitLab 18.x/19.x):** Глобальные ключевые слова `before_script`, `image`, `cache` на верхнем уровне считаются устаревшими. Рекомендуется использовать блок `default`.

При использовании `extends` массивы команд (`script`, `before_script`, `after_script`) **не дополняются, а полностью заменяются**. Если в родителе 10 строк, а в дочернем — 1, итоговое задание будет содержать только 1 строку. Это не intuitively obvious и приводит к багам:

```yaml
.docker_base:
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker pull $IMAGE

my_deploy:
  extends: .docker_base
  before_script:
    - echo "Deploying..."  # Результат: только эта строка, docker login ПОТЕРЯН
```

**Обход:** Используйте `!reference` для вставки родительских команд:
```yaml
my_deploy:
  extends: .docker_base
  before_script:
    - !reference [.docker_base, before_script]
    - echo "Deploying..."  # Обе строки сохранены
```

## Практические сценарии

### Предварительные условия

Для осознанного перехода с этапа Boilerplate необходимо:
- **Инвентаризация:** Провести аудит всех `.gitlab-ci.yml` в организации и выявить повторяющиеся блоки.
- **Репозиторий-хранилище:** Выделить отдельный проект (например, `shared/ci-templates`) для хранения шаблонов.
- **Доступ:** Настроить права на чтение (Developer+) для всех проектов, которые будут подключать шаблоны.
- **Согласование:** Определить единый набор стадий и образов для организации.

### Риски и скрытые затраты

1.  **Инфраструктурная фрагментация (Technical Sprawl):**
    В компании одновременно используются десятки версий одного и того же инструмента (например, Python 3.9 в одном сервисе и 3.12 в другом для идентичных задач). Это делает невозможным оптимизацию Runner'ов и кэширования.
2.  **Масштабируемые ошибки:**
    Уязвимость в скрипте сборки, обнаруженная в одном проекте, с вероятностью 100% присутствует во всех остальных. Время реакции на инцидент безопасности (MTTR) растет пропорционально количеству репозиториев.
3.  **Блокировка инноваций:**
    Попытка внедрить современный инструмент (например, замена DinD на Kaniko) превращается в проект длиною в месяцы, так как требует ручного обновления сотен файлов.
4.  **Фрагментация среды выполнения:**
    Разные проекты используют разные версии базовых образов (`alpine:3.18` vs `alpine:3.20`), что затрудняет кэширование слоев и управление уязвимостями.
5.  **Дублирование конфигураций серверов:**
    Конфигурации nginx, sysctl, trusted certs генерируются через `cat > file << 'EOF'` в каждом проекте — любое изменение (например, обновление TLS-политики) требует правки сотен файлов.

### Выявление Boilerplate-кода (Аудит)

Перед переходом к централизации необходимо оценить масштаб проблемы.

**Инструменты поиска:**
Использование GitLab API или локального поиска по коду (`grep`) в зеркалированных репозиториях:
```bash
# Поиск всех проектов, использующих устаревшую версию Docker
grep -r "image: docker:20.10" ./all-projects/

# Поиск идентичных скриптов логина в реестр
grep -r "docker login -u \$CI_REGISTRY_USER" ./all-projects/ | wc -l

# Поиск дублирования SSH-блоков
grep -r "eval \$(ssh-agent -s)" ./all-projects/ | wc -l

# Поиск heredoc-паттернов (генерация конфигов)
grep -r "cat > .* << 'EOF'" ./all-projects/ | wc -l

# Поиск зашитых IP-адресов (антипаттерн)
grep -rE "[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+" ./all-projects/ --include="*.yml" | wc -l
```

**Метрика GPL (GitLab Project Lint):**
```bash
# Проверка одного проекта
glab ci lint

# Экспорт раскрытого YAML для анализа
glab ci lint --show-expanded > expanded.yml
```

### Сценарий 1: Деплой на сервер по SSH (Boilerplate)

Типичный boilerplate-пайплайн для деплоя на физический сервер через SSH.

```yaml
# Этот блок дублируется в 20+ проектах
stages:
  - build
  - deploy

variables:
  DOCKER_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build --pull -t $DOCKER_IMAGE .
    - docker push $DOCKER_IMAGE

deploy_production:
  stage: deploy
  image: alpine:3.20
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - chmod 600 "$SSH_PRIVATE_KEY"
    - ssh-add "$SSH_PRIVATE_KEY"
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ssh $DEPLOY_USER@$DEPLOY_HOST "
        docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY &&
        docker pull $DOCKER_IMAGE &&
        docker stop my-app || true &&
        docker rm my-app || true &&
        docker run -d --name my-app -p 80:8080 --restart always $DOCKER_IMAGE
      "
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Где здесь дублирование:**
- `before_script` с SSH-агентом — 7 строк, копируемых в каждый проект.
- `docker login` — повторяется в `build` и `deploy`.
- IP-адрес сервера зашит в переменную `DEPLOY_HOST`.

### Сценарий 2: Генерация nginx-конфига (heredoc boilerplate)

Классический паттерн генерации конфигурационных файлов через heredoc:

```yaml
deploy_nginx:
  stage: deploy
  script:
    - |
      cat > /etc/nginx/conf.d/mr-$CI_MERGE_REQUEST_IID.conf <<EOF
      upstream backend {
          server 127.0.0.1:8080;
      }
      server {
          listen 80;
          server_name mr-$CI_MERGE_REQUEST_IID.review.example.com;
          location / {
              proxy_pass http://backend;
              proxy_set_header Host \$host;
              proxy_set_header X-Real-IP \$remote_addr;
          }
      }
      EOF
    - nginx -s reload
```

**Проблема:** Конфиг nginx зашит в YAML. Изменение прокси-заголовков требует правки в каждом проекте.

**Решение (Stage 2):** Вынести конфиг в отдельный шаблон:
```bash
# templates/nginx/reverse_proxy.conf.template
server {
    listen 80;
    server_name ${MR_IID}.review.example.com;
    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Сценарий 3: SSH-ключи и known_hosts (Boilerplate)

Паттерн, который повторяется в каждом проекте, использующем SSH-деплой:

```yaml
# Генерация SSH-ключа
generate_key:
  script:
    - ssh-keygen -t ed25519 -C "gitlab-ci-deploy" -f deploy_key -N ""
    # deploy_key (приватный) → в переменную SSH_PRIVATE_KEY
    # deploy_key.pub (публичный) → добавить в authorized_keys

# Деплой с ssh-agent
deploy:
  before_script:
    - apk add --no-cache openssh-client
    - eval $(ssh-agent -s)
    - chmod 600 "$SSH_PRIVATE_KEY"
    - ssh-add "$SSH_PRIVATE_KEY"
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - ssh -o StrictHostKeyChecking=no $USER@$HOST "deploy.sh"
```

**Генерация known_hosts (Must-do перед первым деплоем):**
```bash
ssh-keyscan -H <deploy_host>
# → Вывод скопируйте в переменную SSH_KNOWN_HOSTS
```

**Генерация SSH-ключа:**
```bash
ssh-keygen -t ed25519 -C "gitlab-ci-deploy" -f deploy_key -N ""
# → deploy_key (приватный) → в переменную SSH_PRIVATE_KEY (тип: File)
# → deploy_key.pub (публичный) → добавьте в ~/.ssh/authorized_keys на целевом сервере
```

### Сценарий 4: Установка системных пакетов и настройка sysctl

Boilerplate для подготовки среды выполнения на серверах:

```yaml
# Дублируется в 15+ проектах для Production-серверов
setup_server:
  stage: prepare
  script:
    - |
      cat > /etc/sysctl.d/99-ci.conf << 'EOF'
      net.core.somaxconn = 65535
      net.ipv4.tcp_max_syn_backlog = 65535
      vm.swappiness = 10
      fs.file-max = 2097152
      EOF
    - sysctl --system
    - apt-get update && apt-get install -y docker.io nginx certbot
```

**Проблема:** Конфигурация sysctl и список пакетов зашиты в YAML. Обновление политики безопасности требует правки каждого проекта.

### Сценарий 5: Настройка trusted certificates (CA Bundle)

Boilerplate для добавления корпоративных сертификатов:

```yaml
# Дублируется во всех проектах, работающих с внутренними реестрами
install_ca:
  before_script:
    - |
      cat > /usr/local/share/ca-certificates/internal-ca.crt << 'EOF'
      -----BEGIN CERTIFICATE-----
      MIIDxTCCAq2gAwIBAgIJAJC1...
      -----END CERTIFICATE-----
      EOF
    - update-ca-certificates
    - mkdir -p /etc/docker/certs.d/$CI_REGISTRY
    - cp /usr/local/share/ca-certificates/internal-ca.crt /etc/docker/certs.d/$CI_REGISTRY/ca.crt
```

**Проблема:** Сертификат зашит прямо в YAML. Обновление CA требует правки во всех проектах.

**Решение (Stage 2):** Хранить сертификат в отдельном репозитории и подключать через `include:project` или artifact.

### Сценарий 6: Конфигурация Ansible Vault

Паттерн для хранения пароля Ansible Vault в пайплайне:

```yaml
ansible_deploy:
  stage: deploy
  before_script:
    - pip install ansible
    - echo "$ANSIBLE_VAULT_PASSWORD" > .vault_pass
    - chmod 600 .vault_pass
  script:
    - ansible-playbook -i inventory/ \
        --vault-password-file .vault_pass \
        playbooks/deploy.yml
  after_script:
    - rm -f .vault_pass  # Очистка
```

**Проблема:** `before_script` с `.vault_pass` дублируется в каждом проекте, использующем Ansible.

### Сценарий 7: Мониторинг и метрики через heredoc

Генерация конфигурации Prometheus Pushgateway через heredoc:

```yaml
report_metrics:
  stage: report
  script:
    - |
      cat <<EOF | curl -s --data-binary @- http://prometheus-pushgateway:9091/metrics/job/frontend-ci/instance/${CI_JOB_ID}
      # HELP build_duration_seconds Build duration in seconds
      # TYPE build_duration_seconds gauge
      build_duration_seconds $(date +%s)
      # HELP build_success Build success status
      # TYPE build_success gauge
      build_success 1
      EOF
```

### Сценарий 8: Сравнение Boilerplate и централизованного подхода

**До (Boilerplate):**
```yaml
# Каждый проект содержит 120+ строк идентичного кода
stages: [build, test, deploy]
variables: { DOCKER_DRIVER: overlay2, IMAGE: ... }
.build_job: { image: docker:29.8, services: [...], script: [...] }
build: { extends: .build_job, stage: build }
test: { stage: test, script: [pytest] }
deploy: { stage: deploy, script: [ssh deploy.sh] }
# ... ещё 80 строк
```

**После (Stage 2 — Include):**
```yaml
# .gitlab-ci.yml сокращается до 15-25 строк
include:
  - project: 'shared/ci-templates'
    file: 'templates/docker-build.yml'
    ref: 'v2.1.0'

build:
  extends: .docker_base
  variables:
    IMAGE_NAME: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

## Валидация состояния

Проект находится на этапе Boilerplate, если выполняется хотя бы одно условие:
1.  Файл `.gitlab-ci.yml` содержит более 50 строк кода, не считая бизнес-логики (тесты, деплой).
2.  Для создания пайплайна в новом сервисе разработчик открывает старый сервис и делает `Ctrl+C` → `Ctrl+V`.
3.  Обновление версии базового образа (например, `alpine:3.20`) требует создания Merge Request'ов в нескольких репозиториях.
4.  Один и тот же `before_script` (SSH, Docker, Ansible) встречается более чем в 3 проектах.
5.  В `.gitlab-ci.yml` есть heredoc-блоки (`cat > file << 'EOF'`) с зашитыми конфигурациями (nginx, sysctl, certificates).
6.  Используются YAML Anchors (`&`/`*`) вместо `!reference` — они не работают между файлами.
7.  Нет выделенного репозитория для шаблонов (shared/ci-templates).
8.  Конфликты имен переменных между шаблонами разных команд решаются через переименование, а не через изоляцию (`$[[ inputs ]]`).

**Быстрая диагностика:**
```bash
# Подсчет дублирования SSH-блоков
grep -rl "eval \$(ssh-agent -s)" ./projects/ | wc -l

# Подсчет дублирования heredoc-паттернов
grep -rl "cat.*<<.*EOF" ./projects/ --include="*.yml" | wc -l

# Проверка наличия центрального шаблона
ls -la shared/ci-templates/ 2>/dev/null || echo "NO CENTRAL TEMPLATE REPO"
```

## Устранение неполадок: Старт миграции

| Трудность | Описание | Первые шаги |
| :--- | :--- | :--- |
| **Огромный объем работы** | Невозможно обновить 100 проектов сразу. | Начните с создания одного шаблона для самого частого типа задач (например, `docker-build`). |
| **Сопротивление команд** | Разработчики привыкли «владеть» своим пайплайном. | Продавайте переход через уменьшение количества кода в их репозиториях (120 строк → 15 строк). |
| **Разные версии инструментов** | Пайплайны уже слишком сильно разошлись (Drift). | Сначала приведите их к единому виду вручную, прежде чем выносить в шаблон. |
| **Нет центрального шаблона** | Не выделен репозиторий для шаблонов. | Создайте `shared/ci-templates` с базовым `docker-build.yml` и `ssh-deploy.yml`. |
| **Конфликты имен заданий** | Шаблон определяет задание `build`, которое уже есть в проекте. | Используйте префиксы в именах заданий или `inputs` для переименования. |
| **Устаревшие YAML Anchors** | Используются `&`/`*` вместо `!reference`. | Замените `*anchor_name` на `!reference [.job_name, key]`. YAML Anchors не работают между файлами. |
| **Отсутствие версионирования** | Шаблоны подключаются через ветку `main`, а не теги. | Внедрите SemVer: `ref: 'v2.1.0'` вместо `ref: 'main'`. |
| **Незнание `default` блока** | Глобальные `before_script`, `image` на верхнем уровне. | Перенесите в `default:` — это рекомендация GitLab 18.x/19.x. |
| **Секреты в variables** | SSH-ключи, пароли зашиты в переменные проекта. | Используйте `File` тип для SSH-ключей, маскируйте секреты (`masked` + `protected`). |

## Преимущества и недостатки

### Преимущества этапа Boilerplate

| Преимущество | Описание |
| :--- | :--- |
| **Нулевой порог входа** | Не требует знания `extends`, `!reference`, `include` или SemVer. |
| **Максимальная гибкость** | Каждый проект может настроить пайплайн под себя без ограничений шаблонов. |
| **Быстрый старт** | Новый сервис можно запустить за минуты, скопировав `.gitlab-ci.yml` из соседнего проекта. |
| **Простая отладка** | Весь код пайплайна в одном файле, не нужно разбирать цепочки `include`/`extends`. |

### Недостатки этапа Boilerplate

| Недостаток | Описание | Масштаб проблемы |
| :--- | :--- | :--- |
| **O(N) обновления** | Любое изменение шаблона требует правки N репозиториев. | Линейный рост с числом проектов |
| **Configuration Drift** | Пайплайны расходятся из-за локальных правок. | Непредсказуемое поведение |
| **Уязвимости** | Баг/уязвимость в шаблоне присутствует во всех проектах. | Критический риск безопасности |
| **Фрагментация среды** | Разные версии инструментов в разных проектах. | Невозможность кэширования |
| **Нет аудита** | Невозможно узнать, кто и когда изменил логику сборки. | Отсутствие трассировки |
| **Блокировка инноваций** | Замена инструмента (DinD → Kaniko) — проект на месяцы. | Торможение развития |
| **Дублирование конфигов** | heredoc-блоки с nginx, sysctl, certs копируются в каждый проект. | Нарушение DRY |
| **Нет типизации** | Ошибки в переменных ловятся только в runtime (после запуска). | Медленная обратная связь |

## Дополнительная информация

### Связанные документы

- **Следующий этап эволюции:** [Централизация с include](./evolution_include.md) — первый шаг к избавлению от дублей (Stage 2).
- **Архитектурный обзор:** [Эволюция переиспользуемых пайплайнов](../evolution_example.md) — все 6 этапов на одной странице.
- **Технические детали:** [Механизм include](../include_keyword.md) — как работает база для переиспользования.
- **Наследование:** [Механизм extends](../extends_keyword.md) — правила слияния YAML и межфайлового наследования.
- **Атомарные вставки:** [Механизм !reference](../reference_and_yaml_anchors.md) — точечное копирование фрагментов кода между файлами.
- **Обзор механизмов:** [Переиспользуемые пайплайны: Обзор](../overview.md) — сравнение `include`, `extends`, `!reference`, `inputs`, компонентов.
- **Директивы:** [Справочник директив GitLab CI/CD](../../Advanced/workflow_rules/directives_definitions.md) — `default`, `before_script`, `after_script`, `rules`, `needs`.
- **Переменные и секреты:** [Переменные и секреты GitLab CI](../../Concepts/gitlab_ci_variables_secrets.md) — безопасное управление SSH-ключами и паролями.
- **Антипаттерны:** [Антипаттерны CI/CD](../../ci_cd_antipatterns.md) — почему копирование убивает скорость поставки.
- **Валидация:** [Валидация и версионирование](../../Advanced/pipeline_validation_and_versioning.md) — `glab ci lint`, CI Lint API.
- **Основы:** [Основы GitLab CI/CD](../../Concepts/gitlab_ci_basics.md) — архитектура, стадии, ключевые слова.
- **CI/CD Catalog:** [Компоненты CI/CD каталога](../ci_cd_catalog_components.md) — Stage 5: типизированные компоненты с SemVer.

### Маршрут эволюции

```
Stage 1: Boilerplate (вы здесь)
    │
    ├── Осознание проблемы: "У нас 50 одинаковых .gitlab-ci.yml"
    │
    ▼
Stage 2: Централизация (include)
    │
    ├── Решение: shared/ci-templates + include:project
    │
    ▼
Stage 3: Наследование (extends + !reference)
    │
    ├── Решение: скрытые задания + атомарные вставки
    │
    ▼
Stage 4: Абстракция (Kaniko)
    │
    ├── Решение: инкапсуляция инструментов
    │
    ▼
Stage 5: CI/CD Catalog (Components)
    │
    ├── Решение: типизированные входы, SemVer, UI-каталог
    │
    ▼
Stage 6: GitLab Steps ( futuro)
```

### Ключевые метрики для отслеживания прогресса

| Метрика | Stage 1 (Boilerplate) | Stage 2+ (Централизация) |
| :--- | :--- | :--- |
| **Средний размер .gitlab-ci.yml** | 100–200 строк | 15–30 строк |
| **Количество дублей одного шаблона** | N (по числу проектов) | 1 |
| **Время обновления версии Docker** | N × время на MR | 1 MR в центральный шаблон |
| **MTTR (среднее время восстановления)** | Высокое (все проекты упали) | Низкое (патч в одном месте) |
| **Покрытие типизацией (`spec:inputs`)** | 0% | 80%+ (Stage 5) |
