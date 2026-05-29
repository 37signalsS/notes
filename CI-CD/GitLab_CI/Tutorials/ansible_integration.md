# Интеграция Ansible с GitLab CI/CD

## Определения

**Интеграция Ansible с GitLab CI/CD** — это процесс автоматизации выполнения плейбуков Ansible с помощью системы непрерывной интеграции и доставки GitLab. Код конфигурации (плейбуки, роли) хранится в Git-репозитории, а GitLab CI/CD реагирует на изменения в нем, запуская задачи по развертыванию или управлению инфраструктурой.

- **Ansible:** Система управления конфигурациями, которая автоматизирует развертывание приложений, настройку систем и выполнение IT-задач.
- **GitLab CI/CD:** Встроенный в GitLab инструмент для создания конвейеров (пайплайнов) сборки, тестирования и развертывания ПО.
- **GitLab Runner:** Агент, который выполняет задания (jobs) из пайплайна GitLab CI/CD. Он устанавливается на отдельный сервер и должен иметь доступ к целевым хостам и необходимым инструментам, таким как Ansible.
- **`.gitlab-ci.yml`:** YAML-файл в корне репозитория, описывающий структуру и правила CI/CD пайплайна.

## Основные концепции

### Преимущества интеграции

1. **Автоматизация запусков:** Плейбуки выполняются автоматически после событий в репозитории (например, слияние в `main`), исключая ошибки, связанные с ручным запуском.
2. **Контроль доступа:** Прямой доступ к продуктивным серверам имеет только GitLab Runner. Права разработчиков и администраторов разграничиваются на уровне GitLab (например, через защищенные ветки и правила `merge request`).
3. **Версионирование и аудит:** Каждое изменение инфраструктуры проходит через Git, оставляя четкий след: кто, когда и какое изменение внес. Любое изменение можно откатить.
4. **Централизованное управление секретами:** CI/CD пайплайн позволяет безопасно управлять доступом к SSH-ключам, паролям и файлам инвентаря.

### Принцип работы

Интеграция основана на двух компонентах: **GitLab Runner** и файле **`.gitlab-ci.yml`**.

- **GitLab Runner** устанавливается на выделенную машину, регистрируется в проекте GitLab и опрашивает его на предмет новых задач. Получив задачу, он выполняет описанные в ней скрипты на машине, где установлен Ansible.
- **`.gitlab-ci.yml`** определяет стадии (`stages`) и задачи (`jobs`) пайплайна. Задачи выполняются последовательно по стадиям (например, `lint` -> `test` -> `deploy`).

### Типовой CI/CD-пайплайн для Ansible

Полный цикл автоматизации provisioning включает следующие шаги:

1. **Инициализация** — коммит или merge request триггерит пайплайн.
2. **Валидация** — `ansible-lint`, `ansible-playbook --syntax-check`.
3. **Тестирование** — опциональный `dry-run` (`--check --diff`).
4. **Развёртывание** — запуск playbook на целевых хостах.
5. **Проверка** — smoke-тесты (HTTP-запрос к сервису, проверка порта).
6. **Откат при сбое** — revert-коммит в `main` и повторный запуск пайплайна на предыдущую версию.

### Управление секретами

**Рекомендуемые подходы:**

1. **GitLab CI/CD Variables:**
    - **Где:** `Settings -> CI/CD -> Variables` в проекте GitLab.
    - **Что хранить:** Пароли, токены API, содержимое SSH-ключей.
    - **Безопасность:** Переменные следует помечать как **"Protected"** (доступны только для защищенных веток) и **"Masked"** (значение скрывается в логах).

2. **Ansible Vault:**
    - **Принцип:** Файлы с чувствительными данными (например, инвентарь) шифруются с помощью `ansible-vault`.
    - **Хранение:** Зашифрованные файлы безопасно хранятся в Git. Пароль для расшифровки помещается в переменную GitLab CI/CD с именем `ANSIBLE_VAULT_PASSWORD`.
    - **Выполнение:** Ansible автоматически использует эту переменную для расшифровки файлов во время запуска плейбука.

3. **Внешние системы управления секретами:** HashiCorp Vault, CyberArk — подтягивают секреты в рантайме пайплайна. Для большинства задач Ansible Vault + GitLab Variables достаточно; внешние системы — overkill для небольших проектов.

### Доступ к внешним репозиториям из пайплайна

Если роли, инвентарь или плейбуки разнесены по разным репозиториям, CI-задача должна получить к ним доступ. Для этого используется **GitLab CI Job Token** (`CI_JOB_TOKEN`) — встроенный токен, доступный в каждой задаче. Он позволяет клонировать приватные репозитории того же GitLab-инстанса без дополнительных секретов.

```yaml
deploy_job:
  script:
    - git clone https://gitlab-ci-token:${CI_JOB_TOKEN}@gitlab.example.com/infra/ansible-roles.git roles/
    - ansible-playbook -i inventory/site.yml deploy.yml
```

Альтернатива — Git submodules или `requirements.yml` с установкой через `ansible-galaxy install -r requirements.yml`.

## Практические сценарии

### Настройка SSH-подключения в CI/CD

Корректное SSH-подключение из CI-задачи требует двух настроек:

1. **SSH-агент** — приватный ключ загружается из переменной GitLab CI/CD в агент, чтобы `ssh`/`ansible-playbook` использовали его без интерактивного ввода passphrase.
2. **StrictHostKeyChecking=no** — отключает интерактивный запрос при подключении к неизвестному хосту. В CI это критично, так как задача не может ответить «yes» вручную.

```yaml
before_script:
  - eval $(ssh-agent -s)
  - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
  - mkdir -p ~/.ssh
  - chmod 700 ~/.ssh
  - echo -e "Host *\n\tStrictHostKeyChecking no\n" > ~/.ssh/config
```

> **Важно:** Для продакшн-сред предпочтительнее управлять `known_hosts` явно (добавлять отпечатки хостов в переменную), чтобы предотвратить MITM-атаки.

### Тестирование и деплой: разделение jobs

Хорошая практика — разделять валидацию и деплой на отдельные jobs. Это позволяет быстро отлавливать синтаксические ошибки до подключения к хостам.

```yaml
stages:
  - test
  - deploy

# Переиспользуемый блок через extend
.ansible_base:
  image: python:3.12
  before_script:
    - pip install ansible
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - echo -e "Host *\n\tStrictHostKeyChecking no\n" > ~/.ssh/config

ansible_syntax_check:
  stage: test
  extends: .ansible_base
  script:
    - ansible-playbook site.yml --syntax-check
  variables:
    ANSIBLE_HOST_KEY_CHECKING: "False"

ansible_deploy:
  stage: deploy
  extends: .ansible_base
  script:
    - ansible-playbook -i inventory/production site.yml --skip-tags github_runner
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual  # Продакшн-деploy только вручную
```

**Ключевые приёмы:**

- **`extends: .ansible_base`** — переиспользование общего блока (установка Ansible, настройка SSH). Механизм `extend` описан в [Reusable Pipelines](../Reusable_Pipelines/overview.md).
- **`--skip-tags`** — исключение задач по тегам (например, установка GitHub Runner не нужна при каждом деплое).
- **`when: manual`** — продакшн-деploy запускается вручную, stage деплоится автоматически.
- **`--check --diff`** — dry-run режим для предпросмотра изменений без применения.

### Полный цикл: валидация → деплой → проверка

```yaml
stages:
  - validate
  - deploy
  - verify

ansible_test:
  stage: validate
  image: python:3.12
  before_script:
    - pip install ansible
  script:
    - ansible-playbook site.yml --syntax-check

ansible_deploy:
  stage: deploy
  image: python:3.12
  before_script:
    - pip install ansible
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - echo -e "Host *\n\tStrictHostKeyChecking no\n" > ~/.ssh/config
  script:
    - ansible-playbook -i inventory/staging site.yml
  environment:
    name: staging

check_service:
  stage: verify
  image: curlimages/curl
  script:
    - curl -sf http://$TARGET_HOST:80/ || exit 1
  needs: ["ansible_deploy"]
  environment:
    name: staging
```

### Настройка и запуск Runner'а

Для выполнения CI/CD-задач необходим GitLab Runner. Runner — это агент, который устанавливается на отдельный сервер и выполняет шаги, описанные в `.gitlab-ci.yml`. Для запуска плейбуков Ansible обычно используется Runner с `shell` или `docker` executor.

Подробное пошаговое руководство по установке и регистрации Runner'а, включая рекомендованный `docker` executor, находится в основном документе: **[Регистрация GitLab Runner](./runner_registration.md)**.

#### Запуск Ansible Playbook из GitLab CI

**Пример структуры проекта:**

```text
.
├── ansible.cfg
├── hosts.ini
├── playbook.yml
└── .gitlab-ci.yml
```

**Пример файлов:**

- **`playbook.yml`**:

  ```yaml
  - name: "Ping hosts"
    hosts: all
    gather_facts: false
    tasks:
      - name: "Ping host"
        ansible.builtin.ping:
  ```

- **`hosts.ini`**:

  ```ini
  testnode ansible_host=1.2.3.4 ansible_user=devops
  ```

- **`ansible.cfg`**:

  ```ini
  [defaults]
  host_key_checking = False
  ```

- **`.gitlab-ci.yml`**:

  ```yaml
  stages:
    - provision

  ansible_run:
    stage: provision
    tags:
      - ansible # Указываем тег нашего Runner'а
    script:
      - ansible --version
      # Создаем временный файл ключа из переменной GitLab CI/CD
      - echo "${SSH_PRIVATE_KEY}" > key.pem
      - chmod 600 key.pem
      - ansible-playbook playbook.yml -i hosts.ini --private-key key.pem
  ```

**Порядок действий:**

1. В проекте GitLab (`Settings -> CI/CD -> Variables`) создайте переменную `SSH_PRIVATE_KEY`.
2. Вставьте в нее содержимое **приватного** SSH-ключа, имеющего доступ к целевым хостам (`testnode`). Пометьте переменную как `Masked`.
3. Закоммитьте файлы в репозиторий. GitLab автоматически запустит пайплайн, который выполнит плейбук.

## Дополнительная информация

Для ускорения пайплайнов рекомендуется предварительно собирать Docker-образ с установленным Ansible, а не устанавливать его на каждом запуске. При работе с конфигурационными файлами используйте `notify` и `handlers` для условного перезапуска сервисов. Это позволяет избежать ненужных перезапусков, если файл не изменился.

Безопасность и управление средами являются ключевыми аспектами. Храните inventory для `staging` и `production` в отдельных файлах, чтобы снизить риск случайного развертывания. Для отката изменений достаточно сделать `revert` коммита в `main` и запустить пайплайн заново.

### Смотрите также

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — для понимания базовых концепций пайплайнов.
- **[Управление секретами](../Concepts/gitlab_ci_variables_secrets.md)** и **[Ansible Vault](../../../Ansible/Vault/basics.md)** — для безопасной работы с учетными данными.
- **[Пример безопасной архитектуры CI/CD с Ansible](../../../Ansible/examples/example_real_world_ci_cd.md)** — для реализации промышленного подхода с изоляцией SSH-ключей.
