# SonarQube / SonarCloud: статический анализ качества и безопасности кода

## Определения

**SonarQube** — open-source платформа (Community Edition) для непрерывного контроля качества кода (Continuous Code Quality), объединяющая статический анализ (SAST), метрики технического долга и контроль соблюдения стандартов кодирования. Является ключевым инструментом реализации практики **Clean Code**.

**SonarCloud** — SaaS-версия SonarQube, управляемая разработчиками SonarSource. Использует тот же сканирующий движок, что и SonarQube, но не требует самостоятельной эксплуатации серверной инфраструктуры. Поддерживает интеграцию с GitHub, GitLab и Bitbucket через GitHub App / GitLab App.

**Edition / Уровень лицензирования:**

| Уровень | Модель | Ключевые ограничения / особенности |
|:---|:---|:---|
| **Community Edition** | Бесплатная, open-source | Базовый SAST, 30+ языков, пороги качества (Quality Gates), Branch Analysis. Нет PR Decoration, enterprise-фич и официальной поддержки. |
| **Developer Edition** | Платная | Добавляет **PR Decoration** (комментарии в MR/PR), ветвление (Branch Analysis), пороги для веток, поддержку большего числа языков. |
| **Enterprise Edition** | Платная | Добавляет управление порогами на уровне портфолио, Saas-безопасность, управление выпусками (Release), глобальные портфельные дашборды. |
| **Data Center Edition** | Платная | Активный-активная кластеризация для критической инфраструктуры с требованиями к SLA. |

**Clean Code** — философия и практика написания кода, который понятен, поддерживаем и безопасен. В контексте SonarQube Clean Code определяется через три измерения:
- **Reliability (Надёжность):** Отсутствие багов, приводящих к падениям или неправильному поведению.
- **Security (Безопасность):** Отсутствие уязвимостей, exploitable извне.
- **Maintainability (Поддерживаемость):** Низкий технический долг, понятность кода, отсутствие "code smells".

**Quality Gate (Ворота качества)** — набор автоматизированных критериев, которые проект должен пройти для успешного завершения анализа. Quality Gate может блокировать слияние кода (MR/PR) или деплой, если условия не выполнены. По умолчанию SonarQube использует условие **"Quality Gate"** (passed/failed), которое вычисляется на основе метрик Reliability, Security, Maintainability Rating и Coverage на новых строках кода.

**Quality Profile (Профиль качества)** — набор правил (rules), активных для конкретного языка программирования в проекте. Определяет, какие паттерны кода будут анализироваться и как классифицироваться. Профили наследуются от родительского проекта или глобального шаблона.

**Issue (Проблема)** — конкретное нарушение, найденное сканером в коде. Каждая Issue привязана к:
- **Rule** — шаблон нарушения.
- **Type (Тип):** Bug, Vulnerability, Code Smell, Security Hotspot.
- **Severity (Серьёзность):** Blocker, Critical, Major, Minor, Info.
- **Status:** Open, Confirmed, Resolved, Closed.
- **Debt (Технический долг):** Оценочное время на исправление.

**Rule (Правило)** — детектор, описывающий паттерн проблемного кода. Каждое правило имеет уникальный ключ (например, `java:S1192`), описание, примеры "хорошего" и "плохого" кода, а также ссылку на стандарт или CWE.

**Security Hotspot (Точка безопасности)** — участок кода, использующий чувствительные API (шифрование, авторизация, сессии), который требует ручного аудита. В отличие от обычных Vulnerability, Security Hotspot не считается автоматически уязвимым — разработчик или аудитор должен подтвердить или опровергнуть риск.

**PR Decoration (Декорирование Merge Request)** — механизм, при котором SonarQube отправляет комментарии прямо в интерфейс GitLab MR или GitHub PR с детальным описанием найденных проблем, обновлённым статусом Quality Gate и данными о покрытии. Доступен только в Developer Edition и выше.

**Branch Analysis (Анализ веток)** — функциональность Developer Edition+, позволяющая анализировать отдельные ветки и вычислять метрики качества только для нового кода (new code) в этой ветке, а не для всего проекта.

## Архитектура

### Компоненты SonarQube Server (self-hosted)

```text
[Сканер (Scanner)] → HTTP/HTTPS → [SonarQube Server (Web + Search + Compute Engine)]
                                                    ↓
                                              [База данных (PostgreSQL)]
```

1.  **SonarQube Server:** Выполняет три основные функции:
    - **Web Server:** API, интерфейс, управление проектами и пользователями.
    - **Search Server (Elasticsearch):** Индексация и полнотекстовый поиск по Issues, правилам и исходному коду.
    - **Compute Engine (CE):** Фоновый процесс, который обрабатывает отчеты сканирования, вычисляет метрики, применяет Quality Gates и сохраняет результаты в БД.

2.  **Scanner:** Легковесный агент, который запускается в CI/CD. Читает конфигурацию проекта, анализирует исходный код и отправляет отчет в SonarQube Server. Доступны:
    - **SonarScanner CLI** (универсальный, для любых языков)
    - **SonarScanner for Maven / Gradle / .NET / npm / Jenkins / GitLab** (интегрированные плагины)

3.  **База данных:** PostgreSQL (рекомендуемая) или MySQL/Microsoft SQL Server/Oracle (для Enterprise). Хранит конфигурацию, историю анализов, Issues, метрики.

4.  **Плагины (Plugins):** Расширяют функциональность SonarQube. В 2024+ году большинство языков поддерживаются встроенно (SonarQube Language Plugin), внешние плагины используются реже.

### Версионирование и поддержка

- **LTS (Long-Term Support):** Каждая вторая мажорная версия получает статус LTS (например, 10.x). Рекомендуется для production.
- **Active:** Промежуточные версии с новыми функциями, поддержка ~6 месяцев.
- **Миграция:** Обновление между LTS версиями поддерживается напрямую. Обновление с non-LTS на LTS может требовать промежуточных шагов.

## Основные концепции

### Quality Profiles (Профили качества)

Quality Profile определяет набор активных правил для конкретного языка. Ключевые принципы:
- **Наследование:** Дочерний профиль наследует правила от родительского. Это позволяет создавать корпоративные стандарты (Corporate Profile), которые невозможно отключить в дочерних.
- **Activation (Активация):** Правила могут быть активны по умолчанию, или включаться вручную.
- **Deprecation (Устаревание):** Правила помечаются устаревшими при изменении стандартов. SonarQube предлагает замену (replacement) через Remediation Function.
- **Custom Rules (Кастомные правила):** В Developer Edition+ можно создавать собственные правила на основе шаблонов (XSlicing, XPath) для поиска специфичных паттернов.

### Quality Gates (Ворота качества)

Quality Gate вычисляется **асинхронно** после завершения фонового анализа (Compute Engine). Результат — бинарный статус `PASSED` или `FAILED`.

**Стандартные условия (SonarQube 10.x / SonarCloud 2026):**
- **Reliability Rating:** `A` или `B` (отсутствие критических и блокирующих багов на новом коде).
- **Security Rating:** `A` или `B` (отсутствие критических уязвимостей на новом коде).
- **Maintainability Rating:** `A` или `B` (технический долг < 5% на новом коде).
- **Coverage on New Code:** Покрытие тестами новых строк > 80% (настраиваемо).
- **Duplicated Lines on New Code:** < 3% (настраиваемо).
- **No New Issues (Critical/Blocker):** Отсутствие новых критических проблем.

**Важно:** Quality Gate применяется к **новому коду (New Code)**, а не ко всему проекту. Это соответствует принципу **Clean as You Code**. Определение "нового кода" настраивается:
- **Previous version** (предыдущая версия)
- **Number of days** (например, последние 30 дней)
- **Reference branch** (например, `main`)

### Issues и классификация

| Тип | Описание | Пример |
|:---|:---|:---|
| **Bug** | Потенциальная ошибка, влияющая на надёжность. | Null pointer dereference, resource leak. |
| **Vulnerability** | Уязвимость безопасности, exploitable извне. | SQL injection, XSS, insecure deserialization. |
| **Code Smell** | Проблема поддерживаемости, не влияющая напрямую на безопасность или надёжность. | Дублирование кода, слишком большие функции, неочевидные имена. |
| **Security Hotspot** | Чувствительный участок кода, требующий ручного аудита. | Использование `crypto.random`, ручное управление сессиями. |

**False Positive (Ложное срабатывание):** Разработчик может пометить Issue как `Won't Fix` или `False Positive`, что исключает его из Quality Gate и отчётов.

### Branch Analysis и PR Decoration

**Branch Analysis:**
- Каждая ветка анализируется отдельно.
- Для каждой ветки вычисляются отдельные метрики.
- Ветка считается "основной" (main branch), если она помечена как таковой в настройках проекта.
- Pull Requests анализируются инкрементально: только дифф между базовой веткой и веткой MR.

**PR Decoration (Developer Edition+):**
- После завершения анализа SonarQube отправляет статус в GitLab/GitHub через API.
- В интерфейсе MR/PR появляются:
  - Общий статус Quality Gate (`passed` / `failed`).
  - Список новых Issues с привязкой к строкам кода.
  - Метрики: покрытие новых строк, дублирование, технический долг.
  - Ссылка на детальный отчёт в SonarQube.

## Практические сценарии

### Сценарий 1: Установка SonarQube Server (Docker Compose)

**Требования:**
- Docker Engine 24.0+ и Docker Compose v2.0+
- 4+ CPU, 8+ GB RAM, 50+ GB диска
- PostgreSQL 15+ (можно использовать внешний managed-сервис)

**Файл `docker-compose.yml`:**

```yaml
services:
  sonarqube:
    image: sonarqube:10.8-community
    container_name: sonarqube
    restart: unless-stopped
    ports:
      - "9000:9000"
    environment:
      - SONAR_JDBC_URL=jdbc:postgresql://db:5432/sonarqube
      - SONAR_JDBC_USERNAME=sonarqube
      - SONAR_JDBC_PASSWORD=<SECRET_3b23309b>      volumes:
      - sonarqube_data:/opt/sonarqube/data
      - sonarqube_extensions:/opt/sonarqube/extensions
      - sonarqube_logs:/opt/sonarqube/logs
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16-alpine
    container_name: sonarqube-db
    restart: unless-stopped
    environment:
      - POSTGRES_USER=sonarqube
      - POSTGRES_PASSWORD=<SECRET_3b23309b>      - POSTGRES_DB=sonarqube
    volumes:
      - postgresql_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sonarqube"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  sonarqube_data:
  sonarqube_extensions:
  sonarqube_logs:
  postgresql_data:
```

**Запуск:**

```bash
docker compose up -d
```

**Проверка:**

```bash
# Ожидание готовности (около 1-2 минут)
curl -s http://localhost:9000/api/system/status | jq .
# → {"id":"...","version":"10.8.0","status":"UP"}
```

**Первоначальная настройка:**
1. Открыть `http://<server-ip>:9000`.
2. Войти с логином `admin` / паролем `admin` (смена пароля при первом входе обязательна).
3. Создать проект вручную или через **SonarScanner** (автоматическое определение).
4. Сгенерировать токен доступа (My Account → Security → Generate Tokens).

### Сценарий 2: Интеграция в GitLab CI/CD

**Установка SonarScanner CLI в Runner:**

```yaml
# .gitlab-ci.yml
stages:
  - sonar-scan

variables:
  SONAR_HOST_URL: "https://sonarqube.example.com"
  SONAR_TOKEN: $SONAR_TOKEN  # Переменная в CI/CD Settings → Variables (protected, masked)

sonarqube-scan:
  stage: sonar-scan
  image: sonarsource/sonar-scanner-cli:11
  script:
    - sonar-scanner \
        -Dsonar.projectKey=my-project \
        -Dsonar.sources=. \
        -Dsonar.host.url=$SONAR_HOST_URL \
        -Dsonar.login=$SONAR_TOKEN \
        -Dsonar.language=python \
        -Dsonar.python.coverage.reportPaths=coverage.xml \
        -Dsonar.pullrequest.key=$CI_MERGE_REQUEST_IID \
        -Dsonar.pullrequest.branch=$CI_COMMIT_REF_NAME \
        -Dsonar.pullrequest.base=$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME
  only:
    - merge_requests
    - main
  artifacts:
    when: always
    reports:
      sonarqube: report-task.txt
```

**Важные параметры:**
- `-Dsonar.pullrequest.key`: Номер MR в GitLab (`$CI_MERGE_REQUEST_IID`).
- `-Dsonar.pullrequest.branch`: Имя ветки MR.
- `-Dsonar.pullrequest.base`: Базовая ветка MR (source branch в GitLab API — ветка, в которую делается merge).

**Включение блокировки MR при падении Quality Gate (GitLab Premium/Ultimate):**
GitLab нативно не блокирует Merge Request при падении внешнего Quality Gate. Для реализации блокировки используйте:
1. **GitLab CI/CD Job Rules:** Проверка статуса Quality Gate через API SonarQube.
2. **Merge Request Widget:** SonarQube Developer Edition отображает статус в боковой панели MR, но не блокирует кнопку "Merge".
3. **Approval Rules:** Настройка Approval Rules, где статус Quality Gate является одним из условий (требует кастомной интеграции или использования GitLab Ultimate Policies).

### Сценарий 3: Конфигурация Quality Gate

**Создание кастомного Quality Gate через UI:**

1. Перейти в **Quality Gates** → **Create**.
2. Добавить условия:
   - **Condition 1:** `Coverage on New Code` `< 80%` → `Failed`
   - **Condition 2:** `Duplicated Lines on New Code` `> 3%` → `Failed`
   - **Condition 3:** `New Reliability Rating` `worse than A` → `Failed`
   - **Condition 4:** `New Security Rating` `worse than A` → `Failed`
   - **Condition 5:** `New Maintainability Rating` `worse than A` → `Failed`
3. Назначить Quality Gate проекту:
   - **Project Settings → Quality Gates → Select Quality Gate.**

**Конфигурация через API (Python):**

```python
import requests

SONAR_HOST = "https://sonarqube.example.com"
SONAR_TOKEN = "<your-token>"
HEADERS = {"Authorization": f"Bearer {SONAR_TOKEN}"}

def create_quality_gate(name, conditions):
    """Создание Quality Gate и добавление условий."""
    # Создание гейта
    r = requests.post(
        f"{SONAR_HOST}/api/qualitygates/create",
        headers=HEADERS,
        data={"name": name}
    )
    gate_id = r.json()["id"]

    # Добавление условий
    for cond in conditions:
        requests.post(
            f"{SONAR_HOST}/api/qualitygates/create_condition",
            headers=HEADERS,
            data={
                "gateId": gate_id,
                "metric": cond["metric"],
                "operator": cond["operator"],
                "threshold": cond["threshold"],
                "error": cond["error"]
            }
        )

conditions = [
    {"metric": "coverage", "operator": "LT", "threshold": "80", "error": "Coverage < 80%"},
    {"metric": "duplicated_lines_density", "operator": "GT", "threshold": "3", "error": "Duplication > 3%"},
    {"metric": "new_reliability_rating", "operator": "GT", "threshold": "1", "error": "Reliability worse than A"},
]

create_quality_gate("My Corporate Gate", conditions)
# → Quality Gate created with 3 conditions
```

### Сценарий 4: Установка и настройка плагинов (Extensions)

**Установка плагина через Marketplace (SonarQube 10+):**

1. **Administration → Marketplace.**
2. Найти нужный плагин (например, `SonarJava`, `SonarPython`, `SonarJS`).
3. Нажать **Install** и перезапустить SonarQube.

**Установка плагина вручную (Docker):**

```bash
# Скачать .jar плагина
curl -O https://binaries.sonarsource.com/Distribution/sonar-java-plugin/sonar-java-plugin-7.28.1.33619.jar

# Скопировать в volume extensions
docker cp sonar-java-plugin-7.28.1.33619.jar sonarqube:/opt/sonarqube/extensions/plugins/

# Перезапуск
docker compose restart sonarqube
```

**Список поддерживаемых языков (встроенно, 10.x):**
Java, C#, Python, JavaScript/TypeScript, Go, C/C++, Kotlin, Ruby, PHP, Swift, Scala, Apex, COBOL, PL/SQL, T-SQL, HTML, CSS, XML.

### Сценарий 5: Анализ конфигурации IaC (Terraform, Dockerfile, Kubernetes)

**Важно:** SonarQube анализирует конфигурационные файлы как код. Для Terraform, Dockerfile и Kubernetes манифестов используются отдельные плагины/правила.

```yaml
# Пример: SonarQube обнаруживает insecure defaults в Dockerfile
FROM python:3.12-slim

# Issue (Critical): "A Docker image should not use the root user"
USER root  # ← SonarQube: Security Hotspot

COPY . /app
RUN pip install -r /app/requirements.txt

# Issue (Major): "Dockerfile 'EXPOSE' should not be used"
EXPOSE 8000

CMD ["python", "/app/app.py"]
```

**Рекомендуемые параметры сканирования для многоязычных проектов:**

```bash
sonar-scanner \
  -Dsonar.sources=src \
  -Dsonar.inclusions=**/*.py,**/*.js,**/*.tf \
  -Dsonar.exclusions=**/*.test.js,**/*_test.go,**/vendor/**,**/node_modules/** \
  -Dsonar.python.coverage.reportPaths=coverage/coverage.xml \
  -Dsonar.javascript.lcov.reportPaths=coverage/lcov.info
```

## Дополнительная информация

### Ключевые метрики SonarQube

| Метрика | Описание | Целевое значение |
|:---|:---|:---|
| **Coverage** | Процент строк, покрытых модульными тестами. | > 80% на новом коде |
| **Duplications** | Дублирующиеся блоки кода. | < 3% на новом коде |
| **Technical Debt** | Оценочное время на исправление всех Code Smells. | < 5% на новом коде |
| **Reliability Rating** | Буквенная оценка (A–E) по шкале надёжности. | A или B |
| **Security Rating** | Буквенная оценка по шкале безопасности. | A или B |
| **Maintainability Rating** | Буквенная оценка по шкале поддерживаемости. | A или B |
| **Security Hotspots Reviewed** | Процент Security Hotspots, прошедших ручной аудит. | 100% |
| **Lines of Code** | Общее количество строк кода (LOC). | Аналитическая метрика |
| **Cognitive Complexity** | Сложность понимания логики функции (алгоритм Cognitive Complexity). | < 15 на функцию |

### Основные вкладки интерфейса SonarQube

- **Measures (Метры)** — отображает текущие значения всех метрик (Coverage, Duplications, Debt, Security Rating) по проекту, директориям и типам файлов.
- **Activity (Активность / История)** — показывает динамику изменений метрик между анализами (build'ами). Позволяет отслеживать, улучшается или ухудшается качество со временем, и какие именно коммиты внесли изменения.
- **Issues (Проблемы)** — полный список всех найденных проблем с фильтрацией по типу, тегу, тегу Clean Code, назначенному разработчику и статусу.
- **Code (Код)** — навигация по исходникам с индикаторами проблем (прямо в браузере).
- **Pull Requests (Merge Requests)** — список MR/PR, их статус Quality Gate и декларированные Issues (только Developer Edition+).
- **Administration** — управление профилями качества, Quality Gates, пользователями, группами и правами.

### Сравнение SonarQube с альтернативами

| Инструмент | Тип | Лицензия | Ключевые особенности |
|:---|:---|:---|:---|
| **SonarQube** | SAST / Platform | Community (OSS) + Proprietary | Clean Code, Quality Gates, PR Decoration, 30+ языков. |
| **SonarCloud** | SaaS / SAST | Proprietary | Облачная версия SonarQube, интеграция с GitHub/GitLab/Bitbucket. |
| **Semgrep** | SAST | OSS + Proprietary | Быстрый, rule-based анализ с поддержкой кастомных правил. Меньший охват языков. |
| **Checkmarx** | SAST / Platform | Proprietary | Enterprise-фокус, высокий охват языков, интеграция с ASPM. |
| **CodeQL (GitHub)** | Semantic Analysis | OSS + Proprietary | Анализ кода как базы данных (query-based), глубокая интеграция в GitHub. |

### Ограничения и важные нюансы

1.  **Ресурсы Server:** Вычислительный движок (CE) требует значительных ресурсов для больших кодовых баз (>1M LOC). Рекомендуется выделенный сервер с 8+ CPU и 16+ GB RAM.
2.  **Порог входа:** Настройка кастомных Quality Profiles и Gates требует понимания специфики языка и кодовой базы. Без настройки стандартные профили могут давать высокий уровень шума (false positives).
3.  **Задержка анализа:** Полный анализ может занимать от нескольких минут до часа в зависимости от размера проекта. Инкрементальный анализ (PR Decoration) работает быстрее, но только в Developer Edition+.
4.  **False Positives:** Автоматический анализ не способен понять бизнес-контекст. Разработчик должен вручную классифицировать Won't Fix / False Positive.
5.  **Security Hotspots vs Vulnerabilities:** Security Hotspot — это не уязвимость, а сигнал для аудита. Ошибка классификации (все Hotspots считаются уязвимостями) приводит к необоснованному росту Technical Debt.
6.  **Licensing:** Community Edition полностью бесплатна, но ограничена. Для PR Decoration, Branch Analysis и enterprise-фич требуется лицензия Developer/Enterprise.

### Best Practices

1.  **Shift Left:** Запускайте SonarQube анализ на этапе PR, а не только на main. Это снижает стоимость исправления дефектов.
2.  **Quality Gate как prerequisite:** Настройте Quality Gate так, чтобы падение блокировало деплой в Production. В GitLab это реализуется через `rules` и проверку статуса через API.
3.  **Incremental Analysis:** Используйте `sonar.scm.exclusions.disabled=true` и анализ только нового кода (New Code), чтобы не накапливать долг Legacy-проекта.
4.  **Custom Quality Profiles:** Не используйте стандартные профили "как есть". Адаптируйте их под корпоративные стандарты кодирования, отключая нерелевантные для проекта правила.
5.  **IaC Scanning:** Включите анализ Dockerfile, Terraform, Kubernetes манифестов и GitHub Actions workflows — уязвимости в инфраструктурном коде часто критичнее, чем в прикладном.
6.  **Technical Debt Budget:** Установите лимит на приемлемый технический долг на нового кода (например, < 5%). Это предотвращает "долговую ловушку" в Legacy-проектах.

### Связанные темы

- **[SAST — Обзор](../DevSecOps/sast_overview.md)** — статический анализ безопасности, сопоставление инструментов.
- **[Интеграция SAST/DAST в CI/CD](../DevSecOps/sast_dast_cicd_integration.md)** — практика встраивания в пайплайн.
- **[Уязвимости SAST и DAST](../DevSecOps/sast_dast_vulnerabilities.md)** — классификация дефектов.
- **[WAF (Web Application Firewall)](../../Security/ApplicationSecurity/waf.md)** — виртуальные патчи для runtime.
- **[Mетрики тестового покрытия](../../Testing/testing_coverage_metrics.md)** — связь покрытия и Quality Gates.

### Внешние ресурсы

- [Официальная документация SonarQube](https://docs.sonarqube.org/latest/)
- [SonarQube Editions](https://www.sonarsource.com/plans-and-pricing/)
- [Clean Code as You Code](https://www.sonarsource.com/solutions/clean-code/)
- [SonarScanner CLI](https://docs.sonarqube.org/latest/analysis/scan/sonarscanner/)
- [SonarQube GitLab Integration](https://docs.sonarqube.org/latest/analysis/gitlab/)
