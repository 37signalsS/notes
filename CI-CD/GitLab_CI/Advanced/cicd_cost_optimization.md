# CI/CD Cost Optimization

## Определения

- **CI/CD Cost Optimization** — процесс минимизации затрат на инфраструктуру CI/CD без потери производительности и качества доставки ПО
- **Cost per Pipeline** — стоимость одного запуска пайплайна, включая compute, storage и network ресурсы
- **Shared Runners vs Dedicated Runners** — сравнение моделей использования: общие раннеры (общий пул, меньше контроля) против выделенных (полный контроль, выше стоимость)
- **Cache Hit Rate** — доля успешных восстановлений кэша от общего числа запусков; ключевая метрика эффективности кэширования

## Теоретический блок

### Модели стоимости CI/CD

**Self-hosted (собственная инфраструктура)**
- Начальные инвестиции в серверы/ВМ
- Операционные расходы: электричество, охлаждение, администрирование
- Полный контроль над конфигурацией и безопасностью
- Амортизация оборудования 3-5 лет

**SaaS (облачные сервисы)**
- Оплата по факту использования (pay-as-you-go)
- Минимальные начальные инвестиции
- Зависимость от провайдера и его тарифов
- Автоматическое масштабирование

**Hybrid (гибридная модель)**
- Базовая нагрузка на self-hosted runners
- Пиковые нагрузки на SaaS runners
- Оптимизация стоимости через комбинирование
- Сложность управления и мониторинга

### Факторы стоимости

**Compute (вычислительные ресурсы)**
- Тип инстанса (CPU, RAM)
- Время выполнения задач
- Количество параллельных запусков
- Использование artifact caching

**Storage (хранилище)**
- Docker image layers
- Артефакты сборки
- Логи пайплайнов
- Время хранения данных

**Network (сеть)**
- Трафик между раннерами и реестрами
- Загрузка зависимостей
- Передача артефактов
- Подключение к внешним сервисам

**License (лицензии)**
- GitLab Premium/Ultimate
- Лицензии на ПО для сборки
- Инструменты аналитики

### Анализ стоимости Runner'ов

| Тип инстанса | vCPU | RAM | Стоимость/час | Утилизация | Effective Cost |
|---|---|---|---|---|---|
| small | 1 | 2GB | $0.02 | 80% | $0.025 |
| medium | 2 | 4GB | $0.04 | 60% | $0.067 |
| large | 4 | 8GB | $0.08 | 40% | $0.20 |
| xlarge | 8 | 16GB | $0.16 | 30% | $0.53 |

**Формула эффективной стоимости:**
```
Effective Cost = Nominal Cost / Utilization Rate
```

### Оптимизация кэша

**Стратегии кэширования:**
- `pull-push` — стандартная стратегия (загрузка + сохранение)
- `pull` — только восстановление кэша (read-only)
- `push` — только сохранение кэша (write-only)
- `pull-push` с условиями — условное сохранение

**Cache Hit Rate = (Successful Cache Restores / Total Pipeline Runs) × 100%**

**Оптимальный cache hit rate:**
- < 50% — низкая эффективность, требуется оптимизация
- 50-75% — приемлемо, есть потенциал улучшения
- > 75% — хорошая эффективность
- > 90% — отличная эффективность

### Shared vs Dedicated Runners

| Критерий | Shared Runners | Dedicated Runners |
|---|---|---|
| Стоимость | Оплата за использование | Фиксированная оплата |
| Масштабирование | Автоматическое | Ручное/автоматическое |
| Конфиденциальность | Доступ к общему пулу | Полная изоляция |
| Производительность | Зависит от нагрузки | Предсказуемая |
| Оптимизация | Ограничена | Полная |

**Когда использовать dedicated:**
- Конфиденциальный код
- Специфические требования к производительности
- Регуляторные требования
- Стабильная высокая нагрузка

**Когда использовать shared:**
- Нестабильная нагрузка (spiky)
- Начальные проекты
- Некритичные задачи
- Экономия на инфраструктуре

### Архивирование и очистка артефактов

**Правила хранения:**
- Артефакты релизов: 90 дней
- Артефакты dev веток: 7 дней
- Артефакты feature веток: 3 дня
- Логи失败ших пайплайнов: 30 дней

**Стратегии оптимизации:**
- Сжатие артефактов перед сохранением
- Исключение ненужных файлов через `paths` и `exclude`
- Использование `expire_in` для автоматической очистки
- Регулярный мониторинг использования хранилища

### Мониторинг расходов

**Ключевые метрики:**
- Cost per pipeline
- Cost per commit
- Runner utilization rate
- Cache hit rate
- Artifact storage usage
- Failed pipeline cost (wasted resources)

**Инструменты мониторинга:**
- GitLab CI/CD Analytics
- Cost Allocation Reports
- Custom dashboards (Grafana, Kibana)
- Cloud provider billing dashboards

## Практический блок

### Скрипт анализа стоимости пайплайнов

```bash
#!/bin/bash
# analyze_pipeline_cost.sh
# Анализ стоимости пайплайнов GitLab CI

GITLAB_URL="https://gitlab.example.com"
PROJECT_ID="12345"
PRIVATE_TOKEN="glpat-xxxxx"
DAYS=30

echo "=== Анализ стоимости пайплайнов за $DAYS дней ==="

# Получение данных о пайплайнах
pipelines=$(curl -s --header "PRIVATE-TOKEN: $PRIVATE_TOKEN" \
  "$GITLAB_URL/api/v4/projects/$PROJECT_ID/pipeline?per_page=100&updated_after=$(date -d "$DAYS days ago" -Iseconds)")

# Анализ по статусам
echo -e "\n--- Статистика по статусам ---"
echo "$pipelines" | jq -r '.[].status' | sort | uniq -c | sort -rn

# Анализ длительности
echo -e "\n--- Средняя длительность по статусам ---"
echo "$pipelines" | jq -r 'group_by(.status) | map({status: .[0].status, avg_duration: (map(.duration) | add / length)})'

# Расчет стоимости (базовая оценка)
# Средняя стоимость часа compute: $0.05
HOURLY_RATE=0.05
echo -e "\n--- Оценка стоимости ---"
echo "$pipelines" | jq -r --arg rate "$HOURLY_RATE" '
  group_by(.status) |
  map({
    status: .[0].status,
    count: length,
    total_hours: (map(.duration) | add / 3600),
    estimated_cost: ((map(.duration) | add / 3600) * ($rate | tonumber))
  })'
```

### Оптимизация Docker image size

**Практические рекомендации:**

```yaml
# .gitlab-ci.yml - оптимизированный Docker build

build:optimized:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_BUILDKIT: "1"
  script:
    # Использование multi-stage build
    - docker build --target=production -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .

    # Очистка неиспользуемых образов
    - docker image prune -f

    # Сжатие и отправка
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA

# Пример Dockerfile с оптимизацией
# FROM node:18-alpine AS builder
# WORKDIR /app
# COPY package*.json ./
# RUN npm ci --only=production
# COPY . .
# RUN npm run build
#
# FROM node:18-alpine AS production
# WORKDIR /app
# COPY --from=builder /app/dist ./dist
# COPY --from=builder /app/node_modules ./node_modules
# CMD ["node", "dist/main.js"]
```

**Размер образов (до/после оптимизации):**

| Образ | До | После | Экономия |
|---|---|---|---|
| Node.js app | 1.2GB | 180MB | 85% |
| Python app | 950MB | 220MB | 77% |
| Go app | 800MB | 15MB | 98% |

### Правила архивации артефактов

```yaml
# .gitlab-ci.yml - правила архивации

stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
      - build/
    exclude:
      - node_modules/
      - .git/
      - "*.log"
    expire_in: 7 days
    when: on_success

test:unit:
  stage: test
  script:
    - npm run test:unit
  artifacts:
    reports:
      junit: test-results.xml
    paths:
      - coverage/
    expire_in: 3 days

test:integration:
  stage: test
  script:
    - npm run test:integration
  artifacts:
    paths:
      - test-results/
    expire_in: 5 days
    when: always

deploy:staging:
  stage: deploy
  script:
    - npm run deploy:staging
  artifacts:
    paths:
      - deployment-info.json
    expire_in: 30 days
```

### Очистка старых пайплайнов

```bash
#!/bin/bash
# cleanup_old_pipelines.sh
# Очистка пайплайнов старше N дней

GITLAB_URL="https://gitlab.example.com"
PROJECT_ID="12345"
PRIVATE_TOKEN="glpat-xxxxx"
KEEP_DAYS=30
DRY_RUN=true

echo "=== Очистка пайплайнов старше $KEEP_DAYS дней ==="
echo "DRY_RUN: $DRY_RUN"

# Получение всех пайплайнов
page=1
pipelines=()

while true; do
  response=$(curl -s --header "PRIVATE-TOKEN: $PRIVATE_TOKEN" \
    "$GITLAB_URL/api/v4/projects/$PROJECT_ID/pipeline?per_page=100&page=$page")

  count=$(echo "$response" | jq length)
  if [ "$count" -eq 0 ]; then
    break
  fi

  pipelines+=("$response")
  page=$((page + 1))
done

# Фильтрация старых пайплайнов
cutoff_date=$(date -d "$KEEP_DAYS days ago" -Iseconds)
old_pipelines=()

for page_data in "${pipelines[@]}"; do
  old=$(echo "$page_data" | jq -r --arg cutoff "$cutoff_date" '
    .[] | select(.updated_at < $cutoff) | .id')
  old_pipelines+=($old)
done

echo -e "\nНайдено старых пайплайнов: ${#old_pipelines[@]}"

# Удаление
for pipeline_id in "${old_pipelines[@]}"; do
  if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN: Удаление пайплайна $pipeline_id"
  else
    curl -s --request DELETE --header "PRIVATE-TOKEN: $PRIVATE_TOKEN" \
      "$GITLAB_URL/api/v4/projects/$PROJECT_ID/pipelines/$pipeline_id"
    echo "Удален пайплайн: $pipeline_id"
  fi
done

echo -e "\nОчистка завершена"
```

### Правильное использование cache policy

```yaml
# .gitlab-ci.yml - стратегии кэширования

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  NPM_CONFIG_CACHE: "$CI_PROJECT_DIR/.cache/npm"

# Кэширование зависимостей (только чтение для test stage)
test:
  stage: test
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .cache/npm
      - node_modules/
    policy: pull
  script:
    - npm ci
    - npm test

# Кэширование зависимостей (чтение + запись для build stage)
build:
  stage: build
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .cache/npm
      - node_modules/
    policy: pull-push
  script:
    - npm ci
    - npm run build

# Кэширование зависимостей Python
test:python:
  stage: test
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip
    policy: pull
  script:
    - pip install -r requirements.txt
    - pytest

build:python:
  stage: build
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .cache/pip
    policy: pull-push
  script:
    - pip install -r requirements.txt
    - python setup.py sdist

# Кэширование Docker layers
build:docker:
  stage: build
  cache:
    key: docker-layers
    paths:
      - .docker-cache/
    policy: pull-push
  script:
    - docker load -i .docker-cache/layers.tar || true
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - mkdir -p .docker-cache
    - docker save $(docker images -q) > .docker-cache/layers.tar
```

### Анализ использования runner'ов

```bash
#!/bin/bash
# analyze_runners.sh
# Анализ использования GitLab runners

GITLAB_URL="https://gitlab.example.com"
PRIVATE_TOKEN="glpat-xxxxx"
GROUP_ID="67890"

echo "=== Анализ использования runners ==="

# Получение runners группы
runners=$(curl -s --header "PRIVATE-TOKEN: $PRIVATE_TOKEN" \
  "$GITLAB_URL/api/v4/groups/$GROUP_ID/runners?per_page=100")

echo -e "\n--- Список runners ---"
echo "$runners" | jq -r '.[] | "\(.id)\t\(.description)\t\(.status)\t\(.active)"'

# Статистика использования
echo -e "\n--- Статистика использования ---"
for runner_id in $(echo "$runners" | jq -r '.[].id'); do
  jobs=$(curl -s --header "PRIVATE-TOKEN: $PRIVATE_TOKEN" \
    "$GITLAB_URL/api/v4/runners/$runner_id/jobs?per_page=100")

  total_jobs=$(echo "$jobs" | jq length)
  successful=$(echo "$jobs" | jq '[.[] | select(.status == "success")] | length')
  failed=$(echo "$jobs" | jq '[.[] | select(.status == "failed")] | length')
  running=$(echo "$jobs" | jq '[.[] | select(.status == "running")] | length')

  echo -e "\nRunner $runner_id:"
  echo "  Всего задач: $total_jobs"
  echo "  Успешных: $successful"
  echo "  Неуспешных: $failed"
  echo "  Выполняется: $running"
  echo "  Процент успеха: $((successful * 100 / total_jobs))%"
done

# Рекомендации
echo -e "\n--- Рекомендации ---"
echo "1. Deactivate неиспользуемые runners"
echo "2. Оптимизируйте теги для правильного маршрутизации задач"
echo "3. Рассмотрите автоматическое масштабирование для пиковых нагрузок"
echo "4. Настройте timeout для предотвращения зависших задач"
```

## Дополнительная информация

### Связанные темы

- GitLab CI/CD Pipeline Configuration
- Docker Multi-stage Builds
- Kubernetes Cost Optimization
- Cloud Cost Management (AWS/GCP/Azure)
- FinOps Practices
- Infrastructure as Code (Terraform, Pulumi)
- Monitoring and Observability (Prometheus, Grafana)
- GitOps Workflows

### Чек-лист оптимизации стоимости

**Инфраструктура:**
- [ ] Проведен аудит текущих расходов на CI/CD
- [ ] Определены неиспользуемые ресурсы
- [ ] Настроено автоматическое масштабирование
- [ ] Выбраны оптимальные типы инстансов
- [ ] Настроена утилизация ресурсов (reserved instances, spot)

**Пайплайны:**
- [ ] Оптимизированы Docker образы (multi-stage, alpine)
- [ ] Настроено кэширование зависимостей
- [ ] Уменьшена частота запуска пайплайнов
- [ ] Используются conditional jobs
- [ ] Настроена parallelization для уменьшения времени выполнения

**Хранилище:**
- [ ] Настроены правила архивации артефактов
- [ ] Очищены старые артефакты и логи
- [ ] Оптимизированы Docker registry layers
- [ ] Настроена автоматическая очистка

**Мониторинг:**
- [ ] Настроены метрики стоимости пайплайнов
- [ ] Ведется учет cost per commit
- [ ] Мониторится cache hit rate
- [ ] Регулярно проводится анализ использования runners
- [ ] Настраиваются алерты на превышение бюджета

**Процессы:**
- [ ] Внедрены best practices для написания .gitlab-ci.yml
- [ ] Проводятся регулярные код-ревью конфигурации CI/CD
- [ ] Документированы стандарты оптимизации
- [ ] Обучена команда по cost optimization
- [ ] Внедрена культура ответственности за расходы