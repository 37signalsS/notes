# Nomad — CI/CD Pipeline

## Определения

**CI/CD Pipeline для Nomad** — автоматизированный конвейер, обеспечивающий сборку, тестирование, упаковку и развёртывание приложений в Nomad-кластер при каждом коммите или релизе. Является мостом между исходным кодом и production-средой.

**Nomad Pack** — пакетный менеджер Nomad, позволяющий инкапсулировать HCL-конфигурации, переменные и зависимости в переиспользуемые пакеты для единообразного деплоя через CI/CD.

**GitOps для Nomad** — подход, при котором Git-репозиторий является единственным источником правды для конфигурации Nomad-заданий; изменения применяются автоматически через pull request или merge.

**Artifact Repository** — хранилище собранных артефактов (Docker-образы, бинарные файлы, Nomad Pack), используемое CI/CD-пайплайном для доставки в Nomad.

## Основные концепции

### Архитектура CI/CD для Nomad

Типичный пайплайн включает следующие этапы:

| Этап | Описание | Инструменты |
| :--- | :--- | :--- |
| **Source** | Получение исходного кода, проверка изменений | Git, GitHub/GitLab |
| **Build** | Компиляция бинарника или сборка Docker-образа | Go, Docker, Buildah |
| **Test** | Unit-, integration-, smoke-тесты | Go test, Terratest |
| **Package** | Упаковка в Nomad Pack или HCL-файл | Nomad Pack, Jinja2 |
| **Publish** | Публикация артефакта в registry | Docker Registry, Artifactory |
| **Deploy** | Развёртывание в Nomad | `nomad job run`, Terraform |
| **Verify** | Проверка здоровья после деплоя | health check, smoke-тесты |

### Подходы к деплою

#### 1. Прямой `nomad job run` через CI

Самый простой подход: CI-раннер выполняет `nomad job run` напрямую.

**Преимущества:**
- Минимальная сложность настройки.
- Полный контроль над процессом.

**Недостатки:**
- Требует установки Nomad CLI на раннере.
- Нет механизма отката через Git (каждый push меняет состояние).

#### 2. Nomad Pack через CI

CI-раннер устанавливает Nomad Pack и использует его для деплоя.

**Преимущества:**
- Переиспользуемые пакеты с параметризацией.
- Версионирование пакетов.
- Поддержка зависимостей между сервисами.

#### 3. Terraform Provider Nomad через CI

Использование Terraform с провайдером `hashicorp/nomad` для декларативного управления джобами.

**Преимущества:**
- Единый workflow для инфраструктуры и приложений.
- State management и plan перед применением.
- Интеграция с其他 Terraform-ресурсами.

#### 4. GitOps (Argo CD / Flux)

Внешний контроллер следит за Git-репозиторием и автоматически применяет изменения к Nomad.

**Преимущества:**
- Audit trail через Git history.
- Автоматический rollback через revert коммита.
- Визуализация состояния в UI.

### Типичные паттерны пайплайнов

#### GitLab CI для Nomad

```yaml
stages:
  - build
  - test
  - package
  - deploy

variables:
  NOMAD_ADDR: "https://nomad.example.com:4646"
  NOMAD_TOKEN: "${NOMAD_TOKEN}"

build:
  stage: build
  script:
    - go build -o bin/app ./cmd/app
    - docker build -t registry.example.com/app:${CI_COMMIT_SHA} .
    - docker push registry.example.com/app:${CI_COMMIT_SHA}

test:
  stage: test
  script:
    - go test ./...

deploy_canary:
  stage: deploy
  only:
    - main
  script:
    - nomad job run -var="image_version=${CI_COMMIT_SHA}" -var="deploy_mode=canary" jobs/app.nomad.hcl
    - nomad deployment status -monitor

promote:
  stage: deploy
  only:
    - main
  when: manual
  script:
    - nomad deployment promote $(nomad deployment status -json | jq -r '.[0].ID')
```

#### GitHub Actions для Nomad

```yaml
name: Deploy to Nomad
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Nomad
        run: |
          wget -qO- https://releases.hashicorp.com/nomad/1.8.0/nomad_1.8.0_linux_amd64.zip | funzip > nomad
          sudo mv nomad /usr/local/bin/

      - name: Deploy
        env:
          NOMAD_ADDR: ${{ secrets.NOMAD_ADDR }}
          NOMAD_TOKEN: ${{ secrets.NOMAD_TOKEN }}
        run: |
          nomad job run -var="image_version=${{ github.sha }}" jobs/app.nomad.hcl

      - name: Verify
        run: |
          sleep 30
          nomad job status app | grep -q "running"
```

### Nomad Pack в CI/CD

Nomad Pack позволяет инкапсулировать конфигурацию приложения в переиспользуемый пакет:

```bash
# Инициализация пакета
nomad-pack init my-webapp

# Структура пакета
my-webapp/
├── templates/
│   └── job.nomad.hcl
├── vars/
│   └── defaults.hcl
└── README.md
```

** vars/defaults.hcl:**
```hcl
variable "image" {
  type    = string
  default = "registry/webapp:latest"
}

variable "count" {
  type    = number
  default = 3
}
```

** templates/job.nomad.hcl:**
```hcl
job "webapp" {
  datacenters = ["dc1"]
  type        = "service"

  group "app" {
    count = var.count

    network {
      port "http" { to = 8080 }
    }

    service {
      name = "webapp"
      port = "http"
      provider = "nomad"
    }

    task "server" {
      driver = "docker"
      config {
        image = var.image
        ports = ["http"]
      }
      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}
```

**Деплой через Nomad Pack:**
```bash
nomad-pack run my-webapp \
  -f overrides-production.hcl \
  -var "image=registry/webapp:v2.1" \
  -var "count=5"
```

### Безопасность CI/CD

#### Токены и секреты

| Параметр | Рекомендация |
| :--- | :--- |
| `NOMAD_TOKEN` | Хранить в secrets CI-системы, не в коде |
| ACL政策 | Minimal privilege: только `submit-job` и `read-job` для deploy-роли |
| Namespace | Ограничить деплой определёнными неймспейсами |
| Sentinel | Запретить определённые драйверы или образы через политики |

#### Пример минимальной ACL-политики для CI/CD

```hcl
namespace "production" {
  policy       = "write"
  capabilities = ["submit-job", "read-job", "list-jobs"]
}

namespace "staging" {
  policy       = "write"
  capabilities = ["submit-job", "read-job", "list-jobs", "destroy-job"]
}
```

### Валидация и откат

#### Преддеплойная проверка

```bash
# Dry-run: проверка изменений без применения
nomad job plan app.nomad.hcl

# Валидация HCL-файла
nomad job validate app.nomad.hcl
```

#### Мониторинг деплоя

```bash
# Отслеживание статуса деплоя
nomad deployment status -monitor

# Проверка canary-аллокаций
nomad alloc status <canary-alloc-id>
```

#### Автоматический откат

```hcl
update {
  auto_revert      = true
  healthy_deadline = "5m"
  progress_deadline = "10m"
}
```

#### Ручной откат

```bash
# Откат к предыдущей версии
nomad job rollback <job-name>

# Или через deployment fail
nomad deployment fail <deployment-id>
```

## Практические сценарии

### Сценарий 1: Multi-stage Pipeline с Canary

Полный пайплайн с автоматическим canary-деплоем и ручным промоутом:

**Jenkinsfile:**
```groovy
pipeline {
    agent any
    environment {
        NOMAD_ADDR = 'https://nomad.example.com:4646'
        NOMAD_TOKEN = credentials('nomad-token')
    }
    stages {
        stage('Build') {
            steps {
                sh 'docker build -t registry/app:${GIT_COMMIT} .'
                sh 'docker push registry/app:${GIT_COMMIT}'
            }
        }
        stage('Deploy Canary') {
            steps {
                sh """
                    nomad job run \
                      -var="image_version=${GIT_COMMIT}" \
                      -var="canary_count=1" \
                      jobs/app.nomad.hcl
                """
                sh 'nomad deployment status -monitor'
            }
        }
        stage('Verify') {
            steps {
                sh 'sleep 60 && curl -sf http://app.service.consul/health'
            }
        }
        stage('Promote') {
            steps {
                input message: 'Promote canary to production?'
                sh 'nomad deployment promote $(nomad deployment status -json | jq -r ".[0].ID")'
            }
        }
    }
    post {
        failure {
            sh 'nomad deployment fail $(nomad deployment status -json | jq -r ".[0].ID")'
        }
    }
}
```

### Сценарий 2: Terraform + Nomad через CI

Использование Terraform для управления Nomad-джобами:

**main.tf:**
```hcl
provider "nomad" {
  address = var.nomad_addr
  token   = var.nomad_token
}

variable "app_version" {
  type = string
}

resource "nomad_job" "webapp" {
  jobspec = file("${path.module}/jobs/webapp.nomad.hcl")

  var {
    name  = "image_version"
    value = var.app_version
  }
}
```

**CI-скрипт:**
```bash
terraform init
terraform plan -var="app_version=${CI_COMMIT_SHA}" -out=tfplan
terraform apply tfplan
```

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | ACL-токен не имеет прав на деплой | Обновите ACL-политику для CI-роли |
| `job validation failed` | Синтаксическая ошибка в HCL | Выполните `nomad job validate` перед деплоем |
| `deployment stuck` | Health check не проходит | Проверьте endpoint `/health` в новом образе |
| `no nodes available` | Квоты исчерпаны или drain | Проверьте `nomad quota status` и `nomad node status` |
| `artifact download failed` | Недоступен URL артефакта | Проверьте доступность registry или хранилища |

## Дополнительная информация

- [Nomad — практические сценарии](./practical_scenarios.md) — базовые HCL-конфигурации.
- [Nomad — продвинутые темы](./advanced_topics.md) — Nomad Pack и Autoscaler.
- [CI/CD: Стратегии развёртывания](../CI-CD/Deployment_Strategies/comparison.md) — сравнение подходов.
- [Nomad + Terraform](./nomad_terraform_iac.md) — управление инфраструктурой.
