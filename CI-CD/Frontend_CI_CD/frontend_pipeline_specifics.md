# Специфические задачи Frontend CI/CD

## Определения

**Инвалидация CDN (CDN Invalidation / Purge)** — процесс принудительной очистки кэша на пограничных узлах (Edge) для немедленного обновления контента у пользователей. В CI/CD автоматизируется через API провайдера. Позволяет сбросить устаревшие версии файлов до истечения их TTL.

**Cache Busting (Сброс кэша)** — стратегия управления кэшированием, при которой изменение содержимого файла приводит к изменению его URL (обычно через хэш контента). Это заставляет браузер и CDN загрузить новую версию, игнорируя старый кэш, и позволяет использовать заголовки `immutable`.

**Performance Budgets (Бюджеты производительности)** — набор количественных ограничений на метрики производительности (LCP, CLS, TBT) или размеры артефактов (Bundle Size). Если изменения в коде приводят к выходу за эти рамки, пайплайн CI/CD считается проваленным.

**A11y Automation (Accessibility)** — автоматизированная проверка веб-интерфейса на соответствие стандартам доступности (WCAG 2.2/3.0). Цель — выявление проблем навигации и восприятия контента для пользователей с ограниченными возможностями на ранних этапах (Shift-left).

**WebMCP (Web Model Context Protocol)** — стандарт 2026 года для обеспечения «понимания» веб-интерфейса AI-агентами (LLM-браузерами). Включает проверку семантической разметки, доступности данных для парсинга и наличие атрибутов для AI-ориентированного взаимодействия.

## Требования к окружению

Для реализации Frontend-специфичных задач в пайплайне необходимы:

-   **Node.js LTS (v22+):** Стандарт для 2026 года, обеспечивающий поддержку современных API и инструментов сборки.
-   **Headless-окружение для браузеров:** Раннеры с поддержкой Chromium/Puppeteer/Playwright для запуска Lighthouse и pa11y. Рекомендуется использовать образы `mcr.microsoft.com/playwright` или аналоги.
-   **Сетевой доступ к Edge API:** Разрешенные исходящие соединения к API провайдеров (Cloudflare, AWS, Fastly) для выполнения инвалидации.
-   **Секреты (Secrets Management):** Безопасное хранение API-ключей, ID зон CDN и доступов к Object Storage.

## Основные концепции

### Стратегии Cache Busting

В 2026 году стандартом является использование **Immutable Cache** для статики и **Revalidation** для HTML.

#### 1. URL Fingerprinting (Хэширование) — Рекомендуется
Build-инструменты (Vite, Webpack, Rspack) генерируют уникальный хэш на основе содержимого: `app.a3f92bc1.js`.
-   **Плюс:** Позволяет использовать заголовок `Cache-Control: public, max-age=31536000, immutable`.
-   **CI/CD:** Хэширование должно происходить строго на этапе сборки (`build`).
-   **Пример Vite (`vite.config.ts`):**
    ```typescript
    export default defineConfig({
      build: {
        rollupOptions: {
          output: {
            entryFileNames: `[name].[hash].js`,
            chunkFileNames: `[name].[hash].js`,
            assetFileNames: `[name].[hash].[ext]`
          }
        }
      }
    })
    ```

#### 2. Query Strings (Legacy)
Добавление версии через параметры: `style.css?v=1.2.3`.
-   **Минус:** Некоторые прокси-серверы и CDN игнорируют query-параметры при формировании Cache Key. Не рекомендуется для современной инфраструктуры из-за риска получения старой версии.

#### 3. Path Versioning
Использование версии в пути: `/v1.2.3/main.js`.
-   **Применение:** Полезно для версионирования API или библиотек, где важна обратная совместимость путей и атомарность переключения версий.

### Инвалидация CDN в пайплайне

Инвалидация должна происходить **после** успешной загрузки новых артефактов на Origin (S3/GCS/Nginx).

#### Сценарий 1: Полная очистка (Purge All)
Используется при глобальных обновлениях, смене архитектуры или если Cache Busting не применяется для части ресурсов.
```bash
# Пример для Cloudflare через API (GitHub Actions / GitLab CI)
curl -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
     -H "Authorization: Bearer ${CF_API_TOKEN}" \
     -H "Content-Type: application/json" \
     --data '{"purge_everything":true}'
```

#### Сценарий 2: Теговая инвалидация (Surrogate Keys) — Standard 2026
Самый эффективный и экономный метод. Позволяет инвалидировать только связанные ресурсы (например, только страницы товаров из категории X).
1.  **Build:** Присвоение тегов через заголовки ответа (например, `Cache-Tag: assets-v1`, `Surrogate-Key: page-home`).
2.  **CI/CD:** Вызов Purge по конкретному тегу через API провайдера (Fastly, Akamai, CloudFront).
```bash
# Пример запроса к Fastly API
curl -X POST "https://api.fastly.com/service/${SERVICE_ID}/purge/${TAG_NAME}" \
     -H "Fastly-Key: ${FASTLY_API_TOKEN}" \
     -H "Accept: application/json"
```
```bash
# Пример AWS CloudFront API (классический путь)
aws cloudfront create-invalidation --distribution-id ${DIST_ID} --paths "/static/*"
```

---

## Практические сценарии

### Тестирование производительности (Lighthouse CI)

Интеграция **LHCI** в пайплайн предотвращает деградацию Core Web Vitals (LCP, CLS, INP) через механизмы **Quality Gates** и **Regression Detection**. Подробная методология: **[Методология тестирования производительности](../../Testing/performance_testing_methodology.md)**.

#### Конфигурация (`.lighthouserc.js`)
Для минимизации вариативности в CI (Network Jitter) рекомендуется делать минимум 3–5 прогонов и использовать медианные значения.

```javascript
module.exports = {
  ci: {
    collect: {
      numberOfRuns: 3,
      startServerCommand: 'npm run start',
      settings: {
        emulatedFormFactor: 'mobile',
        throttlingMethod: 'simulate',
      },
    },
    assert: {
      // 1. Абсолютные пороги (Quality Gates)
      assertions: {
        'categories:performance': ['error', {minScore: 0.9}],
        'largest-contentful-paint': ['error', {maxNumericValue: 2500}],
        'cumulative-layout-shift': ['error', {maxNumericValue: 0.1}],
      },
    },
    upload: {
      target: 'temporary-public-storage',
    },
  },
};
```

#### Regression Detection (Сравнение с Baseline)
В 2026 году стандартной практикой является сравнение с результатами из `main` ветки для выявления деградации даже при прохождении абсолютных порогов.

1.  **LHCI Server:** Используйте выделенный сервер LHCI для хранения истории прогонов. LHCI автоматически сравнивает текущий билд с базовым (base commit) и отображает диффы метрик в GitHub/GitLab.
2.  **Сравнение артефактов:** Если сервер не используется, сохраняйте `manifest.json` как артефакт и сравнивайте его в CI:
    ```yaml
    performance-check:
      script:
        - lhci collect && lhci assert
        - |
          # Сравнение LCP с базовой линией (baseline.json)
          CURR_LCP=$(jq '.[0].summary.lcp' .lighthouseci/manifest.json)
          BASE_LCP=$(jq '.[0].summary.lcp' baseline.json)
          if (( $(echo "$CURR_LCP > $BASE_LCP * 1.1" | bc -l) )); then
            echo "Frontend Performance Regression: LCP increased by >10%"
            exit 1
          fi
    ```

### Тестирование доступности (A11y)

Использование `pa11y-ci` для базового контроля WCAG 2.2 в пайплайне.

#### Интеграция в пайплайн (GitLab CI)
```yaml
test_a11y:
  stage: test
  image: mcr.microsoft.com/playwright:v1.49.0-noble # Образ с браузерами
  script:
    - npm install -g pa11y-ci
    - pa11y-ci --standard WCAG2AA --threshold 0 --sitemap https://preview.example.com/sitemap.xml
  allow_failure: true # Можно оставить true для постепенного внедрения
```

### Визуальное регрессионное тестирование (Visual Regression)

Контроль целостности UI через сравнение скриншотов. Позволяет отловить ошибки верстки, которые не выявляются функциональными тестами. Детальное руководство: **[Visual Regression в CI/CD](../Testing/visual-regression-cicd.md)**.

#### Сценарий для Frontend пайплайна
В 2026 году рекомендуется разделять визуальные тесты на два уровня:
1.  **Компонентный уровень:** Тестирование изолированных компонентов (например, через Playwright + Storybook).
2.  **E2E уровень:** Проверка критических страниц (Landing, Checkout) в сборе.

#### Пример интеграции с Playwright (`.gitlab-ci.yml`)
```yaml
test_visual:
  stage: test
  image: mcr.microsoft.com/playwright:v1.49.0-noble
  script:
    - npm ci
    # Использование Docker-образа гарантирует консистентность шрифтов
    - npx playwright test --grep @visual
  artifacts:
    when: on_failure
    paths:
      - playwright-report/
    expire_in: 1 week
```

#### Управление эталонами (Snapshots)
Для фронтенд-проектов в GitLab CI наиболее эффективны:
-   **Percy/Applitools:** Полностью снимают проблему хранения и сравнения скриншотов, предоставляя удобный UI для дизайнеров.
-   **Git LFS:** Если используется Playwright `toHaveScreenshot`, эталоны хранятся в Git. Требует обязательного обновления эталонов строго в том же Docker-контейнере, что и в CI.

### WebMCP (AI Readiness)

В 2026 году тесты доступности расширяются проверкой на «понятность» для AI-агентов:
- **Семантика:** Наличие корректных `aria-label` для интерактивных элементов, не имеющих текста.
- **Данные:** Отсутствие «пустых» ссылок и кнопок.
- **Микроразметка:** Валидация JSON-LD или Schema.org для предоставления структурированных данных AI-парсерам.
- **AI-Hinting:** Проверка наличия `data-ai-description` для сложных динамических компонентов.

---

## Проверка корректности

После выполнения деплоя и инвалидации необходимо убедиться в успехе операций:

1.  **Проверка заголовков кэширования:**
    ```bash
    curl -I https://cdn.example.com/assets/main.abc123.js
    # Ожидаемый результат: Cache-Control: public, max-age=31536000, immutable
    ```
2.  **Валидация инвалидации (X-Cache):**
    Запросите ресурс через `curl` и проверьте заголовки `X-Cache` (или аналогичные у провайдера). Первый запрос после деплоя должен вернуть `Miss` или `Refresh`, второй — `Hit`.
3.  **Анализ отчетов LHCI:**
    Убедитесь, что все «пороги» (assertions) пройдены, и ссылка на детальный отчет доступна в логах сборки.

## Диагностика и устранение проблем

-   **Высокая вариативность Lighthouse:**
    - *Причина:* Нестабильность ресурсов CI-раннера.
    - *Решение:* Используйте выделенные (dedicated) раннеры или увеличьте `numberOfRuns` до 5, ориентируясь на медиану.
-   **404 после деплоя (Race Condition):**
    - *Причина:* Инвалидация CDN сработала быстрее, чем файлы долетели до Object Storage.
    - *Решение:* Добавьте проверку доступности файла на Origin перед запуском Purge (например, через `curl --retry`).
-   **CDN не сбрасывает кэш по тегу:**
    - *Причина:* Неправильная настройка Surrogate-Key на уровне Origin (заголовок не пробрасывается).
    - *Решение:* Проверьте, что Origin отправляет заголовки тегов, и CDN настроена их интерпретировать.

## Лучшие практики

-   **Атомарные деплои:** Используйте уникальные пути для каждого релиза (например, по ID коммита), чтобы избежать смешивания старых и новых файлов в процессе переключения трафика.
-   **Сначала статика, потом HTML:** В пайплайне сначала загружайте JS/CSS/Assets, и только последним шагом — `index.html`. Это гарантирует, что пользователь не получит HTML, ссылающийся на еще не загруженные скрипты.
-   **Локальные бюджеты:** Настройте запуск `lhci` и `pa11y` в pre-push хуках, чтобы разработчики видели проблемы до запуска пайплайна.
-   **Мониторинг инвалидаций:** Логируйте время выполнения и объем инвалидаций (особенно для Purge All), чтобы отслеживать нагрузку на Origin.

---

## Практическая реализация (CI/CD Workflow)

1.  **Stage: Build**
    - Сборка с генерацией хэшей (URL Fingerprinting).
    - Линитинг метаданных WebMCP.
2.  **Stage: Test**
    - Запуск `pa11y-ci`.
    - Запуск `LHCI` (на временном окружении или Preview URL).
3.  **Stage: Deploy**
    - Синхронизация файлов с S3/Origin.
    - Установка метаданных (Surrogate Keys) и заголовков `Cache-Control: immutable`.
4.  **Stage: Post-Deploy**
    - Инвалидация CDN через API (Purge по тегу или путям).
    - Проверка доступности (Health Check / Smoke Test).

---

## Дополнительная информация

### См. также
- **[Политики кэширования и инвалидации в CDN](../../Networking/CDN/cdn_caching_and_invalidation.md)** — общие принципы работы и теория TTL.
- **[Тестирование производительности веб-приложений](../../WebServers/Concepts/web_performance/testing_principles.md)** — методология, эмуляция условий и метрики.
- **[Клиентское кэширование в Nginx](../../WebServers/Nginx/Performance/Caching/client_caching.md)** — реализация заголовков и Cache Busting на стороне сервера.
- **[Автоматизация миграций в CI/CD](../Databases/Concepts/migrations/database-ci-cd.md)** — концепции Quality Gates, применимые и к фронтенду.
