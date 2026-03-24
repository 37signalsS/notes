# Интеграция SAST и DAST в CI/CD

## Определения

Интеграция сканеров статического ([SAST](./sast_overview.md)) и динамического ([DAST](./dast_overview.md)) анализа в CI/CD конвейер — ключевая практика [DevSecOps](./devsecops_overview.md). Цель — получить быстрый и воспроизводимый сигнал о рисках безопасности до релиза, не замедляя разработку и не создавая ложных блокировок.

## Основные концепции

### Точки встраивания в конвейер

| Этап конвейера | Тип сканирования | Цель | Особенности |
| :--- | :--- | :--- | :--- |
| **Pull/Merge Request**| SAST | Ранний сигнал по изменённому коду | Инкрементальный анализ (diff), комментарии в MR. |
| **После сборки** | SAST | Проверка артефактов и зависимостей | Полный скан исходников и build-артефактов. |
| **Review-окружение** | DAST | Тестирование живого приложения | Аутентифицированные сценарии, ограничение нагрузки. |
| **Ночной регресс** | SAST/DAST | Полное глубокое сканирование | Длительные профили, расширенные правила. |
| **Перед релизом** | SAST/DAST | Финальный контроль (Release Gate) | Политики блокировки по критичности. |

### Политики и пороги

- **Порог критичности:** Минимальный уровень серьезности уязвимости (`High`, `Critical`), при котором сборка помечается как проваленная.
- **Бейзлайн (Baseline):** Фиксация текущего состояния уязвимостей. Пайплайн падает, только если появляются *новые* находки.
- **Исключения (Exceptions):** Централизованное управление ложными или принятыми рисками через файл конфигурации с указанием причины, ответственного и срока действия. Подробнее см. [Управление исключениями](#управление-исключениями).

### Оптимизация выполнения

- **Инкрементальные SAST-сканы:** Анализ только измененного кода для ускорения проверок в MR.
- **Кэширование:** Сохранение кэша сканера и его зависимостей между запусками.
- **Таймауты:** Установка жестких ограничений по времени выполнения, чтобы избежать "зависших" сборок.
- **Стандартизированные отчеты:** Использование форматов вроде SARIF для последующей агрегации и анализа.

## Практические сценарии

### Пример конфигурации GitLab CI

```yaml
stages: [build, test, security, deploy]

sast:
  stage: test
  image: registry.example.com/tools/sast:latest
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
  script:
    - sast-tool scan --changed-only --format sarif --out reports/sast.sarif
    - sast-tool gate --min-severity=high --input reports/sast.sarif
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

dast:
  stage: security
  needs: ["deploy_review"]
  image: registry.example.com/tools/dast:stable
  rules:
    - if: '$REVIEW_URL'
  variables:
    TARGET_URL: $REVIEW_URL
  script:
    - dast-tool auth --user test --password $TEST_PASS
    - dast-tool scan $TARGET_URL --profile quick --report reports/dast.json
    - dast-tool gate --min-severity=medium --input reports/dast.json
  artifacts:
    when: always
    paths: [reports/dast.json]
    expire_in: 7 days
```

### Пример Jenkinsfile (укороченный)

```groovy
pipeline {
  agent any
  stages {
    stage('SAST') {
      steps {
        sh 'sast-tool scan --format sarif -o reports/sast.sarif'
      }
    }
    stage('Deploy Review') {
      steps { sh './scripts/deploy_review.sh' }
    }
    stage('DAST') {
      steps {
        sh 'dast-tool scan "$REVIEW_URL" --profile quick -o reports/dast.json'
      }
    }
  }
  post {
    always { archiveArtifacts artifacts: 'reports/*', fingerprint: true }
  }
}
```

## Дополнительная информация

### Изоляция и безопасность DAST

- **Эфемерные окружения:** Запускайте DAST на временных средах, которые уничтожаются после сканирования.
- **Тестовые учетные данные:** Используйте временные или ограниченные в правах учетные записи.
- **Сетевые политики:** Изолируйте DAST-сканер и тестовую среду от продакшен-сегмента сети.

Подробнее о типах уязвимостей, выявляемых DAST, см. в [обзоре DAST](./dast_overview.md) и [типичных уязвимостях](./sast_dast_vulnerabilities.md).

### Управление исключениями

- Храните файл с исключениями в репозитории (`.sast-ignore`, `dast-exceptions.json`).
- Каждое исключение должно содержать идентификатор уязвимости, причину, автора и срок, до которого оно действует.
- Запрещайте бессрочные исключения и настройте автоматические уведомления об их пересмотре.

См. также [управление секретами](./secrets_management.md) для безопасного хранения чувствительных данных.

