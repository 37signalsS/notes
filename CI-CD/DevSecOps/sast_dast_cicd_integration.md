# Интеграция SAST и DAST в CI/CD

## Определения

**Интеграция сканеров статического (SAST — Static Application Security Testing)** и **динамического (DAST — Dynamic Application Security Testing)** анализа в конвейер **CI/CD (Continuous Integration / Continuous Deployment — непрерывная интеграция и непрерывное развертывание)** является ключевой практикой методологии **DevSecOps**.

Цель интеграции — получение быстрого и воспроизводимого сигнала о рисках безопасности до релиза, минимизация времени обнаружения уязвимостей и предотвращение их попадания в промышленную среду без создания неоправданных задержек в процессе разработки.

## Основные концепции

### Точки встраивания в конвейер

| Этап конвейера | Тип сканирования | Цель | Особенности |
| :--- | :--- | :--- | :--- |
| **Pull/Merge Request**| SAST | Ранний сигнал по изменённому коду | Инкрементальный анализ (diff), комментарии в **MR (Merge Request — запрос на слияние)**. |
| **После сборки** | SAST | Проверка артефактов и зависимостей | Полный скан исходников и build-артефактов. |
| **Review-окружение** | DAST | Тестирование живого приложения | Аутентифицированные сценарии, ограничение нагрузки. |
| **Ночной регресс** | SAST/DAST | Полное глубокое сканирование | Длительные профили, расширенные правила. |
| **Перед релизом** | SAST/DAST | Финальный контроль (Release Gate) | Политики блокировки по критичности. |

### Политики и пороги качества (Quality Gates)

- **Порог критичности:** Минимальный уровень серьезности уязвимости (`High`, `Critical`), при котором автоматизированная сборка помечается как проваленная.
- **Бейзлайн (Baseline):** Фиксация текущего состояния безопасности. Пайплайн блокируется только при обнаружении *новых* уязвимостей, появившихся после фиксации базы.
- **Управление исключениями:** Централизованная обработка ложных срабатываний или принятых рисков через конфигурационные файлы (например, `.sast-ignore`) с указанием обоснования и срока действия.

### Оптимизация производительности

- **Инкрементальное сканирование:** Анализ только измененных файлов для ускорения обратной связи в MR.
- **Кэширование:** Сохранение промежуточных результатов и баз данных сканера между запусками.
- **Таймауты:** Установка жестких лимитов времени выполнения для предотвращения блокировки конвейера зависшими процессами.
- **Стандартизация отчетов:** Использование открытых форматов, таких как **SARIF (Static Analysis Results Interchange Format — формат обмена результатами статического анализа)**, для агрегации данных из разных инструментов.

## Практические сценарии

### Пример конфигурации в GitLab CI

```yaml
stages: [build, test, security, deploy]

sast_scan:
  stage: test
  image: registry.example.com/tools/sast:latest
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
  script:
    # Запуск анализа только измененного кода
    - sast-tool scan --changed-only --format sarif --out reports/sast.sarif
    # Проверка на соответствие порогу критичности
    - sast-tool gate --min-severity=high --input reports/sast.sarif
    # → Результат: задача завершится с ошибкой при обнаружении уязвимостей уровня High и выше
  artifacts:
    when: always
    paths: [reports/sast.sarif]
    expire_in: 7 days

deploy_review:
  stage: deploy
  script: ./scripts/deploy_review.sh
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: $REVIEW_URL

dast_scan:
  stage: security
  needs: ["deploy_review"]
  image: registry.example.com/tools/dast:stable
  rules:
    - if: '$REVIEW_URL'
  variables:
    TARGET_URL: $REVIEW_URL
  script:
    # Выполнение аутентификации перед сканированием
    - dast-tool auth --user test --password $TEST_PASS
    # Запуск динамического анализа review-окружения
    - dast-tool scan $TARGET_URL --profile quick --report reports/dast.json
    # Применение порогов безопасности
    - dast-tool gate --min-severity=medium --input reports/dast.json
    # → Результат: отчет dast.json и остановка пайплайна при обнаружении Medium-уязвимостей
  artifacts:
    when: always
    paths: [reports/dast.json]
    expire_in: 7 days
```

### Пример: Интеграция встроенного SAST в GitLab CI (бесплатная версия)

В бесплатной версии GitLab можно использовать стандартный шаблон и добавить задачу для анализа его результатов.

```yaml
stages: [test, report]

include:
  - template: Security/SAST.gitlab-ci.yml

# Задача 'sast' из шаблона генерирует отчет gl-sast-report.json

analyze_sast_results:
  stage: report
  image: alpine:latest
  before_script:
    - apk add --no-cache jq
  script:
    # Анализ JSON-отчета и поиск уязвимостей
    - |
      if [ -f "gl-sast-report.json" ] && [ $(jq '.vulnerabilities | length' gl-sast-report.json) -gt 0 ]; then
        echo "ALERT: Security issues detected!"
        cat gl-sast-report.json
        exit 1
      else
        echo "No security issues detected."
      fi
    # → Результат: пайплайн будет остановлен, если список уязвимостей не пуст
  artifacts:
    paths: [gl-sast-report.json]
```

### Пример Jenkinsfile (укороченный)

```groovy
pipeline {
  agent any
  stages {
    stage('SAST') {
      steps {
        # Статический анализ исходного кода
        sh 'sast-tool scan --format sarif -o reports/sast.sarif'
        # → Результат: генерация отчета в формате SARIF
      }
    }
    stage('Deploy Review') {
      steps { 
        sh './scripts/deploy_review.sh' 
        # → Результат: развертывание временной среды для тестирования
      }
    }
    stage('DAST') {
      steps {
        # Динамический анализ развернутого приложения
        sh 'dast-tool scan "$REVIEW_URL" --profile quick -o reports/dast.json'
        # → Результат: генерация отчета по результатам тестирования "черным ящиком"
      }
    }
  }
  post {
    always { 
      archiveArtifacts artifacts: 'reports/*', fingerprint: true 
    }
  }
}
```

## Дополнительная информация

### Безопасность и изоляция при выполнении DAST

- **Эфемерные окружения:** Использование временных сред, которые уничтожаются сразу после завершения сканирования.
- **Тестовые учетные записи:** Выделение изолированных аккаунтов с ограниченными правами доступа для сканера.
- **Сетевая сегментация:** Изоляция сканера и целевой среды от продуктовых сегментов сети.

Подробнее о специфике методов: [Обзор SAST](./sast_overview.md), [Обзор DAST](./dast_overview.md), [Типичные уязвимости](./sast_dast_vulnerabilities.md).

### Управление исключениями (False Positives)

- Хранение файлов исключений (например, `.sast-ignore`, `dast-exceptions.json`) непосредственно в репозитории проекта.
- Обязательное указание идентификатора уязвимости, причины исключения, автора и срока пересмотра.
- Регулярный аудит списка исключений для предотвращения накопления нерешенных проблем.

См. также [Управление секретами в CI/CD](./secrets_management.md) для защиты чувствительных данных, необходимых сканерам.
