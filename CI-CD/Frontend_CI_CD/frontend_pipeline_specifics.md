# Специфические задачи Frontend CI/CD

**Актуально для:** Node.js v22+, Playwright v1.49.0+, GitLab CI / GitHub Actions

## Определения

**Инвалидация CDN (CDN Invalidation / Purge)** — процесс принудительной очистки кэша на пограничных узлах (Edge) для немедленного обновления контента у пользователей. В CI/CD автоматизируется через API провайдера. Позволяет сбросить устаревшие версии файлов до истечения их TTL. Различается по гранулярности: полная очистка (`purge_everything`), по префиксу/пути (`/static/*`) и по тегу (Surrogate-Key / Cache-Tag) — последняя наиболее точна и дешева, так как затрагивает только связанные ресурсы.

**Cache Busting (Сброс кэша)** — стратегия управления кэшированием, при которой изменение содержимого файла приводит к изменению его URL (обычно через хэш контента). Это заставляет браузер и CDN загрузить новую версию, игнорируя старый кэш, и позволяет использовать заголовки `immutable`. Ключевая идея: имя файла становится частью его версии, поэтому старый кэш физически не может быть возвращён вместо нового.

**Performance Budgets (Бюджеты производительности)** — набор количественных ограничений на метрики производительности (LCP, CLS, TBT, INP) или размеры артефактов (Bundle Size). Если изменения в коде приводят к выходу за эти рамки, пайплайн CI/CD считается проваленным. Бюджеты делятся на две категории: метрики рантайма (Core Web Vitals, проверяются Lighthouse) и метрики размера (вес JS/CSS-бандлов, проверяются на этапе сборки).

**A11y Automation (Accessibility)** — автоматизированная проверка веб-интерфейса на соответствие стандартам доступности (WCAG 2.2). Цель — выявление проблем навигации и восприятия контента для пользователей с ограниченными возможностями на ранних этапах (Shift-left). Покрывает примерно 30–40% критериев WCAG; остальное требует ручной проверки.

**Артефакт сборки (Build Artifact)** — неизменяемый, воспроизводимый результат этапа `build`: скомпилированные и сжатые JS/CSS/HTML-файлы, графика, шрифты и манифест соответствия имён хэшам. Артефакт должен собираться один раз и передаваться между этапами пайплайна (build → test → deploy) без повторной сборки, инача нарушается принцип воспроизводимости и возникает риск расхождения «того, что тестировали» и «того, что задеплоили».

**Атомарный деплой (Atomic Deploy)** — стратегия выкладки, при которой переключение трафика со старой версии на новую происходит мгновенно и целостно (без окна, в котором пользователь видит смесь старых и новых файлов). На уровне файловой системы реализуется через паттерн «каталог релиза + символическая ссылка» (release directory + symlink swap).

**Дымовой тест / Smoke Test (Health Check)** — минимальная автоматическая проверка после деплоя, подтверждающая, что приложение отвечает, отдаёт корректный `index.html` и ссылается на доступные ассеты. Выполняется до объявления релиза успешным и до снятия старых версий.

**Воспроизводимая сборка (Reproducible Build)** — свойство сборки давать бит-в-бит идентичный результат при одинаковых исходниках и зависимостях. Обеспечивается фиксацией lock-файла (`package-lock.json`/`pnpm-lock.yaml`), отключением недетерминированных вставок (timestamp, случайный seed) и изоляцией окружения (контейнер). Критично для аудита и отката.

**Бюджет размера бандла (Bundle Size Budget)** — лимит на суммарный вес JavaScript/CSS-чанков (например, «основной бандл не более 150 КБ сжатого»). Проверяется на этапе сборки инструментами вроде `size-limit`, что дешевле и быстрее Lighthouse и ловит регрессию до прогона браузера.

## Требования к окружению

Для реализации Frontend-специфичных задач в пайплайне необходимы:

-   **Node.js LTS (v22+):** Стандарт для современных инструментов сборки (Vite, Rspack, Playwright). Версия рантайма должна быть зафиксирована в `.nvmrc` / `engines` и совпадать в CI и локально — иначе возникает рассинхрон бинарных нативных модулей (`node-sass`, `esbuild`, `swc`).
-   **Headless-окружение для браузеров:** Раннеры с поддержкой Chromium/Puppeteer/Playwright для запуска Lighthouse и `pa11y`. Рекомендуется использовать образы `mcr.microsoft.com/playwright` или аналоги — они гарантируют консистентность шрифтов и рендеринга, что критично для визуальных тестов.
-   **Сетевой доступ к Edge API:** Разрешенные исходящие соединения к API провайдеров CDN для выполнения инвалидации (см. ограничения ниже).
-   **Секреты (Secrets Management):** Безопасное хранение API-ключей, ID зон CDN и доступов. Секреты НЕ должны попадать в логи; в CI используются встроенные защищённые переменные (masked variables), а не файлы в репозитории.
-   **Сервер выдачи статики (Origin):** Nginx/Angie или любой web-сервер, способный отдавать `Cache-Control: immutable` и корректно обслуживать символические ссылки каталогов релиза. Для атомарного деплоя сервер должен резолвить symlink на момент каждого запроса (стандартное поведение Nginx при `root`).
-   **Хранилище артефактов:** Локальный/сетевой каталог или объектное хранилище для передачи `dist/` между этапами, а также для хранения N последних релизов (нужно для мгновенного отката).

## Основные концепции

### Стратегии Cache Busting

В современной инфраструктуре стандартом является использование **Immutable Cache** для статики и **Revalidation** для HTML. Принцип работы: браузер и промежуточные кэши (CDN, reverse proxy) формируют ключ кэша на основе URL. Если URL не меняется, клиент может получить устаревшую копию даже при истечении TTL из-за эвристик `Last-Modified`. Изменение имени файла (хэш) делает старую копию недостижимой по определению, поэтому для таких файлов безопасно выставлять `max-age=31536000, immutable` — браузер никогда не сделает повторный запрос за этим же URL.

#### 1. URL Fingerprinting (Хэширование) — Рекомендуется
Build-инструменты (Vite, Webpack, Rspack) генерируют уникальный хэш на основе содержимого: `app.a3f92bc1.js`.
-   **Плюс:** Позволяет использовать заголовок `Cache-Control: public, max-age=31536000, immutable`.
-   **CI/CD:** Хэширование должно происходить строго на этапе сборки (`build`). Артефакт с хэшированными именами должен быть получен на этапе `deploy` без пересборки.
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
-   **Теоретический нюанс (double-key caching):** Браузеры используют двойной ключ кэширования (Top-level Site + Resource URL). Это означает, что общие библиотеки с публичного CDN кэшируются отдельно для каждого сайта, поэтому выгода «общего CDN» для бандлов минимальна; хэширование собственных ассетов на своём Origin эффективнее.

#### 2. Query Strings (Строки запроса, Legacy)
Добавление версии через параметры: `style.css?v=1.2.3`.
-   **Минус:** Некоторые промежуточные прокси-серверы и CDN игнорируют query-параметры при формировании Cache Key, либо кэшируют `style.css?v=1.2.3` и `style.css?v=1.2.4` как один объект. Не рекомендуется для современной инфраструктуры из-за риска получения старой версии.

#### 3. Path Versioning (Версионирование пути)
Использование версии в пути: `/v1.2.3/main.js`.
-   **Применение:** Полезно для версионирования API или библиотек, где важна обратная совместимость путей и атомарность переключения версий. Для фронтенд-бандлов уступает fingerprinting, так как не решает проблему «забытого» старого чанка после удаления кода.

### Инвалидация CDN в пайплайне

Инвалидация должна происходить **после** успешной загрузки новых артефактов на Origin и **после** проверки их доступности (во избежание race condition, см. диагностику). HTML инвалидируется всегда (он не имеет хэша в имени), статика с хэшем — только при необходимости сброса закэшированной ошибки 404/500.

#### Сценарий 1: Полная очистка (Purge All)
Используется при глобальных обновлениях, смене архитектуры или если Cache Busting не применяется для части ресурсов.
```bash
# Пример для Cloudflare через API (GitHub Actions / GitLab CI)
curl -X POST "https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/purge_cache" \
     -H "Authorization: Bearer ${CF_API_TOKEN}" \
     -H "Content-Type: application/json" \
     --data '{"purge_everything":true}'
```
-   **Риск:** Purge All создаёт резкий всплеск запросов к Origin (cache stampede). Лимитируйте частоту и логируйте объём.

#### Сценарий 2: Теговая инвалидация (Surrogate Keys) — Standard
Самый эффективный и экономный метод. Позволяет инвалидировать только связанные ресурсы (например, только страницы товаров из категории X).
1.  **Build:** Присвоение тегов через заголовки ответа (например, `Cache-Tag: assets-v1`, `Surrogate-Key: page-home`). Заголовок должен пробрасываться с Origin до Edge без изменений.
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

#### Как Origin должен отдавать Surrogate-Key (пример Nginx)
Чтобы теговая инвалидация работала, Origin обязан отправлять теги и CDN — их интерпретировать. Минимальный пример проброса заголовка с сервера выдачи:
```nginx
location / {
    # Теги формируются приложением или шаблоном деплоя;
    # здесь — пример статического добавления для всех страниц раздела
    add_header Surrogate-Key "page-home assets-v1";
    add_header Cache-Control "public, max-age=60, stale-while-revalidate=300";
    try_files $uri $uri/ /index.html;
}
```
Подробная теория TTL и механизмов инвалидации — в **[Политики кэширования и инвалидации в CDN](../../Networking/CDN/cdn_caching_and_invalidation.md)**.

### Управление артефактами сборки

Артефакт собирается один раз на этапе `build` и передаётся далее через механизм artifacts CI (а не через повторный `npm run build` на каждом этапе). Это гарантирует, что Lighthouse, A11y и деплой тестируют именно тот бинарный результат, который попадёт в прод.

-   **Целостность:** Фиксируйте контрольную сумму артефакта (`sha256sum dist/** > dist.sha256`) и проверяйте её на этапе деплоя — защита от повреждения при передаче между раннерами.
-   **Retention:** Храните последние N артефактов (например, 10) для возможности быстрого отката без пересборки.
-   **Детерминизм:** Используйте `npm ci` (а не `npm install`) — он требует наличия `package-lock.json` и гарантирует идентичный набор зависимостей, что критично для воспроизводимости.

### Атомарный деплой и откат

Паттерн «каталог релиза + symlink» устраняет окно рассинхрона, когда `index.html` уже указывает на новые чанки, а сами файлы ещё не загружены. Структура:
```
/var/www/app/
├── releases/
│   ├── 2026-08-27-1a2b3c/   # полная копия dist/
│   ├── 2026-08-26-9f8e7d/
│   └── ...
└── current -> releases/2026-08-27-1a2b3c   # атомарная ссылка, на которую смотрит Nginx root
```
Переключение версий — это атомарная операция `ln -sfn`, что исключает состояние «частично обновлённого» сайта. Откат = переключение symlink обратно на предыдущий каталог (мгновенно, без повторной сборки).

### Performance Budgets: бюджеты размера бандла

Помимо Lighthouse (рантайм-метрики), размер бандла проверяется на этапе сборки — это быстрее и ловит регрессию до запуска браузера.
```json
// .size-limit.json
[
  {
    "name": "app",
    "path": "dist/assets/*.js",
    "limit": "150 KB",
    "gzip": true
  }
]
```
```bash
npx size-limit
# → Package size limit has exceeded by 12 KB (запуск завершится с exit code 1 → пайплайн упадёт)
```
Для анализа причин роста подключите `webpack-bundle-analyzer` / `rollup-plugin-visualizer` и публикуйте HTML-отчёт как артефакт (`expire_in: 1 week`).

### Наблюдаемость пайплайна (SRE)

Сборка фронтенда — это тоже сервис с метриками. Публикация длительности сборки, размера артефакта и результата тестов в Prometheus (через Pushgateway) позволяет строить тренды деградации и алерты.
```bash
# Пример отправки метрики длительности сборки в Pushgateway (без облачных зависимостей)
BUILD_DURATION_MS=$(echo "$(date +%s%3N) - $BUILD_START_MS" | bc)
cat <<EOF | curl -s --data-binary @- http://prometheus-pushgateway:9091/metrics/job/frontend-ci/instance/${CI_JOB_ID}
# TYPE frontend_build_duration_ms gauge
frontend_build_duration_ms{branch="${CI_COMMIT_REF_SLUG}"} ${BUILD_DURATION_MS}
# TYPE frontend_artifact_bytes gauge
frontend_artifact_bytes{branch="${CI_COMMIT_REF_SLUG}"} $(du -sb dist | cut -f1)
EOF
```
Аналогично пушатся `frontend_lhci_lcp_ms`, `frontend_a11y_errors`, `frontend_deploy_status`. Это превращает «чёрный ящик» CI в наблюдаемый процесс с историей регрессий.

---

## Практические сценарии

### Кэширование зависимостей и воспроизводимая сборка в CI

Повторная установка `node_modules` на каждом этапе — главный источник медленных пайплайнов и невоспроизводимости. Зависимости кэшируются по хэшу lock-файла, а сборка изолируется в контейнере.

```yaml
# GitLab CI — кэш зависимостей по хэшу lock-файла (подробнее: ключи кэша)
build:
  image: node:22-bookworm
  cache:
    key:
      files:
        - package-lock.json
      prefix: "deps-$CI_JOB_NAME"
    paths:
      - node_modules/
    policy: pull-push
  before_script:
    - npm ci --ignore-scripts   # --ignore-scripts снижает риск выполнения вредоносного postinstall
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week
```
-   **Почему `npm ci`, а не `npm install`:** `npm ci` удаляет `node_modules` и ставит точно то, что описано в lock-файле; `npm install` может обновить lock и дать другую версию. В CI всегда `npm ci`.
-   **Изоляция:** Запуск в `node:22-bookworm` (а не на «голом» раннере) устраняет влияние глобально установленных пакетов и различий ОС.
-   **Монорепозитории:** Для Turborepo/Nx используйте удалённый кэш задач (remote cache) на локальном/сетевом хранилище, ключ — хэш графа задач; это переиспользует результаты сборки между ветками.
-   Детально про политики и ключи кэша в CI — **[Ключи кэша и политики в GitLab CI](../GitLab_CI/Advanced/gitlab_ci_caching/cache_keys.md)**.

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
Стандартной практикой является сравнение с результатами из `main` ветки для выявления деградации даже при прохождении абсолютных порогов.

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

#### Бюджеты размера в том же пайплайне
```yaml
bundle-size:
  stage: test
  image: node:22-bookworm
  script:
    - npx size-limit   # упадёт (exit 1) при превышении лимита из .size-limit.json
  artifacts:
    when: on_failure
    paths:
      - stats.html     # визуализация роста бандла
```

### Тестирование доступности (A11y)

Использование `pa11y-ci` для базового контроля WCAG 2.2 в пайплайне. Для более глубокого покрытия добавьте `axe-core` (через `@axe-core/playwright` или `jest-axe`) на уровне компонентных тестов и `html-validate` для статической проверки разметки.

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

#### Компонентный уровень (jest-axe)
```javascript
import { axe } from 'jest-axe';
it('has no a11y violations', async () => {
  const { container } = render(<CheckoutForm />);
  expect(await axe(container)).toHaveNoViolations();
});
```
-   **Почему two-level:** `pa11y-ci` проверяет готовые страницы (E2E), `jest-axe` — компоненты в изоляции (быстрее, точнее указывает место). Вместе они закрывают ~35% критериев WCAG автоматически.

### Визуальное регрессионное тестирование (Visual Regression)

Контроль целостности UI через сравнение скриншотов с эталоном. Позволяет отловить ошибки верстки, которые не выявляются функциональными тестами. Полное руководство по настройке и CI-интеграции: **[Visual Regression в CI/CD](../Testing/visual-regression-cicd.md)**.

В контексте фронтенд-пайплайна визуальные тесты принято разделять на два уровня:
1.  **Компонентный уровень:** Изолированные компоненты (Playwright + Storybook).
2.  **E2E уровень:** Критические страницы (Landing, Checkout) в сборе.

### Деплой статики на Nginx через атомарную символическую ссылку

Практический sysadmin-сценарий выкладки `dist/` на сервер выдачи. Используется `rsync` в каталог релиза + атомарный `ln -sfn`.

```bash
# Переменные: RELEASE_NAME=$(date +%Y-%m-%d)-${CI_COMMIT_SHORT_SHA}
# 1. Подготовка каталога релиза на сервере
ssh deploy@origin "mkdir -p /var/www/app/releases/${RELEASE_NAME}"

# 2. Передача артефакта (только изменившихся файлов)
rsync -az --delete dist/ deploy@origin:/var/www/app/releases/${RELEASE_NAME}/

# 3. Атомарное переключение symlink (единственная мутация, видимая Nginx)
ssh deploy@origin "ln -sfn /var/www/app/releases/${RELEASE_NAME} /var/www/app/current"

# 4. Очистка старых релизов (оставляем 5 последних) — см. раздел «Откат»
ssh deploy@origin "ls -1dt /var/www/app/releases/* | tail -n +6 | xargs -r rm -rf"
```

Конфигурация Nginx, обслуживающая `current` и выдающая корректные заголовки для хэшированной статики:
```nginx
server {
    root /var/www/app/current;

    # Хэшированные ассеты: кэшируем бесконечно и immutable
    location /assets/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
        try_files $uri =404;
    }

    # HTML и прочее: короткий TTL + revalidation
    location / {
        add_header Cache-Control "public, max-age=60, stale-while-revalidate=300";
        try_files $uri $uri/ /index.html;
    }
}
```
-   **Почему `try_files` + `index.html`:** SPA-маршруты (например, `/profile`) не существуют физически; `try_files` отдаёт `index.html`, который сам подгрузит нужный чанк. Это не ломает Cache Busting, так как имя чанка уже в `$uri`.
-   Детали обслуживания файлов Nginx — **[Выдача статических файлов (serving_files)](../../WebServers/Nginx/Core/Location/serving_files.md)**.

### Откат релиза (Rollback)

Так как деплой — это смена symlink, откат выполняется мгновенно переключением ссылки на предыдущий каталог без пересборки:
```bash
# Список доступных релизов
ssh deploy@origin "ls -1dt /var/www/app/releases/* | head -5"

# Откат на предыдущий (второй по свежести)
PREV=$(ssh deploy@origin "ls -1dt /var/www/app/releases/* | sed -n 2p")
ssh deploy@origin "ln -sfn ${PREV} /var/www/app/current"

# После отката — инвалидация HTML (см. раздел «Инвалидация CDN»)
```
-   **Гарантия:** Старый каталог релиза не трогается до следующего деплоя, поэтому откат не зависит от доступности исходников в CI.
-   **Автоматизация:** шаг `rollback` в пайплайне должен запускаться вручную (`when: manual`) и только после неудачного smoke test.

### Поставка артефактов и целостность цепочки (Supply Chain)

Воспроизводимость и аудит достигаются фиксацией состава зависимостей (SBOM) и контрольных сумм. Это DevOps-практика, не зависящая от облаков.
```bash
# Генерация SBOM в формате CycloneDX (syft — open-source, без облачных зависимостей)
syft dir:. -o cyclonedx-json > sbom.json

# Контрольная сумма артефакта для проверки при деплое
sha256sum dist/assets/*.js > dist.sha256
```
```bash
# На этапе деплоя — проверка целостности перед распаковкой
sha256sum -c dist.sha256 || { echo "Artifact corrupted"; exit 1; }
```
-   **Зачем:** SBOM позволяет быстро найти уязвимые пакеты при публикации CVE; контрольная сумма защищает от повреждения при передаче артефакта между раннерами и серверами.

---

### Стратегии выкатки для статики (Canary / Blue-Green)

Хотя статика деплоится атомарно (symlink), «постепенная поставка» (Progressive Delivery) применима и к фронтенду — на уровне CDN/edge или переключения версий:

- **Blue-Green для статики:** держим две копии — предыдущий (`blue`) и новый (`green`) релиз; переключение трафика — flip symlink + инвалидация HTML. Мгновенный возврат на `blue` при проблемах (см. [Инцидент-респонс](./frontend_incident_response.md)).
- **Canary через CDN/edge:** часть пользователей (по cookie/гео/заголовку) получает новый билд, остальные — старый. Реализуется weighted routing на edge либо через feature flags (см. [Feature flags в доставке фронтенда](./feature_flags_frontend.md)).
- **Канарейка по метрикам:** после переключения мониторим RUM/JS Error Rate (см. [SLO/SLI и RUM](./frontend_slo_rum.md)); при расходе error budget — авто-откат или kill switch.

Общие принципы, типы и здоровье/откат — в **[Стратегии деплоя](../Core_Concepts/deployment_strategies.md)**, **[Canary deployment](../Deployment_Strategies/canary_deployment.md)**, **[Blue-Green](../Deployment_Strategies/blue_green_deployment.md)**, **[Здоровье и откат](../Deployment_Strategies/deployment_health_checks_and_rollback.md)**.

### Продвижение артефактов между средами (Artifact Promotion)

Собранный один раз `dist/` должен **продвигаться** (promote) из `dev → stage → prod` без пересборки — иначе теряется воспроизводимость (тестировали одно, катим другое). Подход:

- Артефакт фиксируется по digest/хэш-сумме и хранится в репозитории артефактов (Nexus/Artifactory/OCI) либо как CI-artifact с `expire_in`.
- На каждой среде — проверка `sha256` перед развёртыванием (см. раздел «Поставка артефактов и целостность цепочки»).
- Продвижение регулируется quality gate (LHCI, A11y, SLO) и политикой удержания (retention, минимум 5 релизов для отката).

Детали жизненного цикла, immutability и SBOM — в **[Управление артефактами](../artifact_management.md)**.

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
3.  **Smoke test (дымовой тест) по факту деплоя:**
    ```bash
    # Проверяем, что index.html отдаётся и ссылается на существующий хэшированный чанк
    INDEX=$(curl -s https://example.com/)
    CHUNK=$(echo "$INDEX" | grep -oE 'assets/[a-z]+\.[a-f0-9]+\.js' | head -1)
    curl -s -o /dev/null -w "%{http_code}\n" "https://example.com/${CHUNK}"
    # → 200 (если 404 — артефакт не долетел до Origin, см. диагностику)
    ```
4.  **Анализ отчетов LHCI:**
    Убедитесь, что все «пороги» (assertions) пройдены, и ссылка на детальный отчет доступна в логах сборки.
5.  **Проверка symlink:**
    ```bash
    ssh deploy@origin "readlink /var/www/app/current"
    # → /var/www/app/releases/2026-08-27-1a2b3c (ожидаемый релиз)
    ```

## Диагностика и устранение проблем

-   **Высокая вариативность Lighthouse:**
    - *Причина:* Нестабильность ресурсов CI-раннера (CPU steal, соседние задачи).
    - *Решение:* Используйте выделенные (dedicated) раннеры или увеличьте `numberOfRuns` до 5, ориентируясь на медиану. Фиксируйте `emulatedFormFactor` и `throttlingMethod: simulate`.
-   **404 после деплоя (Race Condition):**
    - *Причина:* Инвалидация CDN сработала быстрее, чем файлы долетели до Origin, либо `index.html` переключён раньше загрузки ассетов.
    - *Решение:* В атомарном деплое сначала `rsync` ассетов, затем `ln -sfn`, затем инвалидация. Добавьте проверку доступности файла на Origin (`curl --retry`) перед запуском Purge.
-   **CDN не сбрасывает кэш по тегу:**
    - *Причина:* Неправильная настройка Surrogate-Key на уровне Origin (заголовок не пробрасывается или перезаписывается).
    - *Решение:* Проверьте `curl -I` к Origin напрямую — заголовок `Surrogate-Key`/`Cache-Tag` должен присутствовать. Убедитесь, что CDN настроена его интерпретировать (не «pass-through» без действия).
-   **Cache poisoning в CI (отравление кэша зависимостей):**
    - *Причина:* Общий статический ключ кэша между защищённой и feature-веткой; вредоносный MR мог перезаписать `node_modules`.
    - *Решение:* Используйте `cache:key:files` по lock-файлу + изоляцию protected/unprotected веток. Никогда не ставьте `unprotect: true` для зависимостей.
-   **Невоспроизводимая сборка (разные бандлы на разных раннерах):**
    - *Причина:* `npm install` вместо `npm ci`, либо разные версии Node.js на раннере и локально.
    - *Решение:* Зафиксируйте Node.js через `.nvmrc` и используйте тот же Docker-образ в CI; всегда `npm ci`.
-   **Mixed Content / CORS после деплоя:**
    - *Причина:* Новые ассеты загружаются по `http://` из-за абсолютных URL в коде, либо Origin не отдаёт `Access-Control-Allow-Origin` для шрифтов.
    - *Решение:* Используйте относительные/HTTPS URL; в Nginx добавьте `add_header Access-Control-Allow-Origin "*"` для `/assets/`.
-   **Расхождение сжатия (gzip vs brotli) на Edge и Origin:**
    - *Причина:* Отсутствие `Vary: Accept-Encoding` — CDN отдаёт браузеру без Brotli сжатый gzip-версией из кэша другого клиента.
    - *Решение:* Всегда `add_header Vary "Accept-Encoding"` на уровне Origin для сжимаемых ответов.

## Лучшие практики

-   **Атомарные деплои:** Используйте уникальные пути для каждого релиза (по ID коммита/дате) и переключайте трафик через symlink, чтобы избежать смешивания старых и новых файлов в процессе переключения.
-   **Сначала статика, потом HTML:** В пайплайне сначала загружайте JS/CSS/Assets, и только последним шагом — `index.html` (или атомарно переключайте symlink после загрузки всех ассетов). Это гарантирует, что пользователь не получит HTML, ссылающийся на ещё не загруженные скрипты.
-   **Локальные бюджеты:** Настройте запуск `lhci`, `size-limit` и `pa11y` в pre-push хуках, чтобы разработчики видели проблемы до запуска пайплайна.
-   **Мониторинг инвалидаций:** Логируйте время выполнения и объём инвалидаций (особенно для Purge All), чтобы отслеживать нагрузку на Origin и избегать cache stampede.
-   **Retention релизов:** Храните минимум 5 последних каталогов релиза для мгновенного отката; автоматически удаляйте более старые.
-   **Изоляция окружения:** Сборка и тесты только в контейнере с фиксированной версией Node.js; зависимости через `npm ci` + кэш по lock-файлу.
-   **Наблюдаемость:** Пушьте метрики длительности сборки, размера артефакта и результатов тестов в Prometheus — это превращает CI в управляемый SRE-процесс с историей регрессий.
-   **Целостность:** Генерируйте SBOM и `sha256` артефакта; проверяйте суммы при деплое.

---

## Практическая реализация (CI/CD Workflow)

1.  **Stage: Build**
    - Сборка с генерацией хэшей (URL Fingerprinting) и `npm ci`.
    - Генерация SBOM и контрольных сумм артефакта.
    - Проверка бюджета размера бандла (`size-limit`).
    - Сохранение `dist/` как artifact (без повторной сборки на следующих этапах).
2.  **Stage: Test**
    - Запуск `pa11y-ci` и `jest-axe` (A11y).
    - Запуск `LHCI` (на временном окружении или Preview URL) с Regression Detection.
    - Визуальные тесты Playwright (консистентный Docker-образ).
3.  **Stage: Deploy**
    - `rsync` артефакта в каталог релиза на Origin.
    - Атомарное переключение symlink (`ln -sfn`).
    - Установка метаданных (Surrogate Keys) и заголовков `Cache-Control: immutable` на стороне Nginx.
4.  **Stage: Post-Deploy**
    - Инвалидация CDN через API (Purge по тегу или путям) — строго после проверки доступности ассетов.
    - Smoke test / Health Check (проверка `index.html` и ссылок на чанки).
    - Откат (`rollback`, `when: manual`) при неудаче smoke test.

## Особые случаи

- **Race condition: CDN инвалидирует раньше, чем ассеты долетели до Origin.** Симптом: после деплоя `X-Cache: Miss` для HTML, но `404` на чанки. Порядок операций: `rsync` ассетов → проверка доступности (`curl --retry`) → `ln -sfn` → инвалидация. Никогда не инвалидируйте до загрузки ассетов.
- **Cache stampede при Purge All.** Полная очистка CDN создаёт всплеск запросов к Origin. Решения: ограничьте частоту Purge All, используйте теговую инвалидацию по умолчанию, добавьте Origin-level rate limiting.
- **Stale SW после отката symlink.** Откат на старый релиз не обновляет SW: старый SW продолжает кэшировать старые хэши. Решения: инвалидировать `sw.js` в CDN, добавить баннер обновления, использовать `skipWaiting` + `clients.claim`. Детали — в **[Service Worker и PWA](./service_worker_pwa_cicd.md)**.
- **Partial deploy на multi-DC.** Если деплой идёт на несколько дата-центров, откат должен быть синхронным. Проверяйте `readlink` на каждом хосте; используйте orchestration (Ansible, Fleet) вместо ручного `ssh` в цикле.
- **Эфемерные раннеры без remote cache.** При каждом pipeline создаётся новый runner, локальный `.turbo`/`.nx/cache` не сохраняется. Без remote cache каждый прогон собирает всё с нуля. Решение: настройте S3-совместимый бакет (MinIO) или self-hosted Nx cache server.
- **Разные версии Node.js между CI и локально.** Минорная версия меняет хэш `node_modules` и ломает remote cache. Фиксируйте `.nvmrc` и используйте тот же Docker-образ в CI, что и локально.
- **LHCI вариативность на перегруженных раннерах.** CPU steal, IO contention дают разный LCP/CLS на одном и том же коде. Решения: выделенные (dedicated) раннеры, `numberOfRuns: 5` с медианой, фиксированные `emulatedFormFactor` и `throttlingMethod: simulate`.
- **`npm ci` с повреждённым lock-файлом.** Если `package-lock.json` повреждён или не соответствует `package.json`, `npm ci` завершится с ошибкой. Добавьте pre-build проверку: `npm ci --dry-run` или `npm audit --audit-level=high`.
- **Nginx `try_files` и SPA-маршруты с query-параметрами.** `try_files $uri $uri/ /index.html` не передаёт query string к бэкенду при SSR. Если приложение использует query для маршрутизации, добавьте `$is_args$args` или переходите на path-based routing.
- **Большой SBOM для монорепозиториев.** Генерация SBOM для 100+ пакетов замедляет пайплайн. Решения: инкрементальный SBOM (только изменённые пакеты), кэширование SBOM артефакта, отключение `syft` для preview-сред.

---

## Дополнительная информация

### См. также

- **[Управление артефактами](../artifact_management.md)** — жизненный цикл артефактов, immutability, SBOM, retention policies, promotion между средами.
- **[Инцидент-респонс для фронтенда](./frontend_incident_response.md)** — runbook для отката symlink, инвалидации CDN, kill switch.
- **[Стратегии деплоя и здоровье](../Core_Concepts/deployment_strategies.md)** — общие принципы canary/blue-green, health checks и отката, применимые к фронтенду.
- **[Secrets Management в CI/CD](../DevSecOps/secrets_management.md)** — Vault, dynamic secrets, rotation и интеграция с GitLab CI.
- **[Supply Chain Security](../../Security/Supply_Chain_Security/)** — Snyk, Renovate, Trivy, Grype, SBOM и подпись артефактов.
- **[Контейнеризация фронтенда](./frontend_containerization.md)** — Dockerfile, multi-stage builds, registry security и Cosign/Notary.
- **[Деплой фронтенда в Kubernetes](./frontend_kubernetes_deployment.md)** — Deployment, Service, Ingress, HPA, PDB и NetworkPolicy.
