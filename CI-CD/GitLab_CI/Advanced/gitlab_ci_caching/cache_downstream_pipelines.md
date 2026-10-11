# Кэш в downstream-пайплайнах GitLab CI

**Актуально для:** GitLab 19.x / GitLab Runner 19.x
**Совместимость:** GitLab 18.x / Runner 18.x поддерживаются, но ряд флагов и оптимизаций требует 19.x.

## Определения

**Downstream-пайплайн** — пайплайн, запущенный из другого пайплайна через `trigger`. Включает parent-child (внутри одного проекта) и multi-project (между проектами).

**Bridge Job** — специальная задача, которая не выполняется на Runner'е, а служит прокси для запуска downstream-пайплайна.

**Кэш downstream-пайплайна** — кэш, созданный задачами дочернего пайплайна. Не наследуется автоматически от родительского пайплайна.

**Shared Distributed Cache** — общий S3/MinIO кэш, доступный из нескольких проектов или пайплайнов через одинаковые ключи.

## Предварительные требования

Для работы с кэшем в downstream-пайплайнах необходимо:
- **GitLab:** 19.x (совместимость с 18.x сохранена, ряд оптимизаций требует 19.x)
- **GitLab Runner:** 19.x (для `zipzstd` и параллельного кэширования требуется Runner 19.3+)
- **Объектное хранилище:** настроенный S3/MinIO backend для Distributed Cache при использовании cross-project кэширования
- **Сеть:** Runner'ы должны иметь доступ к объектному хранилищу по HTTPS (443/8443)
- **RBAC:** Для настройки кэша и триггеров в downstream-проекте требуется роль Maintainer или Owner
- **Синхронизация времени (NTP):** Требуется для корректной работы pre-signed URL в Distributed Cache

### Переменные окружения и конфигурация Runner

| Переменная | Версия | Значение по умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `CACHE_COMPRESSION_FORMAT` | Runner 16.2+ | `zip` / `zstd` | Алгоритм сжатия кэша. `zipzstd` доступен в Runner 19.3+ |
| `CACHE_COMPRESSION_LEVEL` | Runner 16.11+ | `1` | Уровень сжатия (1–22 для zstd). Более высокий уровень уменьшает размер, но увеличивает CPU |
| `FF_USE_FASTZIP` | Runner 13.1+ | `false` | Включает конкурентную упаковку/распаковку. Требует многоядерный CPU |
| `CACHE_LIMIT` | Runner 13.12+ | не задан | Максимальный размер кэша на задачу |
| `CACHE_FALLBACK_KEY` | Runner 8.0+ | не задан | Глобальный резервный ключ при отсутствии основного |

## Основные концепции

### 1. Кэш в parent-child пайплайнах

Parent-child пайплайн запускает дочерний пайплайн через `trigger`. Общая архитектура parent-child: см. SSoT **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)**.

#### 1.1. Поведение кэша

- **Родительский пайплайн** создаёт свой кэш на основе своих ключей.
- **Дочерний пайплайн** создаёт свой собственный кэш на основе своих ключей.
- Даже если ключи кэша совпадают, дочерний пайплайн не видит кэш родителя, если они используют разные Runner pools или разные конфигурации кэша.

#### 1.2. Передача артефактов от родителя к дочернему

Для передачи зависимостей от родителя к дочернему пайплайну используйте артефакты:

```yaml
# Родительский пайплайн
generate_config:
  stage: prepare
  script:
    - python3 scripts/generate-config.py > child-pipeline.yml
  artifacts:
    paths: [child-pipeline.yml]

trigger_child:
  stage: trigger
  trigger:
    include:
      artifact: child-pipeline.yml
    strategy: depend
```

**Важно:** Артефакты передаются через Bridge Job. Размер артефактов ограничен лимитами GitLab (по умолчанию 100 MB на instance-level).

#### 1.3. Общий Distributed Cache

Если родительский и дочерний пайплайн используют:
- Один и тот же S3/MinIO bucket для кэша.
- Одинаковые ключи кэша.
- Runner'ы с доступом к этому bucket.

Тогда дочерний пайплайн может использовать кэш, созданный родительским:

```yaml
# Оба пайплайна используют одинаковый ключ
cache:
  key:
    files: [package-lock.json]
    prefix: shared-deps
  paths: [.npm/]
  policy: pull-push
```

**Условия:**
- Ключи кэша должны совпадать.
- `policy: pull-push` в дочернем пайплайне позволяет читать и дополнять кэш.
- Runner'ы дочернего пайплайна должны иметь доступ к тому же S3 bucket.

### 2. Кэш в multi-project пайплайнах

Multi-project пайплайн запускает пайплайн в другом проекте через `trigger:project`. Общая архитектура multi-project: см. SSoT **[Multi-project пайплайны](../Downstream_Pipelines/multi_project_pipelines.md)**.

#### 2.1. Изоляция кэша по проектам

Кэш в GitLab CI **изолирован по проектам**. Даже при использовании одинаковых ключей, кэш проекта А не виден из проекта Б.

```yaml
# Проект А
trigger_project_b:
  stage: trigger
  trigger:
    project: group/project-b
    branch: main
```

**Поведение:** Project B создаёт свой собственный кэш. Кэш Project A не передаётся.

#### 2.2. Обход изоляции

Для общего кэша между проектами используйте:
1. **Общий S3 bucket** с одинаковой конфигурацией в `config.toml` Runner'ов обоих проектов.
2. **Одинаковые ключи кэша** в `.gitlab-ci.yml`.
3. **Shared Runner** — Runner, доступный для обоих проектов.

```yaml
# Оба проекта
cache:
  key:
    files: [package-lock.json]
    prefix: cross-project-deps
  paths: [.npm/]
  policy: pull-push
```

**Предупреждение:** Общий кэш между проектами снижает изоляцию и увеличивает риск cache poisoning. Используйте только в доверенных окружениях.

#### 2.3. Передача артефактов между проектами

Для передачи данных между проектами используйте `needs:project`:

```yaml
# Проект Б
integration_test:
  stage: test
  needs:
    - project: group/project-a
      job: build_binary
      ref: main
      artifacts: true
  script:
    - ./run-integration.sh
```

**Кэш:** `needs:project` передаёт только артефакты, не кэш. Для кэша используйте общий Distributed Cache.

### 3. Практические сценарии

#### Сценарий 1: Parent-child с общим кэшем

```yaml
# Родительский пайплайн (.gitlab-ci.yml)
stages:
  - prepare
  - trigger

generate_child_config:
  stage: prepare
  script:
    - python3 scripts/generate-child-config.py > child.yml
  artifacts:
    paths: [child.yml]

trigger_child:
  stage: trigger
  trigger:
    include:
      artifact: child.yml
    strategy: depend
  cache:
    key:
      files: [package-lock.json]
      prefix: parent-child-shared
    paths: [.npm/]
    policy: pull-push
```

```yaml
# Дочерний пайплайн (child.yml)
stages:
  - build
  - test

install:
  stage: build
  script:
    - npm ci
  cache:
    key:
      files: [package-lock.json]
      prefix: parent-child-shared
    paths: [.npm/]
    policy: pull-push

test:
  stage: test
  script:
    - npm test
  cache:
    key:
      files: [package-lock.json]
      prefix: parent-child-shared
    paths: [.npm/]
    policy: pull
```

**Поведение:**
- `generate_child_config` создаёт конфигурацию дочернего пайплайна.
- `trigger_child` запускает дочерний пайплайн.
- Оба пайплайна используют одинаковый ключ кэша `parent-child-shared`.
- Дочерний пайплайн читает кэш, созданный родительским (если Runner'ы имеют доступ к тому же S3 bucket).

#### Сценарий 2: Multi-project с общим кэшем провайдеров

```yaml
# Проект A (.gitlab-ci.yml)
cache:
  key:
    files: [package-lock.json]
    prefix: cross-project-deps
  paths: [.npm/]
  policy: pull-push

build:
  stage: build
  script:
    - npm ci
    - npm run build

trigger_project_b:
  stage: trigger
  trigger:
    project: group/project-b
    branch: main
```

```yaml
# Проект B (.gitlab-ci.yml)
cache:
  key:
    files: [package-lock.json]
    prefix: cross-project-deps
  paths: [.npm/]
  policy: pull-push

build:
  stage: build
  script:
    - npm ci
    - npm run build
```

**Условия:**
- Оба проекта используют одинаковый S3 bucket в `config.toml`.
- Runner'ы обоих проектов имеют доступ к этому bucket.
- Ключи кэша совпадают.

**Результат:** Project B читает кэш, созданный Project A, и наоборот.

#### Сценарий 3: Передача артефактов через needs:project

```yaml
# Проект B
integration_test:
  stage: test
  needs:
    - project: group/project-a
      job: build_binary
      ref: main
      artifacts: true
  script:
    - ls backend-api/
    - ./run-integration.sh
```

**Кэш:** `needs:project` передаёт только артефакты. Кэш не передаётся. Для кэша используйте общий Distributed Cache.

#### Сценарий 4: Downstream с динамической конфигурацией

```yaml
# Родительский пайплайн
generate_config:
  stage: prepare
  script:
    - python3 scripts/generate-config.py > child.yml
  artifacts:
    paths: [child.yml]

trigger_child:
  stage: trigger
  trigger:
    include:
      artifact: child.yml
    strategy: depend
```

**Проблема:** Дочерний пайплайн может иметь другие ключи кэша, чем родительский. Решение — используйте общий префикс в ключах:

```yaml
# Дочерний пайплайн
cache:
  key:
    files: [package-lock.json]
     prefix: parent-child-shared  # Одинаковый префикс
  paths: [.npm/]
```

### Best Practices

#### Выбор стратегии кэширования

1. **Parent-child пайплайны:** Используйте общий Distributed Cache только когда parent и child используют общий Runner pool. В противном случае кэш не будет доступен из-за изоляции на уровне Runner'ов.
2. **Multi-project пайплайны:** Предпочитайте артефакты (`needs:project`) вместо общего кэша для критичных данных. Кэш — best-effort механизм: он не гарантирует целостность и может быть удалён в любой момент.
3. **Изоляция:** Для production-проектов используйте уникальные префиксы кэша. Общий кэш между проектами снижает изоляцию и увеличивает риск cache poisoning.
4. **Размер:** Держите кэш минимально необходимым. Для больших зависимостей используйте Package Registry вместо кэша.
5. **Fallback:** Используйте `fallback_keys` с базовым ключом из `main` для обеспечения стабильности при изменении lock-файлов.

#### SRE: Мониторинг и алертинг

- **Метрика:** Процент cache hit/miss по downstream-пайплайнам. Низкий hit rate указывает на несовпадающие ключи или отсутствие общего S3/MinIO backend.
- **Алерт:** Cache miss в downstream после успешного parent-пайплайна с совпадающими ключами — проверьте доступ Runner'ов к S3 bucket и конфигурацию `config.toml`.
- **Алерт:** Размер кэша превышает лимит Runner'а — проверьте `CACHE_LIMIT` и lifecycle политики S3.
- **Алерт:** Повышение времени restore кэша — проверьте сетевую задержку между Runner'ами и S3/MinIO.

#### Sysadmin: Эксплуатация

- **S3 lifecycle:** Настройте lifecycle политики для удаления устаревших кэшей. Слишком агрессивные политики вызывают cache miss; слишком мягкие — заполняют bucket.
- **Версионирование:** Включите versioning в S3/MinIO для отката при cache poisoning или случайном удалении.
- **Сеть:** При использовании S3-совместимого storage в self-managed инсталляции откройте порт 443/8443 между Runner'ами и storage.
- **Синхронизация времени:** Синхронизируйте время между GitLab, Runner'ами и S3/MinIO через NTP. Это критично для pre-signed URL.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Downstream-пайплайн не видит кэш parent-пайплайна | Кэш изолирован по проектам по умолчанию | Настройте общий S3/MinIO bucket с одинаковыми ключами кэша в конфигурации Runner'ов |
| Downstream-пайплайн не видит кэш parent-пайплайна | Runner'ы используют разные pools | Перенесите downstream на Runner'ы с доступом к тому же S3/MinIO backend |
| Cache miss при совпадающих ключах | Runner'ы downstream не имеют доступа к S3/MinIO bucket | Проверьте сетевую доступность и конфигурацию S3 в `config.toml` Runner'ов |
| Cache miss после успешного parent-пайплайна | Кэш удалён по S3 lifecycle политике | Увеличьте TTL в lifecycle или используйте `fallback_keys` с базовым ключом |
| Артефакт >100 MB не передаётся downstream | Instance limit (по умолчанию 100 MB) | Используйте Package Registry, внешнее хранилище или общий Distributed Cache |
| Взаимная блокировка пайплайнов | Одинаковая `resource_group` с `oldest_first` | Определите `resource_group` в родительской задаче `trigger`, а не в дочерней |
| Cache poisoning в shared кэше | Общий кэш с экспериментальной веткой | Используйте уникальные префиксы кэша или изолируйте кэш по проектам |
| Downstream-пайплайн запускается медленнее parent | Cache miss из-за несовпадающих ключей | Убедитесь, что ключи кэша (`files`, `prefix`) идентичны в parent и downstream |

#### Диагностика

Для диагностики проблем с кэшем в downstream-пайплайнах:

1. **Проверьте конфигурацию Runner'ов:**
    ```bash
    # Проверьте конфигурацию кэша в config.toml
    cat /etc/gitlab-runner/config.toml | grep -A 10 cache
    ```

2. **Проверьте ключи кэша в логах задачи:**
    GitLab Runner логирует используемый ключ кэша. Ищите строку с ключом кэша в выводе задачи.

3. **Проверьте доступность S3/MinIO:**
    ```bash
    # Проверьте доступность S3/MinIO из среды Runner'а
    curl -I https://minio.example.com/
    ```

4. **Проверьте метрики кэша в UI:**
    - Откройте пайплайн в GitLab UI: `CI/CD > Pipelines > [pipeline] > [job]`
    - Раздел Cache показывает статистику hit/miss

### 5. Дополнительная информация

#### См. также

- **[Обзор кэширования](./caching_overview.md)** — архитектура и уровни хранения.
- **[Ключи и политики](./cache_keys.md)** — `cache:key`, `fallback_keys`, `policy`.
- **[Лучшие практики](./cache_best_practices.md)** — безопасность, мониторинг, SRE.
- **[Практические сценарии](./cache_scenarios.md)** — примеры для языков и инфраструктуры.
- **[Артефакты в GitLab CI](./gitlab_ci_artifacts.md)** — передача данных между стадиями.
- **[Кэш и директивки пайплайна](./cache_pipeline_directives.md)** — взаимодействие `rules`, `needs`, `interruptible` и `resource_group` с кэшем.
- **[Кэш и executor'ы](./cache_executor_specifics.md)** — особенности кэширования для Docker, Shell, Kubernetes и Instance executor'ов.
- **[Родительско-дочерние пайплайны](../Downstream_Pipelines/parent_child_pipelines.md)** — архитектура, Bridge Jobs, strategy mirror.
- **[Multi-project пайплайны](../Downstream_Pipelines/multi_project_pipelines.md)** — кросс-проектные триггеры и Zero Trust.
- **[Downstream-пайплайны: лучшие практики](../Downstream_Pipelines/best_practices.md)** — CI_JOB_TOKEN, allowlist, ограничения.
