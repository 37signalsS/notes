# Типичный поток пайплайна

## Определения

- **Поток пайплайна (Pipeline Workflow)** — последовательность этапов и задач, выполняемых для автоматизированной доставки кода от момента фиксации (commit) до развертывания в продуктивной среде.

- **Quality Gates (Ворота качества)** — автоматизированные проверки на определенных этапах пайплайна (например, порог покрытия тестами или отсутствие критических уязвимостей), непрохождение которых блокирует дальнейшее продвижение изменений.

- **DAG (Directed Acyclic Graph)** — механизм в CI/CD, позволяющий запускать задачи на основе их зависимостей, а не только по завершении целого этапа, что значительно ускоряет выполнение пайплайна.

## Основные концепции

### Принципы эффективного пайплайна

1. **Fail-Fast (Падай быстро)**
   Самые быстрые и критичные проверки (линтеры, Unit-тесты) должны выполняться первыми. Это экономит время разработчика и ресурсы инфраструктуры.

2. **Параллелизм и DAG**
   Независимые задачи должны выполняться одновременно. Использование **needs** (в GitLab CI) позволяет начать сборку артефакта сразу после завершения тестов, не дожидаясь окончания всех задач на этапе тестирования.

3. **Иммутабельность артефактов**
   Артефакт (например, Docker-образ) должен собираться один раз и проходить через все среды (`staging`, `prod`) без пересборки. Для идентификации используются уникальные теги (например, `Git SHA`).

### Каноническая структура (Lifecycle)

Современный пайплайн интегрирует практики **DevSecOps** и включает следующие фазы:

1. **Lint (Статический анализ)**
   - Проверка стиля кода, синтаксических ошибок и безопасности кода (**SAST**).
   - Инструменты: `eslint`, `golangci-lint`, `hadolint` (для Dockerfile).

2. **Test (Тестирование)**
   - Запуск Unit-тестов и расчет покрытия (**Coverage**).
   - Применение **Quality Gate**: если покрытие ниже целевого (например, 80%), пайплайн прерывается.

3. **Build (Сборка)**
   - Создание исполняемых файлов или Docker-образов.
   - Использование **Multi-stage builds** для минимизации размера и повышения безопасности образа.

4. **Security Scan (Сканирование)**
   - Проверка собранного образа на наличие известных уязвимостей (**SCA**).
   - Инструменты: `Trivy`, `Grype`.

5. **Push (Публикация)**
   - Отправка проверенного образа в **Container Registry** с иммутабельным тегом.

6. **Deploy (Развертывание)**
   - Автоматическая выкатка в `development`/`staging`.
   - Развертывание в `production` после ручного подтверждения (**Manual Approval**) или автоматизировано после прохождения `E2E`-тестов в `staging`.

## Практические сценарии

### Пример современного пайплайна (GitLab CI)

```yaml
stages:
  - validate
  - test
  - build
  - security
  - deploy

variables:
  IMAGE_TAG: "${CI_COMMIT_SHORT_SHA}"

# 1. Быстрая проверка
lint:
  stage: validate
  script:
    - golangci-lint run ./...

# 2. Тесты с Quality Gate
unit_tests:
  stage: test
  script:
    - go test -coverprofile=coverage.out ./...
    - go tool cover -func=coverage.out | grep total | awk '{print $3}' | sed 's/%//' > coverage.txt
    - if [ $(cat coverage.txt | cut -d. -f1) -lt 80 ]; then echo "Coverage too low"; exit 1; fi
  artifacts:
    reports:
      junit: report.xml

# 3. Сборка (зависит только от тестов через DAG)
build_image:
  stage: build
  needs: ["unit_tests"]
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$IMAGE_TAG .
    - docker push $CI_REGISTRY_IMAGE:$IMAGE_TAG

# 4. Сканирование безопасности
vulnerability_scan:
  stage: security
  needs: ["build_image"]
  script:
    - trivy image --exit-code 1 --severity CRITICAL $CI_REGISTRY_IMAGE:$IMAGE_TAG

# 5. Деплой (авто в dev, ручной в prod)
deploy_prod:
  stage: deploy
  when: manual
  only:
    - main
  script:
    - ./deploy.sh production $IMAGE_TAG
  environment: production
```

## Дополнительная информация

- **Глоссарий терминов:** [Определения Jobs, Stages, Runners](./pipeline_glossary.md).
- **Метрики эффективности:** [Метрики DORA (Lead Time, CFR)](./dora_metrics.md).
- **Стратегии развертывания:** [Rolling Update, Canary, Blue-Green](./deployment_strategies.md).
- **Основы GitLab CI:** [Синтаксис и возможности](../GitLab_CI/Concepts/gitlab_ci_basics.md).
- **GitOps подход:** [Пример GitOps-пайплайна](../../GitOps/gitops_pipeline_example.md).
