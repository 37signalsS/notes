# Инструменты для генерации отчётов (JUnit, Allure)

## Обзор

Тестовые отчёты позволяют конвейеру автоматически интерпретировать результаты прогона, визуализировать падения и делать регресс-анализ. На практике используются два класса артефактов: машинно-читаемые отчёты в формате JUnit XML и человеко-ориентированные интерактивные отчёты Allure.

## JUnit XML: стандарт де-факто для CI

JUnit — это не только фреймворк для Java-тестов, но и формат XML-отчёта, который поддерживают большинство рантаймов и CI-систем. Многие не-Java инструменты умеют экспортировать в JUnit: pytest, Cypress, PHPUnit, Go test и др. В отчёте фиксируются тестовые сьюты, кейсы, статусы, длительности, сообщения об ошибках и логи.

### Минимальный фрагмент JUnit XML

```xml
<testsuite name="api" tests="3" failures="1" time="1.234">
  <testcase classname="api.users" name="test_get_user" time="0.120"/>
  <testcase classname="api.users" name="test_create_user" time="0.540">
    <failure message="Expected 201">AssertionError...</failure>
  </testcase>
  <testcase classname="api.users" name="test_delete_user" time="0.574">
    <skipped/>
  </testcase>
</testsuite>
```

Этот формат напрямую понимают Jenkins (шаг junit), GitLab (artifacts:reports:junit), GitHub Actions (анализ артефактов сторонними действиями).

### Генерация примерами

```bash
# Pytest
pytest --junitxml=report.xml

# Maven Surefire/FailSafe (JUnit/TestNG)
mvn -DskipTests=false test
# отчёты: target/surefire-reports/*.xml
```

## Allure: интерактивные отчёты и аналитика

Allure формирует детальные отчёты с шагами, прикреплениями, категориями дефектов, флейки-детектором и историей. Поток типовой: тестовый раннер сохраняет результаты в allure-results (JSON + вложения), затем генератор строит HTML-отчёт.

### Особенности

- Структура по сьютам, фичам, история запуска и тренды
- Вложения: скриншоты, запросы/ответы, логи
- Лейблы и ссылки на задачи для трассируемости

### Генерация (Python)

```bash
pip install allure-pytest
pytest --alluredir=allure-results
allure generate allure-results -o allure-report --clean
```

### Java-проекты (JUnit 5)

```xml
<!-- pom.xml -->
<dependencies>
  <dependency>
    <groupId>io.qameta.allure</groupId>
    <artifactId>allure-junit5</artifactId>
  </dependency>
</dependencies>
```

```bash
mvn test
# результаты появятся в target/allure-results
allure generate target/allure-results -o target/allure-report --clean
```

## Сравнение

| Критерий | JUnit XML | Allure |
|----------|-----------|--------|
| Назначение | Машинный формат для CI | Интерактивная аналитика |
| Содержимое | Статусы, тайминги, логи | Шаги, вложения, истории, категории |
| Поддержка в CI | Нативная публикация | Плагин/генерация + артефакт |
| Вес/скорость | Минимальные | Выше из‑за HTML и вложений |

## Интеграция в пайплайны

### Jenkins (Declarative Pipeline)

```groovy
pipeline {
  stages {
    stage('Test') {
      steps {
        sh 'pytest --junitxml=report.xml --alluredir=allure-results'
      }
      post {
        always {
          junit 'report.xml'
          allure includeProperties: false, results: [[path: 'allure-results']]
        }
      }
    }
  }
}
```

### GitLab CI

```yaml
test:
  image: python:3.12
  script:
    - pip install pytest allure-pytest
    - pytest --junitxml=report.xml --alluredir=allure-results
    - allure generate allure-results -o allure-report --clean
  artifacts:
    reports:
      junit: report.xml
    paths:
      - allure-report
    expire_in: 7 days
```

### GitHub Actions (фрагмент)

```yaml
- run: pytest --junitxml=report.xml --alluredir=allure-results
- uses: actions/upload-artifact@v4
  with:
    name: junit
    path: report.xml
- run: allure generate allure-results -o allure-report --clean
- uses: actions/upload-artifact@v4
  with:
    name: allure
    path: allure-report
```

## Практики

- Единый шаблон имён тестов и сьютов для устойчивых трендов
- Прикрепляйте ключевые артефакты: запросы/ответы API, скриншоты, логи
- Разделяйте отчёты по компонентам и веткам, добавляйте build tags/labels
- Храните директорию history из предыдущего отчёта Allure, чтобы сохранить тренды между прогонами
- Учитывайте параллелизм: сводите результаты из шардов перед генерацией Allure
