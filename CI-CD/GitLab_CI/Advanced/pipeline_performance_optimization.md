# Оптимизация производительности пайплайнов GitLab CI/CD

## Определения

**Pipeline Performance Optimization** — процесс анализа и улучшения времени выполнения, ресурсоемкости и надежности CI/CD пайплайнов без изменения бизнес-логики приложения.

**Bottleneck (узкое место)** — этап или задача пайплайна, которая ограничивает общую скорость выполнения и не может быть ускорена параллелизацией.

**Feedback Loop** — время от коммита разработчика до получения результата проверки (тесты, сборка, линтер). Чем короче, тем выше производительность команды.

**Pipeline Profiling** — процесс измерения времени выполнения каждого этапа пайплайна для выявления наиболее затратных шагов.

## Теоретический блок

### Категории оптимизации

| Категория | Эффект | Сложность |
|:---|:---|:---|
| **Параллелизм** | Снижение времени за счёт параллельного выполнения | Средняя |
| **Кэширование** | Ускорение повторных запусков | Низкая |
| **Оптимизация образов** | Ускорение загрузки и запуска контейнеров | Средняя |
| **Сокращение этапов** | Уменьшение количества задач | Низкая |
| **Оптимизация зависимостей** | Параллельная загрузка и кэширование | Средняя |
| **Hardware** | Увеличение мощности Runner'ов | Высокая |

### Анализ времени выполнения

**Типичная структура пайплайна и время:**

```
git clone        → 5-30 сек (зависит от размера репозитория)
restore cache    → 2-10 сек
install deps     → 10-120 сек (npm install, pip install)
build            → 30-600 сек (компиляция)
test             → 60-1800 сек (unit/integration/e2e)
docker build     → 30-300 сек
push image       → 5-30 сек
deploy           → 10-60 сек
```

**Правило 80/20:** 80% времени пайплайна обычно тратится на 20% задач. Найдите эти задачи.

### Стратегии оптимизации

#### 1. DAG (needs) вместо stages

```
Без DAG (последовательно):
build (2 мин) → test (5 мин) → lint (1 мин) = 8 минут

С DAG (параллельно):
build (2 мин) → test (5 мин) → lint (1 мин) = 5 минут
             ↘ lint (1 мин) ↗
```

#### 2. Кэширование зависимостей

| Тип кэша | Время восстановления | Рекомендация |
|:---|:---|:---|
| package-lock.json | 5-15 сек | Используйте `key: files` |
| node_modules | 10-30 сек | Кэшируйте только `node_modules` |
| .m2/repository | 10-60 сек | Для Java/Maven |
| pip cache | 5-20 сек | Для Python |
| Docker layers | 30-120 сек | Multi-stage builds |

#### 3. Оптимизация Docker образов

```dockerfile
# Плохо: один тяжёлый образ
FROM ubuntu:22.04
RUN apt-get update && apt-get install -y build-essential python3
COPY . /app
RUN make build

# Хорошо: multi-stage build
FROM golang:1.21 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app/binary

FROM alpine:3.19
COPY --from=builder /app/binary /app/binary
ENTRYPOINT ["/app/binary"]
```

#### 4. Параллелизация тестов

```yaml
# Плохо: все тесты в одной задаче (10 минут)
test:all:
  script: ./run-all-tests.sh

# Хорошо: параллельный запуск по модулям (3 минуты)
test:unit:
  script: ./run-unit-tests.sh
test:integration:
  script: ./run-integration-tests.sh
test:e2e:
  script: ./run-e2e-tests.sh
```

#### 5. Only/Except и rules для пропуска ненужных задач

```yaml
# Не запускать тесты при изменении документации
test:unit:
  rules:
    - changes:
        - src/**/*
        - tests/**/*
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

#### 6. Разделение артефактов и кэша

Артефакты и кэш решают разные задачи. Частая ошибка — использовать артефакты для передачи зависимостей (`node_modules`, `vendor`, `.m2`) между стадиями. Это приводит к:
- Росту размера хранилища (каждый запуск создаёт архив размером в сотни мегабайт)
- Увеличению времени пайплайна (скачивание/загрузка артефактов)
- Засорению хранилища GitLab

**Правило:** зависимости передаются через `cache`, результаты сборки — через `artifacts`.

```yaml
# ПЛОХО: зависимости передаются через артефакты
build:
  stage: build
  script: npm install
  artifacts:
    paths: [node_modules/]  # 100+ МБ на каждый запуск

# ХОРОШО: зависимости кэшируются, артефакты — только результаты
build:
  stage: build
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths: [node_modules/]
  script: npm run build
  artifacts:
    paths: [dist/]
```

### Метрики производительности

| Метрика | Целевое значение | Как измерять |
|:---|:---|:---|
| **Total Pipeline Time** | < 10 минут | `pipeline.finished_at - pipeline.created_at` |
| **Feedback Loop** | < 5 минут | Время до первого failed/success |
| **Cache Hit Rate** | > 80% | `cache_hits / (cache_hits + cache_misses)` |
| **Queue Wait Time** | < 1 минуты | `job.started_at - job.created_at` |
| **Docker Build Time** | < 2 минут | `docker build` время |
| **Test Parallelization** | > 3x ускорение | Сравнение serial vs parallel |

## Практический блок

### Профилирование пайплайна

```yaml
# Добавление таймингов к каждой задаче
.profile_template:
  before_script:
    - export CI_STEP_START=$(date +%s)
  after_script:
    - export CI_STEP_END=$(date +%s)
    - echo "Step duration: $((CI_STEP_END - CI_STEP_START)) seconds"

build:
  extends: .profile_template
  script:
    - ./build.sh
  artifacts:
    paths: [build-timing.txt]
    when: always
```

#### Пример разбора времени сборки

При анализе реального пайплайна (TypeScript-проект, 7 минут сборки) Bottleneck'ы распределились следующим образом:

| Этап | Время | Доля | Причина |
|:---|:---|:---|:---|
| `install_deps` | 1 мин 45 сек | 25% | Скачивание `node_modules` без кэша |
| `build_image` | 3 мин 45 сек | 53% | Сборка Docker-образа, копирование всего проекта |
| `test` | 1 мин 30 сек | 22% | Запуск тестов в тяжёлом образе |
| **Итого** | **7 мин** | **100%** | |

После оптимизации (кэш `node_modules`, `cache:key:files`, `COPY --link` в Dockerfile, параллельные тесты) время сократилось до 2 минут.

**Действия:**
1. Включите `cache:key:files` для `package-lock.json` → убираете 1 мин 45 сек.
2. Оптимизируйте Dockerfile (multi-stage, `COPY --link`) → убираете 2 мин из сборки образа.
3. Параллелизуйте тесты (`parallel:matrix`) → убираете 45 сек.

### Оптимизация кэша с анализом

```yaml
# Анализ эффективности кэша
cache_analysis:
  stage: .pre
  script:
    - |
      echo "=== Cache Analysis ==="
      echo "Cache key: $CI_COMMIT_REF_SLUG"
      echo "Cache policy: $CI_CACHE_POLICY"
      
      # Проверка размера кэша
      if [ -d "node_modules" ]; then
        echo "node_modules size: $(du -sh node_modules | cut -f1)"
        echo "node_modules files: $(find node_modules -type f | wc -l)"
      fi
      
      # Проверка времени восстановления
      time npm ci --prefer-offline 2>&1 | tee npm-install.log
      
      # Анализ причин промахов кэша
      echo "=== Cache Miss Reasons ==="
      grep -i "cache miss\|not found\| expired" npm-install.log || echo "No cache misses detected"
  rules:
    - when: always
```

### Параллелизация через matrix

```yaml
# Параллельное тестирование на разных платформах
test:matrix:
  stage: test
  parallel:matrix:
    NODE_VERSION: [18, 20, 22]
    OS: [linux, macos]
  script:
    - nvm use $NODE_VERSION
    - npm test
  artifacts:
    reports:
      junit: test-results.xml

# Автоматическая агрегация результатов
test:report:
  stage: report
  needs: [test:matrix]
  script:
    - merge-reports test-results-*.xml > combined-results.xml
  artifacts:
    reports:
      junit: combined-results.xml
```

### Оптимизация Docker сборки

```yaml
# Кэширование Docker слоёв
docker:build:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_BUILDKIT: "1"
    COMPOSE_DOCKER_CLI_BUILD: "1"
  script:
    - |
      docker build \
        --cache-from $CI_REGISTRY_IMAGE:latest \
        --build-arg BUILDKIT_INLINE_CACHE=1 \
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA \
        -t $CI_REGISTRY_IMAGE:latest \
        .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
    - docker push $CI_REGISTRY_IMAGE:latest
```

### Анализ и отчёт

```yaml
performance_report:
  stage: .post
  image: python:3.11
  script:
    - |
      python3 << 'PYTHON'
      import json
      import requests
      
      # Получение данных о последнем пайплайне
      url = f"$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID"
      headers = {"PRIVATE-TOKEN": "$CI_JOB_TOKEN"}
      pipeline = requests.get(url, headers=headers).json()
      
      # Анализ задач
      jobs_url = f"$CI_API_V4_URL/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID/jobs"
      jobs = requests.get(jobs_url, headers=headers).json()
      
      slow_jobs = []
      for job in jobs:
          if job["duration"] and job["duration"] > 300:  # > 5 минут
              slow_jobs.append({
                  "name": job["name"],
                  "duration": job["duration"],
                  "stage": job["stage"]
              })
      
      report = {
          "pipeline_id": pipeline["id"],
          "total_duration": pipeline["duration"],
          "slow_jobs": slow_jobs,
          "recommendations": []
      }
      
      if slow_jobs:
          report["recommendations"].append("Consider parallelizing slow jobs")
      
      if pipeline["duration"] > 600:
          report["recommendations"].append("Pipeline exceeds 10-minute threshold")
      
      print(json.dumps(report, indent=2))
      PYTHON
  artifacts:
    paths: [performance-report.json]
    when: always
  rules:
    - when: always
```

## Дополнительная информация

### Связанные темы
- **[DAG с needs](./workflow_rules/dag_with_needs.md)** — параллельное выполнение задач
- **[Матричные сборки](./workflow_rules/matrix_builds_and_serialization.md)** — параллелизация тестов
- **[Кэширование](./gitlab_ci_caching/caching_overview.md)** — стратегии кэширования
- **[Артефакты](./gitlab_ci_caching/gitlab_ci_artifacts.md)** — передача данных между задачами
- **[Отладка](./debugging_and_troubleshooting.md)** — диагностика проблем
- **[Мониторинг](./monitoring_and_metrics.md)** — метрики производительности

### Чек-лист оптимизации
- [ ] Включить DAG (needs) для параллельного выполнения
- [ ] Настроить кэширование зависимостей
- [ ] Использовать multi-stage Docker builds
- [ ] Параллелизовать тесты через matrix
- [ ] Добавить `rules:changes` для пропуска ненужных задач
- [ ] Проверить время восстановления кэша
- [ ] Настроить `pull_policy: ["if-not-present"]` для Runner'ов, чтобы избежать повторного скачивания неизменяемых образов
- [ ] Убедиться, что артефакты не используются для хранения зависимостей (node_modules, vendor, .m2)
- [ ] Настроить алерты на рост времени пайплайна
- [ ] Регулярно анализировать slow jobs
